"""Tests for Paired Entry strategy (Phase 3).

Covers:
- PairedEntryDetector: detection logic, edge cases, filters
- PairedEntrySimulator: paper trade simulation, JSONL output
- Integration with EventDrivenLoop
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from poly24h.models.market import Market, MarketSource
from poly24h.strategy.paired_entry import (
    PairedEntryDetector,
    PairedEntryOpportunity,
    PairedEntrySimulator,
    PairedPaperTrade,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def detector():
    return PairedEntryDetector()


@pytest.fixture
def strict_detector():
    """Detector with strict settings."""
    return PairedEntryDetector(
        max_combined_cost=0.95,
        min_spread=0.02,
        min_size_usd=10.0,
    )


@pytest.fixture
def market():
    return Market(
        id="mkt_btc_001",
        question="Will BTC be above $100,000 at 2pm UTC?",
        source=MarketSource.HOURLY_CRYPTO,
        yes_token_id="tok_yes_btc",
        no_token_id="tok_no_btc",
        yes_price=0.45,
        no_price=0.50,
        liquidity_usd=10000.0,
        end_date=datetime.now(tz=timezone.utc) + timedelta(hours=1),
        event_id="evt_btc",
        event_title="BTC Hourly",
    )


@pytest.fixture
def tmp_data_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


# ===========================================================================
# PairedEntryDetector Tests
# ===========================================================================


class TestPairedEntryDetector:
    def test_detect_basic_opportunity(self, detector, market):
        """YES+NO < 0.98 → opportunity."""
        opp = detector.detect(market, yes_ask=0.45, no_ask=0.50)
        assert opp is not None
        assert opp.total_cost == pytest.approx(0.95, abs=0.001)
        assert opp.spread == pytest.approx(0.05, abs=0.001)
        assert opp.roi_pct == pytest.approx(5.263, abs=0.1)
        assert opp.market is market

    def test_detect_no_opportunity_total_too_high(self, detector, market):
        """YES+NO >= 0.98 → no opportunity."""
        opp = detector.detect(market, yes_ask=0.50, no_ask=0.50)
        assert opp is None

    def test_detect_no_opportunity_exactly_at_threshold(self, detector, market):
        """YES+NO == 0.98 → no opportunity (not strictly less)."""
        opp = detector.detect(market, yes_ask=0.49, no_ask=0.49)
        assert opp is None

    def test_detect_marginal_opportunity(self, detector, market):
        """Just barely under threshold."""
        opp = detector.detect(market, yes_ask=0.48, no_ask=0.48)
        assert opp is not None
        assert opp.spread == pytest.approx(0.04, abs=0.001)

    def test_detect_filters_zero_price(self, detector, market):
        """Zero price → no opportunity."""
        assert detector.detect(market, yes_ask=0.0, no_ask=0.50) is None
        assert detector.detect(market, yes_ask=0.50, no_ask=0.0) is None

    def test_detect_filters_negative_price(self, detector, market):
        """Negative price → no opportunity."""
        assert detector.detect(market, yes_ask=-0.1, no_ask=0.50) is None

    def test_detect_filters_garbage_low_price(self, detector, market):
        """Price below min_price ($0.02) → filtered."""
        opp = detector.detect(market, yes_ask=0.001, no_ask=0.50)
        assert opp is None

    def test_detect_filters_low_spread(self, market):
        """Spread below min_spread → filtered."""
        det = PairedEntryDetector(min_spread=0.05)
        opp = det.detect(market, yes_ask=0.47, no_ask=0.50)
        # total=0.97, spread=0.03 < 0.05 → filtered
        assert opp is None

    def test_detect_with_sizes(self, detector, market):
        """Sizes provided → max_shares calculated."""
        opp = detector.detect(
            market, yes_ask=0.45, no_ask=0.50,
            yes_size=100.0, no_size=80.0,
        )
        assert opp is not None
        assert opp.max_shares == 80.0  # min(100, 80)
        assert opp.yes_size == 100.0
        assert opp.no_size == 80.0

    def test_detect_insufficient_liquidity(self, market):
        """Min size filter: both sides must have enough USD value."""
        det = PairedEntryDetector(min_size_usd=10.0)
        # yes_size=5 * yes_ask=0.45 = $2.25 < $10 → filtered
        opp = det.detect(
            market, yes_ask=0.45, no_ask=0.50,
            yes_size=5.0, no_size=100.0,
        )
        assert opp is None

    def test_detect_without_sizes_skips_liquidity_filter(self, detector, market):
        """When sizes are 0, liquidity filter is skipped."""
        opp = detector.detect(market, yes_ask=0.45, no_ask=0.50)
        assert opp is not None
        assert opp.max_shares == 0.0

    def test_detect_source_tracking(self, detector, market):
        """Source parameter is passed through."""
        opp = detector.detect(
            market, yes_ask=0.45, no_ask=0.50, source="ws_cache",
        )
        assert opp is not None
        assert opp.source == "ws_cache"

    def test_detect_potential_profit(self, detector, market):
        """potential_profit_usd calculation."""
        opp = detector.detect(
            market, yes_ask=0.45, no_ask=0.50,
            yes_size=100.0, no_size=100.0,
        )
        assert opp is not None
        assert opp.potential_profit_usd == pytest.approx(5.0, abs=0.1)

    def test_strict_detector_rejects_narrow_spread(self, strict_detector, market):
        """Strict detector with higher thresholds rejects marginal spreads."""
        # total=0.96, spread=0.04 > 0.02 but total > 0.95 → rejected
        opp = strict_detector.detect(market, yes_ask=0.48, no_ask=0.48)
        assert opp is None

    def test_strict_detector_accepts_wide_spread(self, strict_detector, market):
        """Strict detector accepts large spreads with sufficient liquidity."""
        opp = strict_detector.detect(
            market, yes_ask=0.40, no_ask=0.45,
            yes_size=50.0, no_size=50.0,
        )
        assert opp is not None
        assert opp.spread == pytest.approx(0.15, abs=0.001)

    def test_to_dict_serialization(self, detector, market):
        """Opportunity serialization to dict."""
        opp = detector.detect(market, yes_ask=0.45, no_ask=0.50)
        d = opp.to_dict()
        assert d["market_id"] == "mkt_btc_001"
        assert d["yes_ask"] == 0.45
        assert d["no_ask"] == 0.50
        assert d["spread"] == pytest.approx(0.05, abs=0.001)
        assert "detected_at" in d


# ===========================================================================
# PairedEntrySimulator Tests
# ===========================================================================


class TestPairedEntrySimulator:
    def test_simulate_basic_trade(self, detector, market, tmp_data_dir):
        """Basic paper trade simulation."""
        sim = PairedEntrySimulator(paper_size_usd=20.0, data_dir=tmp_data_dir)
        opp = detector.detect(market, yes_ask=0.45, no_ask=0.50)

        trade = sim.simulate_trade(opp)

        assert trade.market_id == "mkt_btc_001"
        assert trade.cost_usd == 20.0
        assert trade.shares == pytest.approx(20.0 / 0.95, abs=0.01)
        assert trade.guaranteed_profit == pytest.approx(0.05 * (20.0 / 0.95), abs=0.01)
        assert trade.status == "open"

    def test_simulate_writes_jsonl(self, detector, market, tmp_data_dir):
        """Simulation writes to JSONL file."""
        sim = PairedEntrySimulator(paper_size_usd=10.0, data_dir=tmp_data_dir)
        opp = detector.detect(market, yes_ask=0.45, no_ask=0.50)
        sim.simulate_trade(opp)

        # Check JSONL file exists
        files = list(Path(tmp_data_dir).glob("paired_*.jsonl"))
        assert len(files) == 1

        with open(files[0]) as f:
            data = json.loads(f.read().strip())
        assert data["market_id"] == "mkt_btc_001"
        assert data["guaranteed_profit"] > 0

    def test_multiple_trades_summary(self, detector, market, tmp_data_dir):
        """Multiple trades → summary accumulates."""
        sim = PairedEntrySimulator(paper_size_usd=10.0, data_dir=tmp_data_dir)
        opp = detector.detect(market, yes_ask=0.45, no_ask=0.50)

        sim.simulate_trade(opp)
        sim.simulate_trade(opp)
        sim.simulate_trade(opp)

        summary = sim.get_summary()
        assert summary["total_trades"] == 3
        assert summary["total_cost"] == pytest.approx(30.0, abs=0.01)
        assert summary["total_guaranteed_profit"] > 0
        assert summary["avg_roi_pct"] > 0

    def test_empty_summary(self, tmp_data_dir):
        """Empty summary when no trades."""
        sim = PairedEntrySimulator(data_dir=tmp_data_dir)
        summary = sim.get_summary()
        assert summary["total_trades"] == 0
        assert summary["avg_roi_pct"] == 0.0


# ===========================================================================
# PairedPaperTrade Tests
# ===========================================================================


class TestPairedPaperTrade:
    def test_to_dict_roundtrip(self):
        trade = PairedPaperTrade(
            market_id="mkt_1",
            market_question="Will BTC go up?",
            market_source="hourly_crypto",
            yes_ask=0.45,
            no_ask=0.50,
            total_cost=0.95,
            spread=0.05,
            roi_pct=5.26,
            shares=21.05,
            cost_usd=20.0,
            guaranteed_profit=1.05,
            source="ws_cache",
            timestamp="2025-01-01T00:00:00+00:00",
        )

        d = trade.to_dict()
        trade2 = PairedPaperTrade.from_dict(d)
        assert trade2.market_id == trade.market_id
        assert trade2.guaranteed_profit == pytest.approx(trade.guaranteed_profit)
        assert trade2.source == "ws_cache"


# ===========================================================================
# Edge Cases
# ===========================================================================


class TestPairedEntryEdgeCases:
    def test_very_wide_spread(self, market):
        """Extreme spread: YES=$0.10 + NO=$0.10 = $0.20 → 400% ROI."""
        det = PairedEntryDetector()
        opp = det.detect(market, yes_ask=0.10, no_ask=0.10)
        assert opp is not None
        assert opp.spread == pytest.approx(0.80, abs=0.01)
        assert opp.roi_pct == pytest.approx(400.0, abs=1.0)

    def test_one_side_near_one(self, market):
        """YES=$0.01 (garbage), NO=$0.95 → YES below min_price → filtered."""
        det = PairedEntryDetector()
        opp = det.detect(market, yes_ask=0.01, no_ask=0.95)
        assert opp is None

    def test_both_sides_at_50_50(self, market):
        """YES=NO=$0.50 → total=1.0 → no opportunity."""
        det = PairedEntryDetector()
        opp = det.detect(market, yes_ask=0.50, no_ask=0.50)
        assert opp is None

    def test_tiny_sizes_filtered(self, market):
        """Very small sizes that don't meet min_size_usd."""
        det = PairedEntryDetector(min_size_usd=5.0)
        # yes_size=1, yes_ask=0.45 → $0.45 < $5 → filtered
        opp = det.detect(
            market, yes_ask=0.45, no_ask=0.50,
            yes_size=1.0, no_size=100.0,
        )
        assert opp is None
