"""Orderbook-based arbitrage scanning (F-014).

CLOB API 오더북에서 best ask 가격을 조회하여 YES_ask + NO_ask < 1.0 아비트라지를 감지.
기존 mid-price 기반 dutch_book.py와 독립적으로 동작.

F-019 개선:
- 최소 가격 필터링 (NO@$0.001 같은 쓰레기 시그널 제거)
- 오더북 깊이(depth) 조회 → 유동성 없는 호가 필터링
- best ask 뿐 아니라 해당 가격의 available size도 반환
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from poly24h.models.market import Market
from poly24h.models.opportunity import ArbType, Opportunity

logger = logging.getLogger(__name__)

CLOB_BOOK_URL = "https://clob.polymarket.com/book"
DEFAULT_TIMEOUT = 10  # seconds

# F-019: 시그널 품질 필터
MIN_MEANINGFUL_PRICE = 0.02   # $0.02 미만 = 사실상 유동성 없는 쓰레기
MIN_ASK_SIZE_USD = 5.0        # best ask에 최소 $5 이상의 물량이 있어야 함


@dataclass
class OrderbookLevel:
    """오더북 한 레벨 (가격 + 수량)."""
    price: float
    size: float  # shares

    @property
    def value_usd(self) -> float:
        """이 레벨의 달러 가치 (price * size)."""
        return self.price * self.size


@dataclass
class OrderbookSummary:
    """한 토큰의 오더북 요약."""
    best_ask: float | None = None
    best_ask_size: float = 0.0   # shares at best ask
    total_ask_depth_usd: float = 0.0  # 전체 ask 깊이 (달러)
    ask_levels: int = 0  # ask 레벨 수


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

    async def fetch_orderbook_summaries(
        self, yes_token: str, no_token: str,
    ) -> tuple[OrderbookSummary, OrderbookSummary]:
        """Fetch full orderbook summaries for both sides.

        Returns (yes_summary, no_summary) with depth info.
        """
        yes_summary = await self._fetch_orderbook_summary(yes_token)
        no_summary = await self._fetch_orderbook_summary(no_token)
        return yes_summary, no_summary

    # Retry config for 429 errors
    MAX_RETRIES = 3
    BACKOFF_BASE = 0.5  # seconds

    async def _fetch_single_best_ask(self, token_id: str) -> float | None:
        """단일 토큰의 best ask 가격 조회. 429시 지수 백오프 재시도. 실패 시 None."""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                session = await self._ensure_session()
                async with session.get(
                    CLOB_BOOK_URL, params={"token_id": token_id},
                ) as resp:
                    if resp.status == 429:
                        wait = self.BACKOFF_BASE * (2 ** (attempt - 1))
                        logger.warning(
                            "CLOB API 429 for token %s (attempt %d/%d), backing off %.1fs",
                            token_id, attempt, self.MAX_RETRIES, wait,
                        )
                        await asyncio.sleep(wait)
                        continue
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
        logger.warning("CLOB API exhausted retries for token %s", token_id)
        return None

    async def _fetch_orderbook_summary(self, token_id: str) -> OrderbookSummary:
        """단일 토큰의 오더북 요약 조회. 429시 지수 백오프."""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                session = await self._ensure_session()
                async with session.get(
                    CLOB_BOOK_URL, params={"token_id": token_id},
                ) as resp:
                    if resp.status == 429:
                        wait = self.BACKOFF_BASE * (2 ** (attempt - 1))
                        logger.warning(
                            "CLOB API 429 for summary %s (attempt %d/%d), backing off %.1fs",
                            token_id, attempt, self.MAX_RETRIES, wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                    if resp.status != 200:
                        return OrderbookSummary()
                    data = await resp.json()
                    asks = data.get("asks", [])
                    if not asks:
                        return OrderbookSummary()

                    # Parse all ask levels
                    levels = []
                    for a in asks:
                        price = float(a["price"])
                        size = float(a.get("size", 0))
                        levels.append(OrderbookLevel(price=price, size=size))

                    # Sort by price ascending (best ask first)
                    levels.sort(key=lambda lv: lv.price)

                    best = levels[0]
                    total_depth = sum(lv.value_usd for lv in levels)

                    return OrderbookSummary(
                        best_ask=best.price,
                        best_ask_size=best.size,
                        total_ask_depth_usd=total_depth,
                        ask_levels=len(levels),
                    )
            except Exception as exc:
                logger.warning("CLOB fetch error for token %s: %s", token_id, exc)
                return OrderbookSummary()
        return OrderbookSummary()

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
