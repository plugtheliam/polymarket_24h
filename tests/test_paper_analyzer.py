"""Tests for paper trade analyzer (Phase 4)."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from poly24h.analysis.paper_analyzer import (
    AnalysisResult,
    AssetSummary,
    DailySummary,
    MarketSummary,
    PaperTradeAnalyzer,
    TradeSummary,
    format_analysis_report,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Create a temporary data directory with sample JSONL files."""
    paper_dir = tmp_path / "paper_trades"
    paper_dir.mkdir()

    # Single-side trades file
    trades = [
        {
            "market_id": "mkt_1",
            "market_question": "Will BTC be above $100,000?",
            "market_source": "hourly_crypto",
            "side": "YES",
            "price": 0.42,
            "shares": 23.81,
            "cost": 10.0,
            "timestamp": "2026-02-07T04:00:05+00:00",
            "end_date": "2026-02-07T05:00:00+00:00",
            "status": "settled",
            "winner": "YES",
            "payout": 23.81,
            "pnl": 13.81,
        },
        {
            "market_id": "mkt_2",
            "market_question": "Will ETH be above $5,000?",
            "market_source": "hourly_crypto",
            "side": "YES",
            "price": 0.45,
            "shares": 22.22,
            "cost": 10.0,
            "timestamp": "2026-02-07T05:00:05+00:00",
            "end_date": "2026-02-07T06:00:00+00:00",
            "status": "settled",
            "winner": "NO",
            "payout": 0.0,
            "pnl": -10.0,
        },
        {
            "market_id": "mkt_3",
            "market_question": "Will SOL be above $200?",
            "market_source": "hourly_crypto",
            "side": "NO",
            "price": 0.40,
            "shares": 25.0,
            "cost": 10.0,
            "timestamp": "2026-02-07T06:00:05+00:00",
            "end_date": "2026-02-07T07:00:00+00:00",
            "status": "open",
            "winner": "",
            "payout": 0.0,
            "pnl": 0.0,
        },
    ]
    with open(paper_dir / "2026-02-07.jsonl", "w") as f:
        for t in trades:
            f.write(json.dumps(t) + "\n")

    # Paired trades file
    paired_trades = [
        {
            "market_id": "mkt_1",
            "market_question": "Will BTC be above $100,000?",
            "market_source": "hourly_crypto",
            "yes_ask": 0.45,
            "no_ask": 0.50,
            "total_cost": 0.95,
            "spread": 0.05,
            "roi_pct": 5.26,
            "shares": 21.05,
            "cost_usd": 20.0,
            "guaranteed_profit": 1.05,
            "source": "ws_cache",
            "timestamp": "2026-02-07T04:48:36+00:00",
            "status": "open",
            "actual_pnl": 0.0,
        },
        {
            "market_id": "mkt_1",
            "market_question": "Will BTC be above $100,000?",
            "market_source": "hourly_crypto",
            "yes_ask": 0.40,
            "no_ask": 0.45,
            "total_cost": 0.85,
            "spread": 0.15,
            "roi_pct": 17.65,
            "shares": 23.53,
            "cost_usd": 20.0,
            "guaranteed_profit": 3.53,
            "source": "ws_cache",
            "timestamp": "2026-02-07T04:49:49+00:00",
            "status": "open",
            "actual_pnl": 0.0,
        },
    ]
    with open(paper_dir / "paired_2026-02-07.jsonl", "w") as f:
        for t in paired_trades:
            f.write(json.dumps(t) + "\n")

    # Market stats file
    stats = [
        {
            "market_id": "mkt_1",
            "market_question": "Will BTC be above $100,000?",
            "market_source": "hourly_crypto",
            "asset_symbol": "BTC",
            "trigger_side": "YES",
            "trigger_price": 0.42,
            "spread": 0.97,
            "seconds_since_open": 5.0,
            "detection_source": "ws_cache",
            "is_paired": False,
            "timestamp": "2026-02-07T04:00:05+00:00",
        },
        {
            "market_id": "mkt_1",
            "market_question": "Will BTC be above $100,000?",
            "market_source": "hourly_crypto",
            "asset_symbol": "BTC",
            "trigger_side": "PAIRED",
            "trigger_price": 0.95,
            "spread": 0.05,
            "seconds_since_open": 10.0,
            "detection_source": "ws_cache",
            "is_paired": True,
            "timestamp": "2026-02-07T04:00:10+00:00",
        },
        {
            "market_id": "mkt_2",
            "market_question": "Will ETH be above $5,000?",
            "market_source": "hourly_crypto",
            "asset_symbol": "ETH",
            "trigger_side": "YES",
            "trigger_price": 0.45,
            "spread": 0.92,
            "seconds_since_open": 15.0,
            "detection_source": "http_poll",
            "is_paired": False,
            "timestamp": "2026-02-07T05:00:15+00:00",
        },
    ]
    with open(paper_dir / "market_stats_2026-02-07.jsonl", "w") as f:
        for s in stats:
            f.write(json.dumps(s) + "\n")

    return paper_dir


# ===========================================================================
# TradeSummary Tests
# ===========================================================================


class TestTradeSummary:
    def test_defaults(self):
        s = TradeSummary()
        assert s.total_trades == 0
        assert s.win_rate == 0.0
        assert s.avg_pnl == 0.0
        assert s.settled_count == 0

    def test_win_rate(self):
        s = TradeSummary(wins=7, losses=3)
        assert s.win_rate == pytest.approx(0.7)

    def test_avg_pnl(self):
        s = TradeSummary(wins=5, losses=5, total_pnl=50.0)
        assert s.avg_pnl == pytest.approx(5.0)


# ===========================================================================
# PaperTradeAnalyzer Tests
# ===========================================================================


class TestAnalyzerLoading:
    def test_analyze_with_data(self, tmp_data_dir):
        analyzer = PaperTradeAnalyzer(data_dir=str(tmp_data_dir))
        result = analyzer.analyze()

        assert result.files_read > 0
        assert result.overall.total_trades == 3
        assert result.paired.total_trades == 2

    def test_analyze_empty_dir(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        analyzer = PaperTradeAnalyzer(data_dir=str(empty_dir))
        result = analyzer.analyze()

        assert result.overall.total_trades == 0
        assert result.paired.total_trades == 0
        assert result.date_range == "No data"

    def test_analyze_nonexistent_dir(self, tmp_path):
        analyzer = PaperTradeAnalyzer(data_dir=str(tmp_path / "nonexistent"))
        result = analyzer.analyze()

        assert result.overall.total_trades == 0

    def test_analyze_with_specific_date(self, tmp_data_dir):
        analyzer = PaperTradeAnalyzer(data_dir=str(tmp_data_dir))
        target = datetime(2026, 2, 7, tzinfo=timezone.utc)
        result = analyzer.analyze(start_date=target, end_date=target)

        assert result.overall.total_trades == 3

    def test_analyze_with_days(self, tmp_data_dir):
        analyzer = PaperTradeAnalyzer(data_dir=str(tmp_data_dir))
        result = analyzer.analyze(days=30)

        assert result.overall.total_trades == 3


class TestAnalyzerSingleTrades:
    def test_settled_pnl(self, tmp_data_dir):
        analyzer = PaperTradeAnalyzer(data_dir=str(tmp_data_dir))
        result = analyzer.analyze()
        s = result.overall

        # Win: +13.81, Loss: -10.0
        assert s.wins == 1
        assert s.losses == 1
        assert s.open_trades == 1
        assert s.total_pnl == pytest.approx(3.81)
        assert s.max_gain == pytest.approx(13.81)
        assert s.max_loss == pytest.approx(-10.0)

    def test_avg_price(self, tmp_data_dir):
        analyzer = PaperTradeAnalyzer(data_dir=str(tmp_data_dir))
        result = analyzer.analyze()
        s = result.overall

        # avg of 0.42, 0.45, 0.40
        expected = (0.42 + 0.45 + 0.40) / 3
        assert s.avg_price == pytest.approx(expected, abs=0.01)


class TestAnalyzerPairedTrades:
    def test_paired_summary(self, tmp_data_dir):
        analyzer = PaperTradeAnalyzer(data_dir=str(tmp_data_dir))
        result = analyzer.analyze()
        p = result.paired

        assert p.total_trades == 2
        assert p.total_cost == pytest.approx(40.0)
        # guaranteed_profit: 1.05 + 3.53
        assert p.total_pnl == pytest.approx(4.58, abs=0.01)


class TestAnalyzerDailyBreakdown:
    def test_daily_breakdown(self, tmp_data_dir):
        analyzer = PaperTradeAnalyzer(data_dir=str(tmp_data_dir))
        result = analyzer.analyze()

        assert len(result.by_date) >= 1
        # All trades on 2026-02-07
        day = result.by_date[0]
        assert day.date == "2026-02-07"
        assert day.trades == 5  # 3 single + 2 paired


class TestAnalyzerMarketBreakdown:
    def test_by_market(self, tmp_data_dir):
        analyzer = PaperTradeAnalyzer(data_dir=str(tmp_data_dir))
        result = analyzer.analyze()

        # All hourly_crypto
        assert len(result.by_market) >= 1
        crypto = [m for m in result.by_market if m.name == "hourly_crypto"]
        assert len(crypto) == 1
        assert crypto[0].trades == 5


class TestAnalyzerAssetBreakdown:
    def test_by_asset(self, tmp_data_dir):
        analyzer = PaperTradeAnalyzer(data_dir=str(tmp_data_dir))
        result = analyzer.analyze()

        assert len(result.by_asset) >= 2
        btc = [a for a in result.by_asset if a.symbol == "BTC"]
        assert len(btc) == 1
        assert btc[0].total_signals == 2
        assert btc[0].paired_signals == 1
        assert btc[0].single_signals == 1


# ===========================================================================
# Report Formatting Tests
# ===========================================================================


class TestFormatReport:
    def test_format_with_data(self, tmp_data_dir):
        analyzer = PaperTradeAnalyzer(data_dir=str(tmp_data_dir))
        result = analyzer.analyze()
        report = format_analysis_report(result)

        assert "Paper Trade Analysis Report" in report
        assert "Single-Side Trades" in report
        assert "Paired Entry" in report
        assert "Daily Breakdown" in report
        assert "By Market Source" in report
        assert "By Asset" in report

    def test_format_empty(self):
        result = AnalysisResult()
        report = format_analysis_report(result)

        assert "Paper Trade Analysis Report" in report
        assert "Total trades:    0" in report

    def test_format_contains_pnl(self, tmp_data_dir):
        analyzer = PaperTradeAnalyzer(data_dir=str(tmp_data_dir))
        result = analyzer.analyze()
        report = format_analysis_report(result)

        # Should contain P&L info
        assert "P&L" in report
        assert "Win rate" in report


# ===========================================================================
# Edge Cases
# ===========================================================================


class TestAnalyzerEdgeCases:
    def test_malformed_jsonl(self, tmp_path):
        """Malformed lines should be skipped gracefully."""
        paper_dir = tmp_path / "paper_trades"
        paper_dir.mkdir()
        with open(paper_dir / "2026-02-07.jsonl", "w") as f:
            f.write('{"valid": true, "status": "open", "cost": 10.0, "price": 0.42, "timestamp": "2026-02-07T04:00:00+00:00"}\n')
            f.write("not json at all\n")
            f.write('{"also_valid": true, "status": "open", "cost": 5.0, "price": 0.45, "timestamp": "2026-02-07T05:00:00+00:00"}\n')

        analyzer = PaperTradeAnalyzer(data_dir=str(paper_dir))
        # Should not crash
        result = analyzer.analyze()
        assert result.overall.total_trades >= 1

    def test_file_outside_date_range(self, tmp_data_dir):
        """Files outside requested date range should be excluded."""
        # Add a file for a different date
        with open(tmp_data_dir / "2025-01-01.jsonl", "w") as f:
            f.write(json.dumps({
                "market_id": "old",
                "status": "settled",
                "pnl": 100.0,
                "cost": 10.0,
                "price": 0.42,
                "timestamp": "2025-01-01T00:00:00+00:00",
            }) + "\n")

        analyzer = PaperTradeAnalyzer(data_dir=str(tmp_data_dir))
        target = datetime(2026, 2, 7, tzinfo=timezone.utc)
        result = analyzer.analyze(start_date=target, end_date=target)

        # Should only include 2026-02-07 trades
        assert result.overall.total_trades == 3

    def test_all_open_trades(self, tmp_path):
        """All open trades — no settled P&L."""
        paper_dir = tmp_path / "paper_trades"
        paper_dir.mkdir()
        trades = [
            {
                "market_id": f"mkt_{i}",
                "market_source": "hourly_crypto",
                "side": "YES",
                "price": 0.42,
                "cost": 10.0,
                "status": "open",
                "pnl": 0.0,
                "timestamp": "2026-02-07T04:00:00+00:00",
            }
            for i in range(5)
        ]
        with open(paper_dir / "2026-02-07.jsonl", "w") as f:
            for t in trades:
                f.write(json.dumps(t) + "\n")

        analyzer = PaperTradeAnalyzer(data_dir=str(paper_dir))
        result = analyzer.analyze()

        assert result.overall.total_trades == 5
        assert result.overall.open_trades == 5
        assert result.overall.settled_count == 0
        assert result.overall.total_pnl == 0.0
