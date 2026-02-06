"""Tests for F-005: Dry-Run Main Loop."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest
from aioresponses import aioresponses

from poly24h.config import BotConfig
from poly24h.main import (
    BANNER,
    detect_all,
    format_opportunity_line,
    log_results,
    parse_args,
    run_cycle,
)
from poly24h.models.market import Market, MarketSource
from poly24h.models.opportunity import ArbType, Opportunity

EVENTS_PATTERN = re.compile(r"^https://gamma-api\.polymarket\.com/events\b")


def _sample_market(**kwargs) -> Market:
    # Alias: market_id → id (convenience for tests)
    if "market_id" in kwargs:
        kwargs["id"] = kwargs.pop("market_id")
    defaults = dict(
        id="mkt_1",
        question="Will BTC be above $100k in 1 hour?",
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
    defaults.update(kwargs)
    return Market(**defaults)


def _sample_opportunity(market=None) -> Opportunity:
    mkt = market or _sample_market()
    return Opportunity(
        market=mkt,
        arb_type=ArbType.SINGLE_CONDITION,
        yes_price=0.45,
        no_price=0.40,
        total_cost=0.85,
        margin=0.15,
        roi_pct=17.65,
        recommended_size_usd=0.0,
        detected_at=datetime.now(tz=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------


class TestBanner:
    def test_banner_exists(self):
        assert BANNER is not None
        assert len(BANNER) > 0

    def test_banner_contains_project_name(self):
        assert "poly24h" in BANNER.lower() or "24h" in BANNER.lower()


# ---------------------------------------------------------------------------
# detect_all
# ---------------------------------------------------------------------------


class TestDetectAll:
    def test_detect_all_finds_arb(self):
        """Should detect arb opportunities from market list."""
        markets = [
            _sample_market(yes_price=0.45, no_price=0.40),  # arb: margin=0.15
        ]
        opps = detect_all(markets, min_spread=0.01)
        assert len(opps) == 1
        assert opps[0].margin == pytest.approx(0.15)

    def test_detect_all_no_arb(self):
        """Should return empty when no arb exists."""
        markets = [
            _sample_market(yes_price=0.50, no_price=0.50),
        ]
        opps = detect_all(markets, min_spread=0.01)
        assert len(opps) == 0

    def test_detect_all_mixed(self):
        """Should find only markets with arb."""
        markets = [
            _sample_market(market_id="arb", yes_price=0.45, no_price=0.40),
            _sample_market(market_id="no_arb", yes_price=0.50, no_price=0.50),
        ]
        opps = detect_all(markets, min_spread=0.01)
        assert len(opps) == 1

    def test_detect_all_empty_markets(self):
        """Empty markets → empty opportunities."""
        assert detect_all([], min_spread=0.01) == []

    def test_detect_all_ranked(self):
        """Results should be ranked by ROI descending."""
        markets = [
            _sample_market(market_id="low", yes_price=0.48, no_price=0.48),   # margin=0.04
            _sample_market(market_id="high", yes_price=0.40, no_price=0.40),  # margin=0.20
        ]
        opps = detect_all(markets, min_spread=0.01)
        assert len(opps) == 2
        assert opps[0].roi_pct > opps[1].roi_pct


# ---------------------------------------------------------------------------
# format_opportunity_line
# ---------------------------------------------------------------------------


class TestFormatOpportunityLine:
    def test_format_contains_key_info(self):
        opp = _sample_opportunity()
        line = format_opportunity_line(opp)
        assert "17.6" in line or "17.65" in line  # ROI
        assert "0.15" in line or "15" in line      # margin
        assert "BTC" in line or "mkt_1" in line    # market reference


# ---------------------------------------------------------------------------
# log_results
# ---------------------------------------------------------------------------


class TestLogResults:
    def test_log_results_with_opportunities(self, capsys):
        """Should print opportunity details."""
        opps = [_sample_opportunity()]
        log_results(opps, dry_run=True)
        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out or "dry" in captured.out.lower()

    def test_log_results_empty(self, capsys):
        """Should print 'no opportunities' message."""
        log_results([], dry_run=True)
        captured = capsys.readouterr()
        assert "no opportunit" in captured.out.lower() or "0" in captured.out


# ---------------------------------------------------------------------------
# run_cycle (integration)
# ---------------------------------------------------------------------------


class TestRunCycle:
    async def test_run_cycle_with_arb(self):
        """Full cycle: scan → detect → return opportunities."""
        end_date = (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat()
        event = {
            "id": "evt_1",
            "title": "BTC 1 hour market",
            "endDate": end_date,
            "enableNegRisk": False,
            "markets": [{
                "id": "mkt_1",
                "question": "Will BTC be above $100k in 1 hour?",
                "outcomePrices": "[0.45, 0.40]",
                "clobTokenIds": '["tok_y", "tok_n"]',
                "liquidity": "5000",
                "endDate": end_date,
                "active": True,
                "closed": False,
            }],
        }
        config = BotConfig()
        scanner_config = {
            "hourly_crypto": {"enabled": True, "min_liquidity_usd": 3000, "min_spread": 0.01},
        }
        with aioresponses() as m:
            m.get(EVENTS_PATTERN, payload=[event])
            opps = await run_cycle(config, scanner_config)
            assert len(opps) >= 1

    async def test_run_cycle_no_markets(self):
        """Empty API → no opportunities."""
        config = BotConfig()
        scanner_config = {
            "hourly_crypto": {"enabled": True, "min_liquidity_usd": 3000, "min_spread": 0.01},
        }
        with aioresponses() as m:
            m.get(EVENTS_PATTERN, payload=[])
            opps = await run_cycle(config, scanner_config)
            assert opps == []

    async def test_run_cycle_api_error_no_crash(self):
        """API failure → empty results, no crash."""
        config = BotConfig()
        scanner_config = {
            "hourly_crypto": {"enabled": True, "min_liquidity_usd": 3000, "min_spread": 0.01},
        }
        with aioresponses() as m:
            for _ in range(3):
                m.get(EVENTS_PATTERN, status=500)
            opps = await run_cycle(config, scanner_config)
            assert opps == []


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


class TestParseArgs:
    def test_default_args(self):
        args = parse_args([])
        assert args.interval == 60
        assert args.live is False

    def test_interval_override(self):
        args = parse_args(["--interval", "30"])
        assert args.interval == 30

    def test_live_flag(self):
        args = parse_args(["--live"])
        assert args.live is True

    def test_sources_override(self):
        args = parse_args(["--sources", "crypto,nba"])
        assert args.sources == "crypto,nba"
