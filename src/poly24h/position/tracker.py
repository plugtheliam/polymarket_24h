"""Single-market position tracker — YES/NO shares + settlement.

마켓 하나의 YES/NO 포지션을 추적하고 정산(settle) 처리.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class PositionTracker:
    """Track YES/NO position for a single market."""

    def __init__(self):
        self.yes_shares: float = 0.0
        self.no_shares: float = 0.0
        self.yes_cost: float = 0.0   # total USD spent on YES
        self.no_cost: float = 0.0    # total USD spent on NO

    def add_yes(self, shares: float, cost_per_share: float) -> None:
        """YES 매수 기록."""
        if shares < 0:
            raise ValueError(f"shares must be non-negative: {shares}")
        if cost_per_share < 0:
            raise ValueError(f"cost_per_share must be non-negative: {cost_per_share}")
        self.yes_shares += shares
        self.yes_cost += shares * cost_per_share

    def add_no(self, shares: float, cost_per_share: float) -> None:
        """NO 매수 기록."""
        if shares < 0:
            raise ValueError(f"shares must be non-negative: {shares}")
        if cost_per_share < 0:
            raise ValueError(f"cost_per_share must be non-negative: {cost_per_share}")
        self.no_shares += shares
        self.no_cost += shares * cost_per_share

    @property
    def balanced_pairs(self) -> float:
        """매칭된 YES/NO 쌍 수 = min(yes, no)."""
        return min(self.yes_shares, self.no_shares)

    @property
    def avg_yes_cost(self) -> float:
        """YES 평균 매수 단가."""
        return self.yes_cost / self.yes_shares if self.yes_shares > 0 else 0.0

    @property
    def avg_no_cost(self) -> float:
        """NO 평균 매수 단가."""
        return self.no_cost / self.no_shares if self.no_shares > 0 else 0.0

    @property
    def locked_profit(self) -> float:
        """확정 수익 = balanced_pairs × (1.0 - avg_yes - avg_no).

        balanced pair는 어느 쪽이 이기든 $1.00 정산.
        """
        pairs = self.balanced_pairs
        if pairs == 0:
            return 0.0
        return pairs * (1.0 - self.avg_yes_cost - self.avg_no_cost)

    @property
    def total_invested(self) -> float:
        """총 투자액 (USD)."""
        return self.yes_cost + self.no_cost

    def settle(self, winner: str) -> float:
        """마켓 정산. winner="YES" or "NO".

        Args:
            winner: 승리 아웃컴.

        Returns:
            realized PnL (USD).

        Raises:
            ValueError: 유효하지 않은 winner.
        """
        winner = winner.upper()
        if winner not in ("YES", "NO"):
            raise ValueError(f"Invalid winner: {winner!r}. Must be 'YES' or 'NO'.")

        if self.yes_shares == 0 and self.no_shares == 0:
            return 0.0

        if winner == "YES":
            payout = self.yes_shares * 1.0  # YES shares each pay $1
        else:
            payout = self.no_shares * 1.0  # NO shares each pay $1

        total_cost = self.total_invested
        pnl = payout - total_cost

        logger.info(
            "Settled %s wins: payout=$%.2f, cost=$%.2f, pnl=$%.2f",
            winner, payout, total_cost, pnl,
        )

        # 포지션 리셋
        self.yes_shares = 0.0
        self.no_shares = 0.0
        self.yes_cost = 0.0
        self.no_cost = 0.0

        return pnl
