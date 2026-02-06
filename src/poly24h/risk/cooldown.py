"""Cooldown manager — 연속 손실 시 거래 일시 중지."""

from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class CooldownManager:
    """Pause trading after consecutive losses.

    Args:
        max_consecutive_losses: 연속 손실 한도.
        cooldown_seconds: 쿨다운 시간 (초).
    """

    def __init__(
        self,
        max_consecutive_losses: int = 3,
        cooldown_seconds: int = 300,
    ):
        self.max_consecutive_losses = max_consecutive_losses
        self.cooldown_seconds = cooldown_seconds
        self._consecutive_losses: int = 0
        self._cooldown_start: Optional[float] = None

    def record_loss(self) -> None:
        """손실 기록."""
        self._consecutive_losses += 1

    def record_win(self) -> None:
        """승리 기록 — streak 리셋."""
        self._consecutive_losses = 0

    def check(self) -> tuple[bool, int]:
        """쿨다운 체크.

        Returns:
            (approved, remaining_seconds). approved=True면 거래 가능.
        """
        # 쿨다운 중이면 만료 확인
        if self._cooldown_start is not None:
            elapsed = time.time() - self._cooldown_start
            if elapsed >= self.cooldown_seconds:
                # 쿨다운 만료 → 리셋
                logger.info("Cooldown expired, resetting")
                self._cooldown_start = None
                self._consecutive_losses = 0
                return True, 0
            remaining = int(self.cooldown_seconds - elapsed)
            return False, max(1, remaining)

        # 쿨다운 아닌데 한도 도달 → 쿨다운 시작
        if self._consecutive_losses >= self.max_consecutive_losses:
            self._cooldown_start = time.time()
            logger.warning(
                "Cooldown triggered: %d consecutive losses, %ds cooldown",
                self._consecutive_losses, self.cooldown_seconds,
            )
            return False, self.cooldown_seconds

        return True, 0
