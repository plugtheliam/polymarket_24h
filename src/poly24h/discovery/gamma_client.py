"""Gamma API client with retry and error handling."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

GAMMA_API_URL = "https://gamma-api.polymarket.com"
CLOB_API_URL = "https://clob.polymarket.com"
DEFAULT_TIMEOUT = 15  # seconds
DEFAULT_MAX_RETRIES = 3


def is_market_active(end_date_str: str | None) -> bool:
    """Check if market end date is in the future.
    
    Args:
        end_date_str: ISO format datetime string
        
    Returns:
        True if market is still active (end date > now)
    """
    if not end_date_str:
        return False
    
    try:
        end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
        return end_date > datetime.now(tz=timezone.utc)
    except (ValueError, AttributeError):
        return False


class GammaClient:
    """Async client for Polymarket Gamma API.

    Usage:
        async with GammaClient() as client:
            events = await client.fetch_events(tag="crypto")
    """

    def __init__(
        self,
        base_url: str = GAMMA_API_URL,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self.base_url = base_url
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self._session: Optional[aiohttp.ClientSession] = None

    async def open(self) -> None:
        """Open aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)

    async def close(self) -> None:
        """Close aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> GammaClient:
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # F-022: New methods for direct market lookup and CLOB verification
    # ------------------------------------------------------------------

    async def get_market_by_id(self, market_id: str) -> dict | None:
        """GET /markets/{id} — Direct market lookup by ID.
        
        Args:
            market_id: Market ID (e.g., "1326267")
            
        Returns:
            Market data dict or None if not found
        """
        url = f"{self.base_url}/markets/{market_id}"
        return await self._get_dict(url, {})

    async def verify_clob_liquidity(
        self, 
        token_id: str, 
        min_liquidity: float = 10000.0
    ) -> bool:
        """Verify market has sufficient liquidity in CLOB orderbook.
        
        Args:
            token_id: CLOB token ID for YES or NO side
            min_liquidity: Minimum liquidity threshold (default $10k)
            
        Returns:
            True if market has sufficient liquidity
        """
        url = f"{CLOB_API_URL}/book"
        params = {"token_id": token_id}
        
        orderbook = await self._get_dict(url, params)
        if not orderbook:
            return False
        
        asks = orderbook.get("asks", [])
        bids = orderbook.get("bids", [])
        
        # Calculate total liquidity
        total_ask_size = sum(float(a.get("size", 0)) for a in asks)
        total_bid_size = sum(float(b.get("size", 0)) for b in bids)
        total_liquidity = total_ask_size + total_bid_size
        
        return total_liquidity >= min_liquidity

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_events(self, tag: str, limit: int = 100) -> list[dict]:
        """GET /events — 태그별 이벤트 조회. 실패 시 빈 리스트."""
        url = f"{self.base_url}/events"
        params = {
            "active": "true",
            "closed": "false",
            "tag": tag,
            "limit": str(limit),
        }
        return await self._get_list(url, params)

    async def fetch_events_by_tag_slug(
        self, tag_slug: str, limit: int = 100,
    ) -> list[dict]:
        """GET /events?tag_slug= — 태그 slug로 이벤트 조회."""
        url = f"{self.base_url}/events"
        params = {
            "active": "true",
            "closed": "false",
            "tag_slug": tag_slug,
            "limit": str(limit),
        }
        return await self._get_list(url, params)

    async def fetch_events_by_date_range(
        self,
        end_date_min: str,
        end_date_max: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """GET /events with date range filter."""
        url = f"{self.base_url}/events"
        params = {
            "active": "true",
            "closed": "false",
            "end_date_min": end_date_min,
            "end_date_max": end_date_max,
            "limit": str(limit),
            "offset": str(offset),
        }
        return await self._get_list(url, params)

    # ------------------------------------------------------------------
    # F-026: Generic game events by series_id
    # ------------------------------------------------------------------

    NBA_SERIES_ID = "10345"   # nba-2026 series
    NBA_GAMES_TAG_ID = "100639"  # game bets (excludes futures)

    async def fetch_game_events_by_series(
        self,
        series_id: str,
        tag_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
        include_ended: bool = False,
    ) -> list[dict]:
        """Fetch game events for any sport using series_id.

        Args:
            series_id: Sport/league series identifier.
            tag_id: Optional tag filter (e.g., games only, excludes futures).
            limit: Max results per page.
            offset: Pagination offset.
            include_ended: If True, include games that already ended.

        Returns:
            List of game event dicts with full sports metadata.
        """
        url = f"{self.base_url}/events"
        params = {
            "series_id": series_id,
            "active": "true",
            "closed": "false",
            "order": "startDate",
            "ascending": "true",
            "limit": str(limit),
            "offset": str(offset),
        }
        if tag_id is not None:
            params["tag_id"] = tag_id

        events = await self._get_list(url, params)

        if not include_ended:
            events = [e for e in events if not e.get("ended")]

        return events

    async def fetch_nba_game_events(
        self,
        limit: int = 100,
        offset: int = 0,
        include_ended: bool = False,
    ) -> list[dict]:
        """Fetch NBA game events (backward-compatible wrapper).

        Delegates to fetch_game_events_by_series with NBA series_id.
        """
        return await self.fetch_game_events_by_series(
            series_id=self.NBA_SERIES_ID,
            tag_id=self.NBA_GAMES_TAG_ID,
            limit=limit,
            offset=offset,
            include_ended=include_ended,
        )

    async def fetch_clob_orderbook(self, token_id: str) -> dict | None:
        """GET orderbook from CLOB API (not Gamma). 실패 시 None."""
        url = "https://clob.polymarket.com/book"
        params = {"token_id": token_id}
        return await self._get_dict(url, params)

    async def fetch_orderbook(self, token_id: str) -> Optional[dict]:
        """GET /book — 토큰 오더북 조회. 실패 시 None."""
        url = f"{self.base_url}/book"
        params = {"token_id": token_id}
        return await self._get_dict(url, params)

    @staticmethod
    def best_ask(orderbook: Optional[dict]) -> Optional[float]:
        """오더북에서 최저 ask 가격 추출."""
        if not orderbook:
            return None
        asks = orderbook.get("asks", [])
        if not asks:
            return None
        try:
            return min(float(a["price"]) for a in asks)
        except (ValueError, KeyError):
            return None

    # ------------------------------------------------------------------
    # HTTP helpers with retry
    # ------------------------------------------------------------------

    async def _get_list(self, url: str, params: dict) -> list[dict]:
        """GET → list. 429시 지수 백오프. 실패 시 빈 리스트 반환 (크래시 방지)."""
        for attempt in range(1, self.max_retries + 1):
            try:
                async with self._session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data if isinstance(data, list) else []
                    if resp.status == 429:
                        wait = 1.0 * (2 ** (attempt - 1))
                        logger.warning(
                            "API 429 rate limit %s (attempt %d/%d), backing off %.1fs",
                            url, attempt, self.max_retries, wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                    logger.warning(
                        "Gamma API %s returned %d (attempt %d/%d)",
                        url, resp.status, attempt, self.max_retries,
                    )
            except Exception as exc:
                logger.warning(
                    "Gamma API %s error (attempt %d/%d): %s",
                    url, attempt, self.max_retries, exc,
                )

            # exponential backoff (짧게 — 테스트에서 빠르게)
            if attempt < self.max_retries:
                await asyncio.sleep(0.1 * (2 ** (attempt - 1)))

        return []

    async def _get_dict(self, url: str, params: dict) -> Optional[dict]:
        """GET → dict. 429시 지수 백오프. 실패 시 None 반환."""
        for attempt in range(1, self.max_retries + 1):
            try:
                async with self._session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data if isinstance(data, dict) else None
                    if resp.status == 429:
                        wait = 1.0 * (2 ** (attempt - 1))
                        logger.warning(
                            "API 429 rate limit %s (attempt %d/%d), backing off %.1fs",
                            url, attempt, self.max_retries, wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                    logger.warning(
                        "Gamma API %s returned %d (attempt %d/%d)",
                        url, resp.status, attempt, self.max_retries,
                    )
            except Exception as exc:
                logger.warning(
                    "Gamma API %s error (attempt %d/%d): %s",
                    url, attempt, self.max_retries, exc,
                )

            if attempt < self.max_retries:
                await asyncio.sleep(0.1 * (2 ** (attempt - 1)))

        return None
