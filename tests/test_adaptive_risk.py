"""Tests for adaptive risk management and Kelly Criterion (Phase 4)."""

from __future__ import annotations

import pytest

from poly24h.risk.adaptive import (
    AdaptiveRiskManager,
    AdaptiveState,
    KellyResult,
    kelly_criterion,
)


# ===========================================================================
# Kelly Criterion Tests
# ===========================================================================


class TestKellyCriterion:
    def test_positive_edge(self):
        """60% WR, 2:1 win/loss ratio → positive Kelly fraction."""
        result = kelly_criterion(win_rate=0.6, avg_win=20.0, avg_loss=10.0)
        assert result.is_positive_edge
        assert result.fraction > 0.0
        assert result.half_kelly > 0.0
        assert result.half_kelly == pytest.approx(result.fraction / 2.0)

    def test_negative_edge(self):
        """30% WR, 1:1 ratio → no edge → fraction = 0."""
        result = kelly_criterion(win_rate=0.3, avg_win=10.0, avg_loss=10.0)
        assert not result.is_positive_edge
        assert result.fraction == 0.0

    def test_coin_flip_no_edge(self):
        """50% WR, 1:1 ratio → zero edge."""
        result = kelly_criterion(win_rate=0.5, avg_win=10.0, avg_loss=10.0)
        assert result.edge == pytest.approx(0.0, abs=1e-6)
        assert result.fraction == 0.0

    def test_high_win_rate_small_payoff(self):
        """80% WR, small wins, big losses."""
        result = kelly_criterion(win_rate=0.8, avg_win=5.0, avg_loss=20.0)
        assert result.fraction >= 0.0  # May or may not be positive

    def test_zero_win_rate(self):
        """0% WR → no betting."""
        result = kelly_criterion(win_rate=0.0, avg_win=10.0, avg_loss=10.0)
        assert result.fraction == 0.0

    def test_full_win_rate(self):
        """100% WR → invalid, returns 0."""
        result = kelly_criterion(win_rate=1.0, avg_win=10.0, avg_loss=10.0)
        assert result.fraction == 0.0

    def test_zero_avg_win(self):
        """Avg win = 0 → no edge."""
        result = kelly_criterion(win_rate=0.6, avg_win=0.0, avg_loss=10.0)
        assert result.fraction == 0.0

    def test_zero_avg_loss(self):
        """Avg loss = 0 → invalid."""
        result = kelly_criterion(win_rate=0.6, avg_win=10.0, avg_loss=0.0)
        assert result.fraction == 0.0

    def test_known_values(self):
        """Verify against known Kelly calculation.

        f* = (p * b - q) / b where p=0.6, q=0.4, b=2 (avg_win/avg_loss)
        f* = (0.6 * 2 - 0.4) / 2 = (1.2 - 0.4) / 2 = 0.8 / 2 = 0.4
        """
        result = kelly_criterion(win_rate=0.6, avg_win=20.0, avg_loss=10.0)
        assert result.fraction == pytest.approx(0.4, abs=0.01)
        assert result.half_kelly == pytest.approx(0.2, abs=0.01)
        assert result.bankroll_fraction_pct == pytest.approx(40.0, abs=1.0)


class TestKellyResult:
    def test_is_positive_edge(self):
        r = KellyResult(fraction=0.2, half_kelly=0.1, edge=0.5, bankroll_fraction_pct=20.0)
        assert r.is_positive_edge

    def test_negative_edge(self):
        r = KellyResult(fraction=0.0, half_kelly=0.0, edge=-0.1, bankroll_fraction_pct=0.0)
        assert not r.is_positive_edge


# ===========================================================================
# AdaptiveState Tests
# ===========================================================================


class TestAdaptiveState:
    def test_defaults(self):
        s = AdaptiveState()
        assert s.total_trades == 0
        assert s.win_rate == 0.0
        assert s.avg_win == 0.0
        assert s.avg_loss == 0.0

    def test_win_rate(self):
        s = AdaptiveState(total_wins=7, total_losses=3)
        assert s.win_rate == pytest.approx(0.7)

    def test_avg_win_loss(self):
        s = AdaptiveState(
            recent_pnls=[10.0, 20.0, -5.0, -15.0, 30.0],
        )
        assert s.avg_win == pytest.approx(20.0)
        assert s.avg_loss == pytest.approx(10.0)


# ===========================================================================
# AdaptiveRiskManager Tests
# ===========================================================================


class TestAdaptiveRiskManagerBasic:
    def test_initial_threshold(self):
        arm = AdaptiveRiskManager(base_threshold=0.48)
        assert arm.current_threshold == 0.48

    def test_record_win(self):
        arm = AdaptiveRiskManager()
        arm.record_trade_result(5.0)
        assert arm.state.total_wins == 1
        assert arm.state.consecutive_wins == 1
        assert arm.state.consecutive_losses == 0

    def test_record_loss(self):
        arm = AdaptiveRiskManager()
        arm.record_trade_result(-5.0)
        assert arm.state.total_losses == 1
        assert arm.state.consecutive_losses == 1
        assert arm.state.consecutive_wins == 0

    def test_win_resets_loss_streak(self):
        arm = AdaptiveRiskManager()
        arm.record_trade_result(-5.0)
        arm.record_trade_result(-5.0)
        assert arm.state.consecutive_losses == 2
        arm.record_trade_result(10.0)
        assert arm.state.consecutive_losses == 0
        assert arm.state.consecutive_wins == 1


class TestAdaptiveThresholdAdjustment:
    def test_loss_streak_lowers_threshold(self):
        arm = AdaptiveRiskManager(
            base_threshold=0.48,
            min_threshold=0.42,
            step_down=0.01,
            loss_streak_trigger=3,
        )
        # 3 consecutive losses
        arm.record_trade_result(-5.0)
        arm.record_trade_result(-5.0)
        arm.record_trade_result(-5.0)
        assert arm.current_threshold < 0.48
        assert arm.current_threshold == pytest.approx(0.47)

    def test_win_streak_raises_threshold(self):
        arm = AdaptiveRiskManager(
            base_threshold=0.48,
            max_threshold=0.50,
            step_up=0.005,
            win_streak_trigger=3,
        )
        arm.record_trade_result(5.0)
        arm.record_trade_result(5.0)
        arm.record_trade_result(5.0)
        assert arm.current_threshold > 0.48
        assert arm.current_threshold == pytest.approx(0.485)

    def test_threshold_never_below_min(self):
        arm = AdaptiveRiskManager(
            base_threshold=0.43,
            min_threshold=0.42,
            step_down=0.02,
            loss_streak_trigger=3,
        )
        for _ in range(10):
            arm.record_trade_result(-5.0)
        assert arm.current_threshold >= 0.42

    def test_threshold_never_above_max(self):
        arm = AdaptiveRiskManager(
            base_threshold=0.49,
            max_threshold=0.50,
            step_up=0.02,
            win_streak_trigger=3,
        )
        for _ in range(10):
            arm.record_trade_result(5.0)
        assert arm.current_threshold <= 0.50

    def test_no_adjustment_under_trigger(self):
        arm = AdaptiveRiskManager(
            base_threshold=0.48,
            loss_streak_trigger=3,
            win_streak_trigger=3,
        )
        arm.record_trade_result(-5.0)
        arm.record_trade_result(-5.0)
        # Only 2 losses — under trigger
        assert arm.current_threshold == 0.48


class TestAdaptiveKelly:
    def test_kelly_insufficient_data(self):
        """Not enough trades for Kelly — returns zero."""
        arm = AdaptiveRiskManager()
        for _ in range(5):
            arm.record_trade_result(5.0)
        result = arm.get_kelly_sizing()
        assert result.fraction == 0.0

    def test_kelly_with_data(self):
        """Enough trades with positive edge → positive Kelly."""
        arm = AdaptiveRiskManager(bankroll_usd=5000.0)
        # 7 wins, 3 losses (70% WR)
        for _ in range(7):
            arm.record_trade_result(10.0)
        for _ in range(3):
            arm.record_trade_result(-5.0)

        result = arm.get_kelly_sizing()
        assert result.is_positive_edge
        assert result.fraction > 0.0

    def test_position_size_default_on_insufficient_data(self):
        """Fallback to default size when data insufficient."""
        arm = AdaptiveRiskManager()
        size = arm.get_position_size_usd(default_size=10.0)
        assert size == 10.0

    def test_position_size_with_kelly(self):
        """Kelly-based sizing with sufficient data."""
        arm = AdaptiveRiskManager(bankroll_usd=5000.0)
        for _ in range(8):
            arm.record_trade_result(20.0)
        for _ in range(2):
            arm.record_trade_result(-10.0)

        size = arm.get_position_size_usd(default_size=10.0)
        # Should be more than default since we have positive edge
        assert size >= 5.0  # At least min_size
        assert size <= 500.0  # Max 10% of bankroll

    def test_position_size_negative_edge(self):
        """Negative edge → fallback to default."""
        arm = AdaptiveRiskManager(bankroll_usd=5000.0)
        for _ in range(2):
            arm.record_trade_result(5.0)
        for _ in range(8):
            arm.record_trade_result(-10.0)

        size = arm.get_position_size_usd(default_size=10.0)
        assert size == 10.0


class TestAdaptiveReset:
    def test_reset(self):
        arm = AdaptiveRiskManager(base_threshold=0.48)
        arm.record_trade_result(-5.0)
        arm.record_trade_result(-5.0)
        arm.record_trade_result(-5.0)
        assert arm.current_threshold != 0.48

        arm.reset()
        assert arm.current_threshold == 0.48
        assert arm.state.total_trades == 0


class TestAdaptiveSummary:
    def test_summary(self):
        arm = AdaptiveRiskManager()
        arm.record_trade_result(10.0)
        arm.record_trade_result(-5.0)

        s = arm.summary()
        assert s["total_trades"] == 2
        assert s["current_threshold"] == arm.current_threshold
        assert "kelly_fraction" in s
        assert "recommended_size_usd" in s


class TestAdaptiveRecentPnlsTrimming:
    def test_recent_pnls_trimmed(self):
        arm = AdaptiveRiskManager(max_recent_trades=10)
        for i in range(20):
            arm.record_trade_result(float(i))
        assert len(arm.state.recent_pnls) == 10
