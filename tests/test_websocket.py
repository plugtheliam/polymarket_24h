"""Tests for WebSocket real-time prices (F-011).

PriceCache 완전 테스트 + PriceWebSocket mock 테스트.
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from poly24h.websocket.price_cache import PriceCache
from poly24h.websocket.price_ws import PriceWebSocket

# ===========================================================================
# PriceCache tests
# ===========================================================================


class TestPriceCache:
    def test_update_and_get(self):
        cache = PriceCache()
        cache.update("tok_1", 0.45)
        assert cache.get_price("tok_1") == 0.45

    def test_get_nonexistent(self):
        cache = PriceCache()
        assert cache.get_price("tok_missing") is None

    def test_update_overwrites(self):
        cache = PriceCache()
        cache.update("tok_1", 0.45)
        cache.update("tok_1", 0.50)
        assert cache.get_price("tok_1") == 0.50

    def test_multiple_tokens(self):
        cache = PriceCache()
        cache.update("tok_1", 0.45)
        cache.update("tok_2", 0.55)
        assert cache.get_price("tok_1") == 0.45
        assert cache.get_price("tok_2") == 0.55

    def test_get_market_prices(self):
        cache = PriceCache()
        cache.update("yes_tok", 0.45)
        cache.update("no_tok", 0.55)
        result = cache.get_market_prices("yes_tok", "no_tok")
        assert result == (0.45, 0.55)

    def test_get_market_prices_missing_yes(self):
        cache = PriceCache()
        cache.update("no_tok", 0.55)
        assert cache.get_market_prices("yes_tok", "no_tok") is None

    def test_get_market_prices_missing_no(self):
        cache = PriceCache()
        cache.update("yes_tok", 0.45)
        assert cache.get_market_prices("yes_tok", "no_tok") is None

    def test_get_market_prices_both_missing(self):
        cache = PriceCache()
        assert cache.get_market_prices("yes_tok", "no_tok") is None

    def test_is_stale_not_stale(self):
        cache = PriceCache()
        cache.update("tok_1", 0.45)
        assert cache.is_stale("tok_1", max_age_secs=30.0) is False

    def test_is_stale_old_entry(self):
        cache = PriceCache()
        cache.update("tok_1", 0.45)
        # 강제로 타임스탬프를 과거로 설정
        cache._timestamps["tok_1"] = time.time() - 60.0
        assert cache.is_stale("tok_1", max_age_secs=30.0) is True

    def test_is_stale_nonexistent(self):
        cache = PriceCache()
        assert cache.is_stale("tok_missing") is True

    def test_clear(self):
        cache = PriceCache()
        cache.update("tok_1", 0.45)
        cache.update("tok_2", 0.55)
        cache.clear()
        assert cache.get_price("tok_1") is None
        assert cache.get_price("tok_2") is None

    def test_is_stale_custom_max_age(self):
        cache = PriceCache()
        cache.update("tok_1", 0.45)
        cache._timestamps["tok_1"] = time.time() - 5.0
        assert cache.is_stale("tok_1", max_age_secs=10.0) is False
        assert cache.is_stale("tok_1", max_age_secs=3.0) is True

    def test_update_refreshes_timestamp(self):
        cache = PriceCache()
        cache.update("tok_1", 0.45)
        cache._timestamps["tok_1"] = time.time() - 60.0
        assert cache.is_stale("tok_1", max_age_secs=30.0) is True
        cache.update("tok_1", 0.46)
        assert cache.is_stale("tok_1", max_age_secs=30.0) is False


# ===========================================================================
# PriceWebSocket tests (mock-based)
# ===========================================================================


class TestPriceWebSocket:
    def test_init_default_url(self):
        cache = PriceCache()
        ws = PriceWebSocket(cache)
        assert ws._url.startswith("wss://")
        assert ws._cache is cache

    def test_init_custom_url(self):
        cache = PriceCache()
        ws = PriceWebSocket(cache, url="wss://custom.example.com/ws")
        assert ws._url == "wss://custom.example.com/ws"

    @pytest.mark.asyncio
    async def test_connect_sets_connected(self):
        cache = PriceCache()
        ws = PriceWebSocket(cache)
        mock_ws = AsyncMock()
        with patch("poly24h.websocket.price_ws.websockets") as mock_lib:
            mock_lib.connect = AsyncMock(return_value=mock_ws)
            await ws.connect()
            assert ws._connected is True

    @pytest.mark.asyncio
    async def test_subscribe_sends_message(self):
        cache = PriceCache()
        ws = PriceWebSocket(cache)
        mock_ws = AsyncMock()
        ws._ws = mock_ws
        ws._connected = True

        await ws.subscribe(["tok_1", "tok_2"])
        mock_ws.send.assert_called_once()
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert "tok_1" in sent["assets_ids"]
        assert "tok_2" in sent["assets_ids"]

    @pytest.mark.asyncio
    async def test_subscribe_not_connected(self):
        cache = PriceCache()
        ws = PriceWebSocket(cache)
        # subscribe 시도하지만 연결 안됨 → 에러 없이 무시
        await ws.subscribe(["tok_1"])

    @pytest.mark.asyncio
    async def test_unsubscribe_sends_message(self):
        cache = PriceCache()
        ws = PriceWebSocket(cache)
        mock_ws = AsyncMock()
        ws._ws = mock_ws
        ws._connected = True

        await ws.unsubscribe(["tok_1"])
        mock_ws.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_close(self):
        cache = PriceCache()
        ws = PriceWebSocket(cache)
        mock_ws = AsyncMock()
        ws._ws = mock_ws
        ws._connected = True

        await ws.close()
        mock_ws.close.assert_called_once()
        assert ws._connected is False

    @pytest.mark.asyncio
    async def test_close_not_connected(self):
        cache = PriceCache()
        ws = PriceWebSocket(cache)
        await ws.close()  # no error

    @pytest.mark.asyncio
    async def test_listen_updates_cache(self):
        """listen()이 price_change 메시지를 캐시에 업데이트."""
        cache = PriceCache()
        ws = PriceWebSocket(cache)

        msg = json.dumps({
            "event_type": "price_change",
            "asset_id": "tok_1",
            "price": "0.55",
        })

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[msg, asyncio.CancelledError()])
        ws._ws = mock_ws
        ws._connected = True

        with pytest.raises(asyncio.CancelledError):
            await ws.listen()

        assert cache.get_price("tok_1") == 0.55

    @pytest.mark.asyncio
    async def test_listen_handles_book_event(self):
        """listen()이 book 이벤트도 처리."""
        cache = PriceCache()
        ws = PriceWebSocket(cache)

        msg = json.dumps({
            "event_type": "book",
            "asset_id": "tok_2",
            "bids": [{"price": "0.44", "size": "100"}],
            "asks": [{"price": "0.46", "size": "100"}],
        })

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[msg, asyncio.CancelledError()])
        ws._ws = mock_ws
        ws._connected = True

        with pytest.raises(asyncio.CancelledError):
            await ws.listen()

        # book 이벤트에서 best ask 가격을 캐시
        assert cache.get_price("tok_2") == 0.46

    @pytest.mark.asyncio
    async def test_listen_ignores_unknown_event(self):
        """알 수 없는 이벤트 타입 무시."""
        cache = PriceCache()
        ws = PriceWebSocket(cache)

        msg = json.dumps({"event_type": "unknown", "data": "test"})

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[msg, asyncio.CancelledError()])
        ws._ws = mock_ws
        ws._connected = True

        with pytest.raises(asyncio.CancelledError):
            await ws.listen()

        assert cache.get_price("any") is None

    @pytest.mark.asyncio
    async def test_listen_handles_malformed_json(self):
        """잘못된 JSON 무시."""
        cache = PriceCache()
        ws = PriceWebSocket(cache)

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=["not json{{{", asyncio.CancelledError()])
        ws._ws = mock_ws
        ws._connected = True

        with pytest.raises(asyncio.CancelledError):
            await ws.listen()
        # No crash

    @pytest.mark.asyncio
    async def test_max_reconnect_attempts(self):
        """최대 재연결 횟수 속성."""
        cache = PriceCache()
        ws = PriceWebSocket(cache)
        assert ws._max_reconnect == 5
