"""Gamma API client with retry and error handling."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

GAMMA_API_URL = "https://gamma-api.polymarket.com"
DEFAULT_TIMEOUT = 15  # seconds
DEFAULT_MAX_RETRIES = 3


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
        """GET → list. 실패 시 빈 리스트 반환 (크래시 방지)."""
        for attempt in range(1, self.max_retries + 1):
            try:
                async with self._session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data if isinstance(data, list) else []
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
        """GET → dict. 실패 시 None 반환."""
        for attempt in range(1, self.max_retries + 1):
            try:
                async with self._session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data if isinstance(data, dict) else None
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
