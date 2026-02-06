"""Multi-market portfolio manager.

여러 마켓의 PositionTracker를 관리하고 전체 포트폴리오 통계 제공.
"""

from __future__ import annotations

import logging
from typing import Optional

from poly24h.position.tracker import PositionTracker

logger = logging.getLogger(__name__)


class PortfolioManager:
    """Manage positions across multiple markets."""

    def __init__(self):
        self._positions: dict[str, PositionTracker] = {}
        self._realized_pnl: float = 0.0

    def add_trade(
        self,
        market_id: str,
        side: str,
        shares: float,
        cost_per_share: float,
    ) -> None:
        """거래 기록.

        Args:
            market_id: 마켓 ID.
            side: "YES" or "NO".
            shares: 매수 수량.
            cost_per_share: 주당 비용.

        Raises:
            ValueError: 유효하지 않은 side.
        """
        side = side.upper()
        if side not in ("YES", "NO"):
            raise ValueError(f"Invalid side: {side!r}. Must be 'YES' or 'NO'.")

        tracker = self._positions.get(market_id)
        if tracker is None:
            tracker = PositionTracker()
            self._positions[market_id] = tracker

        if side == "YES":
            tracker.add_yes(shares, cost_per_share)
        else:
            tracker.add_no(shares, cost_per_share)

    def get_position(self, market_id: str) -> Optional[PositionTracker]:
        """마켓별 포지션 조회. 없으면 None."""
        return self._positions.get(market_id)

    def active_positions(self) -> dict[str, PositionTracker]:
        """활성 포지션 (shares > 0인 마켓만)."""
        return {
            mid: tracker
            for mid, tracker in self._positions.items()
            if tracker.yes_shares > 0 or tracker.no_shares > 0
        }

    @property
    def total_invested(self) -> float:
        """전체 투자액."""
        return sum(t.total_invested for t in self._positions.values())

    @property
    def total_locked_profit(self) -> float:
        """전체 확정 수익."""
        return sum(t.locked_profit for t in self._positions.values())

    @property
    def total_realized_pnl(self) -> float:
        """전체 실현 손익."""
        return self._realized_pnl

    def settle(self, market_id: str, winner: str) -> float:
        """마켓 정산.

        Returns:
            Realized PnL for this market. 0.0 if market not found.
        """
        tracker = self._positions.get(market_id)
        if tracker is None:
            return 0.0

        pnl = tracker.settle(winner)
        self._realized_pnl += pnl

        logger.info("Portfolio settle %s (%s): pnl=$%.2f", market_id, winner, pnl)
        return pnl
