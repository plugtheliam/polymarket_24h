"""Tests for F-003: Market Discovery & Filtering."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from aioresponses import aioresponses

from poly24h.discovery.gamma_client import GammaClient
from poly24h.discovery.market_filter import MarketFilter
from poly24h.discovery.market_scanner import MarketScanner
from poly24h.models.market import MarketSource

EVENTS_PATTERN = re.compile(r"^https://gamma-api\.polymarket\.com/events\b")


def _make_event(
    event_id: str = "evt_1",
    title: str = "BTC 1 hour market",
    tag: str = "crypto",
    markets: list | None = None,
    enable_neg_risk: bool = False,
    end_date: str | None = None,
) -> dict:
    """Helper: build a Gamma API event dict."""
    if end_date is None:
        end_date = (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat()
    if markets is None:
        markets = [_make_market()]
    return {
        "id": event_id,
        "title": title,
        "endDate": end_date,
        "markets": markets,
        "enableNegRisk": enable_neg_risk,
    }


def _make_market(
    market_id: str = "mkt_1",
    question: str = "Will BTC be above $100,000 in 1 hour?",
    yes_price: float = 0.45,
    no_price: float = 0.55,
    liquidity: float = 5000.0,
    end_date: str | None = None,
    active: bool = True,
    closed: bool = False,
) -> dict:
    """Helper: build a Gamma API market dict."""
    if end_date is None:
        end_date = (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat()
    return {
        "id": market_id,
        "question": question,
        "outcomePrices": f"[{yes_price}, {no_price}]",
        "clobTokenIds": '["tok_yes", "tok_no"]',
        "liquidity": str(liquidity),
        "endDate": end_date,
        "active": active,
        "closed": closed,
    }


# ---------------------------------------------------------------------------
# MarketFilter tests
# ---------------------------------------------------------------------------


class TestMarketFilter:
    def test_is_blacklisted_15min(self):
        assert MarketFilter.is_blacklisted("Will BTC go up in 15 minutes?")

    def test_is_blacklisted_15_min_variant(self):
        assert MarketFilter.is_blacklisted("BTC 15-min market")

    def test_not_blacklisted_hourly(self):
        assert not MarketFilter.is_blacklisted("Will BTC be above $100k in 1 hour?")

    def test_matches_hourly_crypto(self):
        assert MarketFilter.matches_hourly_crypto("Will BTC go up in 1 hour?")

    def test_matches_hourly_crypto_variant(self):
        assert MarketFilter.matches_hourly_crypto("BTC hourly market")

    def test_not_matches_hourly_15min(self):
        """15-min market should not match hourly patterns."""
        assert not MarketFilter.matches_hourly_crypto("BTC 15 minute market")

    def test_is_within_24h_true(self):
        future = (datetime.now(tz=timezone.utc) + timedelta(hours=12)).isoformat()
        assert MarketFilter.is_within_24h(future)

    def test_is_within_24h_false_past(self):
        past = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()
        assert not MarketFilter.is_within_24h(past)

    def test_is_within_24h_false_too_far(self):
        far_future = (datetime.now(tz=timezone.utc) + timedelta(hours=25)).isoformat()
        assert not MarketFilter.is_within_24h(far_future)

    def test_is_within_24h_bad_string(self):
        assert not MarketFilter.is_within_24h("not-a-date")

    def test_is_within_24h_empty(self):
        assert not MarketFilter.is_within_24h("")

    def test_is_active_market(self):
        mkt = {"active": True, "closed": False}
        assert MarketFilter.is_active(mkt)

    def test_closed_market_not_active(self):
        mkt = {"active": True, "closed": True}
        assert not MarketFilter.is_active(mkt)

    def test_inactive_market(self):
        mkt = {"active": False, "closed": False}
        assert not MarketFilter.is_active(mkt)

    def test_meets_min_liquidity(self):
        assert MarketFilter.meets_min_liquidity({"liquidity": "5000"}, 3000)

    def test_below_min_liquidity(self):
        assert not MarketFilter.meets_min_liquidity({"liquidity": "2000"}, 3000)

    def test_liquidity_null(self):
        assert not MarketFilter.meets_min_liquidity({"liquidity": None}, 3000)


# ---------------------------------------------------------------------------
# MarketScanner integration tests
# ---------------------------------------------------------------------------


class TestMarketScannerHourlyCrypto:
    async def test_discover_hourly_crypto(self):
        """Should find hourly crypto markets matching patterns."""
        event = _make_event(
            title="BTC 1 hour market",
            markets=[_make_market(question="Will BTC be above $100,000 in 1 hour?")],
        )
        with aioresponses() as m:
            m.get(EVENTS_PATTERN, payload=[event])
            async with GammaClient() as client:
                scanner = MarketScanner(client)
                markets = await scanner.discover_hourly_crypto()
                assert len(markets) == 1
                assert markets[0].source == MarketSource.HOURLY_CRYPTO

    async def test_exclude_15min_market(self):
        """15-min markets should be excluded by blacklist."""
        event = _make_event(
            title="BTC 15 min market",
            markets=[_make_market(question="Will BTC go up in 15 minutes?")],
        )
        with aioresponses() as m:
            m.get(EVENTS_PATTERN, payload=[event])
            async with GammaClient() as client:
                scanner = MarketScanner(client)
                markets = await scanner.discover_hourly_crypto()
                assert len(markets) == 0

    async def test_exclude_low_liquidity(self):
        """Markets below min liquidity should be excluded."""
        event = _make_event(
            markets=[_make_market(
                question="Will BTC be above $100k in 1 hour?",
                liquidity=1000.0,
            )],
        )
        with aioresponses() as m:
            m.get(EVENTS_PATTERN, payload=[event])
            async with GammaClient() as client:
                scanner = MarketScanner(client)
                markets = await scanner.discover_hourly_crypto()
                assert len(markets) == 0

    async def test_exclude_expired_market(self):
        """Markets past 24h should be excluded."""
        far_future = (datetime.now(tz=timezone.utc) + timedelta(hours=25)).isoformat()
        event = _make_event(
            markets=[_make_market(
                question="Will BTC be above $100k in 1 hour?",
                end_date=far_future,
            )],
            end_date=far_future,
        )
        with aioresponses() as m:
            m.get(EVENTS_PATTERN, payload=[event])
            async with GammaClient() as client:
                scanner = MarketScanner(client)
                markets = await scanner.discover_hourly_crypto()
                assert len(markets) == 0

    async def test_exclude_closed_market(self):
        """Closed markets should be excluded."""
        event = _make_event(
            markets=[_make_market(
                question="Will BTC be above $100k in 1 hour?",
                closed=True,
            )],
        )
        with aioresponses() as m:
            m.get(EVENTS_PATTERN, payload=[event])
            async with GammaClient() as client:
                scanner = MarketScanner(client)
                markets = await scanner.discover_hourly_crypto()
                assert len(markets) == 0


class TestMarketScannerSports:
    async def test_discover_nba(self):
        """Should find NBA game markets."""
        event = _make_event(
            title="Lakers vs Celtics",
            markets=[_make_market(
                question="Will Lakers win?",
                liquidity=6000.0,
            )],
        )
        with aioresponses() as m:
            m.get(EVENTS_PATTERN, payload=[event])
            async with GammaClient() as client:
                scanner = MarketScanner(client)
                markets = await scanner.discover_sports("nba")
                assert len(markets) == 1
                assert markets[0].source == MarketSource.NBA

    async def test_exclude_neg_risk_season_market(self):
        """NegRisk season markets should be excluded."""
        event = _make_event(
            title="NBA Championship 2025",
            enable_neg_risk=True,
            markets=[_make_market(
                question="Will Lakers win NBA championship?",
                liquidity=10000.0,
            )],
        )
        with aioresponses() as m:
            m.get(EVENTS_PATTERN, payload=[event])
            async with GammaClient() as client:
                scanner = MarketScanner(client)
                markets = await scanner.discover_sports("nba")
                assert len(markets) == 0


class TestMarketScannerDiscoverAll:
    async def test_discover_all_enabled_sources(self):
        """discover_all should scan only enabled sources."""
        crypto_event = _make_event(
            event_id="evt_crypto",
            title="BTC 1 hour market",
            markets=[_make_market(
                market_id="mkt_crypto",
                question="Will BTC be above $100k in 1 hour?",
            )],
        )
        nba_event = _make_event(
            event_id="evt_nba",
            title="Lakers vs Celtics",
            markets=[_make_market(
                market_id="mkt_nba",
                question="Will Lakers win?",
                liquidity=6000.0,
            )],
        )
        config = {
            "hourly_crypto": {"enabled": True, "min_liquidity_usd": 3000, "min_spread": 0.01},
            "nba": {"enabled": True, "min_liquidity_usd": 5000, "min_spread": 0.015},
            "nhl": {"enabled": False, "min_liquidity_usd": 5000, "min_spread": 0.015},
        }
        with aioresponses() as m:
            m.get(EVENTS_PATTERN, payload=[crypto_event])  # crypto tag
            m.get(EVENTS_PATTERN, payload=[nba_event])      # nba tag
            async with GammaClient() as client:
                scanner = MarketScanner(client, config=config)
                markets = await scanner.discover_all()
                assert len(markets) == 2

    async def test_discover_all_empty(self):
        """Should return empty list when no markets found."""
        config = {
            "hourly_crypto": {"enabled": True, "min_liquidity_usd": 3000, "min_spread": 0.01},
        }
        with aioresponses() as m:
            m.get(EVENTS_PATTERN, payload=[])
            async with GammaClient() as client:
                scanner = MarketScanner(client, config=config)
                markets = await scanner.discover_all()
                assert markets == []

    async def test_discover_all_disabled_sources(self):
        """Should return empty if all sources disabled."""
        config = {
            "hourly_crypto": {"enabled": False, "min_liquidity_usd": 3000, "min_spread": 0.01},
            "nba": {"enabled": False, "min_liquidity_usd": 5000, "min_spread": 0.015},
        }
        async with GammaClient() as client:
            scanner = MarketScanner(client, config=config)
            markets = await scanner.discover_all()
            assert markets == []

    async def test_discover_all_dedup(self):
        """Should deduplicate markets with same ID."""
        mkt = _make_market(market_id="same_id", question="Will BTC be above $100k in 1 hour?")
        event = _make_event(markets=[mkt, mkt])  # same market twice
        config = {
            "hourly_crypto": {"enabled": True, "min_liquidity_usd": 3000, "min_spread": 0.01},
        }
        with aioresponses() as m:
            m.get(EVENTS_PATTERN, payload=[event])
            async with GammaClient() as client:
                scanner = MarketScanner(client, config=config)
                markets = await scanner.discover_all()
                ids = [m.id for m in markets]
                assert len(set(ids)) == len(ids)

    async def test_api_failure_no_crash(self):
        """API failure should not crash — just return empty."""
        config = {
            "hourly_crypto": {"enabled": True, "min_liquidity_usd": 3000, "min_spread": 0.01},
        }
        with aioresponses() as m:
            for _ in range(3):
                m.get(EVENTS_PATTERN, status=500)
            async with GammaClient() as client:
                scanner = MarketScanner(client, config=config)
                markets = await scanner.discover_all()
                assert markets == []
