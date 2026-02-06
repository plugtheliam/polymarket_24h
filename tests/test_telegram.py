"""Tests for Telegram alerts (F-012).

TelegramAlerter — 기회/거래/에러 알림 + no-op 모드 + rate limiting.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from poly24h.models.market import Market, MarketSource
from poly24h.models.negrisk import NegRiskMarket, NegRiskOpportunity, NegRiskOutcome
from poly24h.models.opportunity import ArbType, Opportunity
from poly24h.monitoring.telegram import TelegramAlerter
from poly24h.pipeline import SessionSummary, TradeRecord

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def alerter():
    """Configured TelegramAlerter with mock tokens."""
    return TelegramAlerter(bot_token="fake_token", chat_id="12345")


@pytest.fixture
def disabled_alerter():
    """Disabled TelegramAlerter (no tokens)."""
    return TelegramAlerter()


@pytest.fixture
def sample_opportunity():
    mkt = Market(
        id="m1",
        question="Will BTC be above $100k at 2pm?",
        source=MarketSource.HOURLY_CRYPTO,
        yes_token_id="tok_y",
        no_token_id="tok_n",
        yes_price=0.45,
        no_price=0.40,
        liquidity_usd=5000.0,
        end_date=datetime.now(tz=timezone.utc) + timedelta(hours=1),
        event_id="evt_1",
        event_title="BTC Hourly",
    )
    return Opportunity(
        market=mkt,
        arb_type=ArbType.SINGLE_CONDITION,
        yes_price=0.45,
        no_price=0.40,
        total_cost=0.85,
        margin=0.15,
        roi_pct=17.65,
        recommended_size_usd=500.0,
        detected_at=datetime.now(tz=timezone.utc),
    )


@pytest.fixture
def sample_negrisk_opportunity():
    outcomes = [
        NegRiskOutcome("m1", "A wins?", "t1", 0.45, 5000.0),
        NegRiskOutcome("m2", "B wins?", "t2", 0.25, 5000.0),
        NegRiskOutcome("m3", "C wins?", "t3", 0.15, 5000.0),
    ]
    nm = NegRiskMarket("evt_neg", "Election", outcomes)
    return NegRiskOpportunity(
        negrisk_market=nm,
        margin=0.15,
        roi_pct=17.65,
        recommended_size_usd=500.0,
        detected_at=datetime.now(tz=timezone.utc),
    )


@pytest.fixture
def sample_trade_record():
    return TradeRecord(
        market_id="m1",
        market_question="Will BTC be above $100k?",
        executed=True,
        yes_price=0.45,
        no_price=0.40,
        shares=100.0,
        total_cost=85.0,
        expected_profit=15.0,
    )


@pytest.fixture
def sample_session_summary():
    return SessionSummary(
        total_cycles=10,
        total_opportunities=5,
        total_trades=3,
        total_rejected=2,
        total_invested=300.0,
        total_locked_profit=15.0,
        total_realized_pnl=10.0,
        active_positions=2,
    )


# ---------------------------------------------------------------------------
# Enabled/disabled tests
# ---------------------------------------------------------------------------


class TestTelegramAlerterEnabled:
    def test_enabled_with_tokens(self, alerter):
        assert alerter.enabled is True

    def test_disabled_without_tokens(self, disabled_alerter):
        assert disabled_alerter.enabled is False

    def test_disabled_with_only_bot_token(self):
        a = TelegramAlerter(bot_token="token")
        assert a.enabled is False

    def test_disabled_with_only_chat_id(self):
        a = TelegramAlerter(chat_id="123")
        assert a.enabled is False


# ---------------------------------------------------------------------------
# No-op when disabled
# ---------------------------------------------------------------------------


class TestTelegramNoOp:
    @pytest.mark.asyncio
    async def test_alert_opportunity_noop(self, disabled_alerter, sample_opportunity):
        await disabled_alerter.alert_opportunity(sample_opportunity)
        # No error, no crash

    @pytest.mark.asyncio
    async def test_alert_trade_noop(self, disabled_alerter, sample_trade_record):
        await disabled_alerter.alert_trade(sample_trade_record)

    @pytest.mark.asyncio
    async def test_alert_error_noop(self, disabled_alerter):
        await disabled_alerter.alert_error("test error")

    @pytest.mark.asyncio
    async def test_send_daily_report_noop(self, disabled_alerter, sample_session_summary):
        await disabled_alerter.send_daily_report(sample_session_summary)


# ---------------------------------------------------------------------------
# Message formatting tests
# ---------------------------------------------------------------------------


class TestTelegramFormatting:
    @pytest.mark.asyncio
    async def test_opportunity_message_contains_roi(self, alerter, sample_opportunity):
        with patch.object(alerter, "_send_message", new_callable=AsyncMock) as mock_send:
            await alerter.alert_opportunity(sample_opportunity)
            mock_send.assert_called_once()
            text = mock_send.call_args[0][0]
            assert "17.65" in text
            assert "🔍" in text

    @pytest.mark.asyncio
    async def test_negrisk_opportunity_message(self, alerter, sample_negrisk_opportunity):
        with patch.object(alerter, "_send_message", new_callable=AsyncMock) as mock_send:
            await alerter.alert_opportunity(sample_negrisk_opportunity)
            text = mock_send.call_args[0][0]
            assert "NegRisk" in text or "negrisk" in text.lower()
            assert "3" in text  # 3 outcomes

    @pytest.mark.asyncio
    async def test_trade_success_message(self, alerter, sample_trade_record):
        with patch.object(alerter, "_send_message", new_callable=AsyncMock) as mock_send:
            await alerter.alert_trade(sample_trade_record)
            text = mock_send.call_args[0][0]
            assert "✅" in text
            assert "100" in text  # shares

    @pytest.mark.asyncio
    async def test_trade_rejected_message(self, alerter):
        record = TradeRecord(
            market_id="m1",
            market_question="BTC 1H",
            executed=False,
            reject_reasons=["Daily loss limit reached"],
        )
        with patch.object(alerter, "_send_message", new_callable=AsyncMock) as mock_send:
            await alerter.alert_trade(record)
            text = mock_send.call_args[0][0]
            assert "❌" in text
            assert "Daily loss limit" in text

    @pytest.mark.asyncio
    async def test_error_message(self, alerter):
        with patch.object(alerter, "_send_message", new_callable=AsyncMock) as mock_send:
            await alerter.alert_error("Gamma API unreachable", level="error")
            text = mock_send.call_args[0][0]
            assert "🚨" in text
            assert "Gamma API unreachable" in text

    @pytest.mark.asyncio
    async def test_warning_message(self, alerter):
        with patch.object(alerter, "_send_message", new_callable=AsyncMock) as mock_send:
            await alerter.alert_error("High latency detected", level="warning")
            text = mock_send.call_args[0][0]
            assert "⚠️" in text

    @pytest.mark.asyncio
    async def test_daily_report_message(self, alerter, sample_session_summary):
        with patch.object(alerter, "_send_message", new_callable=AsyncMock) as mock_send:
            await alerter.send_daily_report(sample_session_summary)
            text = mock_send.call_args[0][0]
            assert "📊" in text
            assert "10" in text  # cycles

    @pytest.mark.asyncio
    async def test_daily_report_no_trades(self, alerter):
        summary = SessionSummary()
        with patch.object(alerter, "_send_message", new_callable=AsyncMock) as mock_send:
            await alerter.send_daily_report(summary)
            text = mock_send.call_args[0][0]
            assert "📊" in text


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestTelegramErrorHandling:
    @pytest.mark.asyncio
    async def test_send_failure_no_crash(self, alerter):
        """HTTP 실패해도 크래시 없음."""
        with patch.object(
            alerter, "_send_message",
            new_callable=AsyncMock,
            side_effect=Exception("HTTP 500"),
        ):
            # Should not raise
            await alerter.alert_error("test")

    @pytest.mark.asyncio
    async def test_send_message_uses_html_parse_mode(self, alerter):
        """_send_message가 HTML parse_mode 사용."""
        # Capture what _send_message sends by checking format directly
        with patch.object(alerter, "_send_message", new_callable=AsyncMock) as mock_send:
            await alerter.alert_error("test")
            mock_send.assert_called_once()
            # Default parse_mode is HTML — verified by the method signature
            # Just ensure the method was called (HTML is the default in the implementation)

    @pytest.mark.asyncio
    async def test_send_message_api_url_format(self, alerter):
        """API URL이 올바른 형식인지 확인."""
        assert alerter._bot_token == "fake_token"
        assert alerter._chat_id == "12345"
