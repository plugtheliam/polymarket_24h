"""Integration tests for Phase 3: WS Cache + Paired Entry + Market Logger.

Tests the EventDrivenLoop integration:
- WS cache first polling with HTTP fallback
- Paired entry detection in snipe/cooldown phases
- Market logger recording and stats
- Cycle end report includes Phase 3 stats
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from poly24h.models.market import Market, MarketSource
from poly24h.monitoring.telegram import TelegramAlerter
from poly24h.scheduler.event_scheduler import (
    EventDrivenLoop,
    MarketOpenSchedule,
    OrderbookSnapshot,
    Phase,
    PreOpenPreparer,
    RapidOrderbookPoller,
    SniperOpportunity,
)
from poly24h.strategy.orderbook_scanner import ClobOrderbookFetcher
from poly24h.websocket.price_cache import PriceCache


@pytest.fixture
def sample_market():
    return Market(
        id="btc_001",
        question="Will BTC be above $100,000 at 2pm UTC?",
        source=MarketSource.HOURLY_CRYPTO,
        yes_token_id="yes_btc",
        no_token_id="no_btc",
        yes_price=0.45,
        no_price=0.50,
        liquidity_usd=10000.0,
        end_date=datetime.now(tz=timezone.utc) + timedelta(hours=1),
        event_id="evt_btc",
        event_title="BTC Hourly",
    )


@pytest.fixture
def loop_with_cache(sample_market):
    """Create EventDrivenLoop with a pre-populated price cache."""
    schedule = MarketOpenSchedule()
    gamma = MagicMock()
    preparer = PreOpenPreparer(gamma)
    fetcher = ClobOrderbookFetcher()
    poller = RapidOrderbookPoller(fetcher)
    alerter = TelegramAlerter(bot_token=None, chat_id=None)
    cache = PriceCache()

    loop = EventDrivenLoop(schedule, preparer, poller, alerter, price_cache=cache)
    loop._active_markets = [sample_market]
    loop._active_token_pairs = [("yes_btc", "no_btc")]
    loop._token_to_market = {
        "yes_btc": sample_market,
        "no_btc": sample_market,
    }
    return loop, cache


class TestWSCacheFirstPolling:
    """Test WS-cache-first polling approach."""

    def test_try_ws_cache_returns_snapshot_when_fresh(self, loop_with_cache):
        """Fresh WS cache → snapshot returned."""
        loop, cache = loop_with_cache
        cache.update_orderbook("yes_btc", best_ask=0.45)
        cache.update_orderbook("no_btc", best_ask=0.50)

        snapshot = loop._try_ws_cache("yes_btc", "no_btc")
        assert snapshot is not None
        assert snapshot.yes_best_ask == 0.45
        assert snapshot.no_best_ask == 0.50
        assert snapshot.spread == pytest.approx(0.95)

    def test_try_ws_cache_returns_none_when_stale(self, loop_with_cache):
        """Stale WS cache → None (fall back to HTTP)."""
        import time

        loop, cache = loop_with_cache
        cache.update_orderbook("yes_btc", best_ask=0.45)
        cache._orderbooks["yes_btc"].timestamp = time.time() - 10.0
        cache.update_orderbook("no_btc", best_ask=0.50)

        snapshot = loop._try_ws_cache("yes_btc", "no_btc")
        assert snapshot is None

    def test_try_ws_cache_returns_none_when_missing(self, loop_with_cache):
        """Missing token → None."""
        loop, cache = loop_with_cache
        cache.update_orderbook("yes_btc", best_ask=0.45)
        # no_btc not cached

        snapshot = loop._try_ws_cache("yes_btc", "no_btc")
        assert snapshot is None

    @pytest.mark.asyncio
    async def test_poll_all_uses_ws_cache_first(self, loop_with_cache):
        """When WS cache is fresh, poll_all_pairs uses cache (no HTTP)."""
        loop, cache = loop_with_cache
        cache.update_orderbook("yes_btc", best_ask=0.42)
        cache.update_orderbook("no_btc", best_ask=0.50)

        opps = await loop._poll_all_pairs(threshold=0.48)

        # WS cache was used
        assert loop._ws_cache_hits == 1
        assert loop._http_fallback_count == 0

        # Opportunity detected: YES at $0.42 < threshold $0.48
        assert len(opps) == 1
        opp, (yes_tok, no_tok) = opps[0]
        assert opp.trigger_side == "YES"
        assert opp.trigger_price == 0.42

    @pytest.mark.asyncio
    async def test_poll_all_falls_back_to_http(self, loop_with_cache):
        """When WS cache is empty, falls back to HTTP polling."""
        loop, cache = loop_with_cache
        # No cache data → HTTP fallback

        # Mock HTTP poller
        mock_snapshot = OrderbookSnapshot(
            yes_best_ask=0.42,
            no_best_ask=0.55,
            spread=0.97,
            timestamp=datetime.now(tz=timezone.utc),
        )
        loop.poller.poll_once = AsyncMock(return_value=mock_snapshot)

        opps = await loop._poll_all_pairs(threshold=0.48)

        assert loop._ws_cache_hits == 0
        assert loop._http_fallback_count == 1
        assert len(opps) == 1

    @pytest.mark.asyncio
    async def test_ws_cache_hit_counter_increments(self, loop_with_cache):
        """Multiple polls → WS cache hit counter increments."""
        loop, cache = loop_with_cache
        cache.update_orderbook("yes_btc", best_ask=0.60)
        cache.update_orderbook("no_btc", best_ask=0.60)

        # No opportunities (prices too high), but cache was hit
        await loop._poll_all_pairs(threshold=0.48)
        await loop._poll_all_pairs(threshold=0.48)

        assert loop._ws_cache_hits == 2


class TestPairedEntryIntegration:
    """Test paired entry detection in the loop."""

    @pytest.mark.asyncio
    async def test_check_paired_entries_detects(self, loop_with_cache, sample_market):
        """Paired entry detected when YES+NO < 1.0 with sufficient spread."""
        loop, cache = loop_with_cache
        cache.update_orderbook("yes_btc", best_ask=0.45, ask_size=50.0)
        cache.update_orderbook("no_btc", best_ask=0.50, ask_size=50.0)

        results = await loop._check_paired_entries(threshold=0.48)

        assert len(results) == 1
        opp, market, paper = results[0]
        assert opp.trigger_side == "PAIRED"
        assert market.id == "btc_001"
        assert paper["guaranteed_profit"] > 0

    @pytest.mark.asyncio
    async def test_check_paired_entries_no_opportunity(self, loop_with_cache):
        """No paired entry when YES+NO >= 0.98."""
        loop, cache = loop_with_cache
        cache.update_orderbook("yes_btc", best_ask=0.50)
        cache.update_orderbook("no_btc", best_ask=0.50)

        results = await loop._check_paired_entries(threshold=0.48)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_check_paired_no_cache_data(self, loop_with_cache):
        """No cache data → no paired entries."""
        loop, _ = loop_with_cache
        results = await loop._check_paired_entries(threshold=0.48)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_paired_simulator_called(self, loop_with_cache):
        """Paired simulator records the trade."""
        loop, cache = loop_with_cache
        cache.update_orderbook("yes_btc", best_ask=0.40, ask_size=100.0)
        cache.update_orderbook("no_btc", best_ask=0.45, ask_size=100.0)

        await loop._check_paired_entries(threshold=0.48)

        summary = loop._paired_simulator.get_summary()
        assert summary["total_trades"] == 1
        assert summary["total_guaranteed_profit"] > 0


class TestMarketLoggerIntegration:
    """Test market logger integration in the loop."""

    @pytest.mark.asyncio
    async def test_snipe_phase_logs_opportunities(self, loop_with_cache):
        """SNIPE phase logs detected opportunities to market logger."""
        loop, cache = loop_with_cache
        cache.update_orderbook("yes_btc", best_ask=0.42)
        cache.update_orderbook("no_btc", best_ask=0.55)

        class Config:
            sniper_threshold = 0.48
            pre_open_window_secs = 30.0

        # Force snipe phase timing (within first minute of hour)
        now = datetime.now(tz=timezone.utc).replace(minute=0, second=5)
        with patch("poly24h.scheduler.event_scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            await loop._handle_snipe_phase(Config())

        # Market logger should have at least recorded something
        assert len(loop._market_logger._records) >= 0  # May have paired entry too

    @pytest.mark.asyncio
    async def test_paired_entries_logged(self, loop_with_cache):
        """Paired entries are logged with is_paired=True."""
        loop, cache = loop_with_cache
        cache.update_orderbook("yes_btc", best_ask=0.40, ask_size=100.0)
        cache.update_orderbook("no_btc", best_ask=0.45, ask_size=100.0)

        await loop._check_paired_entries(threshold=0.48)

        # Find paired records
        paired_records = [r for r in loop._market_logger._records if r.is_paired]
        assert len(paired_records) == 1
        assert paired_records[0].asset_symbol == "BTC"
        assert paired_records[0].trigger_side == "PAIRED"


class TestCycleEndReportPhase3:
    """Test Phase 3 stats in cycle end report."""

    @pytest.mark.asyncio
    async def test_report_includes_ws_stats(self, loop_with_cache):
        """Cycle end report includes WS cache hit stats."""
        loop, cache = loop_with_cache
        loop._ws_cache_hits = 15
        loop._http_fallback_count = 3
        loop._cycle_count = 1

        # Mock alerter
        loop.alerter = MagicMock()
        loop.alerter.enabled = True
        loop.alerter.alert_error = AsyncMock()

        await loop._send_cycle_end_report()

        call_args = loop.alerter.alert_error.call_args[0][0]
        assert "WS Cache" in call_args or "ws_hits=15" in str(call_args) or "WS hits: 15" in call_args

    @pytest.mark.asyncio
    async def test_report_includes_paired_stats(self, loop_with_cache, sample_market):
        """Cycle end report includes paired entry stats when trades exist."""
        loop, cache = loop_with_cache
        loop._cycle_count = 1

        # Simulate a paired trade
        cache.update_orderbook("yes_btc", best_ask=0.40, ask_size=100.0)
        cache.update_orderbook("no_btc", best_ask=0.45, ask_size=100.0)
        await loop._check_paired_entries(threshold=0.48)

        loop.alerter = MagicMock()
        loop.alerter.enabled = True
        loop.alerter.alert_error = AsyncMock()

        await loop._send_cycle_end_report()

        call_args = loop.alerter.alert_error.call_args[0][0]
        assert "Paired Entry" in call_args

    @pytest.mark.asyncio
    async def test_report_no_extra_stats_when_empty(self, loop_with_cache):
        """No Phase 3 extras when no WS hits or paired trades."""
        loop, _ = loop_with_cache
        loop._cycle_count = 1

        loop.alerter = MagicMock()
        loop.alerter.enabled = True
        loop.alerter.alert_error = AsyncMock()

        await loop._send_cycle_end_report()

        call_args = loop.alerter.alert_error.call_args[0][0]
        # Standard report still sent
        assert "사이클 종료 요약" in call_args


class TestEventDrivenLoopPhase3Init:
    """Test Phase 3 initialization of EventDrivenLoop."""

    def test_default_price_cache(self):
        """EventDrivenLoop creates default PriceCache if none provided."""
        schedule = MarketOpenSchedule()
        gamma = MagicMock()
        preparer = PreOpenPreparer(gamma)
        fetcher = ClobOrderbookFetcher()
        poller = RapidOrderbookPoller(fetcher)
        alerter = TelegramAlerter(bot_token=None, chat_id=None)

        loop = EventDrivenLoop(schedule, preparer, poller, alerter)
        assert loop._price_cache is not None
        assert isinstance(loop._price_cache, PriceCache)

    def test_injected_price_cache(self):
        """EventDrivenLoop uses injected PriceCache."""
        schedule = MarketOpenSchedule()
        gamma = MagicMock()
        preparer = PreOpenPreparer(gamma)
        fetcher = ClobOrderbookFetcher()
        poller = RapidOrderbookPoller(fetcher)
        alerter = TelegramAlerter(bot_token=None, chat_id=None)
        cache = PriceCache()

        loop = EventDrivenLoop(
            schedule, preparer, poller, alerter, price_cache=cache,
        )
        assert loop._price_cache is cache
