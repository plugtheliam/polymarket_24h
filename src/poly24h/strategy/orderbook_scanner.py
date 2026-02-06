"""Orderbook-based arbitrage scanning (F-014).

CLOB API 오더북에서 best ask 가격을 조회하여 YES_ask + NO_ask < 1.0 아비트라지를 감지.
기존 mid-price 기반 dutch_book.py와 독립적으로 동작.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from poly24h.models.market import Market
from poly24h.models.opportunity import ArbType, Opportunity

logger = logging.getLogger(__name__)

CLOB_BOOK_URL = "https://clob.polymarket.com/book"
DEFAULT_TIMEOUT = 10  # seconds


class ClobOrderbookFetcher:
    """Fetch orderbooks from CLOB API (https://clob.polymarket.com/book)."""

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self._session = session
        self._owns_session = session is None
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
            self._owns_session = True
        return self._session

    async def fetch_best_asks(
        self, yes_token: str, no_token: str,
    ) -> tuple[float | None, float | None]:
        """Fetch best ask for YES and NO tokens from CLOB API.

        Returns (yes_best_ask, no_best_ask). None for either side on failure.
        """
        yes_ask = await self._fetch_single_best_ask(yes_token)
        no_ask = await self._fetch_single_best_ask(no_token)
        return yes_ask, no_ask

    async def _fetch_single_best_ask(self, token_id: str) -> float | None:
        """단일 토큰의 best ask 가격 조회. 실패 시 None."""
        try:
            session = await self._ensure_session()
            async with session.get(
                CLOB_BOOK_URL, params={"token_id": token_id},
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        "CLOB API returned %d for token %s", resp.status, token_id,
                    )
                    return None
                data = await resp.json()
                asks = data.get("asks", [])
                if not asks:
                    return None
                # asks may not be sorted — find min
                return min(float(a["price"]) for a in asks)
        except Exception as exc:
            logger.warning("CLOB fetch error for token %s: %s", token_id, exc)
            return None

    async def close(self) -> None:
        """Close owned aiohttp session."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
            self._session = None


class OrderbookArbDetector:
    """Detect arb from orderbook best asks (YES_ask + NO_ask < 1.0)."""

    def detect(
        self,
        market: Market,
        yes_ask: float,
        no_ask: float,
        min_spread: float = 0.015,
    ) -> Optional[Opportunity]:
        """Returns Opportunity if spread exists, None otherwise.

        Args:
            market: 바이너리 마켓
            yes_ask: YES 토큰 best ask
            no_ask: NO 토큰 best ask
            min_spread: 최소 마진 (exclusive — margin must be > min_spread)
        """
        if yes_ask <= 0 or no_ask <= 0:
            return None

        total_cost = yes_ask + no_ask
        margin = 1.0 - total_cost

        # margin must exceed min_spread (exclusive threshold)
        if margin <= min_spread:
            return None

        roi_pct = (margin / total_cost) * 100.0

        return Opportunity(
            market=market,
            arb_type=ArbType.SINGLE_CONDITION,
            yes_price=yes_ask,
            no_price=no_ask,
            total_cost=total_cost,
            margin=margin,
            roi_pct=roi_pct,
            recommended_size_usd=0.0,
            detected_at=datetime.now(tz=timezone.utc),
        )


class OrderbookBatchScanner:
    """Batch scan markets for orderbook arb with concurrency control."""

    def __init__(
        self,
        fetcher: ClobOrderbookFetcher,
        detector: OrderbookArbDetector,
        concurrency: int = 5,
    ):
        self.fetcher = fetcher
        self.detector = detector
        self._semaphore = asyncio.Semaphore(concurrency)

    async def scan(
        self,
        markets: list[Market],
        min_spread: float = 0.015,
    ) -> list[Opportunity]:
        """Scan all markets concurrently (semaphore-limited). Returns ranked opportunities."""
        if not markets:
            return []

        tasks = [
            self._scan_one(market, min_spread) for market in markets
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        opportunities: list[Opportunity] = []
        for result in results:
            if isinstance(result, Opportunity):
                opportunities.append(result)
            elif isinstance(result, Exception):
                logger.warning("Orderbook scan error: %s", result)

        # ROI 내림차순 정렬
        opportunities.sort(key=lambda o: o.roi_pct, reverse=True)
        return opportunities

    async def _scan_one(
        self, market: Market, min_spread: float,
    ) -> Optional[Opportunity]:
        """Semaphore-limited single market scan."""
        async with self._semaphore:
            yes_ask, no_ask = await self.fetcher.fetch_best_asks(
                market.yes_token_id, market.no_token_id,
            )
            if yes_ask is None or no_ask is None:
                return None
            return self.detector.detect(market, yes_ask, no_ask, min_spread)
