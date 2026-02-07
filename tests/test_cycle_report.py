"""Tests for Phase 2: Cycle end summary report."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from poly24h.monitoring.cycle_report import CycleStats, MarketPriceStat, format_cycle_report


# ---------------------------------------------------------------------------
# MarketPriceStat
# ---------------------------------------------------------------------------


class TestMarketPriceStat:
    def test_initial_state(self):
        stat = MarketPriceStat(question="BTC up?", source="hourly_crypto")
        assert stat.min_yes_ask == float("inf")
        assert stat.max_yes_ask == 0.0
        assert stat.signal_count == 0

    def test_update_yes(self):
        stat = MarketPriceStat(question="BTC up?", source="hourly_crypto")
        stat.update(yes_ask=0.48, no_ask=None)
        assert stat.min_yes_ask == 0.48
        assert stat.max_yes_ask == 0.48
        assert stat.signal_count == 1

    def test_update_both(self):
        stat = MarketPriceStat(question="BTC up?", source="hourly_crypto")
        stat.update(yes_ask=0.48, no_ask=0.52)
        stat.update(yes_ask=0.45, no_ask=0.55)
        assert stat.min_yes_ask == 0.45
        assert stat.max_yes_ask == 0.48
        assert stat.min_no_ask == 0.52
        assert stat.max_no_ask == 0.55
        assert stat.signal_count == 2

    def test_skip_zero(self):
        stat = MarketPriceStat(question="BTC up?", source="hourly_crypto")
        stat.update(yes_ask=0.0, no_ask=0.0)
        assert stat.min_yes_ask == float("inf")
        assert stat.signal_count == 1  # Still counted

    def test_skip_none(self):
        stat = MarketPriceStat(question="BTC up?", source="hourly_crypto")
        stat.update(yes_ask=None, no_ask=None)
        assert stat.min_yes_ask == float("inf")
        assert stat.signal_count == 1


# ---------------------------------------------------------------------------
# CycleStats
# ---------------------------------------------------------------------------


class TestCycleStats:
    def test_initial_state(self):
        stats = CycleStats()
        assert stats.markets_discovered == 0
        assert stats.total_polls == 0
        assert stats.raw_signals == 0
        assert stats.filtered_signals == 0
        assert stats.paper_trades == 0

    def test_record_discovery(self):
        stats = CycleStats()
        stats.record_discovery(137, {"hourly_crypto": 94, "nba": 43})
        assert stats.markets_discovered == 137
        assert stats.markets_by_source["hourly_crypto"] == 94

    def test_record_poll(self):
        stats = CycleStats()
        stats.record_poll()
        stats.record_poll()
        assert stats.total_polls == 2

    def test_record_filtered_signal(self):
        stats = CycleStats()
        stats.record_filtered_signal(
            market_question="Will BTC go up this hour?",
            market_source="hourly_crypto",
            trigger_price=0.47,
            trigger_side="YES",
            paper_size_usd=10.0,
        )
        assert stats.filtered_signals == 1
        assert stats.paper_trades == 1
        assert stats.paper_total_invested == 10.0

        # Check market_stats
        key = "Will BTC go up this hour?"[:60]
        assert key in stats.market_stats
        ms = stats.market_stats[key]
        assert ms.min_yes_ask == 0.47
        assert ms.signal_count == 1

    def test_record_multiple_signals_same_market(self):
        stats = CycleStats()
        q = "Will BTC go up this hour?"
        stats.record_filtered_signal(q, "crypto", 0.47, "YES")
        stats.record_filtered_signal(q, "crypto", 0.45, "YES")
        stats.record_filtered_signal(q, "crypto", 0.46, "NO")

        key = q[:60]
        ms = stats.market_stats[key]
        assert ms.min_yes_ask == 0.45
        assert ms.max_yes_ask == 0.47
        assert ms.min_no_ask == 0.46
        assert ms.max_no_ask == 0.46
        assert ms.signal_count == 3

    def test_finalize(self):
        stats = CycleStats()
        stats.finalize()
        assert stats.cycle_end is not None
        assert stats.duration_minutes >= 0

    def test_duration_minutes(self):
        stats = CycleStats()
        # Duration should be very small (just created)
        assert stats.duration_minutes < 1.0


# ---------------------------------------------------------------------------
# format_cycle_report
# ---------------------------------------------------------------------------


class TestFormatCycleReport:
    def test_empty_cycle(self):
        stats = CycleStats()
        stats.finalize()
        report = format_cycle_report(stats)
        assert "사이클 종료 요약" in report
        assert "Markets: 0" in report
        assert "Raw: 0" in report

    def test_full_cycle(self):
        stats = CycleStats()
        stats.record_discovery(137, {"hourly_crypto": 94, "nba": 43})
        for _ in range(10):
            stats.record_poll()
        stats.raw_signals = 25

        # Record some filtered signals
        stats.record_filtered_signal(
            "Will BTC go up?", "hourly_crypto", 0.47, "YES"
        )
        stats.record_filtered_signal(
            "Lakers vs Celtics", "nba", 0.45, "NO"
        )
        stats.finalize()

        report = format_cycle_report(stats)
        assert "Markets: 137" in report
        assert "Polls: 10" in report
        assert "Raw: 25" in report
        assert "Filtered: 2" in report
        assert "Paper Trades" in report
        assert "건수: 2" in report
        assert "마켓별 가격 요약" in report
        assert "Will BTC go up?" in report

    def test_no_market_stats_section_when_empty(self):
        stats = CycleStats()
        stats.finalize()
        report = format_cycle_report(stats)
        assert "마켓별 가격 요약" not in report

    def test_quality_pass_rate_zero_raw(self):
        stats = CycleStats()
        stats.raw_signals = 0
        stats.finalize()
        report = format_cycle_report(stats)
        # Should not crash on division by zero
        assert "quality pass rate: 0%" in report
