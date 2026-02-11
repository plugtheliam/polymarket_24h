"""TDD tests for ETH decoupling fix (P1-1).

When ETH's momentum diverges from BTC, the model should reduce its
confidence rather than blindly following the majority trend.
"""

from poly24h.strategy.crypto_fair_value import CryptoFairValueCalculator


class TestETHDecouplingAdjustment:
    """ETH gets a decoupling penalty when its momentum diverges from BTC."""

    def test_decoupling_factor_same_direction(self):
        """When ETH and BTC both go up, no penalty."""
        calc = CryptoFairValueCalculator()
        factor = calc.eth_decoupling_factor(
            eth_momentum=1.5, btc_momentum=1.0,
        )
        assert factor == 1.0  # No penalty: same direction

    def test_decoupling_factor_opposite_direction(self):
        """When ETH goes up but BTC goes down, apply penalty."""
        calc = CryptoFairValueCalculator()
        factor = calc.eth_decoupling_factor(
            eth_momentum=1.5, btc_momentum=-1.0,
        )
        assert 0.0 < factor < 1.0  # Penalized

    def test_decoupling_factor_both_down(self):
        """When both go down, no penalty."""
        calc = CryptoFairValueCalculator()
        factor = calc.eth_decoupling_factor(
            eth_momentum=-1.5, btc_momentum=-1.0,
        )
        assert factor == 1.0

    def test_decoupling_factor_eth_flat(self):
        """When ETH is flat (no momentum), no penalty."""
        calc = CryptoFairValueCalculator()
        factor = calc.eth_decoupling_factor(
            eth_momentum=0.0, btc_momentum=-1.0,
        )
        assert factor == 1.0  # Near-zero momentum doesn't trigger penalty

    def test_fair_probability_with_decoupling(self):
        """Fair probability should be closer to 0.50 when decoupling."""
        calc = CryptoFairValueCalculator()

        # Normal case: strong up momentum → high fair prob
        normal_prob = calc.calculate_fair_probability(
            rsi=50, price=100, bb_lower=95, bb_upper=105,
            momentum=2.0, volume_spike=1.0, trend_direction=1.0,
        )
        assert normal_prob > 0.55  # Strongly bullish

        # With decoupling penalty: same momentum but penalized
        decoupled_prob = calc.calculate_fair_probability(
            rsi=50, price=100, bb_lower=95, bb_upper=105,
            momentum=2.0, volume_spike=1.0, trend_direction=1.0,
            decoupling_factor=0.5,
        )
        # Should be closer to 0.50 than normal_prob
        assert abs(decoupled_prob - 0.50) < abs(normal_prob - 0.50)

    def test_fair_probability_no_decoupling_factor(self):
        """Default decoupling_factor=1.0 has no effect."""
        calc = CryptoFairValueCalculator()
        prob_default = calc.calculate_fair_probability(
            rsi=50, price=100, bb_lower=95, bb_upper=105,
            momentum=1.5, volume_spike=1.0, trend_direction=1.0,
        )
        prob_explicit = calc.calculate_fair_probability(
            rsi=50, price=100, bb_lower=95, bb_upper=105,
            momentum=1.5, volume_spike=1.0, trend_direction=1.0,
            decoupling_factor=1.0,
        )
        assert prob_default == prob_explicit
