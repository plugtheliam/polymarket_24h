"""F-032b/d: Sports Paired Scanner TDD tests.

Kent Beck TDD — Red phase first.
SportsPairedScanner finds YES+NO CPP < threshold arbitrage in sports markets.
No fair value needed — pure market structure arbitrage.

F-032d: run_forever loop, 24H filter, paired position tracking.
"""

import asyncio
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_market(
    market_id: str = "123",
    question: str = "Rockets vs. Hornets",
    yes_token: str = "yes_token_123",
    no_token: str = "no_token_123",
    end_date=None,
):
    """Create a minimal mock market."""
    m = MagicMock()
    m.id = market_id
    m.question = question
    m.yes_token_id = yes_token
    m.no_token_id = no_token
    m.end_date = end_date or (datetime.now(timezone.utc) + timedelta(hours=12))
    m.event_id = "event_1"
    m.source = MagicMock()
    m.source.value = "nba"
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


# =====================================================================
# F-032d: 24H filter, run loop, paired position tracking
# =====================================================================


class TestScanner24HFilter:
    """Only scan markets settling within 24 hours."""

    @pytest.mark.asyncio
    async def test_scanner_24h_filter(self):
        """Market settling in 12H → included. Market settling in 48H → excluded."""
        from poly24h.strategy.sports_paired_scanner import SportsPairedScanner

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_best_asks.return_value = (0.45, 0.48)

        mock_pm = MagicMock()
        mock_pm.can_enter.return_value = True

        scanner = SportsPairedScanner(
            orderbook_fetcher=mock_fetcher,
            position_manager=mock_pm,
            cpp_threshold=0.96,
            max_hours_to_settle=24,
        )

        now = datetime.now(timezone.utc)
        market_12h = _make_market(
            market_id="m1", end_date=now + timedelta(hours=12),
        )
        market_48h = _make_market(
            market_id="m2", end_date=now + timedelta(hours=48),
        )
        market_30min = _make_market(
            market_id="m3", end_date=now + timedelta(minutes=30),
        )

        opportunities = await scanner.scan_markets([market_12h, market_48h, market_30min])

        # Only the 12H market should be scanned (48H too far, 30min too close)
        ids = [o["market_id"] for o in opportunities]
        assert "m1" in ids, "12H market should be included"
        assert "m2" not in ids, "48H market should be excluded"
        assert "m3" not in ids, "30min market should be excluded (< 1H buffer)"


class TestScannerRunLoop:
    """Scanner has run_forever() that discovers and scans markets."""

    @pytest.mark.asyncio
    async def test_scanner_run_loop(self):
        """run_forever() calls discover + scan on each cycle."""
        from poly24h.strategy.sports_paired_scanner import SportsPairedScanner

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_best_asks.return_value = (0.45, 0.48)

        mock_pm = MagicMock()
        mock_pm.can_enter.return_value = True
        mock_pm.reset_cycle_entries = MagicMock()

        mock_market_scanner = AsyncMock()
        now = datetime.now(timezone.utc)
        mock_market_scanner.discover_sport_markets.return_value = [
            _make_market(market_id="m1", end_date=now + timedelta(hours=8)),
        ]

        scanner = SportsPairedScanner(
            orderbook_fetcher=mock_fetcher,
            position_manager=mock_pm,
            cpp_threshold=0.96,
            max_hours_to_settle=24,
            market_scanner=mock_market_scanner,
            sport_configs=[MagicMock()],
            scan_interval=0.01,
        )

        # Run for a brief period then cancel
        task = asyncio.create_task(scanner.run_forever())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have called discover at least once
        assert mock_market_scanner.discover_sport_markets.call_count >= 1


class TestPairedPositionTracking:
    """Track YES+NO paired entries separately from PositionManager."""

    @pytest.mark.asyncio
    async def test_paired_position_tracking(self):
        """Enter paired position records both YES and NO as one record."""
        from poly24h.strategy.sports_paired_scanner import SportsPairedScanner

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_best_asks.return_value = (0.45, 0.48)

        mock_pm = MagicMock()
        mock_pm.can_enter.return_value = True
        mock_pm.bankroll = 5000.0
        mock_pm.max_per_market = 50.0

        with tempfile.TemporaryDirectory() as tmpdir:
            scanner = SportsPairedScanner(
                orderbook_fetcher=mock_fetcher,
                position_manager=mock_pm,
                cpp_threshold=0.96,
                paper_trade_dir=tmpdir,
            )

            market = _make_market(market_id="m1")
            opps = await scanner.scan_markets([market])

            assert len(opps) == 1

            # Enter paired position
            result = scanner.enter_paired_position(opps[0], size_usd=20.0)

            assert result is not None
            assert result["market_id"] == "m1"
            assert result["yes_cost"] > 0
            assert result["no_cost"] > 0
            assert result["guaranteed_profit"] > 0

            # Should be tracked internally (not via PositionManager)
            assert "m1" in scanner.paired_positions
