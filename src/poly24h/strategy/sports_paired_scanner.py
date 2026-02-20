"""F-032b/d: Sports Paired Entry Scanner.

Scans all sports markets for YES+NO CPP (Combined Purchase Price) < threshold.
No fair value needed — pure market structure arbitrage.

When YES best ask + NO best ask < threshold (e.g., 0.96), buying both sides
guarantees a profit at settlement regardless of outcome.

F-032d: run_forever() loop, 24H settlement filter, paired position tracking.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PAPER_TRADE_DIR = "data/paper_trades"


class SportsPairedScanner:
    """Scan sports markets for paired entry (CPP < threshold) arbitrage.

    Fair value not required — this is market-neutral arbitrage.
    If YES@0.45 + NO@0.48 = 0.93, buying both guarantees $0.07/share profit.
    """

    def __init__(
        self,
        orderbook_fetcher,
        position_manager,
        cpp_threshold: float = 0.96,
        min_price: float = 0.02,
        max_hours_to_settle: float = 24.0,
        min_hours_to_settle: float = 1.0,
        market_scanner=None,
        sport_configs: list | None = None,
        scan_interval: float = 300.0,
        paper_trade_dir: str = DEFAULT_PAPER_TRADE_DIR,
        paper_size_usd: float = 20.0,
    ):
        self._fetcher = orderbook_fetcher
        self._pm = position_manager
        self._cpp_threshold = cpp_threshold
        self._min_price = min_price
        self._max_hours = max_hours_to_settle
        self._min_hours = min_hours_to_settle
        self._market_scanner = market_scanner
        self._sport_configs = sport_configs or []
        self._scan_interval = scan_interval
        self._paper_trade_dir = Path(paper_trade_dir)
        self._paper_size_usd = paper_size_usd

        # Internal paired position tracking (bypasses PositionManager 1-per-market limit)
        self.paired_positions: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run_forever(self) -> None:
        """Continuous scan loop — discover markets, check CPP, enter paired."""
        logger.info(
            "SportsPairedScanner started (CPP<%.2f, settle=%d-%dH, interval=%ds)",
            self._cpp_threshold, self._min_hours, self._max_hours, self._scan_interval,
        )
        while True:
            try:
                stats = await self._scan_cycle()
                logger.info(
                    "PAIRED SCAN: %d markets | %d opportunities | %d entries",
                    stats.get("markets", 0),
                    stats.get("opportunities", 0),
                    stats.get("entries", 0),
                )
            except Exception:
                logger.exception("SportsPairedScanner scan error")
            await asyncio.sleep(self._scan_interval)

    async def _scan_cycle(self) -> dict:
        """One scan cycle: discover → filter → check CPP → enter."""
        stats = {"markets": 0, "opportunities": 0, "entries": 0}

        # Discover markets from all sport configs
        all_markets = []
        if self._market_scanner:
            for cfg in self._sport_configs:
                try:
                    markets = await self._market_scanner.discover_sport_markets(cfg)
                    all_markets.extend(markets)
                except Exception as e:
                    logger.warning("Discovery failed for %s: %s", cfg, e)

        stats["markets"] = len(all_markets)

        # Scan for CPP opportunities
        opportunities = await self.scan_markets(all_markets)
        stats["opportunities"] = len(opportunities)

        # Enter paired positions for each opportunity
        for opp in opportunities:
            market_id = opp["market_id"]
            if market_id in self.paired_positions:
                continue  # Already entered

            result = self.enter_paired_position(opp, size_usd=self._paper_size_usd)
            if result is not None:
                stats["entries"] += 1

        return stats

    # ------------------------------------------------------------------
    # Market scanning with 24H filter
    # ------------------------------------------------------------------

    async def scan_markets(self, markets: list) -> list[dict]:
        """Scan markets for CPP < threshold opportunities.

        Applies 24H settlement filter: only markets settling within
        max_hours_to_settle but at least min_hours_to_settle from now.

        Returns list of opportunity dicts.
        """
        opportunities: list[dict] = []
        now = datetime.now(timezone.utc)

        for market in markets:
            # Skip if already have paired position
            if market.id in self.paired_positions:
                continue

            # Skip if PositionManager already has a position
            if not self._pm.can_enter(market.id):
                continue

            # 24H settlement filter
            if not self._is_within_settlement_window(market, now):
                continue

            try:
                yes_ask, no_ask = await self._fetcher.fetch_best_asks(
                    market.yes_token_id, market.no_token_id,
                )
            except Exception as e:
                logger.debug("Orderbook fetch failed for %s: %s", market.id, e)
                continue

            # Skip if either side has no liquidity
            if yes_ask is None or no_ask is None:
                continue

            # Skip garbage prices
            if yes_ask < self._min_price or no_ask < self._min_price:
                continue

            cpp = yes_ask + no_ask

            if cpp < self._cpp_threshold:
                spread = 1.0 - cpp
                roi_pct = (spread / cpp) * 100 if cpp > 0 else 0.0

                end_date = getattr(market, "end_date", "")
                if hasattr(end_date, "isoformat"):
                    end_date = end_date.isoformat()

                opp = {
                    "market_id": market.id,
                    "question": getattr(market, "question", ""),
                    "yes_ask": yes_ask,
                    "no_ask": no_ask,
                    "cpp": cpp,
                    "spread": spread,
                    "roi_pct": roi_pct,
                    "end_date": end_date,
                    "event_id": getattr(market, "event_id", ""),
                }
                opportunities.append(opp)

                logger.info(
                    "SPORTS PAIRED: %s | YES@%.3f + NO@%.3f = CPP %.3f | ROI %.1f%%",
                    getattr(market, "question", "")[:50],
                    yes_ask, no_ask, cpp, roi_pct,
                )

        return opportunities

    # ------------------------------------------------------------------
    # 24H settlement window filter
    # ------------------------------------------------------------------

    def _is_within_settlement_window(self, market, now: datetime) -> bool:
        """Check if market settles within the configured window.

        Returns True if: min_hours < time_to_settle < max_hours
        """
        end_date = getattr(market, "end_date", None)
        if end_date is None:
            return False

        try:
            if isinstance(end_date, str):
                end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            elif isinstance(end_date, datetime):
                end_dt = end_date
            else:
                return False
        except (ValueError, TypeError):
            return False

        time_to_settle = (end_dt - now).total_seconds() / 3600.0

        # Must settle within max_hours and at least min_hours away
        if time_to_settle < self._min_hours:
            return False
        if time_to_settle > self._max_hours:
            return False

        return True

    # ------------------------------------------------------------------
    # Paired position entry + tracking
    # ------------------------------------------------------------------

    def enter_paired_position(self, opp: dict, size_usd: float = 20.0) -> dict | None:
        """Enter a paired position (paper trade): buy both YES and NO.

        Splits size_usd proportionally between YES and NO based on prices.
        Tracks internally (not via PositionManager) to allow both sides.
        Logs to JSONL for analysis.
        """
        market_id = opp["market_id"]
        if market_id in self.paired_positions:
            return None

        yes_ask = opp["yes_ask"]
        no_ask = opp["no_ask"]
        cpp = opp["cpp"]

        if cpp <= 0 or yes_ask <= 0 or no_ask <= 0:
            return None

        # Calculate shares: buy equal number of shares on both sides
        # Total cost per share = cpp, so shares = size_usd / cpp
        shares = size_usd / cpp
        yes_cost = shares * yes_ask
        no_cost = shares * no_ask
        total_cost = yes_cost + no_cost

        # Guaranteed profit = shares * (1.0 - cpp) = shares * spread
        guaranteed_profit = shares * opp["spread"]
        roi_pct = (guaranteed_profit / total_cost) * 100 if total_cost > 0 else 0.0

        now = datetime.now(timezone.utc)
        record = {
            "market_id": market_id,
            "question": opp.get("question", ""),
            "yes_ask": yes_ask,
            "no_ask": no_ask,
            "cpp": cpp,
            "shares": shares,
            "yes_cost": yes_cost,
            "no_cost": no_cost,
            "total_cost": total_cost,
            "guaranteed_profit": guaranteed_profit,
            "roi_pct": roi_pct,
            "end_date": opp.get("end_date", ""),
            "entry_time": now.isoformat(),
            "status": "open",
        }

        # Track internally
        self.paired_positions[market_id] = record

        # Log to JSONL
        self._log_paper_trade(record)

        logger.info(
            "PAIRED ENTRY: %s | $%.2f invested | guaranteed $%.2f profit (%.1f%%)",
            opp.get("question", "")[:50],
            total_cost, guaranteed_profit, roi_pct,
        )

        return record

    def _log_paper_trade(self, record: dict) -> None:
        """Append paper trade to JSONL file."""
        try:
            self._paper_trade_dir.mkdir(parents=True, exist_ok=True)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            filepath = self._paper_trade_dir / f"paired_sports_{today}.jsonl"
            with open(filepath, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.warning("Failed to log paper trade: %s", e)
