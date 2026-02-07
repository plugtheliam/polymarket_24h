"""Tests for Phase 2: Dynamic threshold based on liquidity."""

from __future__ import annotations

import pytest

from poly24h.strategy.dynamic_threshold import (
    DEFAULT_BANDS,
    DynamicThreshold,
    ThresholdBand,
)


class TestDynamicThreshold:
    def test_default_bands(self):
        dt = DynamicThreshold()
        assert len(dt.bands) == 4

    def test_low_liquidity(self):
        dt = DynamicThreshold()
        assert dt.get_threshold(1_000) == 0.45
        assert dt.get_threshold(4_999) == 0.45

    def test_medium_liquidity(self):
        dt = DynamicThreshold()
        assert dt.get_threshold(5_000) == 0.47
        assert dt.get_threshold(10_000) == 0.47
        assert dt.get_threshold(19_999) == 0.47

    def test_high_liquidity(self):
        dt = DynamicThreshold()
        assert dt.get_threshold(20_000) == 0.48
        assert dt.get_threshold(30_000) == 0.48
        assert dt.get_threshold(49_999) == 0.48

    def test_very_high_liquidity(self):
        dt = DynamicThreshold()
        assert dt.get_threshold(50_000) == 0.49
        assert dt.get_threshold(100_000) == 0.49
        assert dt.get_threshold(1_000_000) == 0.49

    def test_zero_liquidity(self):
        dt = DynamicThreshold()
        assert dt.get_threshold(0) == 0.45

    def test_boundary_values(self):
        dt = DynamicThreshold()
        assert dt.get_threshold(4_999.99) == 0.45
        assert dt.get_threshold(5_000.0) == 0.47
        assert dt.get_threshold(19_999.99) == 0.47
        assert dt.get_threshold(20_000.0) == 0.48
        assert dt.get_threshold(49_999.99) == 0.48
        assert dt.get_threshold(50_000.0) == 0.49

    def test_custom_bands(self):
        custom = [
            ThresholdBand(0, 10_000, 0.40, "low"),
            ThresholdBand(10_000, float("inf"), 0.50, "high"),
        ]
        dt = DynamicThreshold(bands=custom)
        assert dt.get_threshold(5_000) == 0.40
        assert dt.get_threshold(15_000) == 0.50

    def test_get_band_label(self):
        dt = DynamicThreshold()
        assert dt.get_band_label(1_000) == "low"
        assert dt.get_band_label(10_000) == "medium"
        assert dt.get_band_label(30_000) == "high"
        assert dt.get_band_label(100_000) == "very_high"

    def test_classify_market(self):
        dt = DynamicThreshold()
        threshold, label = dt.classify_market(75_000)
        assert threshold == 0.49
        assert label == "very_high"

        threshold, label = dt.classify_market(3_000)
        assert threshold == 0.45
        assert label == "low"

    def test_default_threshold_fallback(self):
        """If no band matches, use default."""
        empty_bands: list[ThresholdBand] = []
        dt = DynamicThreshold(bands=empty_bands, default_threshold=0.42)
        assert dt.get_threshold(10_000) == 0.42

    def test_bands_sorted_by_min_liquidity(self):
        """Bands should be sorted regardless of input order."""
        bands = [
            ThresholdBand(50_000, float("inf"), 0.49, "high"),
            ThresholdBand(0, 50_000, 0.45, "low"),
        ]
        dt = DynamicThreshold(bands=bands)
        assert dt.bands[0].min_liquidity_usd == 0
        assert dt.bands[1].min_liquidity_usd == 50_000

    def test_classify_nba_typical_liquidity(self):
        """NBA markets typically have $5K-30K liquidity."""
        dt = DynamicThreshold()
        threshold, label = dt.classify_market(15_000)
        assert threshold == 0.47
        assert label == "medium"

    def test_classify_crypto_typical_liquidity(self):
        """Crypto hourly markets often have $30K-100K+ liquidity."""
        dt = DynamicThreshold()
        threshold, label = dt.classify_market(80_000)
        assert threshold == 0.49
        assert label == "very_high"
