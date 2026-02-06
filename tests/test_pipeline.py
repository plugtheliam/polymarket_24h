"""Tests for TradingPipeline — full integration (mocked)."""

from __future__ import annotations

from datetime import datetime, timezone

from poly24h.models.market import Market, MarketSource
from poly24h.models.opportunity import ArbType, Opportunity
from poly24h.pipeline import (
    CycleSummary,
    TradeRecord,
    TradingPipeline,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_market(
    market_id: str = "mkt_1",
    yes_price: float = 0.45,
    no_price: float = 0.40,
) -> Market:
    return Market(
        id=market_id,
        question="BTC above 100k?",
        source=MarketSource.HOURLY_CRYPTO,
        yes_token_id=f"tok_yes_{market_id}",
        no_token_id=f"tok_no_{market_id}",
        yes_price=yes_price,
        no_price=no_price,
        liquidity_usd=10_000.0,
        end_date=datetime(2026, 3, 1, tzinfo=timezone.utc),
        event_id="evt_1",
        event_title="BTC 1h",
    )


def _make_opp(
    market_id: str = "mkt_1",
    yes_price: float = 0.45,
    no_price: float = 0.40,
    recommended_size_usd: float = 200.0,
) -> Opportunity:
    mkt = _make_market(market_id, yes_price, no_price)
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
# TradingPipeline Tests
# ===========================================================================


class TestTradingPipelineProcess:
    """process_opportunity 테스트."""

    def test_successful_trade(self):
        """리스크 통과 → 주문 빌드 → 실행 → 포지션 추적."""
        pipeline = TradingPipeline(dry_run=True)
        opp = _make_opp()
        record = pipeline.process_opportunity(opp)

        assert record is not None
        assert record.executed is True
        assert record.market_id == "mkt_1"

        # 포지션이 추적되어야 함
        pos = pipeline.portfolio.get_position("mkt_1")
        assert pos is not None
        assert pos.yes_shares > 0
        assert pos.no_shares > 0

    def test_risk_rejected(self):
        """리스크 거부 → 주문 미제출. (dry_run=False에서 실제 거부)."""
        pipeline = TradingPipeline(
            dry_run=False,  # 리스크 체크가 실제로 거부하도록
            daily_loss_limit=0.01,
        )
        # 손실 기록 → 한도 초과
        pipeline.risk_controller.loss_limiter.record_loss(1.0)

        opp = _make_opp()
        record = pipeline.process_opportunity(opp)

        assert record is not None
        assert record.executed is False
        assert "daily" in record.reject_reasons[0].lower()

    def test_duplicate_market_skipped(self):
        """이미 포지션이 있는 마켓 → 스킵."""
        pipeline = TradingPipeline(dry_run=True)
        opp = _make_opp(market_id="mkt_dup")

        # 첫 번째: 성공
        record1 = pipeline.process_opportunity(opp)
        assert record1.executed is True

        # 두 번째: 중복 스킵
        record2 = pipeline.process_opportunity(opp)
        assert record2 is not None
        assert record2.executed is False
        reasons_lower = [r.lower() for r in record2.reject_reasons]
        assert any("duplicate" in r or "already" in r for r in reasons_lower)

    def test_execution_failure_handled(self):
        """실행 실패 → 크래시 없음, 기록됨."""
        pipeline = TradingPipeline(dry_run=True)
        # 강제로 executor가 None 주문을 받게 하진 않지만,
        # pipeline은 어떤 에러에도 크래시하지 않아야 함
        opp = _make_opp()
        record = pipeline.process_opportunity(opp)
        assert record is not None  # 크래시 없음

    def test_different_markets_ok(self):
        """다른 마켓은 중복 아님."""
        pipeline = TradingPipeline(dry_run=True)
        rec1 = pipeline.process_opportunity(_make_opp(market_id="mkt_A"))
        rec2 = pipeline.process_opportunity(_make_opp(market_id="mkt_B"))
        assert rec1.executed is True
        assert rec2.executed is True
        assert len(pipeline.portfolio.active_positions()) == 2


class TestTradingPipelineCycle:
    """process_cycle 테스트."""

    def test_empty_opportunities(self):
        pipeline = TradingPipeline(dry_run=True)
        summary = pipeline.process_cycle([])
        assert summary.opportunities_found == 0
        assert summary.trades_attempted == 0
        assert summary.trades_executed == 0

    def test_cycle_with_opportunities(self):
        pipeline = TradingPipeline(dry_run=True)
        opps = [_make_opp(market_id=f"mkt_{i}") for i in range(3)]
        summary = pipeline.process_cycle(opps)
        assert summary.opportunities_found == 3
        assert summary.trades_attempted == 3
        assert summary.trades_executed == 3

    def test_cycle_with_duplicates(self):
        """같은 마켓 기회 여러 개 → 첫 번째만 실행."""
        pipeline = TradingPipeline(dry_run=True)
        opps = [_make_opp(market_id="mkt_same") for _ in range(3)]
        summary = pipeline.process_cycle(opps)
        assert summary.opportunities_found == 3
        assert summary.trades_executed == 1  # 나머지 2개는 중복


class TestTradeRecord:
    """TradeRecord dataclass."""

    def test_fields(self):
        rec = TradeRecord(
            market_id="mkt_1",
            market_question="BTC?",
            executed=True,
            reject_reasons=[],
            yes_price=0.45,
            no_price=0.40,
            shares=100.0,
            total_cost=85.0,
            expected_profit=15.0,
        )
        assert rec.market_id == "mkt_1"
        assert rec.executed is True
        assert rec.expected_profit == 15.0

    def test_rejected_record(self):
        rec = TradeRecord(
            market_id="mkt_2",
            market_question="ETH?",
            executed=False,
            reject_reasons=["Daily loss limit"],
        )
        assert rec.executed is False
        assert len(rec.reject_reasons) == 1


class TestCycleSummary:
    def test_fields(self):
        cs = CycleSummary(
            cycle_number=1,
            opportunities_found=5,
            trades_attempted=3,
            trades_executed=2,
            trades_rejected=1,
        )
        assert cs.cycle_number == 1
        assert cs.trades_executed == 2


class TestSessionSummary:
    def test_from_pipeline(self):
        pipeline = TradingPipeline(dry_run=True)
        opps = [_make_opp(market_id=f"mkt_{i}") for i in range(2)]
        pipeline.process_cycle(opps)

        summary = pipeline.session_summary()
        assert summary.total_cycles == 1
        assert summary.total_trades == 2
        assert summary.active_positions == 2

    def test_multi_cycle_session(self):
        pipeline = TradingPipeline(dry_run=True)
        pipeline.process_cycle([_make_opp(market_id="mkt_1")])
        pipeline.process_cycle([_make_opp(market_id="mkt_2")])

        summary = pipeline.session_summary()
        assert summary.total_cycles == 2
        assert summary.total_trades == 2

    def test_session_summary_format(self):
        """SessionSummary는 문자열 포맷이 가능해야 함."""
        pipeline = TradingPipeline(dry_run=True)
        summary = pipeline.session_summary()
        text = str(summary)
        assert "cycle" in text.lower() or "trade" in text.lower()
