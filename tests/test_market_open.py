"""Tests for F-017: Market Open Sniper.

Kent Beck TDD — test scenarios from spec.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from poly24h.models.market import Market, MarketSource
from poly24h.strategy.market_open import (
    BinancePriceSignal,
    MarketOpenTimer,
    OpenSniperDetector,
    SniperOpportunity,
)


def _make_market(
    end_date: datetime | None = None,
    market_id: str = "test-mkt-1",
) -> Market:
    """테스트용 Market 객체 생성."""
    if end_date is None:
        end_date = datetime.now(tz=timezone.utc) + timedelta(hours=1)
    return Market(
        id=market_id,
        question="Will BTC go up?",
        source=MarketSource.HOURLY_CRYPTO,
        yes_token_id="yes-token-1",
        no_token_id="no-token-1",
        yes_price=0.50,
        no_price=0.50,
        liquidity_usd=10000.0,
        end_date=end_date,
        event_id="evt-1",
        event_title="BTC 1H Market",
    )


# ============================================================
# SniperOpportunity tests
# ============================================================


class TestSniperOpportunity:
    """SniperOpportunity 속성 테스트."""

    def test_expected_roi(self):
        market = _make_market()
        opp = SniperOpportunity(
            market=market,
            side="yes",
            price=0.40,
            threshold=0.45,
            seconds_since_open=10.0,
            confidence=0.8,
        )
        # roi = (1.0 - 0.40) / 0.40 * 100 = 150.0
        assert opp.expected_roi == pytest.approx(150.0)

    def test_expected_roi_at_50(self):
        market = _make_market()
        opp = SniperOpportunity(
            market=market,
            side="no",
            price=0.50,
            threshold=0.50,
            seconds_since_open=5.0,
            confidence=0.5,
        )
        # roi = (1.0 - 0.50) / 0.50 * 100 = 100.0
        assert opp.expected_roi == pytest.approx(100.0)

    def test_expected_roi_low_price(self):
        market = _make_market()
        opp = SniperOpportunity(
            market=market,
            side="yes",
            price=0.20,
            threshold=0.45,
            seconds_since_open=5.0,
            confidence=0.9,
        )
        # roi = (1.0 - 0.20) / 0.20 * 100 = 400.0
        assert opp.expected_roi == pytest.approx(400.0)


# ============================================================
# MarketOpenTimer tests
# ============================================================


class TestMarketOpenTimer:
    """1시간 마켓 오픈 타이밍 계산 테스트."""

    def test_next_open_at_half_hour(self):
        """14:35 → 15:00."""
        now = datetime(2026, 2, 6, 14, 35, 0, tzinfo=timezone.utc)
        result = MarketOpenTimer.next_open(now)
        assert result == datetime(2026, 2, 6, 15, 0, 0, tzinfo=timezone.utc)

    def test_next_open_at_59_minutes(self):
        """14:59 → 15:00."""
        now = datetime(2026, 2, 6, 14, 59, 0, tzinfo=timezone.utc)
        result = MarketOpenTimer.next_open(now)
        assert result == datetime(2026, 2, 6, 15, 0, 0, tzinfo=timezone.utc)

    def test_next_open_at_exact_hour(self):
        """정각이면 현재 반환."""
        now = datetime(2026, 2, 6, 15, 0, 0, tzinfo=timezone.utc)
        result = MarketOpenTimer.next_open(now)
        assert result == now

    def test_next_open_at_00_01(self):
        """00:01 → 01:00."""
        now = datetime(2026, 2, 6, 0, 1, 0, tzinfo=timezone.utc)
        result = MarketOpenTimer.next_open(now)
        assert result == datetime(2026, 2, 6, 1, 0, 0, tzinfo=timezone.utc)

    def test_next_open_at_23_30(self):
        """23:30 → 다음 날 00:00."""
        now = datetime(2026, 2, 6, 23, 30, 0, tzinfo=timezone.utc)
        result = MarketOpenTimer.next_open(now)
        assert result == datetime(2026, 2, 7, 0, 0, 0, tzinfo=timezone.utc)

    def test_seconds_until_open_half_hour(self):
        now = datetime(2026, 2, 6, 14, 30, 0, tzinfo=timezone.utc)
        result = MarketOpenTimer.seconds_until_open(now)
        assert result == pytest.approx(1800.0)

    def test_seconds_until_open_exact_hour(self):
        now = datetime(2026, 2, 6, 15, 0, 0, tzinfo=timezone.utc)
        result = MarketOpenTimer.seconds_until_open(now)
        assert result == pytest.approx(0.0)

    def test_seconds_until_open_59_30(self):
        """59:30 → 30초 남음."""
        now = datetime(2026, 2, 6, 14, 59, 30, tzinfo=timezone.utc)
        result = MarketOpenTimer.seconds_until_open(now)
        assert result == pytest.approx(30.0)

    def test_is_pre_open_window_30s_before(self):
        """오픈 30초 전 → True."""
        now = datetime(2026, 2, 6, 14, 59, 30, tzinfo=timezone.utc)
        assert MarketOpenTimer.is_pre_open_window(now, window_secs=30.0) is True

    def test_is_pre_open_window_exactly_at_boundary(self):
        """정확히 30초 전 → True."""
        now = datetime(2026, 2, 6, 14, 59, 30, tzinfo=timezone.utc)
        assert MarketOpenTimer.is_pre_open_window(now, window_secs=30.0) is True

    def test_is_pre_open_window_2min_before(self):
        """오픈 2분 전 → False."""
        now = datetime(2026, 2, 6, 14, 58, 0, tzinfo=timezone.utc)
        assert MarketOpenTimer.is_pre_open_window(now, window_secs=30.0) is False

    def test_is_pre_open_window_at_open(self):
        """정각 → True (0초 남음은 window 내)."""
        now = datetime(2026, 2, 6, 15, 0, 0, tzinfo=timezone.utc)
        assert MarketOpenTimer.is_pre_open_window(now, window_secs=30.0) is True

    def test_is_pre_open_window_10s_before(self):
        now = datetime(2026, 2, 6, 14, 59, 50, tzinfo=timezone.utc)
        assert MarketOpenTimer.is_pre_open_window(now, window_secs=30.0) is True

    def test_seconds_since_market_open(self):
        """end_time - 1hour = open_time. 현재가 오픈 10초 후."""
        end_time = datetime(2026, 2, 6, 16, 0, 0, tzinfo=timezone.utc)
        # open_time = 15:00:00
        now = datetime(2026, 2, 6, 15, 0, 10, tzinfo=timezone.utc)
        result = MarketOpenTimer.seconds_since_market_open(end_time, now)
        assert result == pytest.approx(10.0)

    def test_seconds_since_market_open_before_open(self):
        """오픈 전이면 음수."""
        end_time = datetime(2026, 2, 6, 16, 0, 0, tzinfo=timezone.utc)
        now = datetime(2026, 2, 6, 14, 59, 50, tzinfo=timezone.utc)
        result = MarketOpenTimer.seconds_since_market_open(end_time, now)
        assert result == pytest.approx(-10.0)

    def test_seconds_since_market_open_at_open(self):
        end_time = datetime(2026, 2, 6, 16, 0, 0, tzinfo=timezone.utc)
        now = datetime(2026, 2, 6, 15, 0, 0, tzinfo=timezone.utc)
        result = MarketOpenTimer.seconds_since_market_open(end_time, now)
        assert result == pytest.approx(0.0)


# ============================================================
# OpenSniperDetector tests
# ============================================================


class TestOpenSniperDetector:
    """마켓 오픈 직후 저가 기회 감지 테스트."""

    def test_detect_yes_below_threshold(self):
        """Spec: 오픈 10초 후, yes_ask=$0.42 → SniperOpp(YES)."""
        detector = OpenSniperDetector(threshold=0.45, max_seconds=60.0)
        market = _make_market()
        opp = detector.detect(market, yes_ask=0.42, no_ask=0.55, seconds_since_open=10.0)
        assert opp is not None
        assert opp.side == "yes"
        assert opp.price == 0.42

    def test_detect_no_below_threshold(self):
        """no_ask가 threshold 이하면 NO 감지."""
        detector = OpenSniperDetector(threshold=0.45)
        market = _make_market()
        opp = detector.detect(market, yes_ask=0.55, no_ask=0.40, seconds_since_open=5.0)
        assert opp is not None
        assert opp.side == "no"
        assert opp.price == 0.40

    def test_detect_both_below_threshold_picks_cheaper(self):
        """양쪽 다 threshold 이하 → 더 싼 쪽."""
        detector = OpenSniperDetector(threshold=0.45)
        market = _make_market()
        opp = detector.detect(market, yes_ask=0.42, no_ask=0.40, seconds_since_open=5.0)
        assert opp is not None
        assert opp.side == "no"  # 더 저렴
        assert opp.price == 0.40

    def test_detect_both_above_threshold(self):
        """Spec: 양쪽 모두 $0.50/$0.50 → None."""
        detector = OpenSniperDetector(threshold=0.45)
        market = _make_market()
        opp = detector.detect(market, yes_ask=0.50, no_ask=0.50, seconds_since_open=10.0)
        assert opp is None

    def test_detect_too_late(self):
        """Spec: 오픈 60초 후 → None (too late)."""
        detector = OpenSniperDetector(threshold=0.45, max_seconds=60.0)
        market = _make_market()
        opp = detector.detect(market, yes_ask=0.42, no_ask=0.55, seconds_since_open=61.0)
        assert opp is None

    def test_detect_exactly_at_max_seconds(self):
        """경계값: 정확히 max_seconds → None."""
        detector = OpenSniperDetector(threshold=0.45, max_seconds=60.0)
        market = _make_market()
        opp = detector.detect(market, yes_ask=0.42, no_ask=0.55, seconds_since_open=60.0)
        assert opp is None

    def test_detect_threshold_boundary(self):
        """Spec: threshold=$0.45, yes_ask=$0.46 → None."""
        detector = OpenSniperDetector(threshold=0.45)
        market = _make_market()
        opp = detector.detect(market, yes_ask=0.46, no_ask=0.55, seconds_since_open=10.0)
        assert opp is None

    def test_detect_exactly_at_threshold(self):
        """정확히 threshold 가격 → 감지 (<=)."""
        detector = OpenSniperDetector(threshold=0.45)
        market = _make_market()
        opp = detector.detect(market, yes_ask=0.45, no_ask=0.55, seconds_since_open=5.0)
        assert opp is not None
        assert opp.side == "yes"

    def test_confidence_early(self):
        """오픈 직후 confidence 높음."""
        detector = OpenSniperDetector(threshold=0.45, max_seconds=60.0)
        market = _make_market()
        opp = detector.detect(market, yes_ask=0.42, no_ask=0.55, seconds_since_open=0.0)
        assert opp is not None
        assert opp.confidence == pytest.approx(1.0)

    def test_confidence_late(self):
        """Spec: 오픈 60초에 가까울수록 confidence 낮음."""
        detector = OpenSniperDetector(threshold=0.45, max_seconds=60.0)
        market = _make_market()
        opp = detector.detect(market, yes_ask=0.42, no_ask=0.55, seconds_since_open=59.0)
        assert opp is not None
        assert opp.confidence < 0.6  # significantly lower

    def test_confidence_decay(self):
        """시간이 지날수록 confidence 감소."""
        detector = OpenSniperDetector(threshold=0.45, max_seconds=60.0)
        market = _make_market()

        opp_early = detector.detect(market, 0.42, 0.55, seconds_since_open=5.0)
        opp_mid = detector.detect(market, 0.42, 0.55, seconds_since_open=30.0)
        opp_late = detector.detect(market, 0.42, 0.55, seconds_since_open=55.0)

        assert opp_early.confidence > opp_mid.confidence
        assert opp_mid.confidence > opp_late.confidence

    def test_detect_carries_market_ref(self):
        """기회에 market 참조 포함."""
        detector = OpenSniperDetector(threshold=0.45)
        market = _make_market(market_id="btc-hourly-1")
        opp = detector.detect(market, 0.42, 0.55, seconds_since_open=5.0)
        assert opp.market.id == "btc-hourly-1"

    def test_detect_threshold_and_seconds_stored(self):
        detector = OpenSniperDetector(threshold=0.45, max_seconds=60.0)
        market = _make_market()
        opp = detector.detect(market, 0.42, 0.55, seconds_since_open=15.0)
        assert opp.threshold == 0.45
        assert opp.seconds_since_open == 15.0

    def test_custom_threshold(self):
        """다른 threshold 값."""
        detector = OpenSniperDetector(threshold=0.30)
        market = _make_market()
        # 0.35 > 0.30 → None
        opp = detector.detect(market, 0.35, 0.55, seconds_since_open=5.0)
        assert opp is None
        # 0.28 <= 0.30 → detected
        opp = detector.detect(market, 0.28, 0.55, seconds_since_open=5.0)
        assert opp is not None


# ============================================================
# BinancePriceSignal tests
# ============================================================


class TestBinancePriceSignal:
    """Binance 가격 기반 방향 신호 테스트."""

    def test_signal_up(self):
        """가격 상승 > min_change_pct → 'up'."""
        result = BinancePriceSignal.get_signal(
            open_price=100.0, current_price=100.2, min_change_pct=0.1
        )
        assert result == "up"

    def test_signal_down(self):
        """가격 하락 > min_change_pct → 'down'."""
        result = BinancePriceSignal.get_signal(
            open_price=100.0, current_price=99.8, min_change_pct=0.1
        )
        assert result == "down"

    def test_signal_neutral_small_change(self):
        """변동 < min_change_pct → 'neutral'."""
        result = BinancePriceSignal.get_signal(
            open_price=100.0, current_price=100.05, min_change_pct=0.1
        )
        assert result == "neutral"

    def test_signal_neutral_no_change(self):
        result = BinancePriceSignal.get_signal(100.0, 100.0, 0.1)
        assert result == "neutral"

    def test_signal_exactly_at_threshold(self):
        """정확히 min_change_pct — 'neutral' (초과해야 signal)."""
        result = BinancePriceSignal.get_signal(100.0, 100.1, min_change_pct=0.1)
        assert result == "neutral"

    def test_signal_large_move_up(self):
        result = BinancePriceSignal.get_signal(50000.0, 50500.0, min_change_pct=0.1)
        assert result == "up"

    def test_signal_large_move_down(self):
        result = BinancePriceSignal.get_signal(50000.0, 49000.0, min_change_pct=0.1)
        assert result == "down"

    def test_custom_min_change(self):
        """min_change_pct=0.5 → 더 큰 변동 필요."""
        # 0.2% change < 0.5% threshold → neutral
        result = BinancePriceSignal.get_signal(100.0, 100.2, min_change_pct=0.5)
        assert result == "neutral"
        # 0.6% change > 0.5% threshold → up
        result = BinancePriceSignal.get_signal(100.0, 100.6, min_change_pct=0.5)
        assert result == "up"
