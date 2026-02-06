"""Tests for F-004: Dutch Book Arbitrage Detector & Opportunity Ranking."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from poly24h.models.market import Market, MarketSource
from poly24h.models.opportunity import ArbType, Opportunity
from poly24h.strategy.dutch_book import detect_single_condition
from poly24h.strategy.opportunity import rank_opportunities


def _market(
    yes_price: float = 0.45,
    no_price: float = 0.40,
    liquidity: float = 5000.0,
    market_id: str = "mkt_1",
) -> Market:
    return Market(
        id=market_id,
        question="Will BTC be above $100k?",
        source=MarketSource.HOURLY_CRYPTO,
        yes_token_id="tok_y",
        no_token_id="tok_n",
        yes_price=yes_price,
        no_price=no_price,
        liquidity_usd=liquidity,
        end_date=datetime.now(tz=timezone.utc) + timedelta(hours=1),
        event_id="evt_1",
        event_title="BTC Hourly",
    )


# ---------------------------------------------------------------------------
# detect_single_condition tests
# ---------------------------------------------------------------------------


class TestDetectSingleCondition:
    def test_arb_detected(self):
        """YES=0.45 + NO=0.40 = 0.85 → margin=0.15, ROI=17.6%."""
        mkt = _market(yes_price=0.45, no_price=0.40)
        opp = detect_single_condition(mkt)
        assert opp is not None
        assert opp.arb_type == ArbType.SINGLE_CONDITION
        assert opp.total_cost == pytest.approx(0.85)
        assert opp.margin == pytest.approx(0.15)
        assert opp.roi_pct == pytest.approx(17.647, rel=0.01)

    def test_no_arb_sum_equals_one(self):
        """YES=0.50 + NO=0.50 = 1.00 → no opportunity."""
        mkt = _market(yes_price=0.50, no_price=0.50)
        assert detect_single_condition(mkt) is None

    def test_no_arb_sum_exceeds_one(self):
        """YES=0.50 + NO=0.51 = 1.01 → no opportunity."""
        mkt = _market(yes_price=0.50, no_price=0.51)
        assert detect_single_condition(mkt) is None

    def test_min_spread_filter(self):
        """margin=0.01 but min_spread=0.02 → no opportunity."""
        mkt = _market(yes_price=0.49, no_price=0.50)
        assert detect_single_condition(mkt, min_spread=0.02) is None

    def test_min_spread_exactly_met(self):
        """margin=0.02, min_spread=0.02 → still qualifies (margin needs > threshold)."""
        # total_cost = 0.98, threshold = 1.0 - 0.02 = 0.98
        # 0.98 >= 0.98 → not an opportunity
        mkt = _market(yes_price=0.49, no_price=0.49)
        assert detect_single_condition(mkt, min_spread=0.02) is None

    def test_min_spread_just_above(self):
        """margin slightly above min_spread → opportunity."""
        mkt = _market(yes_price=0.48, no_price=0.49)
        opp = detect_single_condition(mkt, min_spread=0.02)
        assert opp is not None
        assert opp.margin == pytest.approx(0.03)

    def test_zero_yes_price(self):
        """Yes price = 0 → skip (invalid)."""
        mkt = _market(yes_price=0.0, no_price=0.40)
        assert detect_single_condition(mkt) is None

    def test_zero_no_price(self):
        """No price = 0 → skip (invalid)."""
        mkt = _market(yes_price=0.40, no_price=0.0)
        assert detect_single_condition(mkt) is None

    def test_negative_price(self):
        """Negative prices → skip."""
        mkt = _market(yes_price=-0.1, no_price=0.40)
        assert detect_single_condition(mkt) is None

    def test_opportunity_has_market_ref(self):
        """Opportunity should reference the original market."""
        mkt = _market(yes_price=0.45, no_price=0.40)
        opp = detect_single_condition(mkt)
        assert opp.market is mkt

    def test_opportunity_detected_at_set(self):
        """detected_at should be set to roughly now."""
        mkt = _market(yes_price=0.45, no_price=0.40)
        opp = detect_single_condition(mkt)
        now = datetime.now(tz=timezone.utc)
        assert abs((opp.detected_at - now).total_seconds()) < 2

    def test_default_min_spread(self):
        """Default min_spread=0.01, so margin 0.015 should pass."""
        mkt = _market(yes_price=0.49, no_price=0.495)
        # total = 0.985, margin = 0.015, threshold = 0.99
        opp = detect_single_condition(mkt)
        assert opp is not None

    def test_very_large_spread(self):
        """Huge spread like 0.10 + 0.10 = 0.20 → massive arb."""
        mkt = _market(yes_price=0.10, no_price=0.10)
        opp = detect_single_condition(mkt)
        assert opp is not None
        assert opp.margin == pytest.approx(0.80)
        assert opp.roi_pct == pytest.approx(400.0)


# ---------------------------------------------------------------------------
# rank_opportunities tests
# ---------------------------------------------------------------------------


class TestRankOpportunities:
    def test_rank_by_roi_descending(self):
        """Should rank by ROI descending."""
        opps = [
            _make_opp(roi=5.0, liquidity=5000),
            _make_opp(roi=12.0, liquidity=5000),
            _make_opp(roi=8.0, liquidity=5000),
        ]
        ranked = rank_opportunities(opps)
        assert ranked[0].roi_pct == pytest.approx(12.0)
        assert ranked[1].roi_pct == pytest.approx(8.0)
        assert ranked[2].roi_pct == pytest.approx(5.0)

    def test_rank_same_roi_higher_liquidity_first(self):
        """Same ROI → higher liquidity first."""
        opps = [
            _make_opp(roi=10.0, liquidity=3000),
            _make_opp(roi=10.0, liquidity=8000),
            _make_opp(roi=10.0, liquidity=5000),
        ]
        ranked = rank_opportunities(opps)
        assert ranked[0].market.liquidity_usd == 8000
        assert ranked[1].market.liquidity_usd == 5000
        assert ranked[2].market.liquidity_usd == 3000

    def test_rank_empty_list(self):
        """Empty list → empty list."""
        assert rank_opportunities([]) == []

    def test_rank_single_item(self):
        """Single item → same single item."""
        opps = [_make_opp(roi=10.0)]
        ranked = rank_opportunities(opps)
        assert len(ranked) == 1

    def test_rank_does_not_mutate_original(self):
        """Ranking should return new list, not mutate original."""
        opps = [
            _make_opp(roi=5.0),
            _make_opp(roi=12.0),
        ]
        original_first_roi = opps[0].roi_pct
        _ = rank_opportunities(opps)
        assert opps[0].roi_pct == original_first_roi  # unchanged


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_opp(
    roi: float = 10.0,
    liquidity: float = 5000.0,
) -> Opportunity:
    mkt = _market(liquidity=liquidity)
    margin = roi / 100.0 * 0.85  # approximate
    return Opportunity(
        market=mkt,
        arb_type=ArbType.SINGLE_CONDITION,
        yes_price=0.45,
        no_price=0.40,
        total_cost=0.85,
        margin=margin,
        roi_pct=roi,
        recommended_size_usd=0.0,
        detected_at=datetime.now(tz=timezone.utc),
    )
