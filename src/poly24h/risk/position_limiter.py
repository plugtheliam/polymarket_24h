"""Position size limiter — 마켓별/전체 포지션 사이즈 제한."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class PositionSizeLimiter:
    """Limit position sizes per-market and portfolio-wide.

    Args:
        max_per_market: 마켓당 최대 노출 (USD).
        max_total: 전체 포트폴리오 최대 노출 (USD).
    """

    def __init__(
        self,
        max_per_market: float = 1000.0,
        max_total: float = 5000.0,
    ):
        self.max_per_market = max_per_market
        self.max_total = max_total

    def check(
        self,
        current_market_exposure: float,
        current_total_exposure: float,
        new_trade_size: float,
    ) -> tuple[bool, float]:
        """포지션 사이즈 체크.

        Args:
            current_market_exposure: 해당 마켓 현재 노출.
            current_total_exposure: 전체 포트폴리오 현재 노출.
            new_trade_size: 신규 거래 사이즈.

        Returns:
            (approved, allowed_size). approved=False면 진입 불가.
        """
        if new_trade_size <= 0:
            return False, 0.0

        # 마켓별 여유
        market_room = max(0.0, self.max_per_market - current_market_exposure)
        # 전체 여유
        total_room = max(0.0, self.max_total - current_total_exposure)

        allowed = min(new_trade_size, market_room, total_room)

        if allowed <= 0:
            logger.warning(
                "Position limit: market_room=$%.2f, total_room=$%.2f",
                market_room, total_room,
            )
            return False, 0.0

        return True, allowed
