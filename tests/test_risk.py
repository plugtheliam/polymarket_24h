"""Tests for risk management modules."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from poly24h.models.market import Market, MarketSource
from poly24h.models.opportunity import ArbType, Opportunity
from poly24h.position.portfolio import PortfolioManager
from poly24h.risk.controller import RiskController, RiskResult
from poly24h.risk.cooldown import CooldownManager
from poly24h.risk.loss_limiter import DailyLossLimiter
from poly24h.risk.position_limiter import PositionSizeLimiter

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
# DailyLossLimiter Tests
# ===========================================================================


class TestDailyLossLimiterBasic:
    def test_default_approved(self):
        lim = DailyLossLimiter(limit_usd=500.0)
        approved, reason = lim.check()
        assert approved is True
        assert reason is None

    def test_under_limit_approved(self):
        lim = DailyLossLimiter(limit_usd=500.0)
        lim.record_loss(400.0)
        approved, reason = lim.check()
        assert approved is True

    def test_at_limit_rejected(self):
        lim = DailyLossLimiter(limit_usd=500.0)
        lim.record_loss(500.0)
        approved, reason = lim.check()
        assert approved is False
        assert "daily loss" in reason.lower()

    def test_over_limit_rejected(self):
        lim = DailyLossLimiter(limit_usd=500.0)
        lim.record_loss(600.0)
        approved, reason = lim.check()
        assert approved is False

    def test_multiple_losses(self):
        lim = DailyLossLimiter(limit_usd=500.0)
        lim.record_loss(200.0)
        lim.record_loss(200.0)
        approved, _ = lim.check()
        assert approved is True  # 400 < 500
        lim.record_loss(100.0)
        approved, _ = lim.check()
        assert approved is False  # 500 >= 500

    def test_zero_limit_always_rejects(self):
        """limit=0이면 $0 >= $0 이므로 항상 거부."""
        lim = DailyLossLimiter(limit_usd=0.0)
        approved, _ = lim.check()
        assert approved is False  # 0 >= 0, no room at all

    def test_current_loss(self):
        lim = DailyLossLimiter(limit_usd=500.0)
        assert lim.current_loss == 0.0
        lim.record_loss(123.0)
        assert lim.current_loss == 123.0


class TestDailyLossLimiterReset:
    def test_reset_clears_loss(self):
        lim = DailyLossLimiter(limit_usd=500.0)
        lim.record_loss(500.0)
        approved, _ = lim.check()
        assert approved is False
        lim.reset()
        approved, _ = lim.check()
        assert approved is True

    def test_midnight_reset(self):
        """자정 경과 시 자동 리셋."""
        lim = DailyLossLimiter(limit_usd=500.0)
        lim.record_loss(500.0)

        # Simulate day change
        yesterday = datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)
        today = datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)

        lim._last_reset_date = yesterday.date()
        with patch("poly24h.risk.loss_limiter._utc_today", return_value=today.date()):
            lim._maybe_reset_daily()

        approved, _ = lim.check()
        assert approved is True


# ===========================================================================
# PositionSizeLimiter Tests
# ===========================================================================


class TestPositionSizeLimiter:
    def test_under_limits(self):
        lim = PositionSizeLimiter(max_per_market=1000.0, max_total=5000.0)
        approved, allowed = lim.check(
            current_market_exposure=0.0,
            current_total_exposure=0.0,
            new_trade_size=500.0,
        )
        assert approved is True
        assert allowed == 500.0

    def test_market_limit_caps(self):
        """마켓 한도 초과 → 허용 사이즈 축소."""
        lim = PositionSizeLimiter(max_per_market=1000.0, max_total=5000.0)
        approved, allowed = lim.check(
            current_market_exposure=800.0,
            current_total_exposure=800.0,
            new_trade_size=500.0,
        )
        assert approved is True
        assert allowed == pytest.approx(200.0)  # 1000 - 800

    def test_total_limit_caps(self):
        """전체 한도 초과 → 허용 사이즈 축소."""
        lim = PositionSizeLimiter(max_per_market=1000.0, max_total=5000.0)
        approved, allowed = lim.check(
            current_market_exposure=0.0,
            current_total_exposure=4800.0,
            new_trade_size=500.0,
        )
        assert approved is True
        assert allowed == pytest.approx(200.0)  # 5000 - 4800

    def test_both_limits_takes_min(self):
        """마켓+전체 한도 모두 적용 → min."""
        lim = PositionSizeLimiter(max_per_market=1000.0, max_total=5000.0)
        approved, allowed = lim.check(
            current_market_exposure=900.0,  # market allows 100
            current_total_exposure=4700.0,  # total allows 300
            new_trade_size=500.0,
        )
        assert approved is True
        assert allowed == pytest.approx(100.0)  # min(100, 300)

    def test_at_market_limit_rejected(self):
        """마켓 한도 도달 → 거부."""
        lim = PositionSizeLimiter(max_per_market=1000.0, max_total=5000.0)
        approved, allowed = lim.check(
            current_market_exposure=1000.0,
            current_total_exposure=1000.0,
            new_trade_size=100.0,
        )
        assert approved is False
        assert allowed == 0.0

    def test_at_total_limit_rejected(self):
        lim = PositionSizeLimiter(max_per_market=1000.0, max_total=5000.0)
        approved, allowed = lim.check(
            current_market_exposure=0.0,
            current_total_exposure=5000.0,
            new_trade_size=100.0,
        )
        assert approved is False
        assert allowed == 0.0

    def test_zero_trade_size(self):
        lim = PositionSizeLimiter(max_per_market=1000.0, max_total=5000.0)
        approved, allowed = lim.check(0.0, 0.0, 0.0)
        assert approved is False
        assert allowed == 0.0


# ===========================================================================
# CooldownManager Tests
# ===========================================================================


class TestCooldownManager:
    def test_default_approved(self):
        cm = CooldownManager(max_consecutive_losses=3, cooldown_seconds=300)
        approved, remaining = cm.check()
        assert approved is True
        assert remaining == 0

    def test_under_limit_approved(self):
        cm = CooldownManager(max_consecutive_losses=3, cooldown_seconds=300)
        cm.record_loss()
        cm.record_loss()
        approved, _ = cm.check()
        assert approved is True

    def test_at_limit_rejected(self):
        cm = CooldownManager(max_consecutive_losses=3, cooldown_seconds=300)
        cm.record_loss()
        cm.record_loss()
        cm.record_loss()
        approved, remaining = cm.check()
        assert approved is False
        assert remaining > 0

    def test_win_resets_streak(self):
        cm = CooldownManager(max_consecutive_losses=3, cooldown_seconds=300)
        cm.record_loss()
        cm.record_loss()
        cm.record_win()
        cm.record_loss()
        approved, _ = cm.check()
        assert approved is True  # streak = 1 (reset by win)

    def test_cooldown_expires(self):
        """쿨다운 만료 후 다시 승인."""
        cm = CooldownManager(max_consecutive_losses=3, cooldown_seconds=1)
        cm.record_loss()
        cm.record_loss()
        cm.record_loss()
        approved, _ = cm.check()
        assert approved is False

        # 쿨다운 시작 시간을 과거로 설정
        cm._cooldown_start = time.time() - 2
        approved, _ = cm.check()
        assert approved is True

    def test_cooldown_resets_streak(self):
        """쿨다운 만료 후 streak도 리셋."""
        cm = CooldownManager(max_consecutive_losses=3, cooldown_seconds=1)
        cm.record_loss()
        cm.record_loss()
        cm.record_loss()
        cm._cooldown_start = time.time() - 2
        cm.check()  # triggers expiry
        assert cm._consecutive_losses == 0


# ===========================================================================
# RiskController Tests
# ===========================================================================


class TestRiskController:
    def test_all_pass(self):
        rc = RiskController(
            daily_loss_limit=500.0,
            max_per_market=1000.0,
            max_total=5000.0,
        )
        portfolio = PortfolioManager()
        opp = _make_opportunity(recommended_size_usd=200.0)
        result = rc.check_risk(opp, portfolio)
        assert result.approved is True

    def test_daily_loss_rejects(self):
        rc = RiskController(daily_loss_limit=500.0)
        rc.loss_limiter.record_loss(500.0)
        portfolio = PortfolioManager()
        opp = _make_opportunity()
        result = rc.check_risk(opp, portfolio)
        assert result.approved is False
        assert any("daily" in r.lower() for r in result.reasons)

    def test_position_limit_caps_size(self):
        rc = RiskController(max_per_market=100.0, max_total=5000.0)
        portfolio = PortfolioManager()
        opp = _make_opportunity(recommended_size_usd=500.0)
        result = rc.check_risk(opp, portfolio)
        assert result.approved is True
        assert result.allowed_size <= 100.0

    def test_cooldown_rejects(self):
        rc = RiskController(
            max_consecutive_losses=2,
            cooldown_seconds=300,
        )
        rc.cooldown.record_loss()
        rc.cooldown.record_loss()
        portfolio = PortfolioManager()
        opp = _make_opportunity()
        result = rc.check_risk(opp, portfolio)
        assert result.approved is False
        assert any("cooldown" in r.lower() for r in result.reasons)

    def test_dry_run_always_approves(self):
        """dry_run 모드: 체크는 실행하되 항상 승인."""
        rc = RiskController(daily_loss_limit=500.0, dry_run=True)
        rc.loss_limiter.record_loss(600.0)
        portfolio = PortfolioManager()
        opp = _make_opportunity()
        result = rc.check_risk(opp, portfolio)
        assert result.approved is True
        # 사유는 여전히 기록
        assert len(result.reasons) > 0

    def test_multiple_failures(self):
        """여러 리스크 체크 실패 시 모든 사유 수집."""
        rc = RiskController(
            daily_loss_limit=100.0,
            max_consecutive_losses=1,
            cooldown_seconds=300,
        )
        rc.loss_limiter.record_loss(200.0)
        rc.cooldown.record_loss()
        portfolio = PortfolioManager()
        opp = _make_opportunity()
        result = rc.check_risk(opp, portfolio)
        assert result.approved is False
        assert len(result.reasons) >= 2

    def test_result_dataclass(self):
        result = RiskResult(approved=True, reasons=[], allowed_size=100.0)
        assert result.approved
        assert result.allowed_size == 100.0
        assert result.reasons == []

    def test_with_existing_portfolio_exposure(self):
        """기존 포지션이 있는 포트폴리오에서 한도 체크."""
        rc = RiskController(max_per_market=1000.0, max_total=2000.0)
        portfolio = PortfolioManager()
        portfolio.add_trade("mkt_1", "YES", 100, 0.45)  # $45
        portfolio.add_trade("mkt_1", "NO", 100, 0.40)   # $40 → total $85

        opp = _make_opportunity(recommended_size_usd=200.0)
        result = rc.check_risk(opp, portfolio)
        assert result.approved is True
