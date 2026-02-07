"""TDD tests for Polymarket fee calculator (Kent Beck style).

Fee structure:
- Taker Fee = 4 * p * (1-p) * 3.15%
- Maker Rebate = Taker Fee * 80%
"""

import pytest
from decimal import Decimal
from poly24h.strategy.fee_calculator import (
    calculate_taker_fee,
    calculate_maker_rebate,
    calculate_real_cost,
    calculate_paired_cpp,
    is_profitable_after_fees,
)


class TestTakerFee:
    """Test taker fee calculation."""

    def test_taker_fee_at_50_percent(self):
        """Max fee at 50% probability."""
        fee = calculate_taker_fee(Decimal("0.50"))
        # 4 * 0.5 * 0.5 * 0.0315 = 0.0315 (3.15%)
        assert fee == Decimal("0.0315")

    def test_taker_fee_at_30_percent(self):
        """Fee at 30% probability."""
        fee = calculate_taker_fee(Decimal("0.30"))
        # 4 * 0.3 * 0.7 * 0.0315 = 0.02646
        assert abs(fee - Decimal("0.02646")) < Decimal("0.0001")

    def test_taker_fee_at_20_percent(self):
        """Fee at 20% probability."""
        fee = calculate_taker_fee(Decimal("0.20"))
        # 4 * 0.2 * 0.8 * 0.0315 = 0.02016
        assert abs(fee - Decimal("0.02016")) < Decimal("0.0001")

    def test_taker_fee_at_extremes(self):
        """Fee approaches 0 at extreme probabilities."""
        fee_low = calculate_taker_fee(Decimal("0.05"))
        fee_high = calculate_taker_fee(Decimal("0.95"))
        # Both should be small
        assert fee_low < Decimal("0.01")
        assert fee_high < Decimal("0.01")


class TestMakerRebate:
    """Test maker rebate calculation."""

    def test_maker_rebate_at_50_percent(self):
        """Rebate is 80% of taker fee."""
        rebate = calculate_maker_rebate(Decimal("0.50"))
        # 0.0315 * 0.80 = 0.0252
        assert rebate == Decimal("0.0252")

    def test_maker_rebate_at_30_percent(self):
        """Rebate at 30% probability."""
        rebate = calculate_maker_rebate(Decimal("0.30"))
        # 0.02646 * 0.80 ≈ 0.021168
        assert abs(rebate - Decimal("0.021168")) < Decimal("0.0001")


class TestRealCost:
    """Test real cost after fees."""

    def test_taker_cost_higher(self):
        """Taker pays price + fee."""
        cost = calculate_real_cost(Decimal("0.50"), is_maker=False)
        # 0.50 + 0.0315 = 0.5315
        assert cost == Decimal("0.5315")

    def test_maker_cost_lower(self):
        """Maker pays price - rebate."""
        cost = calculate_real_cost(Decimal("0.50"), is_maker=True)
        # 0.50 - 0.0252 = 0.4748
        assert cost == Decimal("0.4748")

    def test_taker_at_low_price(self):
        """Taker cost at low price."""
        cost = calculate_real_cost(Decimal("0.20"), is_maker=False)
        # 0.20 + 0.02016 ≈ 0.22016
        assert abs(cost - Decimal("0.22016")) < Decimal("0.001")


class TestPairedCPP:
    """Test Cost Per Pair for paired entry."""

    def test_both_taker(self):
        """Both sides as taker (worst case)."""
        cpp = calculate_paired_cpp(
            yes_price=Decimal("0.45"),
            no_price=Decimal("0.50"),
            yes_is_maker=False,
            no_is_maker=False,
        )
        # YES: 0.45 + fee, NO: 0.50 + fee
        # Combined should be > 0.95
        assert cpp > Decimal("0.95")
        assert cpp < Decimal("1.02")

    def test_both_maker(self):
        """Both sides as maker (best case)."""
        cpp = calculate_paired_cpp(
            yes_price=Decimal("0.45"),
            no_price=Decimal("0.50"),
            yes_is_maker=True,
            no_is_maker=True,
        )
        # With rebates, should be < 0.95
        assert cpp < Decimal("0.95")

    def test_mixed_taker_maker(self):
        """One taker, one maker."""
        cpp = calculate_paired_cpp(
            yes_price=Decimal("0.45"),
            no_price=Decimal("0.50"),
            yes_is_maker=False,
            no_is_maker=True,
        )
        # Should be between both_taker and both_maker
        assert Decimal("0.90") < cpp < Decimal("1.00")


class TestProfitability:
    """Test profitability check after fees."""

    def test_profitable_with_wide_spread(self):
        """Wide spread should be profitable."""
        result = is_profitable_after_fees(
            yes_price=Decimal("0.40"),
            no_price=Decimal("0.45"),
            min_margin=Decimal("0.01"),
        )
        assert result is True

    def test_not_profitable_tight_spread(self):
        """Tight spread not profitable after fees."""
        result = is_profitable_after_fees(
            yes_price=Decimal("0.48"),
            no_price=Decimal("0.50"),
            min_margin=Decimal("0.01"),
        )
        # 0.48 + 0.50 = 0.98, but after ~3% fees, not profitable
        assert result is False

    def test_marginal_case(self):
        """Marginal case: 4% margin vs ~6% fees (both sides)."""
        result = is_profitable_after_fees(
            yes_price=Decimal("0.46"),
            no_price=Decimal("0.50"),
            min_margin=Decimal("0.005"),  # 0.5% min margin
        )
        # 0.96 base + ~6% fees (3% each side) ≈ 1.02, NOT profitable
        assert result is False


class TestIntegration:
    """Integration tests with realistic scenarios."""

    @pytest.mark.parametrize("yes_price,no_price,expected_profitable", [
        (Decimal("0.40"), Decimal("0.45"), True),   # 15% margin - 5% fees = profitable
        (Decimal("0.45"), Decimal("0.48"), True),   # 7% margin - 6% fees = barely profitable
        (Decimal("0.47"), Decimal("0.50"), False),  # 3% margin (eaten by fees)
        (Decimal("0.48"), Decimal("0.50"), False),  # 2% margin (eaten by fees)
        (Decimal("0.30"), Decimal("0.65"), False),  # 5% margin - ~5.5% fees = NOT profitable
    ])
    def test_various_spreads(self, yes_price, no_price, expected_profitable):
        """Test various spread scenarios."""
        result = is_profitable_after_fees(
            yes_price=yes_price,
            no_price=no_price,
            min_margin=Decimal("0.005"),
        )
        assert result is expected_profitable, (
            f"YES={yes_price}, NO={no_price}: expected {expected_profitable}"
        )
