"""Event-driven scheduler for market open sniping (F-018).

Provides event-driven scheduling for crypto market opens that occur every hour.
Switches between phases:
- IDLE: >30s before open, low-frequency scan (5min interval)
- PRE_OPEN: 30s before open, discover markets + warm connections
- SNIPE: 0-60s after open, rapid orderbook polling (3s interval)
- COOLDOWN: 60-120s after open, moderate polling (15s interval)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

import aiohttp

from poly24h.discovery.gamma_client import GammaClient
from poly24h.models.market import Market, MarketSource
from poly24h.monitoring.telegram import TelegramAlerter
from poly24h.strategy.orderbook_scanner import ClobOrderbookFetcher

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
    """Discovers upcoming markets and warms CLOB connections."""

    def __init__(self, gamma_client: GammaClient):
        self.gamma_client = gamma_client

    async def discover_upcoming_markets(self) -> list[Market]:
        """Call GammaClient to find markets opening soon."""
        events = await self.gamma_client.fetch_events(tag="crypto", limit=100)

        markets: list[Market] = []
        for event in events:
            event_id = event.get("id", "")
            event_title = event.get("title", "")

            for market_data in event.get("markets", []):
                market_id = market_data.get("id", "")
                question = market_data.get("question", "")

                # Extract token IDs
                tokens = market_data.get("tokens", [])
                yes_token_id = None
                no_token_id = None

                for token in tokens:
                    outcome = token.get("outcome", "")
                    if outcome.lower() == "yes":
                        yes_token_id = token.get("token_id")
                    elif outcome.lower() == "no":
                        no_token_id = token.get("token_id")

                if yes_token_id and no_token_id:
                    market = Market(
                        id=market_id,
                        question=question,
                        source=MarketSource.HOURLY_CRYPTO,
                        yes_token_id=yes_token_id,
                        no_token_id=no_token_id,
                        yes_price=0.5,  # Default values
                        no_price=0.5,
                        liquidity_usd=0.0,
                        end_date=datetime.now(tz=timezone.utc) + timedelta(hours=1),
                        event_id=event_id,
                        event_title=event_title,
                    )
                    markets.append(market)

        return markets

    def extract_token_pairs(self, markets: list[Market]) -> list[tuple[str, str]]:
        """Extract (yes_token, no_token) pairs from markets."""
        return [(market.yes_token_id, market.no_token_id) for market in markets]

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


class RapidOrderbookPoller:
    """High-frequency orderbook polling during snipe window."""

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
        """Detect opportunity from snapshot using threshold."""
        if snapshot.yes_best_ask is None and snapshot.no_best_ask is None:
            return None

        # Check YES side
        if (snapshot.yes_best_ask is not None and
            snapshot.yes_best_ask <= threshold):
            return SniperOpportunity(
                trigger_price=snapshot.yes_best_ask,
                trigger_side="YES",
                spread=snapshot.spread or 0.0,
                timestamp=snapshot.timestamp
            )

        # Check NO side
        if (snapshot.no_best_ask is not None and
            snapshot.no_best_ask <= threshold):
            return SniperOpportunity(
                trigger_price=snapshot.no_best_ask,
                trigger_side="NO",
                spread=snapshot.spread or 0.0,
                timestamp=snapshot.timestamp
            )

        return None


class EventDrivenLoop:
    """Main orchestration loop for event-driven market open sniping."""

    def __init__(
        self,
        schedule: MarketOpenSchedule,
        preparer: PreOpenPreparer,
        poller: RapidOrderbookPoller,
        alerter: TelegramAlerter
    ):
        self.schedule = schedule
        self.preparer = preparer
        self.poller = poller
        self.alerter = alerter
        self._active_token_pairs: list[tuple[str, str]] = []

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

    async def _handle_idle_phase(self, now: datetime, config) -> None:
        """Handle IDLE phase: sleep until pre_open window or run background scan."""
        seconds_until_open = self.schedule.seconds_until_open(now)
        sleep_until_pre_open = seconds_until_open - config.pre_open_window_secs

        if sleep_until_pre_open > 300:  # More than 5 minutes
            # Run background dutch book scan, then sleep
            logger.info("IDLE: Running background scan, then sleeping %ds", sleep_until_pre_open)
            await asyncio.sleep(300)  # Background scan every 5 minutes
        else:
            # Sleep until pre-open window
            if sleep_until_pre_open > 0:
                logger.info("IDLE: Sleeping %ds until pre-open", sleep_until_pre_open)
                await asyncio.sleep(sleep_until_pre_open)

    async def _handle_pre_open_phase(self, config) -> None:
        """Handle PRE_OPEN phase: discover markets, warm connections."""
        logger.info("PRE_OPEN: Discovering markets and warming connections")

        # Discover upcoming markets
        markets = await self.preparer.discover_upcoming_markets()
        self._active_token_pairs = self.preparer.extract_token_pairs(markets)

        # Warm CLOB connections for all token pairs
        warm_tasks = []
        for yes_token, no_token in self._active_token_pairs:
            warm_tasks.append(self.preparer.warm_clob_connection(yes_token))
            warm_tasks.append(self.preparer.warm_clob_connection(no_token))

        if warm_tasks:
            await asyncio.gather(*warm_tasks, return_exceptions=True)

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

    async def _poll_all_pairs(
        self, threshold: float, phase_label: str = "SNIPE",
    ) -> list[SniperOpportunity]:
        """Poll all active token pairs in parallel, return opportunities."""
        if not self._active_token_pairs:
            return []

        async def _poll_one(yes_token: str, no_token: str) -> SniperOpportunity | None:
            try:
                snapshot = await self.poller.poll_once(yes_token, no_token)
                return self.poller.detect_opportunity(snapshot, threshold)
            except Exception as exc:
                logger.error("[%s] Error polling %s/%s: %s", phase_label, yes_token, no_token, exc)
                return None

        results = await asyncio.gather(
            *[_poll_one(yt, nt) for yt, nt in self._active_token_pairs],
            return_exceptions=True,
        )
        return [r for r in results if isinstance(r, SniperOpportunity)]

    async def _handle_snipe_phase(self, config) -> None:
        """Handle SNIPE phase: rapid parallel orderbook polling with tiered intervals."""
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
            "SNIPE: Polling %d pairs | T+%.1fs | interval=%.2fs",
            len(self._active_token_pairs), seconds_since_open, interval,
        )

        opportunities = await self._poll_all_pairs(config.sniper_threshold, "SNIPE")

        for opp in opportunities:
            logger.info(
                "🎯 OPPORTUNITY: %s side at %.4f (spread=%.4f)",
                opp.trigger_side, opp.trigger_price, opp.spread,
            )
            await self.alerter.alert_error(
                f"🎯 <b>Sniper Opportunity</b>\n"
                f"{'━' * 24}\n"
                f"Side: {opp.trigger_side}\n"
                f"Price: ${opp.trigger_price:.4f}\n"
                f"Spread: ${opp.spread:.4f}\n"
                f"T+{seconds_since_open:.1f}s",
                level="info",
            )

        await asyncio.sleep(interval)

    async def _handle_cooldown_phase(self, config) -> None:
        """Handle COOLDOWN phase: moderate parallel polling."""
        if not self._active_token_pairs:
            await asyncio.sleep(self.COOLDOWN_INTERVAL)
            return

        logger.info("COOLDOWN: Polling %d pairs", len(self._active_token_pairs))

        opportunities = await self._poll_all_pairs(config.sniper_threshold, "COOLDOWN")

        for opp in opportunities:
            await self.alerter.alert_error(
                f"🎯 <b>Sniper (Cooldown)</b>\n"
                f"Side: {opp.trigger_side} | "
                f"Price: ${opp.trigger_price:.4f}",
                level="info",
            )

        await asyncio.sleep(self.COOLDOWN_INTERVAL)
