"""Tests for execution engine — order builder + executor."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from poly24h.execution.executor import ExecutionResult, OrderExecutor, OrderStatus
from poly24h.execution.order_builder import ArbOrderBuilder, Order
from poly24h.models.market import Market, MarketSource
from poly24h.models.opportunity import ArbType, Opportunity

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_market(
    yes_price: float = 0.45,
    no_price: float = 0.40,
    yes_token_id: str = "tok_yes_123",
    no_token_id: str = "tok_no_456",
    liquidity_usd: float = 10_000.0,
) -> Market:
    return Market(
        id="mkt_1",
        question="BTC above 100k in 1h?",
        source=MarketSource.HOURLY_CRYPTO,
        yes_token_id=yes_token_id,
        no_token_id=no_token_id,
        yes_price=yes_price,
        no_price=no_price,
        liquidity_usd=liquidity_usd,
        end_date=datetime(2026, 3, 1, tzinfo=timezone.utc),
        event_id="evt_1",
        event_title="BTC 1h",
    )


def _make_opportunity(
    yes_price: float = 0.45,
    no_price: float = 0.40,
    recommended_size_usd: float = 200.0,
) -> Opportunity:
    mkt = _make_market(yes_price=yes_price, no_price=no_price)
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
# Order Builder Tests
# ===========================================================================


class TestOrderDataclass:
    """Order dataclass basics."""

    def test_order_fields(self):
        order = Order(
            token_id="tok_1",
            side="BUY",
            price=0.45,
            size=100.0,
            total_cost=45.0,
        )
        assert order.token_id == "tok_1"
        assert order.side == "BUY"
        assert order.price == 0.45
        assert order.size == 100.0
        assert order.total_cost == 45.0


class TestArbOrderBuilder:
    """ArbOrderBuilder.build_arb_orders tests."""

    def test_basic_build(self):
        """기본 주문 생성: YES + NO 매수."""
        opp = _make_opportunity(yes_price=0.45, no_price=0.40, recommended_size_usd=200.0)
        builder = ArbOrderBuilder()
        yes_order, no_order = builder.build_arb_orders(opp)

        assert yes_order.token_id == "tok_yes_123"
        assert yes_order.side == "BUY"
        assert yes_order.price == 0.45
        assert no_order.token_id == "tok_no_456"
        assert no_order.side == "BUY"
        assert no_order.price == 0.40

    def test_share_calculation(self):
        """shares = position_usd_per_side / price."""
        opp = _make_opportunity(yes_price=0.45, no_price=0.40, recommended_size_usd=200.0)
        builder = ArbOrderBuilder()
        yes_order, no_order = builder.build_arb_orders(opp)

        # 200 USD total → buy equal shares on each side
        # shares determined by: we buy N shares of each side
        # total_cost = N * yes_price + N * no_price = N * total_cost_per_pair
        # N = budget / total_cost_per_pair
        expected_shares = 200.0 / (0.45 + 0.40)
        assert abs(yes_order.size - expected_shares) < 0.01
        assert abs(no_order.size - expected_shares) < 0.01

    def test_total_cost_calculation(self):
        """total_cost = shares * price."""
        opp = _make_opportunity(yes_price=0.45, no_price=0.40, recommended_size_usd=200.0)
        builder = ArbOrderBuilder()
        yes_order, no_order = builder.build_arb_orders(opp)

        assert abs(yes_order.total_cost - yes_order.size * 0.45) < 0.01
        assert abs(no_order.total_cost - no_order.size * 0.40) < 0.01
        # Combined should be ~200
        assert abs(yes_order.total_cost + no_order.total_cost - 200.0) < 0.01

    def test_max_position_limits_size(self):
        """max_position_usd가 recommended_size보다 작으면 제한."""
        opp = _make_opportunity(recommended_size_usd=500.0)
        builder = ArbOrderBuilder()
        yes_order, no_order = builder.build_arb_orders(opp, max_position_usd=100.0)

        # Total should be capped at $100
        total = yes_order.total_cost + no_order.total_cost
        assert total <= 100.01  # small float tolerance

    def test_max_position_default_uses_recommended(self):
        """max_position_usd=None → recommended_size_usd 사용."""
        opp = _make_opportunity(recommended_size_usd=300.0)
        builder = ArbOrderBuilder()
        yes_order, no_order = builder.build_arb_orders(opp)

        total = yes_order.total_cost + no_order.total_cost
        assert abs(total - 300.0) < 0.01

    def test_zero_price_raises(self):
        """가격이 0인 기회는 ValueError."""
        opp = _make_opportunity(yes_price=0.0, no_price=0.40)
        builder = ArbOrderBuilder()
        with pytest.raises(ValueError, match="price"):
            builder.build_arb_orders(opp)

    def test_negative_budget_raises(self):
        """음수 예산은 ValueError."""
        opp = _make_opportunity()
        builder = ArbOrderBuilder()
        with pytest.raises(ValueError, match="position"):
            builder.build_arb_orders(opp, max_position_usd=-10.0)

    def test_zero_budget_raises(self):
        """0 예산은 ValueError."""
        opp = _make_opportunity()
        builder = ArbOrderBuilder()
        with pytest.raises(ValueError, match="position"):
            builder.build_arb_orders(opp, max_position_usd=0.0)


# ===========================================================================
# Order Executor Tests
# ===========================================================================


class TestOrderStatus:
    """OrderStatus enum."""

    def test_status_values(self):
        assert OrderStatus.SUCCESS.value == "success"
        assert OrderStatus.FAILED.value == "failed"
        assert OrderStatus.PARTIAL.value == "partial"
        assert OrderStatus.TIMEOUT.value == "timeout"


class TestExecutionResult:
    """ExecutionResult dataclass."""

    def test_result_fields(self):
        result = ExecutionResult(
            status=OrderStatus.SUCCESS,
            yes_filled=True,
            no_filled=True,
            yes_order=None,
            no_order=None,
            error=None,
        )
        assert result.status == OrderStatus.SUCCESS
        assert result.yes_filled
        assert result.no_filled


class TestOrderExecutorDryRun:
    """dry_run=True (default) executor tests."""

    def test_dry_run_returns_success(self):
        """dry_run은 항상 시뮬레이션 성공 반환."""
        opp = _make_opportunity()
        builder = ArbOrderBuilder()
        yes_order, no_order = builder.build_arb_orders(opp)

        executor = OrderExecutor(dry_run=True)
        result = executor.execute_arb(yes_order, no_order)

        assert result.status == OrderStatus.SUCCESS
        assert result.yes_filled
        assert result.no_filled

    def test_dry_run_is_default(self):
        """기본값은 dry_run=True."""
        executor = OrderExecutor()
        assert executor.dry_run is True

    def test_dry_run_stores_orders(self):
        """dry_run 결과에 주문 정보 저장."""
        opp = _make_opportunity()
        builder = ArbOrderBuilder()
        yes_order, no_order = builder.build_arb_orders(opp)

        executor = OrderExecutor(dry_run=True)
        result = executor.execute_arb(yes_order, no_order)

        assert result.yes_order is yes_order
        assert result.no_order is no_order

    def test_dry_run_no_error(self):
        """dry_run은 에러 없음."""
        opp = _make_opportunity()
        builder = ArbOrderBuilder()
        yes_order, no_order = builder.build_arb_orders(opp)

        executor = OrderExecutor(dry_run=True)
        result = executor.execute_arb(yes_order, no_order)
        assert result.error is None


class TestOrderExecutorLive:
    """dry_run=False executor tests (placeholder for real API)."""

    def test_live_mode_placeholder(self):
        """live 모드는 로그만 남기고 성공 반환 (Phase 2 placeholder)."""
        opp = _make_opportunity()
        builder = ArbOrderBuilder()
        yes_order, no_order = builder.build_arb_orders(opp)

        executor = OrderExecutor(dry_run=False)
        result = executor.execute_arb(yes_order, no_order)

        assert result.status == OrderStatus.SUCCESS
        assert result.yes_filled
        assert result.no_filled

    def test_execute_never_crashes(self):
        """executor는 어떤 상황에서도 크래시하지 않음."""
        executor = OrderExecutor(dry_run=True)
        # Pass None — should handle gracefully
        result = executor.execute_arb(None, None)
        assert result.status == OrderStatus.FAILED
        assert result.error is not None

    def test_partial_none_yes(self):
        """YES 주문이 None이면 부분 실패."""
        opp = _make_opportunity()
        builder = ArbOrderBuilder()
        _, no_order = builder.build_arb_orders(opp)

        executor = OrderExecutor(dry_run=True)
        result = executor.execute_arb(None, no_order)
        assert result.status == OrderStatus.FAILED

    def test_partial_none_no(self):
        """NO 주문이 None이면 부분 실패."""
        opp = _make_opportunity()
        builder = ArbOrderBuilder()
        yes_order, _ = builder.build_arb_orders(opp)

        executor = OrderExecutor(dry_run=True)
        result = executor.execute_arb(yes_order, None)
        assert result.status == OrderStatus.FAILED
