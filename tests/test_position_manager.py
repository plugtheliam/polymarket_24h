"""TDD tests for PositionManager - Kent Beck style.

Feature: 018-realistic-dryrun
Goal: Realistic dry-run with proper position management.
"""

import pytest
from datetime import datetime, timezone
from poly24h.position_manager import PositionManager, Position


class TestPositionManagerCreation:
    """Test PositionManager initialization."""

    def test_create_with_bankroll_and_max_per_market(self):
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        assert pm.bankroll == 1000.0
        assert pm.max_per_market == 100.0
        assert pm.active_position_count == 0

    def test_create_with_zero_bankroll(self):
        pm = PositionManager(bankroll=0.0, max_per_market=100.0)
        assert pm.bankroll == 0.0


class TestCanEnterPosition:
    """Test position entry eligibility."""

    def test_can_enter_new_market(self):
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        assert pm.can_enter("btc_6pm") is True

    def test_cannot_enter_existing_market(self):
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        pm.enter_position(
            market_id="btc_6pm",
            market_question="Bitcoin Up or Down - Feb 7, 6PM ET",
            side="NO",
            price=0.45,
            end_date="2026-02-08T02:00:00Z",
        )
        assert pm.can_enter("btc_6pm") is False
        assert pm.can_enter("btc_7pm") is True  # Different market OK

    def test_cannot_enter_with_zero_bankroll(self):
        pm = PositionManager(bankroll=0.0, max_per_market=100.0)
        assert pm.can_enter("btc_6pm") is False

    def test_cannot_enter_with_insufficient_bankroll(self):
        pm = PositionManager(bankroll=0.50, max_per_market=100.0)
        # Less than $1 minimum
        assert pm.can_enter("btc_6pm") is False


class TestEnterPosition:
    """Test position entry mechanics."""

    def test_enter_position_creates_position(self):
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        pos = pm.enter_position(
            market_id="btc_6pm",
            market_question="Bitcoin Up or Down - Feb 7, 6PM ET",
            side="NO",
            price=0.45,
            end_date="2026-02-08T02:00:00Z",
        )
        assert pos is not None
        assert pos.market_id == "btc_6pm"
        assert pos.side == "NO"
        assert pos.entry_price == 0.45
        assert pos.size_usd == 100.0  # max_per_market
        assert pos.shares == pytest.approx(222.22, rel=0.01)  # 100 / 0.45

    def test_enter_position_deducts_bankroll(self):
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        pm.enter_position(
            market_id="btc_6pm",
            market_question="Bitcoin",
            side="NO",
            price=0.45,
            end_date="2026-02-08T02:00:00Z",
        )
        assert pm.bankroll == 900.0

    def test_enter_position_limited_by_bankroll(self):
        pm = PositionManager(bankroll=50.0, max_per_market=100.0)
        pos = pm.enter_position(
            market_id="btc_6pm",
            market_question="Bitcoin",
            side="NO",
            price=0.45,
            end_date="2026-02-08T02:00:00Z",
        )
        assert pos.size_usd == 50.0  # Limited by bankroll
        assert pm.bankroll == 0.0

    def test_enter_position_returns_none_if_already_exists(self):
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        pm.enter_position(
            market_id="btc_6pm",
            market_question="Bitcoin",
            side="NO",
            price=0.45,
            end_date="2026-02-08T02:00:00Z",
        )
        # Try to enter same market again
        pos2 = pm.enter_position(
            market_id="btc_6pm",
            market_question="Bitcoin",
            side="YES",
            price=0.55,
            end_date="2026-02-08T02:00:00Z",
        )
        assert pos2 is None
        assert pm.bankroll == 900.0  # No additional deduction


class TestSettlePosition:
    """Test position settlement mechanics."""

    def test_settle_winning_position(self):
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        pm.enter_position(
            market_id="btc_6pm",
            market_question="Bitcoin",
            side="NO",
            price=0.40,  # Entry at 40¢
            end_date="2026-02-08T02:00:00Z",
        )
        # bankroll = 900, shares = 250
        pnl = pm.settle_position("btc_6pm", winner="NO")
        # Won: payout = 250 * $1 = $250, cost = $100, pnl = +$150
        assert pnl == pytest.approx(150.0, rel=0.01)
        assert pm.bankroll == pytest.approx(1150.0, rel=0.01)
        assert pm.active_position_count == 0

    def test_settle_losing_position(self):
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        pm.enter_position(
            market_id="btc_6pm",
            market_question="Bitcoin",
            side="NO",
            price=0.40,
            end_date="2026-02-08T02:00:00Z",
        )
        # bankroll = 900
        pnl = pm.settle_position("btc_6pm", winner="YES")
        # Lost: payout = 0, cost = $100, pnl = -$100
        assert pnl == -100.0
        assert pm.bankroll == 900.0  # No change (already deducted)
        assert pm.active_position_count == 0

    def test_settle_nonexistent_position_returns_zero(self):
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        pnl = pm.settle_position("nonexistent", winner="YES")
        assert pnl == 0.0
        assert pm.bankroll == 1000.0

    def test_can_enter_after_settlement(self):
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        pm.enter_position(
            market_id="btc_6pm",
            market_question="Bitcoin",
            side="NO",
            price=0.40,
            end_date="2026-02-08T02:00:00Z",
        )
        assert pm.can_enter("btc_6pm") is False
        pm.settle_position("btc_6pm", winner="NO")
        # After settlement, can enter new position in same market
        assert pm.can_enter("btc_6pm") is True


class TestPositionManagerStats:
    """Test position statistics."""

    def test_active_position_count(self):
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        assert pm.active_position_count == 0
        pm.enter_position("btc_6pm", "Bitcoin 6PM", "NO", 0.40, "2026-02-08T02:00:00Z")
        assert pm.active_position_count == 1
        pm.enter_position("btc_7pm", "Bitcoin 7PM", "YES", 0.55, "2026-02-08T03:00:00Z")
        assert pm.active_position_count == 2
        pm.settle_position("btc_6pm", "NO")
        assert pm.active_position_count == 1

    def test_get_active_positions(self):
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        pm.enter_position("btc_6pm", "Bitcoin 6PM", "NO", 0.40, "2026-02-08T02:00:00Z")
        pm.enter_position("btc_7pm", "Bitcoin 7PM", "YES", 0.55, "2026-02-08T03:00:00Z")
        positions = pm.get_active_positions()
        assert len(positions) == 2
        assert "btc_6pm" in [p.market_id for p in positions]

    def test_cumulative_pnl(self):
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        pm.enter_position("btc_6pm", "Bitcoin", "NO", 0.40, "2026-02-08T02:00:00Z")
        pm.settle_position("btc_6pm", "NO")  # +$150
        pm.enter_position("btc_7pm", "Bitcoin", "YES", 0.60, "2026-02-08T03:00:00Z")
        pm.settle_position("btc_7pm", "NO")  # -$100
        assert pm.cumulative_pnl == pytest.approx(50.0, rel=0.01)
        assert pm.total_settled == 2
        assert pm.wins == 1
        assert pm.losses == 1


class TestPositionPersistence:
    """Test state persistence."""

    def test_save_and_load_state(self, tmp_path):
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        pm.enter_position("btc_6pm", "Bitcoin 6PM", "NO", 0.40, "2026-02-08T02:00:00Z")
        pm.enter_position("btc_7pm", "Bitcoin 7PM", "YES", 0.55, "2026-02-08T03:00:00Z")
        
        state_file = tmp_path / "positions.json"
        pm.save_state(state_file)
        
        # Create new manager and load
        pm2 = PositionManager(bankroll=0.0, max_per_market=100.0)  # Will be overwritten
        pm2.load_state(state_file)
        
        assert pm2.bankroll == pm.bankroll
        assert pm2.active_position_count == 2
        assert pm2.can_enter("btc_6pm") is False
        assert pm2.can_enter("btc_8pm") is True

    def test_load_nonexistent_state_starts_fresh(self, tmp_path):
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        pm.load_state(tmp_path / "nonexistent.json")
        assert pm.bankroll == 1000.0
        assert pm.active_position_count == 0
