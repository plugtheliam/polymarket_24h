"""F-032b: Sports Paired Entry Scanner.

Scans all sports markets for YES+NO CPP (Combined Purchase Price) < threshold.
No fair value needed — pure market structure arbitrage.

When YES best ask + NO best ask < threshold (e.g., 0.96), buying both sides
guarantees a profit at settlement regardless of outcome.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


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
    ):
        self._fetcher = orderbook_fetcher
        self._pm = position_manager
        self._cpp_threshold = cpp_threshold
        self._min_price = min_price

    async def scan_markets(self, markets: list) -> list[dict]:
        """Scan markets for CPP < threshold opportunities.

        For each market:
        1. Fetch YES/NO best asks from CLOB orderbook
        2. If CPP < threshold, report as opportunity

        Returns list of opportunity dicts with keys:
            market_id, question, yes_ask, no_ask, cpp, spread, roi_pct
        """
        opportunities: list[dict] = []

        for market in markets:
            # Skip if already have position in this market
            if not self._pm.can_enter(market.id):
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

                opp = {
                    "market_id": market.id,
                    "question": market.question,
                    "yes_ask": yes_ask,
                    "no_ask": no_ask,
                    "cpp": cpp,
                    "spread": spread,
                    "roi_pct": roi_pct,
                    "end_date": getattr(market, "end_date", ""),
                    "event_id": getattr(market, "event_id", ""),
                }
                opportunities.append(opp)

                logger.info(
                    "SPORTS PAIRED: %s | YES@%.3f + NO@%.3f = CPP %.3f | ROI %.1f%%",
                    market.question[:50], yes_ask, no_ask, cpp, roi_pct,
                )

        return opportunities
