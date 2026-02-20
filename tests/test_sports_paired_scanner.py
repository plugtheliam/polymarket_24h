"""F-032b: Sports Paired Scanner TDD tests.

Kent Beck TDD — Red phase first.
SportsPairedScanner finds YES+NO CPP < threshold arbitrage in sports markets.
No fair value needed — pure market structure arbitrage.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_market(
    market_id: str = "123",
    question: str = "Rockets vs. Hornets",
    yes_token: str = "yes_token_123",
    no_token: str = "no_token_123",
):
    """Create a minimal mock market."""
    m = MagicMock()
    m.id = market_id
    m.question = question
    m.yes_token_id = yes_token
    m.no_token_id = no_token
    m.end_date = "2026-02-20T00:00:00+00:00"
    m.event_id = "event_1"
    return m


class TestCppBelowThreshold:
    """Detect CPP < threshold as opportunity."""

    @pytest.mark.asyncio
    async def test_cpp_below_threshold_detected(self):
        """YES@0.45 + NO@0.48 = CPP 0.93 < 0.96 → opportunity detected."""
        from poly24h.strategy.sports_paired_scanner import SportsPairedScanner

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_best_asks.return_value = (0.45, 0.48)

        mock_pm = MagicMock()
        mock_pm.can_enter.return_value = True

        scanner = SportsPairedScanner(
            orderbook_fetcher=mock_fetcher,
            position_manager=mock_pm,
            cpp_threshold=0.96,
        )

        market = _make_market()
        opportunities = await scanner.scan_markets([market])

        assert len(opportunities) == 1
        opp = opportunities[0]
        assert opp["market_id"] == "123"
        assert abs(opp["cpp"] - 0.93) < 0.01
        assert opp["yes_ask"] == 0.45
        assert opp["no_ask"] == 0.48


class TestCppAboveThreshold:
    """Skip when CPP >= threshold."""

    @pytest.mark.asyncio
    async def test_cpp_above_threshold_skipped(self):
        """YES@0.50 + NO@0.50 = CPP 1.00 >= 0.96 → no opportunity."""
        from poly24h.strategy.sports_paired_scanner import SportsPairedScanner

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_best_asks.return_value = (0.50, 0.50)

        mock_pm = MagicMock()
        mock_pm.can_enter.return_value = True

        scanner = SportsPairedScanner(
            orderbook_fetcher=mock_fetcher,
            position_manager=mock_pm,
            cpp_threshold=0.96,
        )

        market = _make_market()
        opportunities = await scanner.scan_markets([market])

        assert len(opportunities) == 0


class TestInsufficientLiquidity:
    """Skip when orderbook returns None (no liquidity)."""

    @pytest.mark.asyncio
    async def test_insufficient_liquidity_skipped(self):
        """Orderbook returns None for one side → skip."""
        from poly24h.strategy.sports_paired_scanner import SportsPairedScanner

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_best_asks.return_value = (0.45, None)

        mock_pm = MagicMock()
        mock_pm.can_enter.return_value = True

        scanner = SportsPairedScanner(
            orderbook_fetcher=mock_fetcher,
            position_manager=mock_pm,
            cpp_threshold=0.96,
        )

        market = _make_market()
        opportunities = await scanner.scan_markets([market])

        assert len(opportunities) == 0
