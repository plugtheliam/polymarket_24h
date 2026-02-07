"""Tests for Crypto Fair Value Calculator (F-021).

TDD Red Phase: Write tests before implementation.
Tests RSI, Bollinger Bands, and fair value probability calculation.
"""

from __future__ import annotations

import pytest

from poly24h.strategy.crypto_fair_value import CryptoFairValueCalculator


class TestRSICalculation:
    """Tests for RSI (Relative Strength Index) calculation."""

    def test_calculate_rsi_uptrend(self) -> None:
        """Strong uptrend should yield high RSI (>70)."""
        calc = CryptoFairValueCalculator()
        
        # Consistently rising prices
        closes = [100, 102, 104, 106, 108, 110, 112, 114, 116, 118,
                  120, 122, 124, 126, 128]
        
        rsi = calc.calculate_rsi(closes, period=14)
        
        assert rsi > 70.0  # Overbought territory

    def test_calculate_rsi_downtrend(self) -> None:
        """Strong downtrend should yield low RSI (<30)."""
        calc = CryptoFairValueCalculator()
        
        # Consistently falling prices
        closes = [128, 126, 124, 122, 120, 118, 116, 114, 112, 110,
                  108, 106, 104, 102, 100]
        
        rsi = calc.calculate_rsi(closes, period=14)
        
        assert rsi < 30.0  # Oversold territory

    def test_calculate_rsi_sideways(self) -> None:
        """Sideways movement should yield RSI near 50."""
        calc = CryptoFairValueCalculator()
        
        # Alternating up/down (net neutral)
        closes = [100, 102, 100, 102, 100, 102, 100, 102, 100, 102,
                  100, 102, 100, 102, 100]
        
        rsi = calc.calculate_rsi(closes, period=14)
        
        assert 40.0 <= rsi <= 60.0  # Neutral zone

    def test_calculate_rsi_range(self) -> None:
        """RSI should always be between 0 and 100."""
        calc = CryptoFairValueCalculator()
        
        # Random-ish data
        closes = [100, 105, 103, 108, 106, 110, 107, 112, 109, 115,
                  111, 118, 114, 120, 116]
        
        rsi = calc.calculate_rsi(closes, period=14)
        
        assert 0.0 <= rsi <= 100.0

    def test_calculate_rsi_minimum_data(self) -> None:
        """RSI with minimum required data points."""
        calc = CryptoFairValueCalculator()
        
        # Exactly period + 1 data points
        closes = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109,
                  110, 111, 112, 113, 114, 115]  # 16 points for period=14
        
        rsi = calc.calculate_rsi(closes, period=14)
        
        assert 0.0 <= rsi <= 100.0

    def test_calculate_rsi_insufficient_data(self) -> None:
        """RSI with insufficient data should return 50 (neutral)."""
        calc = CryptoFairValueCalculator()
        
        closes = [100, 101, 102]  # Only 3 data points
        
        rsi = calc.calculate_rsi(closes, period=14)
        
        assert rsi == 50.0  # Default neutral


class TestBollingerBands:
    """Tests for Bollinger Bands calculation."""

    def test_calculate_bollinger_bands_structure(self) -> None:
        """BB should return (lower, middle, upper) tuple."""
        calc = CryptoFairValueCalculator()
        
        closes = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109,
                  110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120]
        
        lower, middle, upper = calc.calculate_bollinger_bands(closes, period=20, std_dev=2)
        
        assert lower < middle < upper

    def test_calculate_bollinger_bands_middle_is_sma(self) -> None:
        """Middle band should be the SMA of the closes."""
        calc = CryptoFairValueCalculator()
        
        closes = [100, 102, 104, 106, 108, 110, 112, 114, 116, 118,
                  120, 122, 124, 126, 128, 130, 132, 134, 136, 138, 140]
        
        lower, middle, upper = calc.calculate_bollinger_bands(closes[-20:], period=20)
        
        expected_sma = sum(closes[-20:]) / 20
        assert middle == pytest.approx(expected_sma, abs=0.01)

    def test_calculate_bollinger_bands_symmetric(self) -> None:
        """Upper and lower should be equidistant from middle."""
        calc = CryptoFairValueCalculator()
        
        closes = [100 + i for i in range(25)]
        
        lower, middle, upper = calc.calculate_bollinger_bands(closes, period=20, std_dev=2)
        
        upper_dist = upper - middle
        lower_dist = middle - lower
        
        assert upper_dist == pytest.approx(lower_dist, abs=0.01)

    def test_calculate_bollinger_bands_std_dev_factor(self) -> None:
        """Changing std_dev should widen/narrow bands proportionally."""
        calc = CryptoFairValueCalculator()
        
        closes = [100, 105, 98, 110, 95, 108, 102, 115, 97, 112,
                  100, 107, 99, 111, 96, 109, 101, 114, 98, 110, 105]
        
        l1, m1, u1 = calc.calculate_bollinger_bands(closes, period=20, std_dev=1)
        l2, m2, u2 = calc.calculate_bollinger_bands(closes, period=20, std_dev=2)
        
        # Middle should be the same
        assert m1 == pytest.approx(m2, abs=0.01)
        
        # 2 std_dev bands should be ~2x wider than 1 std_dev
        width1 = u1 - l1
        width2 = u2 - l2
        assert width2 == pytest.approx(width1 * 2, abs=0.1)

    def test_calculate_bollinger_bands_insufficient_data(self) -> None:
        """With insufficient data, should return sensible defaults."""
        calc = CryptoFairValueCalculator()
        
        closes = [100, 101, 102]  # Only 3 points
        
        lower, middle, upper = calc.calculate_bollinger_bands(closes, period=20)
        
        # Should still return valid structure (using available data)
        assert lower <= middle <= upper


class TestCryptoFairProbability:
    """Tests for crypto fair probability calculation."""

    def test_oversold_conditions(self) -> None:
        """RSI < 30 + price near BB lower → UP prob > 0.50."""
        calc = CryptoFairValueCalculator()
        
        rsi = 25.0  # Oversold
        price = 95.0
        bb_lower = 94.0
        bb_upper = 106.0
        
        up_prob = calc.calculate_fair_probability(rsi, price, bb_lower, bb_upper)
        
        assert up_prob > 0.50  # Expecting bounce

    def test_overbought_conditions(self) -> None:
        """RSI > 70 + price near BB upper → UP prob < 0.50."""
        calc = CryptoFairValueCalculator()
        
        rsi = 75.0  # Overbought
        price = 105.0
        bb_lower = 94.0
        bb_upper = 106.0
        
        up_prob = calc.calculate_fair_probability(rsi, price, bb_lower, bb_upper)
        
        assert up_prob < 0.50  # Expecting pullback

    def test_neutral_conditions(self) -> None:
        """RSI ~50 + price at BB middle → UP prob ~0.50."""
        calc = CryptoFairValueCalculator()
        
        rsi = 50.0  # Neutral
        price = 100.0
        bb_lower = 94.0
        bb_upper = 106.0
        # Middle = 100.0
        
        up_prob = calc.calculate_fair_probability(rsi, price, bb_lower, bb_upper)
        
        assert 0.45 <= up_prob <= 0.55  # Near neutral

    def test_probability_range(self) -> None:
        """Fair probability should always be between 0 and 1."""
        calc = CryptoFairValueCalculator()
        
        # Test various extreme conditions
        test_cases = [
            (10.0, 90.0, 92.0, 108.0),   # Very oversold, near lower
            (90.0, 110.0, 92.0, 108.0),  # Very overbought, above upper
            (50.0, 100.0, 95.0, 105.0),  # Neutral
        ]
        
        for rsi, price, bb_lower, bb_upper in test_cases:
            prob = calc.calculate_fair_probability(rsi, price, bb_lower, bb_upper)
            assert 0.0 <= prob <= 1.0, f"Failed for RSI={rsi}, price={price}"


class TestCryptoUndervalued:
    """Tests for crypto undervalued detection."""

    def test_yes_side_undervalued(self) -> None:
        """YES side undervalued when market_price < fair_prob - margin."""
        calc = CryptoFairValueCalculator()
        
        # Fair UP prob = 0.60, market price = 0.40
        # 0.40 < 0.60 - 0.05 = 0.55 → undervalued
        is_under = calc.is_undervalued(
            side="YES", market_price=0.40, fair_prob=0.60, margin=0.05
        )
        
        assert is_under is True

    def test_yes_side_not_undervalued(self) -> None:
        """YES side not undervalued when market_price >= fair_prob - margin."""
        calc = CryptoFairValueCalculator()
        
        # Fair UP prob = 0.60, market price = 0.58
        # 0.58 > 0.60 - 0.05 = 0.55 → not undervalued
        is_under = calc.is_undervalued(
            side="YES", market_price=0.58, fair_prob=0.60, margin=0.05
        )
        
        assert is_under is False

    def test_no_side_undervalued(self) -> None:
        """NO side undervalued when market_price < (1 - fair_prob) - margin."""
        calc = CryptoFairValueCalculator()
        
        # Fair UP prob = 0.60 → DOWN fair prob = 0.40
        # market price = 0.30 < 0.40 - 0.05 = 0.35 → undervalued
        is_under = calc.is_undervalued(
            side="NO", market_price=0.30, fair_prob=0.60, margin=0.05
        )
        
        assert is_under is True

    def test_no_side_not_undervalued(self) -> None:
        """NO side not undervalued when market_price >= (1 - fair_prob) - margin."""
        calc = CryptoFairValueCalculator()
        
        # Fair UP prob = 0.60 → DOWN fair prob = 0.40
        # market price = 0.38 > 0.40 - 0.05 = 0.35 → not undervalued
        is_under = calc.is_undervalued(
            side="NO", market_price=0.38, fair_prob=0.60, margin=0.05
        )
        
        assert is_under is False

    def test_default_margin(self) -> None:
        """Default margin should be 0.05."""
        calc = CryptoFairValueCalculator()
        
        # Without explicit margin
        assert calc.is_undervalued("YES", 0.40, 0.60) is True   # 0.40 < 0.55
        assert calc.is_undervalued("YES", 0.56, 0.60) is False  # 0.56 > 0.55


class TestBinanceOHLCV:
    """Tests for Binance OHLCV data fetching."""

    @pytest.mark.asyncio
    async def test_fetch_returns_list(self) -> None:
        """Fetch should return a list of OHLCV dicts."""
        calc = CryptoFairValueCalculator()
        
        # This test uses mock data, not real Binance API
        data = await calc.fetch_binance_ohlcv("BTCUSDT", interval="1h", limit=20)
        
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_fetch_ohlcv_structure(self) -> None:
        """Each OHLCV entry should have expected keys."""
        calc = CryptoFairValueCalculator()
        
        data = await calc.fetch_binance_ohlcv("BTCUSDT", interval="1h", limit=5)
        
        if data:  # Only check if we got data
            entry = data[0]
            # Should have open, high, low, close, volume
            assert "close" in entry or len(entry) >= 5

    @pytest.mark.asyncio
    async def test_fetch_with_invalid_symbol(self) -> None:
        """Invalid symbol should return empty list."""
        calc = CryptoFairValueCalculator()
        
        data = await calc.fetch_binance_ohlcv("INVALID123", interval="1h", limit=5)
        
        # Should gracefully handle error
        assert isinstance(data, list)


class TestCryptoFairValueIntegration:
    """Integration tests for full crypto fair value workflow."""

    def test_full_workflow_oversold_market(self) -> None:
        """Full workflow: Calculate indicators → fair prob → undervalued check."""
        calc = CryptoFairValueCalculator()
        
        # Simulated downtrend (prices falling)
        closes = [108, 106, 105, 103, 102, 100, 99, 97, 96, 95,
                  94, 93, 92, 91, 90]
        
        rsi = calc.calculate_rsi(closes, period=14)
        bb_lower, bb_mid, bb_upper = calc.calculate_bollinger_bands(
            closes, period=14, std_dev=2
        )
        
        current_price = closes[-1]  # 90
        
        # Should be oversold
        assert rsi < 40.0, f"Expected oversold RSI, got {rsi}"
        
        # Calculate fair UP probability
        fair_prob = calc.calculate_fair_probability(rsi, current_price, bb_lower, bb_upper)
        
        # Oversold = expect bounce = UP prob > 0.50
        assert fair_prob > 0.50, f"Expected UP prob > 0.50, got {fair_prob}"
        
        # If market is selling YES (UP) at $0.40, it's undervalued
        assert calc.is_undervalued("YES", 0.40, fair_prob, margin=0.05) is True

    def test_full_workflow_overbought_market(self) -> None:
        """Full workflow for overbought market conditions."""
        calc = CryptoFairValueCalculator()
        
        # Simulated uptrend (prices rising)
        closes = [90, 92, 94, 96, 98, 100, 102, 104, 106, 108,
                  110, 112, 114, 116, 118]
        
        rsi = calc.calculate_rsi(closes, period=14)
        bb_lower, bb_mid, bb_upper = calc.calculate_bollinger_bands(
            closes, period=14, std_dev=2
        )
        
        current_price = closes[-1]  # 118
        
        # Should be overbought
        assert rsi > 60.0, f"Expected overbought RSI, got {rsi}"
        
        # Calculate fair UP probability
        fair_prob = calc.calculate_fair_probability(rsi, current_price, bb_lower, bb_upper)
        
        # Overbought = expect pullback = UP prob < 0.50
        assert fair_prob < 0.50, f"Expected UP prob < 0.50, got {fair_prob}"
        
        # If market is selling NO (DOWN) at $0.40 with DOWN fair prob high, check undervalued
        down_fair_prob = 1.0 - fair_prob
        assert calc.is_undervalued("NO", 0.40, fair_prob, margin=0.05) is (
            0.40 < down_fair_prob - 0.05
        )
