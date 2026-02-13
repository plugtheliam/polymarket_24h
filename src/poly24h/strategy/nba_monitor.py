"""F-025: NBA Independent Monitor — Sportsbook Arbitrage.

Independent 5-min scan loop that runs parallel to the hourly crypto sniper.
Discovers NBA markets on Polymarket, compares to sportsbook odds (via The Odds API),
and enters paper trades when edge >= 3%.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_SCAN_INTERVAL = 300  # 5 minutes
DEFAULT_MIN_EDGE = 0.03      # 3%
DEFAULT_MAX_PER_GAME = 500.0  # $500 per game event
DEFAULT_DAILY_LOSS_LIMIT = 300.0  # $300
DEFAULT_KELLY_FRACTION = 0.50  # Half-Kelly


class NBAMonitor:
    """NBA continuous monitoring — sportsbook line vs Polymarket arbitrage detection."""

    def __init__(
        self,
        odds_client,
        market_scanner,
        position_manager,
        orderbook_fetcher,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        min_edge: float = DEFAULT_MIN_EDGE,
        max_per_game: float = DEFAULT_MAX_PER_GAME,
        daily_loss_limit: float = DEFAULT_DAILY_LOSS_LIMIT,
        kelly_fraction: float = DEFAULT_KELLY_FRACTION,
    ):
        self._odds_client = odds_client
        self._scanner = market_scanner
        self._pm = position_manager
        self._fetcher = orderbook_fetcher
        self._scan_interval = scan_interval
        self._min_edge = min_edge
        self._max_per_game = max_per_game
        self._daily_loss_limit = daily_loss_limit
        self._kelly_fraction = kelly_fraction

        # Per-game investment tracking
        self._game_invested: dict[str, float] = defaultdict(float)
        # Daily P&L tracking
        self._daily_pnl: float = 0.0

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run_forever(self) -> None:
        """5-min scan loop — runs as background asyncio task."""
        logger.info("NBA Monitor started (interval=%ds, min_edge=%.1f%%)",
                     self._scan_interval, self._min_edge * 100)
        while True:
            try:
                stats = await self.scan_and_trade()
                logger.info(
                    "NBA SCAN: %d markets | %d matched | %d edges | %d trades",
                    stats["markets_found"], stats.get("matched", 0),
                    stats["edges_found"], stats["trades_entered"],
                )
            except Exception:
                logger.exception("NBA Monitor scan error")
            await asyncio.sleep(self._scan_interval)

    # ------------------------------------------------------------------
    # Core: one scan cycle
    # ------------------------------------------------------------------

    async def scan_and_trade(self) -> dict:
        """One cycle: discover → odds compare → enter.

        Returns:
            Stats dict with markets_found, matched, edges_found, trades_entered.
        """
        stats = {
            "markets_found": 0,
            "matched": 0,
            "edges_found": 0,
            "trades_entered": 0,
        }

        # 0. Ensure GammaClient session is open
        if hasattr(self._scanner, 'client'):
            await self._scanner.client.open()

        # 1. Discover NBA markets
        markets = await self._scanner.discover_nba_markets()
        stats["markets_found"] = len(markets)

        if not markets:
            return stats

        # 2. Fetch sportsbook odds
        games = await self._odds_client.fetch_nba_odds()

        # 3. For each market, find fair value and check edge
        for market in markets:
            fair_prob = self._odds_client.get_fair_prob_for_market(market, games)
            if fair_prob is None:
                continue
            stats["matched"] += 1

            # 4. Get CLOB prices
            yes_ask, no_ask = await self._fetcher.fetch_best_asks(
                market.yes_token_id, market.no_token_id,
            )
            if yes_ask is None or no_ask is None:
                continue

            # 5. Calculate edges
            edge_yes, edge_no = self.calculate_edges(fair_prob, yes_ask, no_ask)

            # 6. Check if either side has edge
            if edge_yes >= self._min_edge or edge_no >= self._min_edge:
                stats["edges_found"] += 1

                # Try entry on the better side
                if edge_yes >= edge_no and edge_yes >= self._min_edge:
                    result = await self.try_enter(market, "YES", yes_ask, edge_yes)
                elif edge_no >= self._min_edge:
                    result = await self.try_enter(market, "NO", no_ask, edge_no)
                else:
                    result = None

                if result is not None:
                    stats["trades_entered"] += 1
            else:
                logger.debug(
                    "NBA SKIP: %s | fair=%.3f | yes_ask=%.3f edge=%.1f%% | no_ask=%.3f edge=%.1f%%",
                    market.question[:50], fair_prob,
                    yes_ask, edge_yes * 100, no_ask, edge_no * 100,
                )

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
        """Calculate edge for YES and NO sides.

        Args:
            fair_prob: Devigged fair probability for YES outcome.
            yes_price: Current YES ask price on Polymarket.
            no_price: Current NO ask price on Polymarket.

        Returns:
            (edge_yes, edge_no) — positive means undervalued.
        """
        edge_yes = fair_prob - yes_price
        edge_no = (1.0 - fair_prob) - no_price
        return edge_yes, edge_no

    # ------------------------------------------------------------------
    # Entry logic
    # ------------------------------------------------------------------

    async def try_enter(
        self,
        market,
        side: str,
        price: float,
        edge: float,
    ):
        """Attempt to enter a paper trade.

        Returns:
            Position object if entered, None if skipped.
        """
        # Edge threshold
        if edge < self._min_edge:
            return None

        # Already have position?
        if not self._pm.can_enter(market.id):
            return None

        # Daily loss limit
        if self.is_daily_loss_exceeded():
            logger.info("NBA DAILY LOSS LIMIT: P&L=$%.2f, limit=-$%.2f",
                        self._daily_pnl, self._daily_loss_limit)
            return None

        # Kelly sizing
        size = self.get_kelly_size(edge, price)
        if size <= 0:
            return None

        # Per-game cap
        event_id = getattr(market, "event_id", "")
        if event_id:
            size = self.cap_for_game(event_id, size)
            if size <= 0:
                return None

        # Enter position
        end_date = ""
        if hasattr(market, "end_date"):
            end_date = market.end_date.isoformat() if hasattr(market.end_date, "isoformat") else str(market.end_date)

        position = self._pm.enter_position(
            market_id=market.id,
            market_question=market.question,
            side=side,
            price=price,
            end_date=end_date,
            event_id=event_id,
            size_override=size,
        )

        if position is not None:
            # Track game investment
            if event_id:
                self._game_invested[event_id] += position.size_usd

            logger.info(
                "NBA ENTRY: %s %s @ $%.3f | edge=%.1f%% | size=$%.2f | game_total=$%.2f",
                side, market.question[:50], price, edge * 100,
                position.size_usd, self._game_invested.get(event_id, 0),
            )

        return position

    # ------------------------------------------------------------------
    # Per-game limit
    # ------------------------------------------------------------------

    def cap_for_game(self, event_id: str, amount: float) -> float:
        """Cap investment amount for a game event.

        Args:
            event_id: Game event identifier.
            amount: Desired investment amount.

        Returns:
            Capped amount (0 if game budget exhausted).
        """
        already = self._game_invested.get(event_id, 0.0)
        remaining = self._max_per_game - already
        if remaining <= 0:
            return 0.0
        return min(amount, remaining)

    # ------------------------------------------------------------------
    # Kelly sizing
    # ------------------------------------------------------------------

    def get_kelly_size(self, edge: float, price: float) -> float:
        """Calculate position size using Half-Kelly.

        Args:
            edge: Edge magnitude (e.g. 0.05 = 5%).
            price: Market price for the side being traded.

        Returns:
            Position size in USD.
        """
        return self._pm.calculate_kelly_size(
            edge=edge,
            market_price=price,
            fraction=self._kelly_fraction,
        )

    # ------------------------------------------------------------------
    # Daily loss limit
    # ------------------------------------------------------------------

    def is_daily_loss_exceeded(self) -> bool:
        """Check if daily P&L has exceeded loss limit.

        Returns:
            True if daily P&L < -daily_loss_limit.
        """
        return self._daily_pnl < -self._daily_loss_limit

    def update_daily_pnl(self, pnl: float) -> None:
        """Update daily P&L after a settlement."""
        self._daily_pnl += pnl

    def reset_daily(self) -> None:
        """Reset daily tracking (call at start of each trading day)."""
        self._daily_pnl = 0.0
        self._game_invested.clear()
