"""Tests for MarketOpportunityLogger (Phase 3).

Covers:
- OpportunityRecord creation and serialization
- Asset symbol extraction from questions
- Per-asset statistics aggregation
- Time distribution analysis
- Source breakdown
- JSONL persistence
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from poly24h.monitoring.market_logger import (
    MarketOpportunityLogger,
    OpportunityRecord,
    extract_asset_symbol,
)


# ===========================================================================
# extract_asset_symbol Tests
# ===========================================================================


class TestExtractAssetSymbol:
    def test_extract_btc(self):
        assert extract_asset_symbol("Will BTC be above $100,000 at 2pm UTC?") == "BTC"

    def test_extract_eth(self):
        assert extract_asset_symbol("Will ETH go up in the next 1 hour?") == "ETH"

    def test_extract_sol(self):
        assert extract_asset_symbol("SOL price above $200?") == "SOL"

    def test_extract_xrp(self):
        assert extract_asset_symbol("Will XRP reach $2.00?") == "XRP"

    def test_extract_case_insensitive(self):
        assert extract_asset_symbol("will btc go up?") == "BTC"

    def test_extract_no_crypto(self):
        assert extract_asset_symbol("Lakers vs Celtics") == ""

    def test_extract_empty_string(self):
        assert extract_asset_symbol("") == ""

    def test_extract_doge(self):
        assert extract_asset_symbol("Will DOGE break $1?") == "DOGE"


# ===========================================================================
# MarketOpportunityLogger Tests
# ===========================================================================


class TestMarketOpportunityLogger:
    @pytest.fixture
    def logger_with_dir(self):
        with tempfile.TemporaryDirectory() as d:
            yield MarketOpportunityLogger(data_dir=d), d

    def test_record_basic(self, logger_with_dir):
        mlogger, _ = logger_with_dir
        rec = mlogger.record(
            market_id="mkt_1",
            market_question="Will BTC go up?",
            market_source="hourly_crypto",
            trigger_side="YES",
            trigger_price=0.42,
            seconds_since_open=5.0,
        )
        assert rec.asset_symbol == "BTC"
        assert rec.trigger_price == 0.42
        assert rec.seconds_since_open == 5.0

    def test_record_writes_jsonl(self, logger_with_dir):
        mlogger, data_dir = logger_with_dir
        mlogger.record(
            market_id="mkt_1",
            market_question="Will ETH go up?",
            market_source="hourly_crypto",
            trigger_side="NO",
            trigger_price=0.38,
        )

        files = list(Path(data_dir).glob("market_stats_*.jsonl"))
        assert len(files) == 1
        with open(files[0]) as f:
            data = json.loads(f.read().strip())
        assert data["asset_symbol"] == "ETH"
        assert data["trigger_side"] == "NO"

    def test_asset_summary_single(self, logger_with_dir):
        mlogger, _ = logger_with_dir
        mlogger.record(
            market_id="1", market_question="BTC up?",
            market_source="crypto", trigger_side="YES", trigger_price=0.40,
        )
        mlogger.record(
            market_id="2", market_question="BTC down?",
            market_source="crypto", trigger_side="NO", trigger_price=0.35,
        )

        summary = mlogger.get_asset_summary()
        assert "BTC" in summary
        assert summary["BTC"]["count"] == 2
        assert summary["BTC"]["yes_count"] == 1
        assert summary["BTC"]["no_count"] == 1
        assert summary["BTC"]["avg_price"] == pytest.approx(0.375, abs=0.01)
        assert summary["BTC"]["min_price"] == 0.35
        assert summary["BTC"]["max_price"] == 0.40

    def test_asset_summary_multiple_assets(self, logger_with_dir):
        mlogger, _ = logger_with_dir
        for _ in range(5):
            mlogger.record(
                market_id="1", market_question="BTC up?",
                market_source="crypto", trigger_side="YES", trigger_price=0.40,
            )
        for _ in range(3):
            mlogger.record(
                market_id="2", market_question="ETH up?",
                market_source="crypto", trigger_side="YES", trigger_price=0.42,
            )
        mlogger.record(
            market_id="3", market_question="SOL up?",
            market_source="crypto", trigger_side="NO", trigger_price=0.38,
        )

        summary = mlogger.get_asset_summary()
        assert summary["BTC"]["count"] == 5
        assert summary["ETH"]["count"] == 3
        assert summary["SOL"]["count"] == 1

    def test_time_distribution(self, logger_with_dir):
        mlogger, _ = logger_with_dir
        # Record at various seconds since open
        for sec in [2, 2, 3, 5, 5, 5, 10]:
            mlogger.record(
                market_id="1", market_question="BTC up?",
                market_source="crypto", trigger_side="YES",
                trigger_price=0.40, seconds_since_open=float(sec),
            )

        dist = mlogger.get_time_distribution()
        assert dist[2] == 2
        assert dist[3] == 1
        assert dist[5] == 3
        assert dist[10] == 1

    def test_peak_seconds(self, logger_with_dir):
        mlogger, _ = logger_with_dir
        for _ in range(10):
            mlogger.record(
                market_id="1", market_question="BTC up?",
                market_source="crypto", trigger_side="YES",
                trigger_price=0.40, seconds_since_open=3.0,
            )
        for _ in range(5):
            mlogger.record(
                market_id="2", market_question="ETH up?",
                market_source="crypto", trigger_side="YES",
                trigger_price=0.42, seconds_since_open=7.0,
            )
        for _ in range(2):
            mlogger.record(
                market_id="3", market_question="SOL up?",
                market_source="crypto", trigger_side="NO",
                trigger_price=0.38, seconds_since_open=15.0,
            )

        peaks = mlogger.get_peak_seconds(top_n=3)
        assert peaks[0] == (3, 10)
        assert peaks[1] == (7, 5)
        assert peaks[2] == (15, 2)

    def test_source_breakdown(self, logger_with_dir):
        mlogger, _ = logger_with_dir
        for _ in range(4):
            mlogger.record(
                market_id="1", market_question="BTC up?",
                market_source="crypto", trigger_side="YES",
                trigger_price=0.40, detection_source="ws_cache",
            )
        for _ in range(2):
            mlogger.record(
                market_id="2", market_question="ETH up?",
                market_source="crypto", trigger_side="YES",
                trigger_price=0.42, detection_source="http_poll",
            )

        breakdown = mlogger.get_source_breakdown()
        assert breakdown["ws_cache"] == 4
        assert breakdown["http_poll"] == 2

    def test_paired_count_in_summary(self, logger_with_dir):
        mlogger, _ = logger_with_dir
        mlogger.record(
            market_id="1", market_question="BTC up?",
            market_source="crypto", trigger_side="PAIRED",
            trigger_price=0.95, is_paired=True,
        )
        mlogger.record(
            market_id="2", market_question="BTC down?",
            market_source="crypto", trigger_side="YES",
            trigger_price=0.40, is_paired=False,
        )

        summary = mlogger.get_asset_summary()
        assert summary["BTC"]["paired_count"] == 1

    def test_format_stats_report(self, logger_with_dir):
        mlogger, _ = logger_with_dir
        mlogger.record(
            market_id="1", market_question="BTC up?",
            market_source="hourly_crypto", trigger_side="YES",
            trigger_price=0.40, seconds_since_open=5.0,
        )

        report = mlogger.format_stats_report()
        assert "마켓별 기회 통계" in report
        assert "BTC" in report
        assert "1건" in report

    def test_format_empty_report(self, logger_with_dir):
        mlogger, _ = logger_with_dir
        report = mlogger.format_stats_report()
        assert "총 기회: 0건" in report

    def test_non_crypto_market(self, logger_with_dir):
        mlogger, _ = logger_with_dir
        mlogger.record(
            market_id="nba_1", market_question="Lakers vs Celtics",
            market_source="nba", trigger_side="YES",
            trigger_price=0.42,
        )

        summary = mlogger.get_asset_summary()
        assert "OTHER" in summary
        assert summary["OTHER"]["count"] == 1

    def test_load_from_jsonl(self, logger_with_dir):
        mlogger, data_dir = logger_with_dir
        mlogger.record(
            market_id="1", market_question="BTC up?",
            market_source="crypto", trigger_side="YES",
            trigger_price=0.40,
        )
        mlogger.record(
            market_id="2", market_question="ETH up?",
            market_source="crypto", trigger_side="NO",
            trigger_price=0.38,
        )

        # Load from file
        loaded = mlogger.load_from_jsonl()
        assert len(loaded) == 2
        assert loaded[0].market_id == "1"
        assert loaded[1].market_id == "2"

    def test_load_nonexistent_date(self, logger_with_dir):
        mlogger, _ = logger_with_dir
        from datetime import timedelta
        past = datetime.now(tz=timezone.utc) - timedelta(days=365)
        loaded = mlogger.load_from_jsonl(date=past)
        assert loaded == []


# ===========================================================================
# OpportunityRecord Tests
# ===========================================================================


class TestOpportunityRecord:
    def test_to_dict(self):
        rec = OpportunityRecord(
            market_id="mkt_1",
            market_question="BTC up?",
            market_source="hourly_crypto",
            asset_symbol="BTC",
            trigger_side="YES",
            trigger_price=0.40,
            spread=0.95,
            seconds_since_open=5.0,
            detection_source="ws_cache",
            is_paired=False,
            timestamp="2025-01-01T00:00:00+00:00",
        )
        d = rec.to_dict()
        assert d["market_id"] == "mkt_1"
        assert d["asset_symbol"] == "BTC"
        assert d["is_paired"] is False
