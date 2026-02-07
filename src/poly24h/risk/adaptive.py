"""Adaptive risk parameter adjustment based on paper trading results.

Phase 4: Automatically adjusts risk parameters based on recent performance:
- Consecutive losses → lower threshold (more conservative)
- Consecutive wins → gradually raise threshold (more aggressive)
- Kelly Criterion for optimal position sizing

Designed to be composable with existing RiskController.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Kelly Criterion
# ---------------------------------------------------------------------------


@dataclass
class KellyResult:
    """Kelly Criterion calculation result."""

    fraction: float  # Optimal fraction of bankroll (0.0 to 1.0)
    half_kelly: float  # Half Kelly (more conservative, recommended)
    edge: float  # Expected edge (win_prob * win_size - loss_prob * loss_size)
    bankroll_fraction_pct: float  # As percentage

    @property
    def is_positive_edge(self) -> bool:
        """True if edge is positive (should bet)."""
        return self.edge > 0.0


def kelly_criterion(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
) -> KellyResult:
    """Calculate Kelly Criterion optimal bet fraction.

    The Kelly formula: f* = (p * b - q) / b
    where:
        p = win probability
        q = loss probability (1 - p)
        b = win/loss ratio (avg_win / avg_loss)

    Args:
        win_rate: Probability of winning (0.0 to 1.0).
        avg_win: Average win amount (positive).
        avg_loss: Average loss amount (positive, will be treated as absolute).

    Returns:
        KellyResult with optimal fraction and half Kelly.
    """
    # Validate inputs
    if win_rate <= 0 or win_rate >= 1.0:
        return KellyResult(
            fraction=0.0,
            half_kelly=0.0,
            edge=0.0,
            bankroll_fraction_pct=0.0,
        )

    if avg_win <= 0 or avg_loss <= 0:
        return KellyResult(
            fraction=0.0,
            half_kelly=0.0,
            edge=0.0,
            bankroll_fraction_pct=0.0,
        )

    p = win_rate
    q = 1.0 - p
    b = avg_win / avg_loss  # Win/loss ratio

    # Kelly fraction: f* = (p * b - q) / b
    edge = p * b - q
    if edge <= 0:
        return KellyResult(
            fraction=0.0,
            half_kelly=0.0,
            edge=edge,
            bankroll_fraction_pct=0.0,
        )

    fraction = edge / b

    # Clamp to [0, 1]
    fraction = max(0.0, min(1.0, fraction))
    half_kelly = fraction / 2.0

    return KellyResult(
        fraction=round(fraction, 6),
        half_kelly=round(half_kelly, 6),
        edge=round(edge, 6),
        bankroll_fraction_pct=round(fraction * 100, 2),
    )


# ---------------------------------------------------------------------------
# Adaptive Threshold
# ---------------------------------------------------------------------------


@dataclass
class AdaptiveState:
    """Tracks adaptive risk state."""

    consecutive_wins: int = 0
    consecutive_losses: int = 0
    total_wins: int = 0
    total_losses: int = 0
    total_pnl: float = 0.0
    recent_pnls: list[float] = field(default_factory=list)

    @property
    def total_trades(self) -> int:
        return self.total_wins + self.total_losses

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.total_wins / self.total_trades

    @property
    def avg_win(self) -> float:
        wins = [p for p in self.recent_pnls if p > 0]
        return sum(wins) / len(wins) if wins else 0.0

    @property
    def avg_loss(self) -> float:
        losses = [abs(p) for p in self.recent_pnls if p < 0]
        return sum(losses) / len(losses) if losses else 0.0


class AdaptiveRiskManager:
    """Adjusts risk parameters based on recent trading performance.

    Threshold adjustment rules:
    - 3+ consecutive losses → decrease threshold by step_down
    - 3+ consecutive wins → increase threshold by step_up
    - Never go below min_threshold or above max_threshold

    Position sizing:
    - Uses Kelly Criterion (half Kelly) for position sizing
    - Falls back to fixed sizing if insufficient data

    Args:
        base_threshold: Starting threshold (default 0.48).
        min_threshold: Floor threshold (default 0.42).
        max_threshold: Ceiling threshold (default 0.50).
        step_up: Threshold increment per win streak (default 0.005).
        step_down: Threshold decrement per loss streak (default 0.01).
        loss_streak_trigger: Consecutive losses to trigger adjustment (default 3).
        win_streak_trigger: Consecutive wins to trigger adjustment (default 3).
        max_recent_trades: Window of recent trades for Kelly calc (default 50).
        bankroll_usd: Total bankroll for position sizing (default 5000).
    """

    def __init__(
        self,
        base_threshold: float = 0.48,
        min_threshold: float = 0.42,
        max_threshold: float = 0.50,
        step_up: float = 0.005,
        step_down: float = 0.01,
        loss_streak_trigger: int = 3,
        win_streak_trigger: int = 3,
        max_recent_trades: int = 50,
        bankroll_usd: float = 5000.0,
    ):
        self.base_threshold = base_threshold
        self.min_threshold = min_threshold
        self.max_threshold = max_threshold
        self.step_up = step_up
        self.step_down = step_down
        self.loss_streak_trigger = loss_streak_trigger
        self.win_streak_trigger = win_streak_trigger
        self.max_recent_trades = max_recent_trades
        self.bankroll_usd = bankroll_usd

        self._current_threshold = base_threshold
        self._state = AdaptiveState()

    @property
    def current_threshold(self) -> float:
        """Current adjusted threshold."""
        return self._current_threshold

    @property
    def state(self) -> AdaptiveState:
        """Current adaptive state."""
        return self._state

    def record_trade_result(self, pnl: float) -> float:
        """Record a trade result and return the updated threshold.

        Args:
            pnl: Trade P&L (positive = win, negative = loss).

        Returns:
            Updated threshold value.
        """
        # Update state
        self._state.total_pnl += pnl
        self._state.recent_pnls.append(pnl)

        # Trim to max recent window
        if len(self._state.recent_pnls) > self.max_recent_trades:
            self._state.recent_pnls = self._state.recent_pnls[-self.max_recent_trades:]

        if pnl > 0:
            self._state.total_wins += 1
            self._state.consecutive_wins += 1
            self._state.consecutive_losses = 0
        elif pnl < 0:
            self._state.total_losses += 1
            self._state.consecutive_losses += 1
            self._state.consecutive_wins = 0
        # pnl == 0: no streak change

        # Adjust threshold
        self._adjust_threshold()

        return self._current_threshold

    def _adjust_threshold(self) -> None:
        """Adjust threshold based on consecutive win/loss streaks."""
        old = self._current_threshold

        if self._state.consecutive_losses >= self.loss_streak_trigger:
            # More conservative: lower threshold
            self._current_threshold = max(
                self.min_threshold,
                self._current_threshold - self.step_down,
            )
            if self._current_threshold != old:
                logger.info(
                    "Adaptive: %d consecutive losses → threshold $%.4f → $%.4f",
                    self._state.consecutive_losses, old, self._current_threshold,
                )

        elif self._state.consecutive_wins >= self.win_streak_trigger:
            # More aggressive: raise threshold
            self._current_threshold = min(
                self.max_threshold,
                self._current_threshold + self.step_up,
            )
            if self._current_threshold != old:
                logger.info(
                    "Adaptive: %d consecutive wins → threshold $%.4f → $%.4f",
                    self._state.consecutive_wins, old, self._current_threshold,
                )

    def get_kelly_sizing(self) -> KellyResult:
        """Calculate Kelly Criterion position sizing from recent trades.

        Returns:
            KellyResult with optimal fraction.
        """
        state = self._state
        if state.total_trades < 10:
            # Not enough data for reliable Kelly
            return KellyResult(
                fraction=0.0,
                half_kelly=0.0,
                edge=0.0,
                bankroll_fraction_pct=0.0,
            )

        return kelly_criterion(
            win_rate=state.win_rate,
            avg_win=state.avg_win,
            avg_loss=state.avg_loss,
        )

    def get_position_size_usd(self, default_size: float = 10.0) -> float:
        """Get recommended position size in USD.

        Uses half-Kelly if enough data, otherwise falls back to default.

        Args:
            default_size: Fallback position size if Kelly insufficient.

        Returns:
            Recommended position size in USD.
        """
        kelly = self.get_kelly_sizing()

        if not kelly.is_positive_edge or self._state.total_trades < 10:
            return default_size

        # Half Kelly × bankroll
        size = kelly.half_kelly * self.bankroll_usd

        # Clamp to reasonable range
        min_size = 5.0
        max_size = self.bankroll_usd * 0.1  # Never more than 10% of bankroll

        size = max(min_size, min(max_size, size))

        logger.info(
            "Kelly sizing: f=%.4f, half=%.4f, edge=%.4f → $%.2f",
            kelly.fraction, kelly.half_kelly, kelly.edge, size,
        )

        return round(size, 2)

    def reset(self) -> None:
        """Reset adaptive state to defaults."""
        self._current_threshold = self.base_threshold
        self._state = AdaptiveState()

    def summary(self) -> dict:
        """Get summary of adaptive risk state."""
        kelly = self.get_kelly_sizing()
        return {
            "current_threshold": self._current_threshold,
            "base_threshold": self.base_threshold,
            "total_trades": self._state.total_trades,
            "win_rate": round(self._state.win_rate * 100, 1),
            "consecutive_wins": self._state.consecutive_wins,
            "consecutive_losses": self._state.consecutive_losses,
            "total_pnl": round(self._state.total_pnl, 2),
            "kelly_fraction": kelly.fraction,
            "kelly_half": kelly.half_kelly,
            "kelly_edge": kelly.edge,
            "recommended_size_usd": self.get_position_size_usd(),
        }
