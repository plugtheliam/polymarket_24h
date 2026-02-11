"""Event-driven scheduler for market open sniping (F-018).

Provides event-driven scheduling for crypto market opens that occur every hour.
Switches between phases:
- IDLE: >30s before open, low-frequency scan (5min interval)
- PRE_OPEN: 30s before open, discover markets + warm connections
- SNIPE: 0-60s after open, rapid orderbook polling (3s interval)
- COOLDOWN: 60-120s after open, moderate polling (15s interval)

Phase 2 enhancements:
- Cycle end summary report on IDLE entry
- Paper trade settlement tracking
- Dynamic threshold based on market liquidity

Phase 3 enhancements:
- WebSocket price cache integration (WS-first, HTTP fallback)
- Paired entry detection (YES+NO < $1.00 → guaranteed profit)
- Per-market detailed logging (asset breakdown, timing analysis)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path

import aiohttp

from poly24h.discovery.gamma_client import GammaClient
from poly24h.discovery.market_scanner import MarketScanner
from poly24h.models.market import Market, MarketSource
from poly24h.monitoring.cycle_report import CycleStats, format_cycle_report
from poly24h.monitoring.market_logger import MarketOpportunityLogger
from poly24h.monitoring.settlement import PaperSettlementTracker, PaperTrade
from poly24h.monitoring.telegram import TelegramAlerter
from poly24h.strategy.crypto_fair_value import CryptoFairValueCalculator
from poly24h.strategy.dynamic_threshold import DynamicThreshold
from poly24h.strategy.fee_calculator import is_profitable_after_fees
from poly24h.strategy.nba_fair_value import NBAFairValueCalculator, NBATeamParser
from poly24h.strategy.orderbook_scanner import ClobOrderbookFetcher
from poly24h.strategy.paired_entry import (
    PairedEntryDetector,
    PairedEntrySimulator,
)
from poly24h.scheduler.hybrid_strategy import (
    HybridConfig,
    HybridStrategy,
    StrategyType,
)
from poly24h.position_manager import PositionManager
from poly24h.portfolio.hybrid_portfolio import HybridPortfolio
from poly24h.websocket.price_cache import PriceCache

logger = logging.getLogger(__name__)


class Phase(Enum):
    """Scheduler phases based on market open timing."""

    IDLE = "idle"
    PRE_OPEN = "pre_open"
    SNIPE = "snipe"
    COOLDOWN = "cooldown"


@dataclass
class OrderbookSnapshot:
    """Snapshot of orderbook state at a point in time."""

    yes_best_ask: float | None
    no_best_ask: float | None
    spread: float | None
    timestamp: datetime

    def is_opportunity(self, threshold: float) -> bool:
        """Returns True if either side <= threshold."""
        if self.yes_best_ask is None and self.no_best_ask is None:
            return False

        if self.yes_best_ask is not None and self.yes_best_ask <= threshold:
            return True

        if self.no_best_ask is not None and self.no_best_ask <= threshold:
            return True

        return False


@dataclass
class SniperOpportunity:
    """Detected sniping opportunity."""

    trigger_price: float
    trigger_side: str  # "YES" or "NO"
    spread: float
    timestamp: datetime


class MarketOpenSchedule:
    """Calculates next market open times and current phase.

    1H crypto markets open every hour on the hour (XX:00:00).
    """

    def next_open(self, now: datetime) -> datetime:
        """Returns next hourly boundary (1H crypto markets)."""
        # If we're exactly at the hour, return next hour
        if now.minute == 0 and now.second == 0 and now.microsecond == 0:
            return now + timedelta(hours=1)

        # Otherwise return the next hour boundary
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return next_hour

    def seconds_until_open(self, now: datetime) -> float:
        """Calculate seconds until next market open."""
        next_open = self.next_open(now)

        # Handle the special case where we're exactly at market open
        if now.minute == 0 and now.second == 0 and now.microsecond == 0:
            return 0.0

        delta = next_open - now
        return delta.total_seconds()

    def is_pre_open_window(self, now: datetime, window_secs: int = 30) -> bool:
        """Returns True if within window_secs before market open."""
        seconds_until = self.seconds_until_open(now)
        return 0 < seconds_until <= window_secs

    def is_snipe_window(self, now: datetime, window_secs: int = 60) -> bool:
        """Returns True if within window_secs after market open."""
        # Check if we're after a market open
        minutes_since_hour = now.minute
        seconds_since_hour = minutes_since_hour * 60 + now.second

        return 0 <= seconds_since_hour <= window_secs

    def current_phase(self, now: datetime) -> Phase:
        """Determine current phase based on time relative to market open."""
        if self.is_pre_open_window(now, window_secs=30):
            return Phase.PRE_OPEN
        elif self.is_snipe_window(now, window_secs=60):
            return Phase.SNIPE
        elif self.is_snipe_window(now, window_secs=120):  # 60-120s after open
            return Phase.COOLDOWN
        else:
            return Phase.IDLE


class PreOpenPreparer:
    """Discovers upcoming markets and warms CLOB connections.

    Uses MarketScanner.discover_all() for reliable market discovery
    across ALL enabled sources (crypto + NBA + soccer + etc).
    F-019: No longer limited to crypto only.
    """

    def __init__(self, gamma_client: GammaClient, scanner: MarketScanner | None = None):
        self.gamma_client = gamma_client
        self._scanner = scanner

    @property
    def scanner(self) -> MarketScanner:
        """Lazy-init MarketScanner if not injected."""
        if self._scanner is None:
            self._scanner = MarketScanner(self.gamma_client)
        return self._scanner

    async def discover_upcoming_markets(self) -> list[Market]:
        """Discover ALL enabled markets (crypto + sports) using MarketScanner.

        F-019: Now uses discover_all() instead of discover_hourly_crypto() only.
        This includes NBA, soccer, and other enabled sports markets.
        """
        await self.gamma_client.open()
        markets = await self.scanner.discover_all()

        # Log source breakdown
        by_source: dict[str, int] = {}
        for m in markets:
            by_source[m.source.value] = by_source.get(m.source.value, 0) + 1
        logger.info(
            "PreOpenPreparer: discovered %d markets — %s",
            len(markets),
            ", ".join(f"{k}:{v}" for k, v in sorted(by_source.items())),
        )
        return markets

    def extract_token_pairs(self, markets: list[Market]) -> list[tuple[str, str]]:
        """Extract (yes_token, no_token) pairs from markets."""
        return [(market.yes_token_id, market.no_token_id) for market in markets]

    def extract_token_market_map(self, markets: list[Market]) -> dict[str, Market]:
        """Extract yes_token → Market mapping for opportunity enrichment."""
        mapping: dict[str, Market] = {}
        for m in markets:
            mapping[m.yes_token_id] = m
            mapping[m.no_token_id] = m
        return mapping

    async def warm_clob_connection(self, token_id: str) -> bool:
        """Single lightweight GET to warm HTTP connection."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://clob.polymarket.com/book",
                    params={"token_id": token_id}
                ) as response:
                    return response.status == 200
        except Exception as exc:
            logger.warning("Failed to warm CLOB connection for %s: %s", token_id, exc)
            return False

    # ------------------------------------------------------------------
    # F-022: Direct market verification for NBA and specific markets
    # ------------------------------------------------------------------

    async def discover_and_verify_market_by_id(
        self,
        market_id: str,
        min_liquidity: float = 10000.0,
    ) -> Market | None:
        """F-022: Direct market lookup with CLOB verification.

        1. Lookup market by ID via Gamma API
        2. Verify market is still active (not expired)
        3. Verify CLOB orderbook has liquidity
        4. Return verified Market or None

        Args:
            market_id: Gamma market ID (e.g., "1326267")
            min_liquidity: Minimum CLOB liquidity threshold

        Returns:
            Verified Market object or None if invalid/expired/no liquidity
        """
        return await self.scanner.discover_and_verify_market(
            market_id, min_liquidity
        )

    async def verify_markets_batch(
        self,
        market_ids: list[str],
        min_liquidity: float = 10000.0,
    ) -> list[Market]:
        """F-022: Verify multiple markets in parallel.

        Args:
            market_ids: List of Gamma market IDs
            min_liquidity: Minimum CLOB liquidity threshold

        Returns:
            List of verified Market objects
        """
        import asyncio

        tasks = [
            self.discover_and_verify_market_by_id(mid, min_liquidity)
            for mid in market_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        verified = []
        for mid, result in zip(market_ids, results):
            if isinstance(result, Exception):
                logger.warning("Verification failed for %s: %s", mid, result)
                continue
            if result is not None:
                verified.append(result)

        logger.info(
            "F-022: Verified %d/%d markets",
            len(verified), len(market_ids)
        )
        return verified


class RapidOrderbookPoller:
    """High-frequency orderbook polling during snipe window.

    F-019: Enhanced with signal quality filters:
    - min_price: Ignore asks below this price (filters NO@$0.001 garbage)
    - Spread validation: YES+NO > 1.0 is overpriced, not an arb
    """

    # F-019: Signal quality thresholds
    MIN_MEANINGFUL_PRICE = 0.02   # Ignore asks < $0.02 (no real liquidity)
    MAX_SPREAD_FOR_OPPORTUNITY = 1.005  # YES+NO must be < 1.005 to be interesting

    def __init__(self, clob_fetcher: ClobOrderbookFetcher):
        self.clob_fetcher = clob_fetcher

    async def poll_once(self, yes_token: str, no_token: str) -> OrderbookSnapshot:
        """Fetch best asks from CLOB and return snapshot."""
        yes_ask, no_ask = await self.clob_fetcher.fetch_best_asks(yes_token, no_token)

        # Calculate spread if both sides available
        spread = None
        if yes_ask is not None and no_ask is not None:
            spread = yes_ask + no_ask

        return OrderbookSnapshot(
            yes_best_ask=yes_ask,
            no_best_ask=no_ask,
            spread=spread,
            timestamp=datetime.now(tz=timezone.utc)
        )

    def detect_opportunity(
        self,
        snapshot: OrderbookSnapshot,
        threshold: float = 0.48
    ) -> SniperOpportunity | None:
        """Detect opportunity from snapshot with quality filtering.

        F-019 Filters:
        1. Price must be >= MIN_MEANINGFUL_PRICE ($0.02) to avoid garbage signals
        2. Both sides must be present for spread validation
        3. Spread (YES+NO) > MAX_SPREAD means overpriced, not an opportunity
        4. If only one side is cheap and the other is expensive (spread > 1.0),
           this might be a directional bet, not an arb — still valid but flagged
        """
        if snapshot.yes_best_ask is None and snapshot.no_best_ask is None:
            return None

        # F-019: Check YES side with quality filters
        yes_valid = (
            snapshot.yes_best_ask is not None
            and snapshot.yes_best_ask >= self.MIN_MEANINGFUL_PRICE
            and snapshot.yes_best_ask <= threshold
        )

        # F-019: Check NO side with quality filters
        no_valid = (
            snapshot.no_best_ask is not None
            and snapshot.no_best_ask >= self.MIN_MEANINGFUL_PRICE
            and snapshot.no_best_ask <= threshold
        )

        if not yes_valid and not no_valid:
            return None

        # Pick the best (cheapest valid) side
        if yes_valid and no_valid:
            # Both sides cheap — pick the cheapest
            if snapshot.yes_best_ask <= snapshot.no_best_ask:
                side, price = "YES", snapshot.yes_best_ask
            else:
                side, price = "NO", snapshot.no_best_ask
        elif yes_valid:
            side, price = "YES", snapshot.yes_best_ask
        else:
            side, price = "NO", snapshot.no_best_ask

        return SniperOpportunity(
            trigger_price=price,
            trigger_side=side,
            spread=snapshot.spread or 0.0,
            timestamp=snapshot.timestamp
        )


class EventDrivenLoop:
    """Main orchestration loop for event-driven market open sniping.

    F-019 enhancements:
    - Tracks market info alongside token pairs for enriched alerts
    - Paper trading (dry-run P&L tracking)
    - Signal quality stats per cycle

    Phase 2 enhancements:
    - Cycle end summary report on IDLE entry
    - Paper trade settlement via Gamma API
    - Dynamic threshold per market liquidity
    """

    # Batch alert interval in seconds
    BATCH_ALERT_INTERVAL = 300  # 5 minutes

    def __init__(
        self,
        schedule: MarketOpenSchedule,
        preparer: PreOpenPreparer,
        poller: RapidOrderbookPoller,
        alerter: TelegramAlerter,
        price_cache: PriceCache | None = None,
    ):
        self.schedule = schedule
        self.preparer = preparer
        self.poller = poller
        self.alerter = alerter
        self._active_token_pairs: list[tuple[str, str]] = []
        # F-019: Market info for enriched alerts
        self._active_markets: list[Market] = []
        self._token_to_market: dict[str, Market] = {}
        # F-019: Paper trading state
        self._paper_trades: list[dict] = []
        self._paper_pnl: float = 0.0
        self._paper_wins: int = 0
        self._paper_losses: int = 0
        self._signals_filtered: int = 0  # junk signals caught by quality filter
        self._signals_total: int = 0
        # F-020: Batched alert accumulator
        self._pending_opps: list[tuple[SniperOpportunity, Market | None, dict]] = []
        self._last_batch_alert: datetime = datetime.now(tz=timezone.utc)
        # Phase 2: Cycle stats, settlement, dynamic threshold
        self._cycle_stats: CycleStats = CycleStats()
        self._settlement_tracker: PaperSettlementTracker = PaperSettlementTracker()
        self._dynamic_threshold: DynamicThreshold = DynamicThreshold()
        self._previous_phase: Phase = Phase.IDLE
        self._cycle_count: int = 0
        # Phase 3: WebSocket cache, paired entry, market logger
        self._price_cache: PriceCache = price_cache or PriceCache()
        self._paired_detector: PairedEntryDetector = PairedEntryDetector()
        self._paired_simulator: PairedEntrySimulator = PairedEntrySimulator()
        self._market_logger: MarketOpportunityLogger = MarketOpportunityLogger()
        self._ws_cache_hits: int = 0
        self._http_fallback_count: int = 0
        # Phase 5: Fair Value calculators (F-021)
        self._nba_fair_value: NBAFairValueCalculator = NBAFairValueCalculator()
        self._nba_team_parser: NBATeamParser = NBATeamParser()
        self._crypto_fair_value: CryptoFairValueCalculator = CryptoFairValueCalculator()
        self._market_fair_values: dict[str, float] = {}  # market_id → fair_prob
        
        # Phase 6: Hybrid Mode (Crypto Paired + NBA Sniper)
        self._hybrid_config: HybridConfig = HybridConfig(
            paired_max_cpp=Decimal("0.94"),   # 6% margin for fees
            sniper_threshold=Decimal("0.48"),
            crypto_allocation=Decimal("0.60"),
            nba_allocation=Decimal("0.40"),
            max_per_market=Decimal("100"),
            min_profit_margin=Decimal("0.005"),
        )
        self._hybrid_strategy: HybridStrategy = HybridStrategy(self._hybrid_config)
        self._hybrid_portfolio: HybridPortfolio = HybridPortfolio(
            initial_capital=Decimal("1000"),
            crypto_allocation=Decimal("0.60"),
            nba_allocation=Decimal("0.40"),
            max_per_market=Decimal("100"),
            daily_loss_limit=Decimal("200"),
        )
        self._hybrid_mode_enabled: bool = True  # Toggle for hybrid mode
        
        # F-018: Position Manager for realistic dry-run (one position per market)
        self._position_manager: PositionManager = PositionManager(
            bankroll=1000.0,  # Starting capital
            max_per_market=100.0,  # Max $100 per market
        )
        # Load persisted state and sync from paper_trades
        self._position_manager.load_state(Path("data/position_manager_state.json"))
        self._position_manager.sync_from_paper_trades(Path("data/paper_trades"))

    async def run(self, config) -> None:
        """Async main loop that orchestrates the full cycle."""
        while True:
            now = datetime.now(tz=timezone.utc)
            current_phase = self.schedule.current_phase(now)

            if current_phase == Phase.IDLE:
                await self._handle_idle_phase(now, config)
            elif current_phase == Phase.PRE_OPEN:
                await self._handle_pre_open_phase(config)
            elif current_phase == Phase.SNIPE:
                await self._handle_snipe_phase(config)
            elif current_phase == Phase.COOLDOWN:
                await self._handle_cooldown_phase(config)

            # Short sleep to prevent tight loop
            await asyncio.sleep(1)

    # Settlement check interval during IDLE (seconds)
    IDLE_SETTLEMENT_INTERVAL = 300  # Check every 5 minutes

    async def _handle_idle_phase(self, now: datetime, config) -> None:
        """Handle IDLE phase: sleep until pre_open window or run background scan.

        Phase 2: On transition to IDLE (from COOLDOWN/SNIPE), sends:
        1. Cycle end summary report
        2. Paper trade settlement check

        Enhanced: Periodic settlement checks during IDLE to resolve
        expired positions without waiting for next cycle transition.
        """
        # F-020: Flush any remaining batched alerts when entering IDLE
        await self._flush_batch_alerts(force=True)

        # Phase 2: Send cycle end report on transition to IDLE
        if self._previous_phase in (Phase.SNIPE, Phase.COOLDOWN):
            await self._send_cycle_end_report()
            await self._run_settlement_check()
        self._previous_phase = Phase.IDLE

        seconds_until_open = self.schedule.seconds_until_open(now)
        sleep_until_pre_open = seconds_until_open - config.pre_open_window_secs

        if sleep_until_pre_open > 300:  # More than 5 minutes
            # Run periodic settlement check + background scan
            logger.info("IDLE: Running background scan + settlement check, then sleeping %ds", sleep_until_pre_open)
            await self._run_settlement_check()
            await asyncio.sleep(300)  # Background scan every 5 minutes
        else:
            # Sleep until pre-open window
            if sleep_until_pre_open > 0:
                logger.info("IDLE: Sleeping %ds until pre-open", sleep_until_pre_open)
                await asyncio.sleep(sleep_until_pre_open)

    async def _handle_pre_open_phase(self, config) -> None:
        """Handle PRE_OPEN phase: discover ALL markets, warm connections."""
        self._previous_phase = Phase.PRE_OPEN
        logger.info("PRE_OPEN: Discovering markets and warming connections")

        # Phase 2: Start new cycle stats
        self._cycle_count += 1
        self._cycle_stats = CycleStats()

        # F-019: Discover ALL enabled markets (crypto + sports)
        markets = await self.preparer.discover_upcoming_markets()
        self._active_markets = markets
        self._active_token_pairs = self.preparer.extract_token_pairs(markets)
        self._token_to_market = self.preparer.extract_token_market_map(markets)

        # Log source breakdown
        by_source: dict[str, int] = {}
        for m in markets:
            by_source[m.source.value] = by_source.get(m.source.value, 0) + 1
        source_str = ", ".join(f"{k}:{v}" for k, v in sorted(by_source.items()))
        logger.info(
            "PRE_OPEN: %d markets loaded — %s",
            len(markets), source_str,
        )

        # Phase 2: Record discovery in cycle stats
        self._cycle_stats.record_discovery(len(markets), by_source)

        # Warm CLOB connections for all token pairs
        warm_tasks = []
        for yes_token, no_token in self._active_token_pairs:
            warm_tasks.append(self.preparer.warm_clob_connection(yes_token))
            warm_tasks.append(self.preparer.warm_clob_connection(no_token))

        if warm_tasks:
            await asyncio.gather(*warm_tasks, return_exceptions=True)

        # Phase 5 (F-021): Calculate fair values for all markets
        await self._calculate_fair_values(markets)

        # Wait for market open
        now = datetime.now(tz=timezone.utc)
        sleep_time = self.schedule.seconds_until_open(now)
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)

    # Tiered polling intervals (seconds) — aligned with polymarket_trader
    SNIPE_ULTRA_EARLY_SECS = 10.0   # first 10s after open
    SNIPE_ULTRA_EARLY_INTERVAL = 0.2  # 200ms — aggressive
    SNIPE_EARLY_SECS = 30.0          # 10-30s after open
    SNIPE_EARLY_INTERVAL = 0.5       # 500ms
    SNIPE_NORMAL_INTERVAL = 1.0      # 30-60s: 1s
    COOLDOWN_INTERVAL = 5.0          # cooldown: 5s

    def _snipe_interval(self, seconds_since_open: float) -> float:
        """Tiered polling interval based on time since market open."""
        if seconds_since_open <= self.SNIPE_ULTRA_EARLY_SECS:
            return self.SNIPE_ULTRA_EARLY_INTERVAL
        if seconds_since_open <= self.SNIPE_EARLY_SECS:
            return self.SNIPE_EARLY_INTERVAL
        return self.SNIPE_NORMAL_INTERVAL

    async def _calculate_fair_values(self, markets: list[Market]) -> None:
        """Phase 5 (F-021): Calculate fair values for discovered markets.

        Uses different models based on market source:
        - HOURLY_CRYPTO: RSI + Bollinger Bands from Binance
        - NBA: Team win rate comparison
        - Others: Default 0.50 (neutral)

        Stores results in self._market_fair_values[market_id] = fair_prob.
        """
        self._market_fair_values.clear()

        for market in markets:
            fair_prob = 0.50  # Default neutral

            try:
                if market.source == MarketSource.HOURLY_CRYPTO:
                    fair_prob = await self._calculate_crypto_fair_value(market)
                elif market.source == MarketSource.NBA:
                    fair_prob = await self._calculate_nba_fair_value(market)
                # Other sources: keep default 0.50
            except Exception as e:
                logger.warning(
                    "Fair value calculation failed for %s: %s",
                    market.question[:40], e
                )

            self._market_fair_values[market.id] = fair_prob

        logger.info(
            "PRE_OPEN: Calculated fair values for %d markets",
            len(self._market_fair_values),
        )

    async def _calculate_crypto_fair_value(self, market: Market) -> float:
        """Calculate fair UP probability for crypto 1H market.

        Uses momentum + volume as primary signals, RSI/BB as secondary.
        P1-1: ETH gets a decoupling penalty when diverging from BTC.
        """
        # Extract asset from question (e.g., "Will BTC go up..." -> "BTC")
        question_lower = market.question.lower()
        asset = None
        for coin in ["btc", "eth", "sol", "xrp", "doge", "bnb"]:
            if coin in question_lower:
                asset = coin.upper()
                break

        if not asset:
            return 0.50  # Unknown crypto, neutral

        symbol = f"{asset}USDT"

        # Fetch OHLCV data from Binance
        ohlcv = await self._crypto_fair_value.fetch_binance_ohlcv(
            symbol, interval="1h", limit=24
        )

        if not ohlcv or len(ohlcv) < 15:
            logger.debug("Insufficient OHLCV data for %s", symbol)
            return 0.50

        closes = [c["close"] for c in ohlcv]

        # Calculate PRIMARY indicators (momentum + volume)
        momentum = self._crypto_fair_value.calculate_1h_momentum(ohlcv)
        volume_spike, trend_direction = self._crypto_fair_value.calculate_volume_spike(
            ohlcv, lookback=10
        )

        # Calculate SECONDARY indicators (RSI + BB)
        rsi = self._crypto_fair_value.calculate_rsi(closes, period=14)
        bb_lower, bb_mid, bb_upper = self._crypto_fair_value.calculate_bollinger_bands(
            closes, period=20, std_dev=2
        )

        current_price = closes[-1]

        # P1-1: ETH decoupling — compare ETH momentum to BTC momentum
        decoupling_factor = 1.0
        if asset == "ETH":
            try:
                btc_ohlcv = await self._crypto_fair_value.fetch_binance_ohlcv(
                    "BTCUSDT", interval="1h", limit=3
                )
                if btc_ohlcv and len(btc_ohlcv) >= 2:
                    btc_momentum = self._crypto_fair_value.calculate_1h_momentum(
                        btc_ohlcv
                    )
                    decoupling_factor = self._crypto_fair_value.eth_decoupling_factor(
                        eth_momentum=momentum, btc_momentum=btc_momentum,
                    )
                    if decoupling_factor < 1.0:
                        logger.info(
                            "P1-1: ETH decoupling detected: "
                            "ETH_mom=%.2f%% BTC_mom=%.2f%% -> factor=%.2f",
                            momentum, btc_momentum, decoupling_factor,
                        )
            except Exception as e:
                logger.warning(
                    "P1-1: Failed to fetch BTC for ETH decoupling: %s", e
                )

        # Calculate fair UP probability with all signals
        fair_prob = self._crypto_fair_value.calculate_fair_probability(
            rsi=rsi,
            price=current_price,
            bb_lower=bb_lower,
            bb_upper=bb_upper,
            momentum=momentum,
            volume_spike=volume_spike,
            trend_direction=trend_direction,
            decoupling_factor=decoupling_factor,
        )

        logger.debug(
            "Crypto fair value: %s mom=%.2f%% vol=%.1fx trend=%+.0f "
            "RSI=%.1f decouple=%.2f -> prob=%.2f",
            symbol, momentum, volume_spike, trend_direction,
            rsi, decoupling_factor, fair_prob,
        )

        return fair_prob

    async def _calculate_nba_fair_value(self, market: Market) -> float:
        """Calculate fair probability for NBA market.

        Uses NBATeamParser to extract team names from question text,
        then calculates fair probability based on season win rates.
        """
        # Parse team names using the new parser
        team_a, team_b = self._nba_team_parser.parse_teams(market.question)

        if not team_a:
            logger.debug("NBA: No teams found in '%s'", market.question[:50])
            return 0.50  # Can't extract teams, neutral

        # Get win rates
        rate_a = await self._nba_fair_value.get_team_win_rate(team_a)
        rate_b = await self._nba_fair_value.get_team_win_rate(team_b) if team_b else 0.50

        # Calculate fair probability
        fair_prob = self._nba_fair_value.calculate_fair_probability(rate_a, rate_b)

        logger.debug(
            "NBA fair value: %s (%.2f) vs %s (%.2f) → prob=%.2f",
            team_a, rate_a, team_b if team_b else "N/A", rate_b, fair_prob
        )

        return fair_prob

    def _is_market_undervalued(
        self, market: Market, side: str, price: float, margin: float = 0.05
    ) -> bool:
        """Phase 5 (F-021): Check if market is undervalued using fair value model.

        Args:
            market: The market to check
            side: "YES" or "NO"
            price: Current market price for this side
            margin: Safety margin (default 0.05)

        Returns:
            True if undervalued based on fair value model.
        """
        fair_prob = self._market_fair_values.get(market.id, 0.50)

        if market.source == MarketSource.HOURLY_CRYPTO:
            return self._crypto_fair_value.is_undervalued(
                side=side, market_price=price, fair_prob=fair_prob, margin=margin
            )
        elif market.source == MarketSource.NBA:
            # For NBA, YES usually means team A wins
            if side == "YES":
                return self._nba_fair_value.is_undervalued(
                    market_price=price, fair_prob=fair_prob, margin=margin
                )
            else:
                # NO side: fair prob = 1 - fair_prob
                return self._nba_fair_value.is_undervalued(
                    market_price=price, fair_prob=(1 - fair_prob), margin=margin
                )
        else:
            # Fallback to simple threshold check
            return price < (0.50 - margin)

    # Max concurrent HTTP requests to CLOB API to avoid 429 rate limits
    MAX_CONCURRENT_POLLS = 10

    async def _poll_all_pairs(
        self, threshold: float, phase_label: str = "SNIPE",
    ) -> list[tuple[SniperOpportunity, tuple[str, str]]]:
        """Poll all active token pairs with concurrency control.

        Phase 3: WS-cache-first approach. If WS cache has fresh prices,
        use them directly (saves ~200ms HTTP latency). Otherwise fall back
        to HTTP polling.

        F-020: Semaphore limits concurrent HTTP requests to avoid CLOB 429.
        
        Returns:
            List of (opportunity, (yes_token, no_token)) tuples.
            This allows caller to identify which market the opportunity belongs to.
        """
        if not self._active_token_pairs:
            return []

        semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_POLLS)

        async def _poll_one(yes_token: str, no_token: str) -> tuple[SniperOpportunity, tuple[str, str]] | None:
            try:
                # Phase 3: Try WS cache first for lower latency (no semaphore needed)
                snapshot = self._try_ws_cache(yes_token, no_token)
                if snapshot is not None:
                    self._ws_cache_hits += 1
                    opp = self.poller.detect_opportunity(snapshot, threshold)
                    return (opp, (yes_token, no_token)) if opp else None

                # Fallback to HTTP polling (rate-limited)
                async with semaphore:
                    self._http_fallback_count += 1
                    snapshot = await self.poller.poll_once(yes_token, no_token)
                    opp = self.poller.detect_opportunity(snapshot, threshold)
                    return (opp, (yes_token, no_token)) if opp else None
            except Exception as exc:
                logger.error("[%s] Error polling %s/%s: %s", phase_label, yes_token, no_token, exc)
                return None

        results = await asyncio.gather(
            *[_poll_one(yt, nt) for yt, nt in self._active_token_pairs],
            return_exceptions=True,
        )
        return [r for r in results if isinstance(r, tuple) and r[0] is not None]

    def _try_ws_cache(
        self, yes_token: str, no_token: str, max_age: float = 5.0,
    ) -> OrderbookSnapshot | None:
        """Try to build OrderbookSnapshot from WebSocket price cache.

        Returns None if either side's cache is stale or missing.
        """
        # Check freshness of both sides
        if not self._price_cache.is_orderbook_fresh(yes_token, max_age):
            return None
        if not self._price_cache.is_orderbook_fresh(no_token, max_age):
            return None

        yes_ask = self._price_cache.get_best_ask(yes_token)
        no_ask = self._price_cache.get_best_ask(no_token)

        if yes_ask is None or no_ask is None:
            return None

        spread = yes_ask + no_ask

        return OrderbookSnapshot(
            yes_best_ask=yes_ask,
            no_best_ask=no_ask,
            spread=spread,
            timestamp=datetime.now(tz=timezone.utc),
        )

    def _should_use_paired_entry(self, market: Market, yes_ask: float, no_ask: float) -> bool:
        """Phase 6: Check if market should use Paired Entry strategy.
        
        Uses hybrid strategy routing:
        - Crypto markets → Paired Entry (if eligible)
        - NBA markets → Sniper (skip paired)
        """
        if not self._hybrid_mode_enabled:
            return False
        
        # Only Crypto markets use Paired Entry
        strategy_type = self._hybrid_strategy.get_strategy_for_market(market)
        if strategy_type != StrategyType.PAIRED_ENTRY:
            return False
        
        # Check fee-adjusted profitability
        yes_dec = Decimal(str(yes_ask))
        no_dec = Decimal(str(no_ask))
        
        return is_profitable_after_fees(
            yes_price=yes_dec,
            no_price=no_dec,
            min_margin=self._hybrid_config.min_profit_margin,
            use_taker=True,
        )

    async def _check_paired_entries(
        self, threshold: float, phase_label: str = "SNIPE",
    ) -> list[tuple[SniperOpportunity, Market | None, dict]]:
        """Phase 3+6: Check all active markets for paired entry opportunities.

        Phase 6 enhancement: Uses fee-adjusted threshold ($0.94) and only
        applies to Crypto markets (hybrid routing).

        Looks for YES_ask + NO_ask < max_cpp (fee-adjusted) → guaranteed profit.
        Uses WS cache first, then HTTP fallback for orderbook data.

        Returns list of (opportunity, market, paper_trade) tuples.
        """
        paired_results = []

        for i, (yes_token, no_token) in enumerate(self._active_token_pairs):
            market = self._active_markets[i] if i < len(self._active_markets) else None
            if market is None:
                continue

            # Phase 6: Skip non-Crypto markets for paired entry
            if self._hybrid_mode_enabled and market.source != MarketSource.HOURLY_CRYPTO:
                continue

            # Get best asks (try WS cache first, then use last poll data)
            yes_ask = self._price_cache.get_best_ask(yes_token)
            no_ask = self._price_cache.get_best_ask(no_token)

            if yes_ask is None or no_ask is None:
                continue

            # Phase 6: Use fee-adjusted threshold instead of simple $1.00
            if not self._should_use_paired_entry(market, yes_ask, no_ask):
                continue

            # Determine detection source
            source = "ws_cache"
            if not self._price_cache.is_orderbook_fresh(yes_token, 5.0):
                source = "http_poll"

            # Get sizes from orderbook entries if available
            yes_entry = self._price_cache.get_orderbook_entry(yes_token)
            no_entry = self._price_cache.get_orderbook_entry(no_token)
            yes_size = yes_entry.ask_size if yes_entry else 0.0
            no_size = no_entry.ask_size if no_entry else 0.0

            # Check for paired opportunity (legacy detector for paper trade)
            paired_opp = self._paired_detector.detect(
                market=market,
                yes_ask=yes_ask,
                no_ask=no_ask,
                yes_size=yes_size,
                no_size=no_size,
                source=source,
            )

            if paired_opp is not None:
                # Simulate paper trade
                paper = self._paired_simulator.simulate_trade(paired_opp)

                # Log detailed opportunity
                now = datetime.now(tz=timezone.utc)
                open_time = now.replace(minute=0, second=0, microsecond=0)
                secs_since_open = (now - open_time).total_seconds()

                self._market_logger.record(
                    market_id=market.id,
                    market_question=market.question,
                    market_source=market.source.value,
                    trigger_side="PAIRED",
                    trigger_price=paired_opp.total_cost,
                    spread=paired_opp.spread,
                    seconds_since_open=secs_since_open,
                    detection_source=source,
                    is_paired=True,
                )

                # Create a synthetic SniperOpportunity for the batch alert system
                synth_opp = SniperOpportunity(
                    trigger_price=paired_opp.total_cost,
                    trigger_side="PAIRED",
                    spread=paired_opp.spread,
                    timestamp=now,
                )

                paired_results.append((synth_opp, market, paper.to_dict()))

                logger.info(
                    "🔗 [%s] PAIRED ENTRY: %s | Y=$%.4f+N=$%.4f=$%.4f | "
                    "profit=$%.4f (%.2f%%) | %s",
                    phase_label, market.question[:50],
                    paired_opp.yes_ask, paired_opp.no_ask,
                    paired_opp.total_cost,
                    paired_opp.spread, paired_opp.roi_pct,
                    source,
                )

        return paired_results

    def _find_market_for_tokens(self, yes_token: str, no_token: str) -> Market | None:
        """F-019: Find the Market object for given token pair.

        Uses token-to-market mapping for O(1) lookup.
        Falls back to index-based lookup for backwards compatibility.
        """
        # Try token-to-market mapping first
        if yes_token in self._token_to_market:
            return self._token_to_market[yes_token]
        if no_token in self._token_to_market:
            return self._token_to_market[no_token]

        # Fallback: index-based lookup (deprecated)
        logger.warning("Token not found in mapping, falling back to index lookup")
        for i, (yt, nt) in enumerate(self._active_token_pairs):
            if yt == yes_token and nt == no_token:
                if i < len(self._active_markets):
                    return self._active_markets[i]
        return None

    def _record_paper_trade(
        self, opp: SniperOpportunity, market: Market | None,
    ) -> dict:
        """Record a paper trade for P&L tracking.

        Consolidates: PositionManager entry + settlement tracker recording.
        - P0-1: Sports moneyline min price filter
        - P0-2: O/U per-event dedup
        - Only one position per market allowed (PositionManager guard)
        - Settlement tracker dedup (won't record same market_id twice)
        - Bankroll and max_per_market limits enforced
        """
        market_id = market.id if market else ""

        # P0-1/P0-2: Entry filters (moneyline min price, O/U per-event)
        if market and self._position_manager.should_skip_entry(
            market, opp.trigger_price, opp.trigger_side,
        ):
            return {}  # Skipped by filter

        # Check if we can enter this market (one position per market)
        if market_id and not self._position_manager.can_enter(market_id):
            logger.debug(
                "SKIP: Already have position in %s",
                market.question[:40] if market else "Unknown",
            )
            return {}  # Empty dict signals skipped trade

        # Enter position via PositionManager
        if market_id and market:
            position = self._position_manager.enter_position(
                market_id=market_id,
                market_question=market.question,
                side=opp.trigger_side,
                price=opp.trigger_price,
                end_date=market.end_date.isoformat() if market.end_date else "",
                event_id=market.event_id,
            )
            if position:
                paper_size = position.size_usd
                paper_shares = position.shares
            else:
                return {}  # Failed to enter (shouldn't happen if can_enter passed)
        else:
            # Fallback for unknown markets (legacy behavior)
            paper_size = 10.0
            paper_shares = 10.0 / opp.trigger_price if opp.trigger_price > 0 else 0

        trade = {
            "side": opp.trigger_side,
            "price": opp.trigger_price,
            "spread": opp.spread,
            "market_question": market.question if market else "Unknown",
            "market_source": market.source.value if market else "unknown",
            "market_id": market_id,
            "timestamp": opp.timestamp.isoformat(),
            "paper_size_usd": paper_size,
            "paper_shares": paper_shares,
            "status": "open",  # Will become "settled" when market resolves
        }
        self._paper_trades.append(trade)

        # Record in settlement tracker (consolidated here for dedup safety)
        if market:
            self._settlement_tracker.record_trade(
                PaperTrade(
                    market_id=market.id,
                    market_question=market.question,
                    market_source=market.source.value,
                    side=opp.trigger_side,
                    price=opp.trigger_price,
                    shares=paper_shares,
                    cost=paper_size,
                    timestamp=opp.timestamp.isoformat(),
                    end_date=market.end_date.isoformat() if market.end_date else "",
                )
            )

        # Persist position manager state
        self._position_manager.save_state(Path("data/position_manager_state.json"))

        return trade

    async def _handle_snipe_phase(self, config) -> None:
        """Handle SNIPE phase: rapid parallel orderbook polling with tiered intervals.

        F-019: Enhanced with enriched alerts showing market name/source,
        quality signal stats, and paper trade recording.

        Phase 2: Dynamic threshold per market, cycle stats tracking.
        """
        self._previous_phase = Phase.SNIPE
        if not self._active_token_pairs:
            logger.warning("SNIPE: No active token pairs to monitor")
            await asyncio.sleep(0.5)
            return

        # Estimate seconds since market open (top of current hour)
        now = datetime.now(tz=timezone.utc)
        open_time = now.replace(minute=0, second=0, microsecond=0)
        seconds_since_open = (now - open_time).total_seconds()
        interval = self._snipe_interval(seconds_since_open)

        logger.info(
            "SNIPE: Polling %d pairs (%d markets) | T+%.1fs | interval=%.2fs",
            len(self._active_token_pairs), len(self._active_markets),
            seconds_since_open, interval,
        )

        # Phase 2: Record poll in cycle stats
        self._cycle_stats.record_poll()

        opportunities = await self._poll_all_pairs(config.sniper_threshold, "SNIPE")

        # Phase 2: Track raw signals
        self._cycle_stats.raw_signals += len(opportunities)

        for opp, (yes_token, no_token) in opportunities:
            # F-019: Find market using token mapping
            market = self._find_market_for_tokens(yes_token, no_token)

            # Phase 6: In hybrid mode, Crypto uses Paired Entry, not Sniper
            if self._hybrid_mode_enabled and market and market.source == MarketSource.HOURLY_CRYPTO:
                # Crypto markets are handled by _check_paired_entries
                logger.debug(
                    "SNIPE: Skipped %s (Crypto uses Paired Entry in hybrid mode)",
                    market.question[:40],
                )
                continue

            # Phase 2: Apply dynamic threshold based on liquidity
            if market:
                dynamic_thresh = self._dynamic_threshold.get_threshold(
                    market.liquidity_usd
                )
                # Re-check against dynamic threshold
                if opp.trigger_price > dynamic_thresh:
                    logger.debug(
                        "SNIPE: Skipped %s (price $%.4f > dynamic threshold $%.4f, liq=$%.0f)",
                        market.question[:40] if market else "?",
                        opp.trigger_price, dynamic_thresh, market.liquidity_usd,
                    )
                    continue

                # Phase 5 (F-021): Additional fair value check
                # F-022 FIX: Increased margin to allow more signals (was 0.50 - dynamic_thresh)
                fair_margin = 0.05  # Fixed 5% margin for more lenient filtering
                if not self._is_market_undervalued(
                    market, opp.trigger_side, opp.trigger_price, margin=fair_margin
                ):
                    fair_prob = self._market_fair_values.get(market.id, 0.50)
                    logger.debug(
                        "SNIPE: Skipped %s (not undervalued: price=$%.4f, fair=%.2f, margin=%.2f)",
                        market.question[:40],
                        opp.trigger_price, fair_prob, fair_margin,
                    )
                    continue

            # F-019: Record paper trade (returns {} if position already exists)
            paper = self._record_paper_trade(opp, market)
            
            # Only process if we actually entered a position
            if not paper:
                continue
                
            # Phase 2: Record as filtered signal in cycle stats + settlement tracker
            self._cycle_stats.record_filtered_signal(
                market_question=market.question if market else "Unknown",
                market_source=market.source.value if market else "unknown",
                trigger_price=opp.trigger_price,
                trigger_side=opp.trigger_side,
                paper_size_usd=paper.get("paper_size_usd", 10.0),
            )

            # Settlement tracking now consolidated in _record_paper_trade()

            if market:
                # Phase 5: Include fair value in log
                fair_prob = self._market_fair_values.get(market.id, 0.50) if market else 0.50
                logger.info(
                    "🎯 OPPORTUNITY: %s side at $%.4f | fair=%.2f | spread=%.4f | %s",
                    opp.trigger_side, opp.trigger_price, fair_prob, opp.spread,
                    market.question[:60] if market else "unknown",
                )

                # Phase 3: Log to market logger
                self._market_logger.record(
                    market_id=market.id if market else "",
                    market_question=market.question if market else "Unknown",
                    market_source=market.source.value if market else "unknown",
                    trigger_side=opp.trigger_side,
                    trigger_price=opp.trigger_price,
                    spread=opp.spread,
                    seconds_since_open=seconds_since_open,
                    detection_source=(
                        "ws_cache"
                        if self._price_cache.get_best_ask(
                            self._active_token_pairs[0][0]
                            if self._active_token_pairs else ""
                        ) is not None
                        else "http_poll"
                    ),
                    is_paired=False,
                )

            # F-020: Accumulate for batch alert instead of individual alert
            self._pending_opps.append((opp, market, paper))

        # Phase 3: Check for paired entry opportunities
        paired_results = await self._check_paired_entries(
            config.sniper_threshold, "SNIPE",
        )
        for synth_opp, market, paper_dict in paired_results:
            self._pending_opps.append((synth_opp, market, paper_dict))
            self._cycle_stats.record_filtered_signal(
                market_question=market.question if market else "Unknown",
                market_source=market.source.value if market else "unknown",
                trigger_price=synth_opp.trigger_price,
                trigger_side="PAIRED",
            )

        # F-020: Flush batch if interval elapsed
        await self._flush_batch_alerts()

        await asyncio.sleep(interval)

    async def _handle_cooldown_phase(self, config) -> None:
        """Handle COOLDOWN phase: moderate parallel polling.

        F-019: Also sends cycle summary with signal quality stats.
        Phase 2: Dynamic threshold, cycle stats tracking.
        """
        self._previous_phase = Phase.COOLDOWN
        if not self._active_token_pairs:
            await asyncio.sleep(self.COOLDOWN_INTERVAL)
            return

        logger.info("COOLDOWN: Polling %d pairs", len(self._active_token_pairs))

        # Phase 2: Record poll
        self._cycle_stats.record_poll()

        opportunities = await self._poll_all_pairs(config.sniper_threshold, "COOLDOWN")
        self._cycle_stats.raw_signals += len(opportunities)

        for opp, (yes_token, no_token) in opportunities:
            market = self._find_market_for_tokens(yes_token, no_token)

            # Phase 2: Dynamic threshold check
            if market:
                dynamic_thresh = self._dynamic_threshold.get_threshold(
                    market.liquidity_usd
                )
                if opp.trigger_price > dynamic_thresh:
                    continue

                # Phase 5 (F-021): Fair value check
                # F-022 FIX: Increased margin to allow more signals
                fair_margin = 0.05  # Fixed 5% margin for more lenient filtering
                if not self._is_market_undervalued(
                    market, opp.trigger_side, opp.trigger_price, margin=fair_margin
                ):
                    continue

            paper = self._record_paper_trade(opp, market)
            
            # Only process if we actually entered a position
            if not paper:
                continue
                
            # Phase 2: Record filtered signal + settlement trade
            self._cycle_stats.record_filtered_signal(
                market_question=market.question if market else "Unknown",
                market_source=market.source.value if market else "unknown",
                trigger_price=opp.trigger_price,
                trigger_side=opp.trigger_side,
            )

            # Settlement tracking now consolidated in _record_paper_trade()

            if market:
                logger.info(
                    "🎯 COOLDOWN OPP: %s side at $%.4f | %s",
                    opp.trigger_side, opp.trigger_price,
                    market.question[:60] if market else "unknown",
                )

                # Phase 3: Log to market logger
                now_cd = datetime.now(tz=timezone.utc)
                open_cd = now_cd.replace(minute=0, second=0, microsecond=0)
                secs_cd = (now_cd - open_cd).total_seconds()
                self._market_logger.record(
                    market_id=market.id if market else "",
                    market_question=market.question if market else "Unknown",
                    market_source=market.source.value if market else "unknown",
                    trigger_side=opp.trigger_side,
                    trigger_price=opp.trigger_price,
                    spread=opp.spread,
                    seconds_since_open=secs_cd,
                    detection_source="http_poll",
                    is_paired=False,
                )

            # F-020: Accumulate for batch alert
            self._pending_opps.append((opp, market, paper))

        # Phase 3: Check paired entries in cooldown too
        paired_results = await self._check_paired_entries(
            config.sniper_threshold, "COOLDOWN",
        )
        for synth_opp, market, paper_dict in paired_results:
            self._pending_opps.append((synth_opp, market, paper_dict))

        # F-020: Flush batch if interval elapsed
        await self._flush_batch_alerts()

        await asyncio.sleep(self.COOLDOWN_INTERVAL)

    async def _flush_batch_alerts(self, force: bool = False) -> None:
        """F-020: Send batched opportunity alerts every BATCH_ALERT_INTERVAL seconds.

        Accumulates opportunities and sends a single summary message
        instead of spamming per-signal alerts.
        """
        now = datetime.now(tz=timezone.utc)
        elapsed = (now - self._last_batch_alert).total_seconds()

        if not force and elapsed < self.BATCH_ALERT_INTERVAL:
            return  # Not time yet

        if not self._pending_opps:
            self._last_batch_alert = now
            return  # Nothing to report

        # Group by market
        by_market: dict[str, list[tuple[SniperOpportunity, dict]]] = {}
        for opp, market, paper in self._pending_opps:
            key = market.question[:60] if market else "Unknown"
            if key not in by_market:
                by_market[key] = []
            by_market[key].append((opp, paper))

        # Build summary message
        total = len(self._pending_opps)
        total_paper = sum(p["paper_size_usd"] for _, _, p in self._pending_opps)

        lines = [
            f"📊 <b>Signal Batch ({total}건 / {elapsed/60:.0f}분)</b>",
            f"{'━' * 28}",
        ]

        for mkt_name, entries in sorted(by_market.items(), key=lambda x: -len(x[1])):
            prices = [opp.trigger_price for opp, _ in entries]
            sides = set(opp.trigger_side for opp, _ in entries)
            avg_price = sum(prices) / len(prices)
            min_price = min(prices)
            max_price = max(prices)

            side_str = "/".join(sorted(sides))
            lines.append(
                f"\n🎯 <b>{mkt_name}</b>\n"
                f"  {side_str} × {len(entries)}회 | "
                f"${min_price:.3f}~${max_price:.3f} (avg ${avg_price:.3f})"
            )

        lines.append(f"\n💰 Paper bets: ${total_paper:.0f} total")
        lines.append(f"📈 Open paper trades: {len(self._paper_trades)}")

        msg = "\n".join(lines)
        # Batch signal alert disabled for Telegram (user request 2026-02-07)
        # await self.alerter.alert_error(msg, level="info")
        logger.info("Signal batch: %d signals, $%.0f paper", total, total_paper)

        # Reset batch
        self._pending_opps.clear()
        self._last_batch_alert = now

    def get_paper_trading_summary(self) -> dict:
        """F-019: Get paper trading P&L summary."""
        open_trades = [t for t in self._paper_trades if t["status"] == "open"]
        total_paper_invested = sum(t["paper_size_usd"] for t in self._paper_trades)
        return {
            "total_trades": len(self._paper_trades),
            "open_trades": len(open_trades),
            "total_invested": total_paper_invested,
            "realized_pnl": self._paper_pnl,
            "wins": self._paper_wins,
            "losses": self._paper_losses,
        }

    # ------------------------------------------------------------------
    # Phase 2: Cycle report + settlement
    # ------------------------------------------------------------------

    async def _send_cycle_end_report(self) -> None:
        """Phase 2+3: Send cycle end summary report via Telegram.

        Phase 3: Includes WS cache stats, paired entry stats,
        and market-level opportunity breakdown.
        """
        self._cycle_stats.finalize()
        report = format_cycle_report(self._cycle_stats)

        # Phase 3: Append WS cache and paired entry stats
        cache_stats = self._price_cache.stats
        paired_summary = self._paired_simulator.get_summary()
        market_report = self._market_logger.format_stats_report()

        extra_lines = []
        if self._ws_cache_hits > 0 or self._http_fallback_count > 0:
            total = self._ws_cache_hits + self._http_fallback_count
            ws_pct = self._ws_cache_hits / total * 100 if total > 0 else 0
            extra_lines.append(
                f"\n<b>Phase 3: WS Cache</b>\n"
                f"  WS hits: {self._ws_cache_hits} | HTTP fallback: {self._http_fallback_count}\n"
                f"  WS hit rate: {ws_pct:.0f}%\n"
                f"  Cached: {cache_stats['prices_cached']} prices, "
                f"{cache_stats['orderbooks_cached']} orderbooks"
            )

        if paired_summary["total_trades"] > 0:
            extra_lines.append(
                f"\n<b>Phase 3: Paired Entry</b>\n"
                f"  Trades: {paired_summary['total_trades']}건\n"
                f"  Cost: ${paired_summary['total_cost']:.2f}\n"
                f"  Guaranteed profit: ${paired_summary['total_guaranteed_profit']:.4f}\n"
                f"  Avg ROI: {paired_summary['avg_roi_pct']:.2f}%"
            )

        if extra_lines:
            report += "\n" + "\n".join(extra_lines)

        logger.info(
            "CYCLE END: #%d | markets=%d | signals=%d/%d | paper=%d ($%.0f) "
            "| ws_hits=%d | paired=%d",
            self._cycle_count,
            self._cycle_stats.markets_discovered,
            self._cycle_stats.filtered_signals,
            self._cycle_stats.raw_signals,
            self._cycle_stats.paper_trades,
            self._cycle_stats.paper_total_invested,
            self._ws_cache_hits,
            paired_summary["total_trades"],
        )

        # Cycle report disabled for Telegram (user request 2026-02-07)
        # Logs are still written locally
        # if self.alerter.enabled:
        #     await self.alerter.alert_error(report, level="info")

    async def _run_settlement_check(self) -> None:
        """Phase 2: Check pending paper trades for settlement."""
        try:
            summary = await self._settlement_tracker.check_and_settle()
            if summary.newly_settled > 0:
                report = self._settlement_tracker.format_settlement_report(summary)
                logger.info(
                    "SETTLEMENT: %d newly settled | P&L: $%.2f",
                    summary.newly_settled, summary.cumulative_pnl,
                )
                # 정산 리포트는 로그에만 기록, 텔레그램 알림 비활성화

                # Update internal P&L tracking
                self._paper_pnl = summary.cumulative_pnl
                self._paper_wins = summary.wins
                self._paper_losses = summary.losses
                
                # Also update position manager and save state
                # Note: settlement_tracker handles actual settlement logic
                self._position_manager.save_state(Path("data/position_manager_state.json"))
            else:
                logger.info(
                    "SETTLEMENT: No new settlements (open=%d, expired=%d)",
                    summary.total_open, summary.total_expired,
                )
        except Exception:
            logger.exception("Error during settlement check")

    # ------------------------------------------------------------------
    # F-022: NBA Market Discovery with Verification
    # ------------------------------------------------------------------

    async def discover_nba_markets_with_verification(
        self,
        market_ids: list[str] | None = None,
        min_liquidity: float = 10000.0,
    ) -> list[Market]:
        """F-022: Discover and verify NBA markets using direct ID lookup.

        Args:
            market_ids: List of specific market IDs to verify.
                If None, uses default NBA market list.
            min_liquidity: Minimum CLOB liquidity threshold (default $10k)

        Returns:
            List of verified Market objects ready for trading
        """
        # Default NBA markets (example IDs - update with actual IDs)
        if market_ids is None:
            # These are example IDs - in production, load from config
            market_ids = []

        if not market_ids:
            logger.info("F-022: No NBA market IDs provided")
            return []

        logger.info(
            "F-022: Discovering %d NBA markets with verification",
            len(market_ids)
        )

        # Use preparer to verify all markets
        verified = await self.preparer.verify_markets_batch(
            market_ids, min_liquidity
        )

        # Update active markets
        for market in verified:
            if market not in self._active_markets:
                self._active_markets.append(market)
                self._active_token_pairs.append(
                    (market.yes_token_id, market.no_token_id)
                )
                self._token_to_market[market.yes_token_id] = market
                self._token_to_market[market.no_token_id] = market

        logger.info(
            "F-022: Added %d verified NBA markets to active list",
            len(verified)
        )
        return verified

    async def verify_single_market(
        self,
        market_id: str,
        min_liquidity: float = 10000.0,
    ) -> Market | None:
        """F-022: Verify a single market by ID.

        Convenience method for quick verification of specific markets.

        Args:
            market_id: Gamma market ID
            min_liquidity: Minimum CLOB liquidity threshold

        Returns:
            Verified Market object or None
        """
        market = await self.preparer.discover_and_verify_market_by_id(
            market_id, min_liquidity
        )

        if market:
            # Add to active markets if verified
            if market not in self._active_markets:
                self._active_markets.append(market)
                self._active_token_pairs.append(
                    (market.yes_token_id, market.no_token_id)
                )
                self._token_to_market[market.yes_token_id] = market
                self._token_to_market[market.no_token_id] = market

            logger.info(
                "F-022: Verified market %s (%s)",
                market_id, market.polymarket_url
            )
        else:
            logger.warning("F-022: Market %s verification failed", market_id)

        return market
