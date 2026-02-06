"""Tests for F-002: Gamma API Client."""

from __future__ import annotations

import re

import pytest
from aioresponses import aioresponses

from poly24h.discovery.gamma_client import GammaClient

GAMMA_URL = "https://gamma-api.polymarket.com"
EVENTS_PATTERN = re.compile(r"^https://gamma-api\.polymarket\.com/events\b")
BOOK_PATTERN = re.compile(r"^https://gamma-api\.polymarket\.com/book\b")


class TestGammaClientContextManager:
    async def test_async_context_manager(self):
        """GammaClient should be usable as async context manager."""
        async with GammaClient() as client:
            assert client is not None
            assert client._session is not None
        # After exit, session should be closed
        assert client._session is None or client._session.closed

    async def test_manual_close(self):
        """GammaClient can be opened and closed manually."""
        client = GammaClient()
        await client.open()
        assert client._session is not None
        await client.close()
        assert client._session is None or client._session.closed


class TestFetchEvents:
    async def test_fetch_events_success(self):
        """Should return list of events for a given tag."""
        mock_events = [
            {
                "id": "evt_1",
                "title": "BTC 1 hour market",
                "markets": [{"id": "mkt_1", "question": "BTC above 100k?"}],
            }
        ]
        with aioresponses() as m:
            m.get(EVENTS_PATTERN, payload=mock_events)
            async with GammaClient() as client:
                events = await client.fetch_events(tag="crypto")
                assert len(events) == 1
                assert events[0]["id"] == "evt_1"

    async def test_fetch_events_with_limit(self):
        """Should pass limit parameter."""
        with aioresponses() as m:
            m.get(EVENTS_PATTERN, payload=[])
            async with GammaClient() as client:
                events = await client.fetch_events(tag="nba", limit=50)
                assert events == []

    async def test_fetch_events_api_error_returns_empty(self):
        """Should return empty list on HTTP error (no crash)."""
        with aioresponses() as m:
            # Need enough mocks for all retries
            for _ in range(3):
                m.get(EVENTS_PATTERN, status=500)
            async with GammaClient() as client:
                events = await client.fetch_events(tag="crypto")
                assert events == []

    async def test_fetch_events_rate_limit_429(self):
        """Should handle 429 rate limit gracefully."""
        with aioresponses() as m:
            for _ in range(3):
                m.get(EVENTS_PATTERN, status=429)
            async with GammaClient() as client:
                events = await client.fetch_events(tag="crypto")
                assert events == []

    async def test_fetch_events_timeout(self):
        """Should return empty list on timeout."""
        with aioresponses() as m:
            for _ in range(3):
                m.get(EVENTS_PATTERN, exception=TimeoutError())
            async with GammaClient() as client:
                events = await client.fetch_events(tag="crypto")
                assert events == []

    async def test_fetch_events_connection_error(self):
        """Should return empty list on connection error."""
        import aiohttp

        with aioresponses() as m:
            for _ in range(3):
                m.get(
                    EVENTS_PATTERN,
                    exception=aiohttp.ClientConnectionError("Connection refused"),
                )
            async with GammaClient() as client:
                events = await client.fetch_events(tag="crypto")
                assert events == []

    async def test_fetch_events_non_list_response(self):
        """Should return empty list if response isn't a list."""
        with aioresponses() as m:
            for _ in range(3):
                m.get(EVENTS_PATTERN, payload={"error": "bad"})
            async with GammaClient() as client:
                events = await client.fetch_events(tag="crypto")
                assert events == []


class TestFetchOrderbook:
    async def test_fetch_orderbook_success(self):
        """Should return orderbook dict with bids and asks."""
        mock_book = {
            "bids": [{"price": "0.45", "size": "100"}],
            "asks": [{"price": "0.48", "size": "200"}],
        }
        with aioresponses() as m:
            m.get(BOOK_PATTERN, payload=mock_book)
            async with GammaClient() as client:
                book = await client.fetch_orderbook(token_id="tok_123")
                assert book is not None
                assert "bids" in book
                assert "asks" in book

    async def test_fetch_orderbook_error(self):
        """Should return None on error."""
        with aioresponses() as m:
            for _ in range(3):
                m.get(BOOK_PATTERN, status=500)
            async with GammaClient() as client:
                book = await client.fetch_orderbook(token_id="tok_123")
                assert book is None

    async def test_best_ask_from_orderbook(self):
        """best_ask should return lowest ask price."""
        mock_book = {
            "bids": [],
            "asks": [
                {"price": "0.50", "size": "100"},
                {"price": "0.48", "size": "200"},
            ],
        }
        with aioresponses() as m:
            m.get(BOOK_PATTERN, payload=mock_book)
            async with GammaClient() as client:
                book = await client.fetch_orderbook(token_id="tok_123")
                best = client.best_ask(book)
                assert best == pytest.approx(0.48)

    async def test_best_ask_empty_asks(self):
        """best_ask should return None for empty asks."""
        async with GammaClient() as client:
            result = client.best_ask({"bids": [], "asks": []})
            assert result is None

    async def test_best_ask_none_book(self):
        """best_ask should return None for None book."""
        async with GammaClient() as client:
            result = client.best_ask(None)
            assert result is None


class TestRetry:
    async def test_retry_on_failure_then_success(self):
        """Should retry and succeed on second attempt."""
        mock_events = [{"id": "evt_1", "title": "ok", "markets": []}]
        with aioresponses() as m:
            # First call fails, second succeeds
            m.get(EVENTS_PATTERN, status=500)
            m.get(EVENTS_PATTERN, payload=mock_events)
            async with GammaClient(max_retries=2) as client:
                events = await client.fetch_events(tag="crypto")
                assert len(events) == 1

    async def test_retry_all_fail(self):
        """Should return empty after all retries exhausted."""
        with aioresponses() as m:
            for _ in range(3):
                m.get(EVENTS_PATTERN, status=500)
            async with GammaClient(max_retries=3) as client:
                events = await client.fetch_events(tag="crypto")
                assert events == []
