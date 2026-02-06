"""Daily loss limiter — 일일 실현 손실 한도 관리."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def _utc_today() -> date:
    """현재 UTC 날짜."""
    return datetime.now(tz=timezone.utc).date()


class DailyLossLimiter:
    """Track daily realized losses and enforce limit.

    Args:
        limit_usd: 일일 최대 허용 손실 (USD).
    """

    def __init__(self, limit_usd: float = 500.0):
        self.limit_usd = limit_usd
        self._current_loss: float = 0.0
        self._last_reset_date: Optional[date] = _utc_today()

    @property
    def current_loss(self) -> float:
        return self._current_loss

    def record_loss(self, amount: float) -> None:
        """손실 기록 (양수 금액)."""
        self._maybe_reset_daily()
        if amount > 0:
            self._current_loss += amount

    def check(self) -> tuple[bool, Optional[str]]:
        """한도 체크.

        Returns:
            (approved, reason). approved=True이면 거래 가능.
        """
        self._maybe_reset_daily()
        if self._current_loss >= self.limit_usd:
            reason = f"Daily loss limit reached: ${self._current_loss:.2f} >= ${self.limit_usd:.2f}"
            logger.warning(reason)
            return False, reason
        return True, None

    def reset(self) -> None:
        """수동 리셋."""
        self._current_loss = 0.0
        self._last_reset_date = _utc_today()

    def _maybe_reset_daily(self) -> None:
        """자정 경과 시 자동 리셋."""
        today = _utc_today()
        if self._last_reset_date != today:
            logger.info("New day — resetting daily loss limiter")
            self._current_loss = 0.0
            self._last_reset_date = today
