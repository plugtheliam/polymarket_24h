"""Integration tests for Fair Value Model in EventDrivenLoop (F-021)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from poly24h.models.market import Market, MarketSource
from poly24h.scheduler.event_scheduler import EventDrivenLoop, MarketOpenSchedule
from poly24h.strategy.crypto_fair_value import CryptoFairValueCalculator
from poly24h.strategy.nba_fair_value import NBAFairValueCalculator


class TestEventDrivenLoopFairValue:
    """Tests for F-021 fair value integration in EventDrivenLoop."""

    def _make_market(
        self,
        market_id: str,
        question: str,
        source: MarketSource,
        yes_price: float = 0.50,
        no_price: float = 0.50,
    ) -> Market:
        """Create a test market."""
        return Market(
            id=market_id,
            question=question,
            source=source,
            yes_token_id=f"yes_{market_id}",
            no_token_id=f"no_{market_id}",
            yes_price=yes_price,
            no_price=no_price,
            liquidity_usd=10000.0,
            end_date=datetime(2025, 2, 8, tzinfo=timezone.utc),
            event_id="event_1",
            event_title="Test Event",
        )

    def test_loop_has_fair_value_calculators(self) -> None:
        """EventDrivenLoop should have fair value calculators initialized."""
        schedule = MagicMock(spec=MarketOpenSchedule)
        preparer = MagicMock()
        poller = MagicMock()
        alerter = MagicMock()

        loop = EventDrivenLoop(schedule, preparer, poller, alerter)

        assert hasattr(loop, "_nba_fair_value")
        assert hasattr(loop, "_crypto_fair_value")
        assert hasattr(loop, "_market_fair_values")
        assert isinstance(loop._nba_fair_value, NBAFairValueCalculator)
        assert isinstance(loop._crypto_fair_value, CryptoFairValueCalculator)

    @pytest.mark.asyncio
    async def test_calculate_crypto_fair_value(self) -> None:
        """Test crypto fair value calculation with mocked Binance data."""
        schedule = MagicMock(spec=MarketOpenSchedule)
        preparer = MagicMock()
        poller = MagicMock()
        alerter = MagicMock()

        loop = EventDrivenLoop(schedule, preparer, poller, alerter)

        market = self._make_market(
            "btc_up",
            "Will BTC go up in the next hour?",
            MarketSource.HOURLY_CRYPTO,
        )

        # Mock Binance OHLCV response (downtrend → oversold)
        mock_ohlcv = [{"close": 50000 - i * 100} for i in range(24)]
        with patch.object(
            loop._crypto_fair_value, "fetch_binance_ohlcv", return_value=mock_ohlcv
        ):
            fair_prob = await loop._calculate_crypto_fair_value(market)

        # Downtrend → oversold → expect UP probability > 0.50
        assert fair_prob > 0.50

    @pytest.mark.asyncio
    async def test_calculate_nba_fair_value(self) -> None:
        """Test NBA fair value calculation."""
        schedule = MagicMock(spec=MarketOpenSchedule)
        preparer = MagicMock()
        poller = MagicMock()
        alerter = MagicMock()

        loop = EventDrivenLoop(schedule, preparer, poller, alerter)

        market = self._make_market(
            "lakers_win",
            "Will Lakers beat Celtics?",
            MarketSource.NBA,
        )

        fair_prob = await loop._calculate_nba_fair_value(market)

        # Lakers vs Celtics: Both are good teams, probability should be reasonable
        assert 0.30 <= fair_prob <= 0.70

    @pytest.mark.asyncio
    async def test_calculate_fair_values_populates_dict(self) -> None:
        """Test that _calculate_fair_values populates _market_fair_values."""
        schedule = MagicMock(spec=MarketOpenSchedule)
        preparer = MagicMock()
        poller = MagicMock()
        alerter = MagicMock()

        loop = EventDrivenLoop(schedule, preparer, poller, alerter)

        markets = [
            self._make_market("m1", "Will BTC go up?", MarketSource.HOURLY_CRYPTO),
            self._make_market("m2", "Will Lakers win?", MarketSource.NBA),
            self._make_market("m3", "Some soccer match", MarketSource.SOCCER),
        ]

        # Mock Binance call
        mock_ohlcv = [{"close": 50000 + i * 10} for i in range(24)]
        with patch.object(
            loop._crypto_fair_value, "fetch_binance_ohlcv", return_value=mock_ohlcv
        ):
            await loop._calculate_fair_values(markets)

        assert len(loop._market_fair_values) == 3
        assert "m1" in loop._market_fair_values
        assert "m2" in loop._market_fair_values
        assert "m3" in loop._market_fair_values

        # Soccer uses default 0.50
        assert loop._market_fair_values["m3"] == 0.50

    def test_is_market_undervalued_crypto(self) -> None:
        """Test _is_market_undervalued for crypto markets."""
        schedule = MagicMock(spec=MarketOpenSchedule)
        preparer = MagicMock()
        poller = MagicMock()
        alerter = MagicMock()

        loop = EventDrivenLoop(schedule, preparer, poller, alerter)

        market = self._make_market("btc_up", "BTC up?", MarketSource.HOURLY_CRYPTO)

        # Set fair value to 0.65 (oversold condition)
        loop._market_fair_values["btc_up"] = 0.65

        # YES at $0.40 should be undervalued (0.40 < 0.65 - 0.05 = 0.60)
        assert loop._is_market_undervalued(market, "YES", 0.40, margin=0.05) is True

        # YES at $0.62 should NOT be undervalued (0.62 > 0.60)
        assert loop._is_market_undervalued(market, "YES", 0.62, margin=0.05) is False

        # NO at $0.25 should be undervalued (fair NO prob = 0.35, 0.25 < 0.35 - 0.05 = 0.30)
        assert loop._is_market_undervalued(market, "NO", 0.25, margin=0.05) is True

    def test_is_market_undervalued_nba(self) -> None:
        """Test _is_market_undervalued for NBA markets."""
        schedule = MagicMock(spec=MarketOpenSchedule)
        preparer = MagicMock()
        poller = MagicMock()
        alerter = MagicMock()

        loop = EventDrivenLoop(schedule, preparer, poller, alerter)

        market = self._make_market("lakers_win", "Lakers win?", MarketSource.NBA)

        # Set Lakers fair value to 0.60
        loop._market_fair_values["lakers_win"] = 0.60

        # YES at $0.48 should be undervalued (0.48 < 0.60 - 0.05 = 0.55)
        assert loop._is_market_undervalued(market, "YES", 0.48, margin=0.05) is True

        # YES at $0.58 should NOT be undervalued (0.58 > 0.55)
        assert loop._is_market_undervalued(market, "YES", 0.58, margin=0.05) is False

    def test_is_market_undervalued_unknown_source(self) -> None:
        """Test _is_market_undervalued with unknown source uses threshold fallback."""
        schedule = MagicMock(spec=MarketOpenSchedule)
        preparer = MagicMock()
        poller = MagicMock()
        alerter = MagicMock()

        loop = EventDrivenLoop(schedule, preparer, poller, alerter)

        market = self._make_market("soccer_match", "Team wins?", MarketSource.SOCCER)
        loop._market_fair_values["soccer_match"] = 0.50

        # $0.40 < 0.50 - 0.05 = 0.45 → undervalued
        assert loop._is_market_undervalued(market, "YES", 0.40, margin=0.05) is True

        # $0.48 > 0.45 → NOT undervalued
        assert loop._is_market_undervalued(market, "YES", 0.48, margin=0.05) is False


class TestCryptoFairValueExtraction:
    """Tests for crypto asset extraction from market questions."""

    @pytest.mark.asyncio
    async def test_extract_btc_from_question(self) -> None:
        """Test BTC extraction from various question formats."""
        schedule = MagicMock(spec=MarketOpenSchedule)
        loop = EventDrivenLoop(schedule, MagicMock(), MagicMock(), MagicMock())

        # Mock the fetch to return empty (will default to 0.50)
        with patch.object(
            loop._crypto_fair_value, "fetch_binance_ohlcv", return_value=[]
        ):
            # Test various question formats
            questions = [
                "Will BTC go up in the next hour?",
                "Will Bitcoin (BTC) close higher?",
                "BTC price movement prediction",
            ]

            for q in questions:
                market = Market(
                    id="test",
                    question=q,
                    source=MarketSource.HOURLY_CRYPTO,
                    yes_token_id="yes",
                    no_token_id="no",
                    yes_price=0.50,
                    no_price=0.50,
                    liquidity_usd=10000,
                    end_date=datetime(2025, 2, 8, tzinfo=timezone.utc),
                    event_id="e1",
                    event_title="Test",
                )
                # Should not crash, returns default 0.50
                result = await loop._calculate_crypto_fair_value(market)
                assert isinstance(result, float)


class TestNBATeamExtraction:
    """Tests for NBA team extraction from market questions."""

    @pytest.mark.asyncio
    async def test_extract_teams_from_question(self) -> None:
        """Test team extraction from various question formats."""
        schedule = MagicMock(spec=MarketOpenSchedule)
        loop = EventDrivenLoop(schedule, MagicMock(), MagicMock(), MagicMock())

        test_cases = [
            ("Will Lakers beat Celtics?", 0.40, 0.60),  # Lakers vs Celtics
            ("Bucks to win against Heat?", 0.50, 0.60),  # Roughly expected
            ("Thunder vs Pistons game", 0.60, 0.80),  # Thunder favored
        ]

        for question, min_prob, max_prob in test_cases:
            market = Market(
                id="test",
                question=question,
                source=MarketSource.NBA,
                yes_token_id="yes",
                no_token_id="no",
                yes_price=0.50,
                no_price=0.50,
                liquidity_usd=10000,
                end_date=datetime(2025, 2, 8, tzinfo=timezone.utc),
                event_id="e1",
                event_title="Test",
            )
            result = await loop._calculate_nba_fair_value(market)
            assert min_prob <= result <= max_prob, f"Failed for: {question}"
