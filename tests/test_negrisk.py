"""Tests for NegRisk multi-outcome arbitrage (F-010).

NegRisk 다중 아웃컴 아비트라지 감지 + 주문 생성 테스트.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from poly24h.models.negrisk import NegRiskMarket, NegRiskOpportunity, NegRiskOutcome
from poly24h.strategy.negrisk import build_negrisk_orders, detect_negrisk_arb

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def five_outcomes() -> list[NegRiskOutcome]:
    """5개 아웃컴 NegRisk 마켓 (합=0.95, 마진=5%)."""
    return [
        NegRiskOutcome("m1", "Candidate A wins?", "tok_a", 0.45, 10000.0),
        NegRiskOutcome("m2", "Candidate B wins?", "tok_b", 0.25, 8000.0),
        NegRiskOutcome("m3", "Candidate C wins?", "tok_c", 0.15, 6000.0),
        NegRiskOutcome("m4", "Candidate D wins?", "tok_d", 0.08, 5000.0),
        NegRiskOutcome("m5", "Candidate E wins?", "tok_e", 0.02, 3000.0),
    ]


@pytest.fixture
def negrisk_market(five_outcomes) -> NegRiskMarket:
    """NegRiskMarket with 5 outcomes."""
    return NegRiskMarket(
        event_id="evt_neg_1",
        event_title="2024 Presidential Election",
        outcomes=five_outcomes,
    )


@pytest.fixture
def no_arb_outcomes() -> list[NegRiskOutcome]:
    """합 > 1.0 → 아비트라지 없음."""
    return [
        NegRiskOutcome("m1", "A wins?", "tok_a", 0.50, 10000.0),
        NegRiskOutcome("m2", "B wins?", "tok_b", 0.30, 8000.0),
        NegRiskOutcome("m3", "C wins?", "tok_c", 0.21, 6000.0),
    ]


@pytest.fixture
def no_arb_negrisk(no_arb_outcomes) -> NegRiskMarket:
    """NegRiskMarket with no arb (total > 1.0)."""
    return NegRiskMarket(
        event_id="evt_neg_2",
        event_title="No arb event",
        outcomes=no_arb_outcomes,
    )


# ---------------------------------------------------------------------------
# NegRiskOutcome tests
# ---------------------------------------------------------------------------


class TestNegRiskOutcome:
    def test_create_outcome(self):
        o = NegRiskOutcome("m1", "A wins?", "tok_a", 0.45, 10000.0)
        assert o.market_id == "m1"
        assert o.question == "A wins?"
        assert o.token_id == "tok_a"
        assert o.price == 0.45
        assert o.liquidity_usd == 10000.0

    def test_zero_price_outcome(self):
        o = NegRiskOutcome("m1", "A wins?", "tok_a", 0.0, 5000.0)
        assert o.price == 0.0

    def test_zero_liquidity_outcome(self):
        o = NegRiskOutcome("m1", "A wins?", "tok_a", 0.50, 0.0)
        assert o.liquidity_usd == 0.0


# ---------------------------------------------------------------------------
# NegRiskMarket property tests
# ---------------------------------------------------------------------------


class TestNegRiskMarket:
    def test_total_prob(self, negrisk_market):
        """5개 아웃컴 합 = 0.95."""
        assert abs(negrisk_market.total_prob - 0.95) < 1e-9

    def test_margin(self, negrisk_market):
        """margin = 1.0 - 0.95 = 0.05."""
        assert abs(negrisk_market.margin - 0.05) < 1e-9

    def test_roi_pct(self, negrisk_market):
        """roi = 0.05 / 0.95 * 100 ≈ 5.26%."""
        expected = (0.05 / 0.95) * 100.0
        assert abs(negrisk_market.roi_pct - expected) < 0.01

    def test_no_arb_market_margin_negative(self, no_arb_negrisk):
        """합 > 1.0이면 margin 음수."""
        assert no_arb_negrisk.margin < 0

    def test_empty_outcomes(self):
        m = NegRiskMarket("evt_0", "Empty", [])
        assert m.total_prob == 0.0
        assert m.margin == 1.0
        assert m.roi_pct == 0.0  # 0 outcomes → no division by zero

    def test_two_outcomes(self):
        """2개 아웃컴 NegRisk (binary처럼 동작)."""
        outcomes = [
            NegRiskOutcome("m1", "A?", "t1", 0.40, 5000.0),
            NegRiskOutcome("m2", "B?", "t2", 0.45, 5000.0),
        ]
        m = NegRiskMarket("evt_2", "Binary-like", outcomes)
        assert abs(m.total_prob - 0.85) < 1e-9
        assert abs(m.margin - 0.15) < 1e-9

    def test_exact_one_total(self):
        """합 = 1.0이면 margin = 0."""
        outcomes = [
            NegRiskOutcome("m1", "A?", "t1", 0.60, 5000.0),
            NegRiskOutcome("m2", "B?", "t2", 0.40, 5000.0),
        ]
        m = NegRiskMarket("evt_exact", "Exact", outcomes)
        assert abs(m.margin) < 1e-9

    def test_many_outcomes(self):
        """10개 아웃컴."""
        outcomes = [
            NegRiskOutcome(f"m{i}", f"Q{i}?", f"t{i}", 0.08, 2000.0)
            for i in range(10)
        ]
        m = NegRiskMarket("evt_10", "Ten outcomes", outcomes)
        assert abs(m.total_prob - 0.80) < 1e-9
        assert abs(m.margin - 0.20) < 1e-9


# ---------------------------------------------------------------------------
# detect_negrisk_arb tests
# ---------------------------------------------------------------------------


class TestDetectNegRiskArb:
    def test_detect_basic_arb(self, negrisk_market):
        """합 0.95 → margin 5% → 기회 감지."""
        opp = detect_negrisk_arb(negrisk_market)
        assert opp is not None
        assert isinstance(opp, NegRiskOpportunity)
        assert abs(opp.margin - 0.05) < 1e-9
        assert opp.roi_pct > 5.0

    def test_detect_no_arb(self, no_arb_negrisk):
        """합 > 1.0 → None."""
        opp = detect_negrisk_arb(no_arb_negrisk)
        assert opp is None

    def test_detect_with_min_spread(self, negrisk_market):
        """min_spread=0.06이면 margin=0.05 → None."""
        opp = detect_negrisk_arb(negrisk_market, min_spread=0.06)
        assert opp is None

    def test_detect_with_exact_min_spread(self, negrisk_market):
        """min_spread=0.05 → margin=0.05 → 경계값: None (not strict enough)."""
        opp = detect_negrisk_arb(negrisk_market, min_spread=0.05)
        assert opp is None

    def test_detect_with_lower_min_spread(self, negrisk_market):
        """min_spread=0.04 → margin=0.05 → 감지됨."""
        opp = detect_negrisk_arb(negrisk_market, min_spread=0.04)
        assert opp is not None

    def test_detect_zero_price_outcome(self):
        """가격 0인 아웃컴이 있으면 스킵."""
        outcomes = [
            NegRiskOutcome("m1", "A?", "t1", 0.45, 5000.0),
            NegRiskOutcome("m2", "B?", "t2", 0.0, 5000.0),
            NegRiskOutcome("m3", "C?", "t3", 0.15, 5000.0),
        ]
        m = NegRiskMarket("evt_zero", "Zero price", outcomes)
        opp = detect_negrisk_arb(m)
        assert opp is None

    def test_detect_empty_outcomes(self):
        """빈 아웃컴 → None."""
        m = NegRiskMarket("evt_empty", "Empty", [])
        opp = detect_negrisk_arb(m)
        assert opp is None

    def test_opportunity_has_correct_fields(self, negrisk_market):
        opp = detect_negrisk_arb(negrisk_market)
        assert opp is not None
        assert opp.negrisk_market is negrisk_market
        assert isinstance(opp.detected_at, datetime)
        assert opp.recommended_size_usd == 0.0  # 리스크 매니저가 채움

    def test_detect_large_margin(self):
        """큰 마진 (20%) 감지."""
        outcomes = [
            NegRiskOutcome(f"m{i}", f"Q{i}?", f"t{i}", 0.08, 5000.0)
            for i in range(10)
        ]  # total = 0.80, margin = 0.20
        m = NegRiskMarket("evt_big", "Big margin", outcomes)
        opp = detect_negrisk_arb(m)
        assert opp is not None
        assert abs(opp.margin - 0.20) < 1e-9


# ---------------------------------------------------------------------------
# build_negrisk_orders tests
# ---------------------------------------------------------------------------


class TestBuildNegRiskOrders:
    def test_build_orders_count(self, negrisk_market):
        """5개 아웃컴 → 5개 주문."""
        opp = detect_negrisk_arb(negrisk_market)
        assert opp is not None
        orders = build_negrisk_orders(opp, budget=1000.0)
        assert len(orders) == 5

    def test_all_orders_are_buy(self, negrisk_market):
        """모든 주문이 BUY."""
        opp = detect_negrisk_arb(negrisk_market)
        orders = build_negrisk_orders(opp, budget=1000.0)
        for order in orders:
            assert order.side == "BUY"

    def test_all_same_shares(self, negrisk_market):
        """모든 아웃컴에 동일 shares 매수."""
        opp = detect_negrisk_arb(negrisk_market)
        orders = build_negrisk_orders(opp, budget=1000.0)
        shares_set = {round(o.size, 6) for o in orders}
        assert len(shares_set) == 1  # 모두 동일

    def test_total_cost_matches_budget(self, negrisk_market):
        """총 비용이 budget에 맞아야 함."""
        opp = detect_negrisk_arb(negrisk_market)
        orders = build_negrisk_orders(opp, budget=1000.0)
        total_cost = sum(o.total_cost for o in orders)
        assert abs(total_cost - 1000.0) < 0.01

    def test_order_prices_match_outcomes(self, negrisk_market):
        """주문 가격이 아웃컴 가격과 일치."""
        opp = detect_negrisk_arb(negrisk_market)
        orders = build_negrisk_orders(opp, budget=1000.0)
        expected_prices = [0.45, 0.25, 0.15, 0.08, 0.02]
        actual_prices = [o.price for o in orders]
        for exp, act in zip(expected_prices, actual_prices):
            assert abs(exp - act) < 1e-9

    def test_order_token_ids(self, negrisk_market):
        """주문 token_id가 아웃컴 token_id와 일치."""
        opp = detect_negrisk_arb(negrisk_market)
        orders = build_negrisk_orders(opp, budget=1000.0)
        expected_tokens = ["tok_a", "tok_b", "tok_c", "tok_d", "tok_e"]
        actual_tokens = [o.token_id for o in orders]
        assert actual_tokens == expected_tokens

    def test_zero_budget_raises(self, negrisk_market):
        """budget=0이면 ValueError."""
        opp = detect_negrisk_arb(negrisk_market)
        with pytest.raises(ValueError):
            build_negrisk_orders(opp, budget=0.0)

    def test_negative_budget_raises(self, negrisk_market):
        """음수 budget이면 ValueError."""
        opp = detect_negrisk_arb(negrisk_market)
        with pytest.raises(ValueError):
            build_negrisk_orders(opp, budget=-100.0)

    def test_small_budget(self, negrisk_market):
        """작은 budget도 정상 동작."""
        opp = detect_negrisk_arb(negrisk_market)
        orders = build_negrisk_orders(opp, budget=10.0)
        total_cost = sum(o.total_cost for o in orders)
        assert abs(total_cost - 10.0) < 0.01

    def test_liquidity_constrained(self):
        """유동성이 낮은 아웃컴이 있으면 사이즈 축소."""
        outcomes = [
            NegRiskOutcome("m1", "A?", "t1", 0.45, 100.0),  # 유동성 $100
            NegRiskOutcome("m2", "B?", "t2", 0.25, 100.0),
            NegRiskOutcome("m3", "C?", "t3", 0.15, 100.0),
        ]
        m = NegRiskMarket("evt_liq", "Low liq", outcomes)
        opp = detect_negrisk_arb(m)
        assert opp is not None
        orders = build_negrisk_orders(opp, budget=5000.0)
        # budget 5000이지만 유동성 제한으로 실제 비용 <= min_liquidity
        total_cost = sum(o.total_cost for o in orders)
        assert total_cost <= 100.0 + 0.01  # 최소 유동성 이하로 제한
