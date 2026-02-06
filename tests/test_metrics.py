"""Tests for MetricsCollector (F-013).

거래 메트릭 수집 + 통계 집계 테스트.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from poly24h.monitoring.metrics import MetricsCollector, TradeMetric

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def collector():
    return MetricsCollector()


@pytest.fixture
def sample_metrics():
    now = datetime.now(tz=timezone.utc)
    return [
        TradeMetric(now, "hourly_crypto", 5.0, 100.0, 5.0, True),
        TradeMetric(now, "hourly_crypto", 3.0, 200.0, 6.0, True),
        TradeMetric(now, "nba", 2.5, 150.0, 3.75, True),
        TradeMetric(now, "hourly_crypto", -1.0, 100.0, -1.0, False),
        TradeMetric(now, "nba", 4.0, 300.0, 12.0, True),
    ]


# ---------------------------------------------------------------------------
# TradeMetric tests
# ---------------------------------------------------------------------------


class TestTradeMetric:
    def test_create(self):
        now = datetime.now(tz=timezone.utc)
        m = TradeMetric(now, "hourly_crypto", 5.0, 100.0, 5.0, True)
        assert m.timestamp == now
        assert m.market_source == "hourly_crypto"
        assert m.roi_pct == 5.0
        assert m.cost == 100.0
        assert m.profit == 5.0
        assert m.success is True


# ---------------------------------------------------------------------------
# MetricsCollector tests
# ---------------------------------------------------------------------------


class TestMetricsCollector:
    def test_empty_stats(self, collector):
        stats = collector.get_stats()
        assert stats["total_trades"] == 0
        assert stats["avg_roi"] == 0.0
        assert stats["win_rate"] == 0.0
        assert stats["total_pnl"] == 0.0

    def test_record_single(self, collector):
        now = datetime.now(tz=timezone.utc)
        m = TradeMetric(now, "hourly_crypto", 5.0, 100.0, 5.0, True)
        collector.record_trade(m)
        stats = collector.get_stats()
        assert stats["total_trades"] == 1
        assert stats["avg_roi"] == 5.0
        assert stats["win_rate"] == 100.0
        assert stats["total_pnl"] == 5.0

    def test_record_multiple(self, collector, sample_metrics):
        for m in sample_metrics:
            collector.record_trade(m)
        stats = collector.get_stats()
        assert stats["total_trades"] == 5
        assert stats["win_rate"] == 80.0  # 4/5

    def test_total_pnl(self, collector, sample_metrics):
        for m in sample_metrics:
            collector.record_trade(m)
        stats = collector.get_stats()
        expected_pnl = 5.0 + 6.0 + 3.75 + (-1.0) + 12.0
        assert abs(stats["total_pnl"] - expected_pnl) < 0.01

    def test_avg_roi(self, collector, sample_metrics):
        for m in sample_metrics:
            collector.record_trade(m)
        stats = collector.get_stats()
        expected_avg = (5.0 + 3.0 + 2.5 + (-1.0) + 4.0) / 5
        assert abs(stats["avg_roi"] - expected_avg) < 0.01

    def test_by_source(self, collector, sample_metrics):
        for m in sample_metrics:
            collector.record_trade(m)
        stats = collector.get_stats()
        assert "hourly_crypto" in stats["by_source"]
        assert "nba" in stats["by_source"]
        assert stats["by_source"]["hourly_crypto"]["count"] == 3
        assert stats["by_source"]["nba"]["count"] == 2

    def test_reset(self, collector, sample_metrics):
        for m in sample_metrics:
            collector.record_trade(m)
        collector.reset()
        stats = collector.get_stats()
        assert stats["total_trades"] == 0

    def test_hourly_summary_empty(self, collector):
        result = collector.hourly_summary()
        assert result == []

    def test_hourly_summary_groups(self, collector):
        now = datetime.now(tz=timezone.utc)
        # 두 시간에 걸쳐 메트릭 기록
        collector.record_trade(
            TradeMetric(now, "crypto", 5.0, 100.0, 5.0, True)
        )
        collector.record_trade(
            TradeMetric(now - timedelta(hours=1), "crypto", 3.0, 200.0, 6.0, True)
        )
        result = collector.hourly_summary()
        assert len(result) >= 1

    def test_win_rate_all_losses(self, collector):
        now = datetime.now(tz=timezone.utc)
        collector.record_trade(TradeMetric(now, "crypto", -1.0, 100.0, -1.0, False))
        collector.record_trade(TradeMetric(now, "crypto", -2.0, 100.0, -2.0, False))
        stats = collector.get_stats()
        assert stats["win_rate"] == 0.0

    def test_by_source_pnl(self, collector, sample_metrics):
        for m in sample_metrics:
            collector.record_trade(m)
        stats = collector.get_stats()
        crypto_pnl = stats["by_source"]["hourly_crypto"]["pnl"]
        assert abs(crypto_pnl - (5.0 + 6.0 + (-1.0))) < 0.01
