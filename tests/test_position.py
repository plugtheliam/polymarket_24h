"""Tests for position tracking — PositionTracker + PortfolioManager."""

from __future__ import annotations

import pytest

from poly24h.position.portfolio import PortfolioManager
from poly24h.position.tracker import PositionTracker

# ===========================================================================
# PositionTracker Tests
# ===========================================================================


class TestPositionTrackerBasic:
    """기본 포지션 추적."""

    def test_empty_tracker(self):
        t = PositionTracker()
        assert t.yes_shares == 0.0
        assert t.no_shares == 0.0
        assert t.yes_cost == 0.0
        assert t.no_cost == 0.0

    def test_add_yes(self):
        t = PositionTracker()
        t.add_yes(100, 0.45)
        assert t.yes_shares == 100.0
        assert t.yes_cost == 45.0

    def test_add_no(self):
        t = PositionTracker()
        t.add_no(80, 0.40)
        assert t.no_shares == 80.0
        assert t.no_cost == 32.0

    def test_add_multiple(self):
        """여러 번 추가 시 누적."""
        t = PositionTracker()
        t.add_yes(50, 0.45)
        t.add_yes(50, 0.50)
        assert t.yes_shares == 100.0
        assert t.yes_cost == pytest.approx(47.5)  # 50*0.45 + 50*0.50

    def test_negative_shares_raises(self):
        t = PositionTracker()
        with pytest.raises(ValueError):
            t.add_yes(-10, 0.45)

    def test_negative_cost_raises(self):
        t = PositionTracker()
        with pytest.raises(ValueError):
            t.add_yes(10, -0.45)


class TestPositionTrackerBalanced:
    """balanced_pairs 및 locked_profit."""

    def test_balanced_pairs_equal(self):
        t = PositionTracker()
        t.add_yes(100, 0.45)
        t.add_no(100, 0.40)
        assert t.balanced_pairs == 100.0

    def test_balanced_pairs_unequal(self):
        """짝수가 맞지 않으면 min."""
        t = PositionTracker()
        t.add_yes(100, 0.45)
        t.add_no(80, 0.40)
        assert t.balanced_pairs == 80.0

    def test_balanced_pairs_empty(self):
        t = PositionTracker()
        assert t.balanced_pairs == 0.0

    def test_locked_profit_basic(self):
        """100 YES@0.45 + 100 NO@0.40 → locked profit = 100 * (1.0 - 0.85) = $15."""
        t = PositionTracker()
        t.add_yes(100, 0.45)
        t.add_no(100, 0.40)
        assert t.locked_profit == pytest.approx(15.0)

    def test_locked_profit_unequal_shares(self):
        """YES=100@0.45, NO=80@0.40 → 80 pairs, profit = 80*(1.0 - 0.45 - 0.40) = $12."""
        t = PositionTracker()
        t.add_yes(100, 0.45)
        t.add_no(80, 0.40)
        # avg yes cost per share = 0.45, avg no cost per share = 0.40
        # locked = 80 * (1.0 - 0.45 - 0.40) = 80 * 0.15 = 12
        assert t.locked_profit == pytest.approx(12.0)

    def test_locked_profit_empty(self):
        t = PositionTracker()
        assert t.locked_profit == 0.0

    def test_total_invested(self):
        t = PositionTracker()
        t.add_yes(100, 0.45)
        t.add_no(100, 0.40)
        assert t.total_invested == pytest.approx(85.0)


class TestPositionTrackerSettle:
    """settle() — 정산."""

    def test_settle_yes_wins(self):
        """YES 승리: YES shares * $1.00 - total_cost."""
        t = PositionTracker()
        t.add_yes(100, 0.45)
        t.add_no(100, 0.40)
        pnl = t.settle("YES")
        # YES 100 * 1.0 = 100, NO = 0 → pnl = 100 - 85 = 15
        assert pnl == pytest.approx(15.0)

    def test_settle_no_wins(self):
        """NO 승리: NO shares * $1.00 - total_cost."""
        t = PositionTracker()
        t.add_yes(100, 0.45)
        t.add_no(100, 0.40)
        pnl = t.settle("NO")
        # NO 100 * 1.0 = 100, YES = 0 → pnl = 100 - 85 = 15
        assert pnl == pytest.approx(15.0)

    def test_settle_clears_position(self):
        """정산 후 포지션 리셋."""
        t = PositionTracker()
        t.add_yes(100, 0.45)
        t.add_no(100, 0.40)
        t.settle("YES")
        assert t.yes_shares == 0.0
        assert t.no_shares == 0.0

    def test_settle_unequal_yes_wins(self):
        """YES 많으면 YES 승리가 더 유리."""
        t = PositionTracker()
        t.add_yes(100, 0.45)
        t.add_no(50, 0.40)
        pnl = t.settle("YES")
        # payout = 100 * 1.0 = 100, cost = 45 + 20 = 65 → pnl = 35
        assert pnl == pytest.approx(35.0)

    def test_settle_empty_position(self):
        """빈 포지션 정산 → 0."""
        t = PositionTracker()
        pnl = t.settle("YES")
        assert pnl == 0.0

    def test_settle_invalid_winner(self):
        """유효하지 않은 winner → ValueError."""
        t = PositionTracker()
        t.add_yes(100, 0.45)
        with pytest.raises(ValueError, match="winner"):
            t.settle("DRAW")


# ===========================================================================
# PortfolioManager Tests
# ===========================================================================


class TestPortfolioManagerBasic:
    """기본 포트폴리오."""

    def test_empty_portfolio(self):
        pm = PortfolioManager()
        assert pm.active_positions() == {}
        assert pm.total_invested == 0.0
        assert pm.total_locked_profit == 0.0
        assert pm.total_realized_pnl == 0.0

    def test_add_trade_yes(self):
        pm = PortfolioManager()
        pm.add_trade("mkt_1", "YES", 100, 0.45)
        pos = pm.get_position("mkt_1")
        assert pos is not None
        assert pos.yes_shares == 100.0

    def test_add_trade_no(self):
        pm = PortfolioManager()
        pm.add_trade("mkt_1", "NO", 80, 0.40)
        pos = pm.get_position("mkt_1")
        assert pos is not None
        assert pos.no_shares == 80.0

    def test_add_trade_creates_tracker(self):
        """존재하지 않는 마켓에 add_trade → 자동 생성."""
        pm = PortfolioManager()
        pm.add_trade("mkt_new", "YES", 50, 0.50)
        assert "mkt_new" in pm.active_positions()

    def test_get_position_missing(self):
        pm = PortfolioManager()
        assert pm.get_position("nonexistent") is None


class TestPortfolioManagerMultiMarket:
    """여러 마켓 관리."""

    def test_multiple_markets(self):
        pm = PortfolioManager()
        pm.add_trade("mkt_1", "YES", 100, 0.45)
        pm.add_trade("mkt_1", "NO", 100, 0.40)
        pm.add_trade("mkt_2", "YES", 50, 0.30)
        pm.add_trade("mkt_2", "NO", 50, 0.50)

        assert len(pm.active_positions()) == 2

    def test_total_invested(self):
        pm = PortfolioManager()
        pm.add_trade("mkt_1", "YES", 100, 0.45)  # $45
        pm.add_trade("mkt_1", "NO", 100, 0.40)    # $40
        pm.add_trade("mkt_2", "YES", 50, 0.30)    # $15
        assert pm.total_invested == pytest.approx(100.0)

    def test_total_locked_profit(self):
        pm = PortfolioManager()
        pm.add_trade("mkt_1", "YES", 100, 0.45)
        pm.add_trade("mkt_1", "NO", 100, 0.40)
        # locked = 100 * (1 - 0.85) = 15
        pm.add_trade("mkt_2", "YES", 50, 0.30)
        pm.add_trade("mkt_2", "NO", 50, 0.50)
        # locked = 50 * (1 - 0.80) = 10
        assert pm.total_locked_profit == pytest.approx(25.0)


class TestPortfolioManagerSettle:
    """포트폴리오 정산."""

    def test_settle_market(self):
        pm = PortfolioManager()
        pm.add_trade("mkt_1", "YES", 100, 0.45)
        pm.add_trade("mkt_1", "NO", 100, 0.40)
        pnl = pm.settle("mkt_1", "YES")
        assert pnl == pytest.approx(15.0)
        assert pm.total_realized_pnl == pytest.approx(15.0)

    def test_settle_removes_from_active(self):
        pm = PortfolioManager()
        pm.add_trade("mkt_1", "YES", 100, 0.45)
        pm.add_trade("mkt_1", "NO", 100, 0.40)
        pm.settle("mkt_1", "YES")
        assert "mkt_1" not in pm.active_positions()

    def test_settle_nonexistent(self):
        """존재하지 않는 마켓 정산 → 0."""
        pm = PortfolioManager()
        pnl = pm.settle("nonexistent", "YES")
        assert pnl == 0.0

    def test_multiple_settles(self):
        pm = PortfolioManager()
        pm.add_trade("mkt_1", "YES", 100, 0.45)
        pm.add_trade("mkt_1", "NO", 100, 0.40)
        pm.add_trade("mkt_2", "YES", 50, 0.30)
        pm.add_trade("mkt_2", "NO", 50, 0.50)

        pnl1 = pm.settle("mkt_1", "YES")
        pnl2 = pm.settle("mkt_2", "NO")

        assert pm.total_realized_pnl == pytest.approx(pnl1 + pnl2)
        assert len(pm.active_positions()) == 0

    def test_add_trade_invalid_side(self):
        pm = PortfolioManager()
        with pytest.raises(ValueError, match="side"):
            pm.add_trade("mkt_1", "DRAW", 100, 0.45)
