"""Tests for Phase 3 WebSocket cache enhancements.

Covers:
- OrderbookEntry caching (best ask/bid with size)
- Cache freshness for orderbooks
- WS-first price lookup (get_best_ask, get_market_best_asks)
- Cache statistics (hit rate tracking)
- PriceWebSocket book message parsing with bid/ask/size
- Integration: WS cache → SNIPE phase OrderbookSnapshot
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from poly24h.websocket.price_cache import OrderbookEntry, PriceCache
from poly24h.websocket.price_ws import PriceWebSocket


# ===========================================================================
# PriceCache Phase 3 Enhancements
# ===========================================================================


class TestPriceCacheOrderbook:
    def test_update_orderbook_basic(self):
        cache = PriceCache()
        cache.update_orderbook("tok_1", best_ask=0.45, best_bid=0.42, ask_size=100.0)

        assert cache.get_best_ask("tok_1") == 0.45
        # Also updates simple price
        assert cache.get_price("tok_1") == 0.45

    def test_update_orderbook_with_bid(self):
        cache = PriceCache()
        cache.update_orderbook(
            "tok_1", best_ask=0.50, best_bid=0.48,
            ask_size=50.0, bid_size=75.0,
        )

        entry = cache.get_orderbook_entry("tok_1")
        assert entry is not None
        assert entry.best_ask == 0.50
        assert entry.best_bid == 0.48
        assert entry.ask_size == 50.0
        assert entry.bid_size == 75.0

    def test_orderbook_freshness(self):
        cache = PriceCache()
        cache.update_orderbook("tok_1", best_ask=0.45)
        assert cache.is_orderbook_fresh("tok_1", max_age_secs=5.0) is True

    def test_orderbook_stale(self):
        cache = PriceCache()
        cache.update_orderbook("tok_1", best_ask=0.45)
        # Force stale timestamp
        entry = cache._orderbooks["tok_1"]
        entry.timestamp = time.time() - 10.0
        assert cache.is_orderbook_fresh("tok_1", max_age_secs=5.0) is False

    def test_orderbook_missing_is_not_fresh(self):
        cache = PriceCache()
        assert cache.is_orderbook_fresh("tok_missing", max_age_secs=5.0) is False

    def test_get_market_best_asks(self):
        cache = PriceCache()
        cache.update_orderbook("yes_tok", best_ask=0.45)
        cache.update_orderbook("no_tok", best_ask=0.55)

        yes_ask, no_ask = cache.get_market_best_asks("yes_tok", "no_tok")
        assert yes_ask == 0.45
        assert no_ask == 0.55

    def test_get_market_best_asks_one_missing(self):
        cache = PriceCache()
        cache.update_orderbook("yes_tok", best_ask=0.45)

        yes_ask, no_ask = cache.get_market_best_asks("yes_tok", "no_missing")
        assert yes_ask == 0.45
        assert no_ask is None

    def test_get_best_ask_falls_back_to_simple_price(self):
        """get_best_ask uses simple price cache if orderbook not available."""
        cache = PriceCache()
        cache.update("tok_1", 0.42)  # Simple price only
        assert cache.get_best_ask("tok_1") == 0.42

    def test_get_best_ask_prefers_orderbook(self):
        """Orderbook price takes precedence over simple price."""
        cache = PriceCache()
        cache.update("tok_1", 0.42)  # Simple price
        cache.update_orderbook("tok_1", best_ask=0.43)  # Orderbook
        assert cache.get_best_ask("tok_1") == 0.43

    def test_get_orderbook_entry_nonexistent(self):
        cache = PriceCache()
        assert cache.get_orderbook_entry("tok_missing") is None

    def test_clear_clears_orderbooks(self):
        cache = PriceCache()
        cache.update_orderbook("tok_1", best_ask=0.45)
        cache.clear()
        assert cache.get_orderbook_entry("tok_1") is None
        assert cache.get_best_ask("tok_1") is None

    def test_update_orderbook_none_ask_no_crash(self):
        """None best_ask → no simple price update but entry still saved."""
        cache = PriceCache()
        cache.update_orderbook("tok_1", best_ask=None, best_bid=0.42)
        entry = cache.get_orderbook_entry("tok_1")
        assert entry is not None
        assert entry.best_ask is None
        assert entry.best_bid == 0.42

    def test_update_orderbook_zero_ask_no_simple_price(self):
        """Zero ask doesn't update simple price cache."""
        cache = PriceCache()
        cache.update_orderbook("tok_1", best_ask=0.0)
        assert cache.get_price("tok_1") is None  # No update for 0


class TestPriceCacheStats:
    def test_initial_stats(self):
        cache = PriceCache()
        assert cache.stats["hits"] == 0
        assert cache.stats["misses"] == 0
        assert cache.stats["hit_rate"] == 0.0

    def test_hit_rate_tracking(self):
        cache = PriceCache()
        cache.update("tok_1", 0.45)
        cache.get_price("tok_1")  # hit
        cache.get_price("tok_1")  # hit
        cache.get_price("tok_missing")  # miss

        assert cache.stats["hits"] == 2
        assert cache.stats["misses"] == 1
        assert cache.stats["hit_rate"] == pytest.approx(0.667, abs=0.01)

    def test_stats_count_cached(self):
        cache = PriceCache()
        cache.update("tok_1", 0.45)
        cache.update("tok_2", 0.55)
        cache.update_orderbook("tok_3", best_ask=0.60)

        stats = cache.stats
        assert stats["prices_cached"] == 3  # tok_1, tok_2, tok_3 (orderbook updates simple too)
        assert stats["orderbooks_cached"] == 1

    def test_clear_resets_stats(self):
        cache = PriceCache()
        cache.update("tok_1", 0.45)
        cache.get_price("tok_1")
        cache.clear()
        assert cache.stats["hits"] == 0
        assert cache.stats["misses"] == 0


# ===========================================================================
# PriceWebSocket Phase 3 Book Parsing
# ===========================================================================


class TestPriceWebSocketPhase3:
    @pytest.mark.asyncio
    async def test_book_event_populates_orderbook_cache(self):
        """Book event with bids and asks → orderbook cache updated."""
        cache = PriceCache()
        ws = PriceWebSocket(cache)

        msg = json.dumps({
            "event_type": "book",
            "asset_id": "tok_1",
            "asks": [
                {"price": "0.50", "size": "100"},
                {"price": "0.55", "size": "200"},
            ],
            "bids": [
                {"price": "0.45", "size": "80"},
                {"price": "0.42", "size": "150"},
            ],
        })

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[msg, asyncio.CancelledError()])
        ws._ws = mock_ws
        ws._connected = True

        with pytest.raises(asyncio.CancelledError):
            await ws.listen()

        # Check orderbook entry
        entry = cache.get_orderbook_entry("tok_1")
        assert entry is not None
        assert entry.best_ask == 0.50  # Lowest ask
        assert entry.ask_size == 100.0
        assert entry.best_bid == 0.45  # Highest bid
        assert entry.bid_size == 80.0

    @pytest.mark.asyncio
    async def test_book_event_unsorted_asks(self):
        """Unsorted asks → best ask is still the lowest."""
        cache = PriceCache()
        ws = PriceWebSocket(cache)

        msg = json.dumps({
            "event_type": "book",
            "asset_id": "tok_2",
            "asks": [
                {"price": "0.60", "size": "50"},
                {"price": "0.45", "size": "100"},
                {"price": "0.55", "size": "75"},
            ],
            "bids": [],
        })

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[msg, asyncio.CancelledError()])
        ws._ws = mock_ws
        ws._connected = True

        with pytest.raises(asyncio.CancelledError):
            await ws.listen()

        entry = cache.get_orderbook_entry("tok_2")
        assert entry is not None
        assert entry.best_ask == 0.45  # Lowest

    @pytest.mark.asyncio
    async def test_message_counter(self):
        """Messages received counter increments."""
        cache = PriceCache()
        ws = PriceWebSocket(cache)

        msg1 = json.dumps({"event_type": "price_change", "asset_id": "t1", "price": "0.5"})
        msg2 = json.dumps({"event_type": "price_change", "asset_id": "t2", "price": "0.6"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[msg1, msg2, asyncio.CancelledError()])
        ws._ws = mock_ws
        ws._connected = True

        with pytest.raises(asyncio.CancelledError):
            await ws.listen()

        assert ws.messages_received == 2

    @pytest.mark.asyncio
    async def test_book_with_empty_asks_no_crash(self):
        """Empty asks list → no crash, no orderbook update."""
        cache = PriceCache()
        ws = PriceWebSocket(cache)

        msg = json.dumps({
            "event_type": "book",
            "asset_id": "tok_3",
            "asks": [],
            "bids": [{"price": "0.42", "size": "100"}],
        })

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[msg, asyncio.CancelledError()])
        ws._ws = mock_ws
        ws._connected = True

        with pytest.raises(asyncio.CancelledError):
            await ws.listen()

        # No orderbook entry (no valid asks)
        assert cache.get_orderbook_entry("tok_3") is None


# ===========================================================================
# Integration: WS Cache → Snipe Phase
# ===========================================================================


class TestWSCacheSnipeIntegration:
    """Test that WS cache data can be used to build OrderbookSnapshot."""

    def test_fresh_cache_produces_snapshot(self):
        """Fresh WS cache → valid OrderbookSnapshot for polling."""
        from poly24h.scheduler.event_scheduler import OrderbookSnapshot

        cache = PriceCache()
        cache.update_orderbook("yes_tok", best_ask=0.45)
        cache.update_orderbook("no_tok", best_ask=0.50)

        # Simulate what _try_ws_cache does
        if cache.is_orderbook_fresh("yes_tok") and cache.is_orderbook_fresh("no_tok"):
            yes_ask = cache.get_best_ask("yes_tok")
            no_ask = cache.get_best_ask("no_tok")

            snapshot = OrderbookSnapshot(
                yes_best_ask=yes_ask,
                no_best_ask=no_ask,
                spread=yes_ask + no_ask,
                timestamp=datetime.now(tz=timezone.utc),
            )

            assert snapshot.yes_best_ask == 0.45
            assert snapshot.no_best_ask == 0.50
            assert snapshot.spread == pytest.approx(0.95)

    def test_stale_cache_returns_none(self):
        """Stale cache → fallback to HTTP."""
        cache = PriceCache()
        cache.update_orderbook("yes_tok", best_ask=0.45)
        # Force stale
        cache._orderbooks["yes_tok"].timestamp = time.time() - 10.0

        assert cache.is_orderbook_fresh("yes_tok", max_age_secs=5.0) is False

    def test_partial_cache_returns_none(self):
        """Only one side cached → can't build complete snapshot."""
        cache = PriceCache()
        cache.update_orderbook("yes_tok", best_ask=0.45)

        yes_ask = cache.get_best_ask("yes_tok")
        no_ask = cache.get_best_ask("no_tok")

        assert yes_ask == 0.45
        assert no_ask is None
