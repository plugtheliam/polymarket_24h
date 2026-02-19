"""F-026: Generic Sports Monitor — parameterized by SportConfig.

SportsMonitor generalizes NBAMonitor to support any sport.
Each instance monitors one sport/league with its own scan interval,
edge threshold, and team matching configuration.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from pathlib import Path

from poly24h.strategy.sport_config import SportConfig

logger = logging.getLogger(__name__)


class SportsMonitor:
    """Generic sports monitor — sportsbook line vs Polymarket arbitrage."""

    def __init__(
        self,
        sport_config: SportConfig,
        odds_client,
        market_scanner,
        position_manager,
        orderbook_fetcher,
        rate_limiter=None,
        daily_loss_limit: float = 300.0,
        kelly_fraction: float = 0.50,
        enable_settlement_sniper: bool = False,
        sport_executor=None,
    ):
        self._config = sport_config
        self._odds_client = odds_client
        self._scanner = market_scanner
        self._pm = position_manager
        self._fetcher = orderbook_fetcher
        self._rate_limiter = rate_limiter
        self._executor = sport_executor  # F-030: live order execution

        # Use config values
        self._scan_interval = sport_config.scan_interval
        self._min_edge = sport_config.min_edge
        self._max_per_game = sport_config.max_per_game
        self._daily_loss_limit = daily_loss_limit
        self._kelly_fraction = kelly_fraction

        # Per-game investment tracking
        self._game_invested: dict[str, float] = defaultdict(float)
        # Daily P&L tracking
        self._daily_pnl: float = 0.0

        # Settlement sniper strategy (optional)
        self._settlement_sniper = None
        if enable_settlement_sniper:
            from poly24h.strategy.settlement_sniper import SettlementSniper
            self._settlement_sniper = SettlementSniper(
                odds_client=odds_client,
                position_manager=position_manager,
                orderbook_fetcher=orderbook_fetcher,
            )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run_forever(self) -> None:
        """Scan loop — runs as background asyncio task."""
        logger.info("%s Monitor started (interval=%ds, min_edge=%.1f%%)",
                     self._config.display_name,
                     self._scan_interval, self._min_edge * 100)
        while True:
            try:
                stats = await self.scan_and_trade()
                logger.info(
                    "%s SCAN: %d markets | %d matched | %d edges | %d trades",
                    self._config.display_name,
                    stats["markets_found"], stats.get("matched", 0),
                    stats["edges_found"], stats["trades_entered"],
                )
            except Exception:
                logger.exception("%s Monitor scan error", self._config.display_name)
            await asyncio.sleep(self._scan_interval)

    # ------------------------------------------------------------------
    # Core: one scan cycle
    # ------------------------------------------------------------------

    async def scan_and_trade(self) -> dict:
        """One cycle: discover → odds compare → enter."""
        # Reset cycle budget so each sport scan has fresh allocation
        self._pm.reset_cycle_entries()

        stats = {
            "markets_found": 0,
            "matched": 0,
            "edges_found": 0,
            "trades_entered": 0,
        }

        # 0. Ensure GammaClient session is open
        if hasattr(self._scanner, 'client'):
            await self._scanner.client.open()

        # 1. Discover markets for this sport
        markets = await self._scanner.discover_sport_markets(self._config)
        stats["markets_found"] = len(markets)

        # 1.5. Filter stale markets (end_date < now + 1H)
        from poly24h.discovery.gamma_client import filter_stale_markets
        markets = filter_stale_markets(markets, buffer_hours=1.0)

        # F-028: Sort by end_date ascending — 24H settlement markets get capital first
        markets.sort(key=lambda m: m.end_date)

        if not markets:
            return stats

        # 1.6. Filter by orderbook liquidity (optional, can be disabled)
        # from poly24h.strategy.orderbook_scanner import filter_by_liquidity_async
        # markets = await filter_by_liquidity_async(
        #     markets, self._fetcher,
        #     max_spread=0.03, min_depth=200.0, max_impact=0.02
        # )

        # if not markets:
        #     return stats

        # 2. Rate limiter check
        if self._rate_limiter and not self._rate_limiter.can_fetch(self._config.name):
            logger.info("%s: Rate limited, skipping odds fetch",
                        self._config.display_name)
            return stats

        # 3. Fetch sportsbook odds
        games = await self._odds_client.fetch_odds(self._config)

        # Record the fetch with rate limiter
        if self._rate_limiter:
            # Get remaining from the latest API header (stored in _fetch_json log)
            remaining = getattr(self._odds_client, '_last_remaining', None)
            if remaining is not None:
                self._rate_limiter.record_fetch(self._config.name, remaining)

        # 3.5. Settlement sniper check (if enabled)
        if self._settlement_sniper:
            sniper_opportunities = await self._settlement_sniper.scan_settling_markets(
                markets, self._config
            )
            for market, side, price, edge in sniper_opportunities:
                result = await self._settlement_sniper.try_enter(market, side, price, edge)
                if result is not None:
                    stats["trades_entered"] += 1

        # 4. For each market, find fair value and check edge
        for market in markets:
            # Skip if already entered via settlement sniper
            if market.id in self._pm._positions:
                continue

            fair_prob = self._odds_client.get_fair_prob_for_market(
                market, games, sport_config=self._config,
            )
            if fair_prob is None:
                continue
            stats["matched"] += 1

            # 5. Get CLOB prices
            yes_ask, no_ask = await self._fetcher.fetch_best_asks(
                market.yes_token_id, market.no_token_id,
            )
            if yes_ask is None or no_ask is None:
                continue

            # 6. Calculate edges
            edge_yes, edge_no = self.calculate_edges(fair_prob, yes_ask, no_ask)

            # 7. Check if either side has edge
            if edge_yes >= self._min_edge or edge_no >= self._min_edge:
                stats["edges_found"] += 1

                if edge_yes >= edge_no and edge_yes >= self._min_edge:
                    result = await self.try_enter(market, "YES", yes_ask, edge_yes)
                elif edge_no >= self._min_edge:
                    result = await self.try_enter(market, "NO", no_ask, edge_no)
                else:
                    result = None

                if result is not None:
                    stats["trades_entered"] += 1

        return stats

    # ------------------------------------------------------------------
    # Edge calculation
    # ------------------------------------------------------------------

    def calculate_edges(
        self,
        fair_prob: float,
        yes_price: float,
        no_price: float,
    ) -> tuple[float, float]:
        """Calculate edge for YES and NO sides."""
        edge_yes = fair_prob - yes_price
        edge_no = (1.0 - fair_prob) - no_price
        return edge_yes, edge_no

    # ------------------------------------------------------------------
    # Entry logic
    # ------------------------------------------------------------------

    async def try_enter(self, market, side: str, price: float, edge: float):
        """Attempt to enter a paper trade."""
        if edge < self._min_edge:
            return None

        if not self._pm.can_enter(market.id):
            return None

        if self.is_daily_loss_exceeded():
            logger.info("%s DAILY LOSS LIMIT: P&L=$%.2f, limit=-$%.2f",
                        self._config.display_name,
                        self._daily_pnl, self._daily_loss_limit)
            return None

        size = self.get_kelly_size(edge, price)
        if size <= 0:
            return None

        event_id = getattr(market, "event_id", "")
        if event_id:
            size = self.cap_for_game(event_id, size)
            if size <= 0:
                return None

        end_date = ""
        if hasattr(market, "end_date"):
            end_date = market.end_date.isoformat() if hasattr(market.end_date, "isoformat") else str(market.end_date)

        # F-031: Live mode — submit order BEFORE recording position
        actual_price = price
        if self._executor and not self._executor.dry_run:
            token_id = market.yes_token_id if side == "YES" else market.no_token_id
            shares_estimate = size / price if price > 0 else 0
            order_result = self._executor.submit_order(
                token_id=token_id,
                side="BUY",
                price=price,
                size=shares_estimate,
            )
            if not order_result.get("success"):
                logger.warning(
                    "%s LIVE ORDER FAILED: %s | %s",
                    self._config.display_name,
                    market.question[:40],
                    order_result.get("error", "unknown"),
                )
                return None  # Order failed → no phantom position

            # Use actual fill price if available
            if order_result.get("fill_price"):
                actual_price = order_result["fill_price"]

        position = self._pm.enter_position(
            market_id=market.id,
            market_question=market.question,
            side=side,
            price=actual_price,
            end_date=end_date,
            event_id=event_id,
            size_override=size,
        )

        if position is not None:
            if event_id:
                self._game_invested[event_id] += position.size_usd

            logger.info(
                "%s ENTRY: %s %s @ $%.3f | edge=%.1f%% | size=$%.2f",
                self._config.display_name,
                side, market.question[:50], actual_price, edge * 100,
                position.size_usd,
            )
            self._pm.save_state(Path("data/position_manager_state.json"))

        return position

    # ------------------------------------------------------------------
    # Per-game limit
    # ------------------------------------------------------------------

    def cap_for_game(self, event_id: str, amount: float) -> float:
        """Cap investment amount for a game event."""
        already = self._game_invested.get(event_id, 0.0)
        remaining = self._max_per_game - already
        if remaining <= 0:
            return 0.0
        return min(amount, remaining)

    # ------------------------------------------------------------------
    # Kelly sizing
    # ------------------------------------------------------------------

    def get_kelly_size(self, edge: float, price: float) -> float:
        """Calculate position size using Half-Kelly."""
        return self._pm.calculate_kelly_size(
            edge=edge,
            market_price=price,
            fraction=self._kelly_fraction,
        )

    # ------------------------------------------------------------------
    # Daily loss limit
    # ------------------------------------------------------------------

    def is_daily_loss_exceeded(self) -> bool:
        """Check if daily P&L has exceeded loss limit."""
        return self._daily_pnl < -self._daily_loss_limit

    def update_daily_pnl(self, pnl: float) -> None:
        """Update daily P&L after a settlement."""
        self._daily_pnl += pnl

    def reset_daily(self) -> None:
        """Reset daily tracking."""
        self._daily_pnl = 0.0
        self._game_invested.clear()
