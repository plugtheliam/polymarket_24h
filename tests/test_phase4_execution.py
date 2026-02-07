"""Tests for Phase 4 execution pipeline enhancements.

Tests:
- Order builder with GTD expiration, nonce, slippage protection
- Order.to_clob_payload() serialization
- Kill switch integration review
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from poly24h.execution.order_builder import (
    ArbOrderBuilder,
    DEFAULT_EXPIRATION_SECONDS,
    MIN_ORDER_SIZE_SHARES,
    Order,
)
from poly24h.models.market import Market, MarketSource
from poly24h.models.opportunity import ArbType, Opportunity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_opportunity(
    yes_price: float = 0.45,
    no_price: float = 0.40,
    recommended_size_usd: float = 200.0,
) -> Opportunity:
    mkt = Market(
        id="mkt_1",
        question="BTC above 100k?",
        source=MarketSource.HOURLY_CRYPTO,
        yes_token_id="tok_yes",
        no_token_id="tok_no",
        yes_price=yes_price,
        no_price=no_price,
        liquidity_usd=10_000.0,
        end_date=datetime(2026, 3, 1, tzinfo=timezone.utc),
        event_id="evt_1",
        event_title="BTC 1h",
    )
    total_cost = yes_price + no_price
    margin = 1.0 - total_cost
    roi_pct = (margin / total_cost) * 100.0
    return Opportunity(
        market=mkt,
        arb_type=ArbType.SINGLE_CONDITION,
        yes_price=yes_price,
        no_price=no_price,
        total_cost=total_cost,
        margin=margin,
        roi_pct=roi_pct,
        recommended_size_usd=recommended_size_usd,
        detected_at=datetime.now(tz=timezone.utc),
    )


# ===========================================================================
# Order Enhancements
# ===========================================================================


class TestOrderPayload:
    def test_to_clob_payload(self):
        """Order serializes correctly to CLOB API format."""
        order = Order(
            token_id="tok_123",
            side="BUY",
            price=0.45,
            size=100.0,
            total_cost=45.0,
            nonce="12345",
            expiration=1700000000,
            fee_rate_bps="0",
        )
        payload = order.to_clob_payload()

        assert payload["tokenID"] == "tok_123"
        assert payload["side"] == "BUY"
        assert payload["price"] == "0.45"
        assert payload["size"] == "100.0"
        assert payload["nonce"] == "12345"
        assert payload["expiration"] == "1700000000"
        assert payload["feeRateBps"] == "0"

    def test_payload_without_nonce(self):
        """Empty nonce → not in payload."""
        order = Order(
            token_id="tok", side="BUY", price=0.5,
            size=10.0, total_cost=5.0,
        )
        payload = order.to_clob_payload()
        assert "nonce" not in payload

    def test_payload_without_expiration(self):
        """expiration=0 → not in payload (GTC)."""
        order = Order(
            token_id="tok", side="BUY", price=0.5,
            size=10.0, total_cost=5.0,
            nonce="abc", expiration=0,
        )
        payload = order.to_clob_payload()
        assert "expiration" not in payload


# ===========================================================================
# ArbOrderBuilder Phase 4 Enhancements
# ===========================================================================


class TestOrderBuilderNonce:
    def test_unique_nonces(self):
        builder = ArbOrderBuilder()
        n1 = builder.generate_nonce()
        n2 = builder.generate_nonce()
        assert n1 != n2

    def test_nonce_is_string(self):
        builder = ArbOrderBuilder()
        nonce = builder.generate_nonce()
        assert isinstance(nonce, str)
        assert len(nonce) > 0

    def test_orders_have_nonces(self):
        builder = ArbOrderBuilder()
        opp = _make_opportunity()
        yes_order, no_order = builder.build_arb_orders(opp)
        assert yes_order.nonce != ""
        assert no_order.nonce != ""
        assert yes_order.nonce != no_order.nonce


class TestOrderBuilderExpiration:
    def test_gtd_expiration(self):
        builder = ArbOrderBuilder(expiration_seconds=300)
        exp = builder.calculate_expiration()
        now = int(time.time())
        assert abs(exp - (now + 300)) <= 2

    def test_gtc_expiration(self):
        builder = ArbOrderBuilder(expiration_seconds=0)
        exp = builder.calculate_expiration()
        assert exp == 0

    def test_orders_have_expiration(self):
        builder = ArbOrderBuilder(expiration_seconds=300)
        opp = _make_opportunity()
        yes_order, no_order = builder.build_arb_orders(opp)
        now = int(time.time())
        assert yes_order.expiration > now
        assert no_order.expiration > now
        # Same expiration for both legs
        assert yes_order.expiration == no_order.expiration


class TestOrderBuilderSlippageProtection:
    def test_thin_spread_rejected(self):
        """Spread too thin → ValueError."""
        builder = ArbOrderBuilder(min_spread=0.01)
        # YES=0.50, NO=0.50 → spread = 0.0
        opp = _make_opportunity(yes_price=0.50, no_price=0.50)
        with pytest.raises(ValueError, match="[Ss]pread"):
            builder.build_arb_orders(opp)

    def test_adequate_spread_accepted(self):
        """Good spread → builds successfully."""
        builder = ArbOrderBuilder(min_spread=0.01)
        opp = _make_opportunity(yes_price=0.45, no_price=0.40)
        yes_order, no_order = builder.build_arb_orders(opp)
        assert yes_order.price == 0.45
        assert no_order.price == 0.40

    def test_negative_spread_rejected(self):
        """Overpriced (YES+NO > 1.0) → ValueError."""
        builder = ArbOrderBuilder(min_spread=0.005)
        opp = _make_opportunity(yes_price=0.55, no_price=0.50)
        with pytest.raises(ValueError, match="[Ss]pread"):
            builder.build_arb_orders(opp)


class TestOrderBuilderMinSize:
    def test_too_small_order_rejected(self):
        """Order below minimum shares → ValueError."""
        builder = ArbOrderBuilder(min_order_size=10.0)
        # Small budget → small shares
        opp = _make_opportunity(
            yes_price=0.45, no_price=0.40,
            recommended_size_usd=5.0,  # 5/(0.45+0.40) ≈ 5.88 shares < 10
        )
        with pytest.raises(ValueError, match="[Oo]rder too small"):
            builder.build_arb_orders(opp)

    def test_adequate_size_accepted(self):
        """Adequate shares → builds OK."""
        builder = ArbOrderBuilder(min_order_size=1.0)
        opp = _make_opportunity(recommended_size_usd=200.0)
        yes_order, no_order = builder.build_arb_orders(opp)
        assert yes_order.size >= 1.0


class TestOrderBuilderBackwardCompat:
    """Ensure Phase 4 changes don't break existing behavior."""

    def test_basic_build_still_works(self):
        builder = ArbOrderBuilder()
        opp = _make_opportunity(yes_price=0.45, no_price=0.40, recommended_size_usd=200.0)
        yes_order, no_order = builder.build_arb_orders(opp)

        assert yes_order.token_id == "tok_yes"
        assert yes_order.side == "BUY"
        assert yes_order.price == 0.45
        assert no_order.token_id == "tok_no"
        assert no_order.price == 0.40

    def test_share_calculation_unchanged(self):
        builder = ArbOrderBuilder()
        opp = _make_opportunity(yes_price=0.45, no_price=0.40, recommended_size_usd=200.0)
        yes_order, no_order = builder.build_arb_orders(opp)

        expected_shares = 200.0 / (0.45 + 0.40)
        assert abs(yes_order.size - expected_shares) < 0.01
        assert abs(no_order.size - expected_shares) < 0.01

    def test_total_cost_unchanged(self):
        builder = ArbOrderBuilder()
        opp = _make_opportunity(yes_price=0.45, no_price=0.40, recommended_size_usd=200.0)
        yes_order, no_order = builder.build_arb_orders(opp)

        total = yes_order.total_cost + no_order.total_cost
        assert abs(total - 200.0) < 0.01

    def test_max_position_still_works(self):
        builder = ArbOrderBuilder()
        opp = _make_opportunity(recommended_size_usd=500.0)
        yes_order, no_order = builder.build_arb_orders(opp, max_position_usd=100.0)

        total = yes_order.total_cost + no_order.total_cost
        assert total <= 100.01

    def test_zero_price_still_raises(self):
        builder = ArbOrderBuilder()
        opp = _make_opportunity(yes_price=0.0, no_price=0.40)
        with pytest.raises(ValueError, match="price"):
            builder.build_arb_orders(opp)

    def test_zero_budget_still_raises(self):
        builder = ArbOrderBuilder()
        opp = _make_opportunity()
        with pytest.raises(ValueError):
            builder.build_arb_orders(opp, max_position_usd=0.0)
