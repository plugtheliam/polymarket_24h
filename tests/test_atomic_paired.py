"""TDD tests for Atomic Paired State Machine (Kent Beck style).

State Machine:
    INIT → SUBMITTED → BOTH_CONFIRMED → COMMITTED
                    → PARTIAL → UNWIND → UNWOUND/FAILED
"""

import pytest
from decimal import Decimal
from poly24h.execution.atomic_paired import (
    PairState,
    LegStatus,
    AtomicPairedTransaction,
)


class TestPairState:
    """Test state transitions."""

    def test_initial_state(self):
        """Transaction starts in INIT state."""
        txn = AtomicPairedTransaction(market_id="test-123")
        assert txn.state == PairState.INIT

    def test_submit_transitions_to_submitted(self):
        """submit() transitions to SUBMITTED."""
        txn = AtomicPairedTransaction(market_id="test-123")
        txn.submit(
            yes_price=Decimal("0.40"),
            no_price=Decimal("0.45"),
            shares=Decimal("100"),
        )
        assert txn.state == PairState.SUBMITTED

    def test_both_confirmed_transitions_to_committed(self):
        """Both legs confirmed → BOTH_CONFIRMED."""
        txn = AtomicPairedTransaction(market_id="test-123")
        txn.submit(Decimal("0.40"), Decimal("0.45"), Decimal("100"))
        
        txn.confirm_leg("YES", filled=Decimal("100"))
        txn.confirm_leg("NO", filled=Decimal("100"))
        
        assert txn.state == PairState.BOTH_CONFIRMED

    def test_partial_yes_only(self):
        """Only YES confirmed → PARTIAL_YES."""
        txn = AtomicPairedTransaction(market_id="test-123")
        txn.submit(Decimal("0.40"), Decimal("0.45"), Decimal("100"))
        
        txn.confirm_leg("YES", filled=Decimal("100"))
        txn.timeout_leg("NO")
        
        assert txn.state == PairState.PARTIAL_YES

    def test_partial_no_only(self):
        """Only NO confirmed → PARTIAL_NO."""
        txn = AtomicPairedTransaction(market_id="test-123")
        txn.submit(Decimal("0.40"), Decimal("0.45"), Decimal("100"))
        
        txn.confirm_leg("NO", filled=Decimal("100"))
        txn.timeout_leg("YES")
        
        assert txn.state == PairState.PARTIAL_NO

    def test_none_confirmed(self):
        """Neither confirmed → NONE_CONFIRMED."""
        txn = AtomicPairedTransaction(market_id="test-123")
        txn.submit(Decimal("0.40"), Decimal("0.45"), Decimal("100"))
        
        txn.timeout_leg("YES")
        txn.timeout_leg("NO")
        
        assert txn.state == PairState.NONE_CONFIRMED


class TestLegStatus:
    """Test leg status tracking."""

    def test_leg_not_filled_initially(self):
        """Leg starts unfilled."""
        leg = LegStatus()
        assert not leg.is_filled()

    def test_leg_filled_when_target_reached(self):
        """Leg is filled when filled >= target."""
        leg = LegStatus(target=Decimal("100"), filled=Decimal("100"))
        assert leg.is_filled()

    def test_leg_partial_fill(self):
        """Leg is not filled with partial fill."""
        leg = LegStatus(target=Decimal("100"), filled=Decimal("50"))
        assert not leg.is_filled()


class TestUnwind:
    """Test unwind logic for partial fills."""

    def test_needs_unwind_partial_yes(self):
        """PARTIAL_YES needs YES unwound."""
        txn = AtomicPairedTransaction(market_id="test-123")
        txn.submit(Decimal("0.40"), Decimal("0.45"), Decimal("100"))
        txn.confirm_leg("YES", filled=Decimal("100"))
        txn.timeout_leg("NO")
        
        assert txn.needs_unwind() == "YES"

    def test_needs_unwind_partial_no(self):
        """PARTIAL_NO needs NO unwound."""
        txn = AtomicPairedTransaction(market_id="test-123")
        txn.submit(Decimal("0.40"), Decimal("0.45"), Decimal("100"))
        txn.confirm_leg("NO", filled=Decimal("100"))
        txn.timeout_leg("YES")
        
        assert txn.needs_unwind() == "NO"

    def test_no_unwind_needed_both_confirmed(self):
        """BOTH_CONFIRMED doesn't need unwind."""
        txn = AtomicPairedTransaction(market_id="test-123")
        txn.submit(Decimal("0.40"), Decimal("0.45"), Decimal("100"))
        txn.confirm_leg("YES", filled=Decimal("100"))
        txn.confirm_leg("NO", filled=Decimal("100"))
        
        assert txn.needs_unwind() is None

    def test_unwind_success_transitions_to_unwound(self):
        """Successful unwind → UNWOUND."""
        txn = AtomicPairedTransaction(market_id="test-123")
        txn.submit(Decimal("0.40"), Decimal("0.45"), Decimal("100"))
        txn.confirm_leg("YES", filled=Decimal("100"))
        txn.timeout_leg("NO")
        
        txn.record_unwind(
            leg="YES",
            success=True,
            sold_shares=Decimal("100"),
            slippage_pct=Decimal("1.5"),
        )
        
        assert txn.state == PairState.UNWOUND


class TestCommit:
    """Test commit logic."""

    def test_commit_from_both_confirmed(self):
        """Can commit from BOTH_CONFIRMED."""
        txn = AtomicPairedTransaction(market_id="test-123")
        txn.submit(Decimal("0.40"), Decimal("0.45"), Decimal("100"))
        txn.confirm_leg("YES", filled=Decimal("100"))
        txn.confirm_leg("NO", filled=Decimal("100"))
        
        txn.commit()
        
        assert txn.state == PairState.COMMITTED

    def test_cannot_commit_from_partial(self):
        """Cannot commit from PARTIAL state."""
        txn = AtomicPairedTransaction(market_id="test-123")
        txn.submit(Decimal("0.40"), Decimal("0.45"), Decimal("100"))
        txn.confirm_leg("YES", filled=Decimal("100"))
        txn.timeout_leg("NO")
        
        with pytest.raises(ValueError):
            txn.commit()


class TestProfitCalculation:
    """Test profit calculation."""

    def test_calculate_expected_profit(self):
        """Calculate profit from paired entry."""
        txn = AtomicPairedTransaction(market_id="test-123")
        txn.submit(Decimal("0.40"), Decimal("0.45"), Decimal("100"))
        txn.confirm_leg("YES", filled=Decimal("100"))
        txn.confirm_leg("NO", filled=Decimal("100"))
        
        # Base: $0.40 + $0.45 = $0.85 cost per pair
        # Payout: $1.00 per pair
        # Gross profit: $0.15 per pair × 100 = $15
        # (fees not included in this basic calc)
        profit = txn.calculate_gross_profit()
        assert profit == Decimal("15.00")


class TestTerminalStates:
    """Test terminal state detection."""

    @pytest.mark.parametrize("final_state", [
        PairState.COMMITTED,
        PairState.UNWOUND,
        PairState.NONE_CONFIRMED,
    ])
    def test_terminal_states(self, final_state):
        """These states are terminal."""
        txn = AtomicPairedTransaction(market_id="test-123")
        txn.state = final_state
        assert txn.is_terminal()

    @pytest.mark.parametrize("non_terminal_state", [
        PairState.INIT,
        PairState.SUBMITTED,
        PairState.PARTIAL_YES,
        PairState.PARTIAL_NO,
    ])
    def test_non_terminal_states(self, non_terminal_state):
        """These states are NOT terminal."""
        txn = AtomicPairedTransaction(market_id="test-123")
        txn.state = non_terminal_state
        assert not txn.is_terminal()
