"""Odds API rate limiter for multi-sport monitoring (F-026).

Manages the shared Odds API budget (500 requests/month) across
multiple sports. Tracks remaining requests from API response headers
and enforces per-sport minimum intervals.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


class OddsAPIRateLimiter:
    """Rate limiter for The Odds API shared budget."""

    def __init__(
        self,
        monthly_budget: int = 500,
        emergency_reserve: int = 50,
        min_interval: int = 300,
    ):
        self._monthly_budget = monthly_budget
        self._emergency_reserve = emergency_reserve
        self._min_interval = min_interval
        self._remaining: int | None = None
        self._last_fetch: dict[str, float] = {}

    @property
    def remaining(self) -> int | None:
        """Current remaining API requests (None if unknown)."""
        return self._remaining

    def can_fetch(self, sport_name: str) -> bool:
        """Check if an API call is allowed for this sport.

        Returns False if:
        - Remaining requests below emergency reserve
        - Too soon since last fetch for this sport
        """
        # Emergency reserve check
        if self._remaining is not None and self._remaining < self._emergency_reserve:
            logger.warning(
                "Odds API BLOCKED: remaining=%d < reserve=%d",
                self._remaining, self._emergency_reserve,
            )
            return False

        # Min interval check
        last = self._last_fetch.get(sport_name)
        if last is not None:
            elapsed = time.time() - last
            if elapsed < self._min_interval:
                return False

        return True

    def record_fetch(self, sport_name: str, remaining: int) -> None:
        """Record a completed API fetch.

        Args:
            sport_name: Sport that was fetched.
            remaining: Remaining requests from API response header.
        """
        self._remaining = remaining
        self._last_fetch[sport_name] = time.time()
        logger.info(
            "Odds API fetch: sport=%s, remaining=%d",
            sport_name, remaining,
        )
