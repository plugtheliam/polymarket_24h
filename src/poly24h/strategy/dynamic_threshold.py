"""Dynamic threshold adjustment based on market liquidity.

Inspired by polymarket_trader's confidence decay and adaptive strategies:
- High liquidity markets: tighter spreads → more aggressive threshold ($0.49)
- Low liquidity markets: wider spreads → conservative threshold ($0.45)
- Default: $0.48

Thresholds are tuned based on observed orderbook depth patterns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ThresholdBand:
    """A liquidity band with its associated threshold."""

    min_liquidity_usd: float
    max_liquidity_usd: float
    threshold: float
    label: str


# Default liquidity bands
DEFAULT_BANDS: list[ThresholdBand] = [
    ThresholdBand(
        min_liquidity_usd=0,
        max_liquidity_usd=5_000,
        threshold=0.45,
        label="low",
    ),
    ThresholdBand(
        min_liquidity_usd=5_000,
        max_liquidity_usd=20_000,
        threshold=0.47,
        label="medium",
    ),
    ThresholdBand(
        min_liquidity_usd=20_000,
        max_liquidity_usd=50_000,
        threshold=0.48,
        label="high",
    ),
    ThresholdBand(
        min_liquidity_usd=50_000,
        max_liquidity_usd=float("inf"),
        threshold=0.49,
        label="very_high",
    ),
]


class DynamicThreshold:
    """Calculates threshold dynamically based on market liquidity.

    Usage:
        dt = DynamicThreshold()
        threshold = dt.get_threshold(liquidity_usd=30000)  # → 0.48
        threshold = dt.get_threshold(liquidity_usd=100000) # → 0.49
        threshold = dt.get_threshold(liquidity_usd=2000)   # → 0.45
    """

    def __init__(
        self,
        bands: list[ThresholdBand] | None = None,
        default_threshold: float = 0.48,
    ):
        self.bands = list(DEFAULT_BANDS) if bands is None else list(bands)
        self.default_threshold = default_threshold
        # Sort by min_liquidity for consistent lookup
        self.bands.sort(key=lambda b: b.min_liquidity_usd)

    def get_threshold(self, liquidity_usd: float) -> float:
        """Get threshold for a given liquidity level.

        Args:
            liquidity_usd: Market liquidity in USD.

        Returns:
            Threshold value (0.45-0.49).
        """
        for band in self.bands:
            if band.min_liquidity_usd <= liquidity_usd < band.max_liquidity_usd:
                return band.threshold
        return self.default_threshold

    def get_band_label(self, liquidity_usd: float) -> str:
        """Get human-readable band label for a given liquidity."""
        for band in self.bands:
            if band.min_liquidity_usd <= liquidity_usd < band.max_liquidity_usd:
                return band.label
        return "unknown"

    def classify_market(
        self, liquidity_usd: float
    ) -> tuple[float, str]:
        """Classify market and return (threshold, label).

        Args:
            liquidity_usd: Market liquidity in USD.

        Returns:
            Tuple of (threshold, band_label).
        """
        threshold = self.get_threshold(liquidity_usd)
        label = self.get_band_label(liquidity_usd)
        return threshold, label
