"""F-024: Profitability Improvement Tests.

Phase 1: Odds API client + NBA fair value refactor
Phase 2: Kelly Criterion position sizing
Phase 3: Crypto directional betting disabled
Phase 4: Bankroll management strengthening
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# Phase 1: Odds API Client Tests
# =============================================================================


class TestAmericanToProb:
    """Test American odds → implied probability conversion."""

    def test_positive_odds(self):
        """Plus odds: +150 → 1/(1+1.5) = 0.40."""
        from poly24h.strategy.odds_api import american_to_prob

        assert abs(american_to_prob(150) - 0.40) < 0.001

    def test_negative_odds(self):
        """Minus odds: -200 → 200/(200+100) = 0.667."""
        from poly24h.strategy.odds_api import american_to_prob

        assert abs(american_to_prob(-200) - 0.6667) < 0.001

    def test_even_odds(self):
        """Even: +100 → 0.50."""
        from poly24h.strategy.odds_api import american_to_prob

        assert abs(american_to_prob(100) - 0.50) < 0.001

    def test_heavy_favorite(self):
        """-500 → 500/600 = 0.8333."""
        from poly24h.strategy.odds_api import american_to_prob

        assert abs(american_to_prob(-500) - 0.8333) < 0.001

    def test_heavy_underdog(self):
        """+500 → 1/6 = 0.1667."""
        from poly24h.strategy.odds_api import american_to_prob

        assert abs(american_to_prob(500) - 0.1667) < 0.001


class TestDevig:
    """Test overround removal (multiplicative devig)."""

    def test_symmetric_vig(self):
        """52% + 52% = 104% → 50% + 50%."""
        from poly24h.strategy.odds_api import devig

        a, b = devig(0.52, 0.52)
        assert abs(a - 0.50) < 0.001
        assert abs(b - 0.50) < 0.001

    def test_asymmetric_vig(self):
        """60% + 44% = 104% → devigged should sum to 100%."""
        from poly24h.strategy.odds_api import devig

        a, b = devig(0.60, 0.44)
        assert abs(a + b - 1.0) < 0.001
        assert a > b  # Favorite stays favorite

    def test_pinnacle_typical(self):
        """Pinnacle ~2% vig: 51% + 51% = 102% → 50% + 50%."""
        from poly24h.strategy.odds_api import devig

        a, b = devig(0.51, 0.51)
        assert abs(a - 0.50) < 0.001
        assert abs(b - 0.50) < 0.001

    def test_preserves_ratio(self):
        """Devig preserves the probability ratio."""
        from poly24h.strategy.odds_api import devig

        a, b = devig(0.70, 0.35)
        # ratio should be 2:1
        assert abs(a / b - 2.0) < 0.01


class TestOddsAPIClient:
    """Test The Odds API client fetch + cache."""

    @pytest.mark.asyncio
    async def test_fetch_nba_odds_returns_games(self):
        """fetch_nba_odds returns list of GameOdds."""
        from poly24h.strategy.odds_api import OddsAPIClient

        sample_response = [
            {
                "id": "game1",
                "sport_key": "basketball_nba",
                "home_team": "Los Angeles Lakers",
                "away_team": "Boston Celtics",
                "commence_time": "2026-02-12T03:00:00Z",
                "bookmakers": [
                    {
                        "key": "pinnacle",
                        "title": "Pinnacle",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Los Angeles Lakers", "price": -150},
                                    {"name": "Boston Celtics", "price": 130},
                                ],
                            },
                            {
                                "key": "spreads",
                                "outcomes": [
                                    {"name": "Los Angeles Lakers", "price": -110, "point": -3.5},
                                    {"name": "Boston Celtics", "price": -110, "point": 3.5},
                                ],
                            },
                            {
                                "key": "totals",
                                "outcomes": [
                                    {"name": "Over", "price": -110, "point": 220.5},
                                    {"name": "Under", "price": -110, "point": 220.5},
                                ],
                            },
                        ],
                    }
                ],
            }
        ]

        client = OddsAPIClient(api_key="test_key")
        with patch.object(client, "_fetch_json", new_callable=AsyncMock, return_value=sample_response):
            games = await client.fetch_nba_odds()

        assert len(games) == 1
        game = games[0]
        assert game.home_team == "Los Angeles Lakers"
        assert game.away_team == "Boston Celtics"
        assert game.h2h is not None
        assert game.spreads is not None
        assert game.totals is not None

    @pytest.mark.asyncio
    async def test_fetch_uses_cache(self):
        """Repeated calls within TTL use cached response."""
        from poly24h.strategy.odds_api import OddsAPIClient

        client = OddsAPIClient(api_key="test_key", cache_ttl=300)
        client._fetch_json = AsyncMock(return_value=[])

        await client.fetch_nba_odds()
        await client.fetch_nba_odds()

        # Should only call API once (second uses cache)
        assert client._fetch_json.call_count == 1

    @pytest.mark.asyncio
    async def test_fetch_handles_api_error(self):
        """API error returns empty list without crashing."""
        from poly24h.strategy.odds_api import OddsAPIClient

        client = OddsAPIClient(api_key="test_key")
        client._fetch_json = AsyncMock(side_effect=Exception("API error"))

        games = await client.fetch_nba_odds()
        assert games == []


class TestMatchToPolymarket:
    """Test sportsbook game ↔ Polymarket market matching."""

    def test_match_moneyline(self):
        """Match h2h game to 'Lakers vs. Celtics' moneyline market."""
        from poly24h.strategy.odds_api import OddsAPIClient, GameOdds, MarketOdds

        client = OddsAPIClient(api_key="test")
        game = GameOdds(
            game_id="g1",
            home_team="Los Angeles Lakers",
            away_team="Boston Celtics",
            commence_time="2026-02-12T03:00:00Z",
            h2h=MarketOdds(outcomes=[
                {"name": "Los Angeles Lakers", "price": -150},
                {"name": "Boston Celtics", "price": 130},
            ]),
            spreads=None,
            totals=None,
        )

        from poly24h.models.market import Market, MarketSource

        market = Market(
            id="m1",
            question="Lakers vs. Celtics",
            source=MarketSource.NBA,
            yes_token_id="t1", no_token_id="t2",
            yes_price=0.55, no_price=0.45,
            liquidity_usd=5000.0,
            end_date=datetime(2026, 2, 12, 6, tzinfo=timezone.utc),
            event_id="e1", event_title="Lakers vs. Celtics",
        )

        matches = client.match_to_polymarket(game, [market])
        assert len(matches) >= 1
        assert matches[0].market_id == "m1"
        assert matches[0].market_type == "moneyline"

    def test_match_spread(self):
        """Match spread line to 'Spread: Lakers (-3.5)' market."""
        from poly24h.strategy.odds_api import OddsAPIClient, GameOdds, MarketOdds

        client = OddsAPIClient(api_key="test")
        game = GameOdds(
            game_id="g1",
            home_team="Los Angeles Lakers",
            away_team="Boston Celtics",
            commence_time="2026-02-12T03:00:00Z",
            h2h=None,
            spreads=MarketOdds(outcomes=[
                {"name": "Los Angeles Lakers", "price": -110, "point": -3.5},
                {"name": "Boston Celtics", "price": -110, "point": 3.5},
            ]),
            totals=None,
        )

        from poly24h.models.market import Market, MarketSource

        market = Market(
            id="m2",
            question="Spread: Lakers (-3.5)",
            source=MarketSource.NBA,
            yes_token_id="t1", no_token_id="t2",
            yes_price=0.50, no_price=0.50,
            liquidity_usd=3000.0,
            end_date=datetime(2026, 2, 12, 6, tzinfo=timezone.utc),
            event_id="e1", event_title="Lakers vs. Celtics",
        )

        matches = client.match_to_polymarket(game, [market])
        assert len(matches) >= 1
        assert matches[0].market_type == "spread"

    def test_match_over_under(self):
        """Match totals line to 'Lakers vs. Celtics: O/U 220.5' market."""
        from poly24h.strategy.odds_api import OddsAPIClient, GameOdds, MarketOdds

        client = OddsAPIClient(api_key="test")
        game = GameOdds(
            game_id="g1",
            home_team="Los Angeles Lakers",
            away_team="Boston Celtics",
            commence_time="2026-02-12T03:00:00Z",
            h2h=None,
            spreads=None,
            totals=MarketOdds(outcomes=[
                {"name": "Over", "price": -110, "point": 220.5},
                {"name": "Under", "price": -110, "point": 220.5},
            ]),
        )

        from poly24h.models.market import Market, MarketSource

        market = Market(
            id="m3",
            question="Lakers vs. Celtics: O/U 220.5",
            source=MarketSource.NBA,
            yes_token_id="t1", no_token_id="t2",
            yes_price=0.48, no_price=0.52,
            liquidity_usd=4000.0,
            end_date=datetime(2026, 2, 12, 6, tzinfo=timezone.utc),
            event_id="e1", event_title="Lakers vs. Celtics",
        )

        matches = client.match_to_polymarket(game, [market])
        assert len(matches) >= 1
        assert matches[0].market_type == "totals"

    def test_no_match_returns_empty(self):
        """No matching game returns empty list."""
        from poly24h.strategy.odds_api import OddsAPIClient, GameOdds

        client = OddsAPIClient(api_key="test")
        game = GameOdds(
            game_id="g1",
            home_team="Chicago Bulls",
            away_team="Miami Heat",
            commence_time="2026-02-12T03:00:00Z",
            h2h=None, spreads=None, totals=None,
        )

        from poly24h.models.market import Market, MarketSource

        market = Market(
            id="m1",
            question="Lakers vs. Celtics",
            source=MarketSource.NBA,
            yes_token_id="t1", no_token_id="t2",
            yes_price=0.50, no_price=0.50,
            liquidity_usd=5000.0,
            end_date=datetime(2026, 2, 12, 6, tzinfo=timezone.utc),
            event_id="e1", event_title="Lakers vs. Celtics",
        )

        matches = client.match_to_polymarket(game, [market])
        assert len(matches) == 0


class TestEdgeCalculation:
    """Test edge = fair_prob - market_price."""

    def test_positive_edge(self):
        """fair=0.55, price=0.48 → edge=0.07."""
        from poly24h.strategy.odds_api import calculate_edge

        assert abs(calculate_edge(0.48, 0.55) - 0.07) < 0.001

    def test_negative_edge(self):
        """fair=0.45, price=0.48 → edge=-0.03."""
        from poly24h.strategy.odds_api import calculate_edge

        assert abs(calculate_edge(0.48, 0.45) - (-0.03)) < 0.001

    def test_zero_edge(self):
        """fair=0.50, price=0.50 → edge=0."""
        from poly24h.strategy.odds_api import calculate_edge

        assert abs(calculate_edge(0.50, 0.50)) < 0.001

    def test_min_edge_filter(self):
        """Edge below 3% should be filtered."""
        from poly24h.strategy.odds_api import calculate_edge

        edge = calculate_edge(0.48, 0.50)  # 2% edge
        min_edge = 0.03
        assert edge < min_edge


# =============================================================================
# Phase 2: Kelly Criterion Tests
# =============================================================================


class TestKellyCriterion:
    """Test Quarter-Kelly position sizing."""

    def test_kelly_small_edge(self):
        """edge=0.03, price=0.45, bankroll=$3000 → ~$16.4."""
        from poly24h.position_manager import PositionManager

        pm = PositionManager(bankroll=3000.0, max_per_market=300.0)
        size = pm.calculate_kelly_size(edge=0.03, market_price=0.45)
        # payout_odds = 0.55/0.45 = 1.222
        # kelly = 0.03/1.222 = 0.02454
        # quarter = 0.02454 * 0.25 = 0.006136
        # size = 3000 * 0.006136 = 18.4 (approximate)
        assert 10.0 <= size <= 25.0

    def test_kelly_large_edge(self):
        """edge=0.10, price=0.40, bankroll=$3000 → ~$50."""
        from poly24h.position_manager import PositionManager

        pm = PositionManager(bankroll=3000.0, max_per_market=300.0)
        size = pm.calculate_kelly_size(edge=0.10, market_price=0.40)
        # payout_odds = 0.60/0.40 = 1.50
        # kelly = 0.10/1.50 = 0.0667
        # quarter = 0.0667 * 0.25 = 0.01667
        # size = 3000 * 0.01667 = 50.0
        assert 40.0 <= size <= 60.0

    def test_kelly_max_cap(self):
        """Very large edge still capped at $300."""
        from poly24h.position_manager import PositionManager

        pm = PositionManager(bankroll=3000.0, max_per_market=300.0)
        size = pm.calculate_kelly_size(edge=0.50, market_price=0.30)
        assert size <= 300.0

    def test_kelly_single_position_cap(self):
        """Single position capped at 10% of bankroll."""
        from poly24h.position_manager import PositionManager

        pm = PositionManager(bankroll=3000.0, max_per_market=300.0)
        size = pm.calculate_kelly_size(edge=0.50, market_price=0.30)
        assert size <= 3000.0 * 0.10  # $300

    def test_kelly_min_floor(self):
        """Very small edge → returns minimum $10 or 0 if below threshold."""
        from poly24h.position_manager import PositionManager

        pm = PositionManager(bankroll=3000.0, max_per_market=300.0)
        size = pm.calculate_kelly_size(edge=0.005, market_price=0.50)
        # kelly = 0.005/1.0 = 0.005, quarter = 0.00125
        # size = 3000 * 0.00125 = $3.75 < $10 min → 0.0
        assert size == 0.0

    def test_kelly_zero_edge(self):
        """Zero edge → 0 size."""
        from poly24h.position_manager import PositionManager

        pm = PositionManager(bankroll=3000.0, max_per_market=300.0)
        size = pm.calculate_kelly_size(edge=0.0, market_price=0.50)
        assert size == 0.0

    def test_kelly_negative_edge(self):
        """Negative edge → 0 size."""
        from poly24h.position_manager import PositionManager

        pm = PositionManager(bankroll=3000.0, max_per_market=300.0)
        size = pm.calculate_kelly_size(edge=-0.05, market_price=0.50)
        assert size == 0.0


# =============================================================================
# Phase 3: Crypto Directional Disable Tests
# =============================================================================


class TestCryptoDisable:
    """Test that crypto directional betting is skipped."""

    def test_crypto_source_skipped(self):
        """HOURLY_CRYPTO markets should be skipped for directional entry."""
        from poly24h.strategy.odds_api import should_skip_crypto_directional
        from poly24h.models.market import MarketSource

        assert should_skip_crypto_directional(MarketSource.HOURLY_CRYPTO) is True

    def test_nba_not_skipped(self):
        """NBA markets should NOT be skipped."""
        from poly24h.strategy.odds_api import should_skip_crypto_directional
        from poly24h.models.market import MarketSource

        assert should_skip_crypto_directional(MarketSource.NBA) is False


# =============================================================================
# Phase 4: Bankroll Management Tests
# =============================================================================


class TestBankrollManagement:
    """Test bankroll protection rules."""

    def test_bankroll_reserve_protection(self):
        """Cannot invest below 30% reserve of initial bankroll."""
        from poly24h.position_manager import PositionManager

        pm = PositionManager(bankroll=3000.0, max_per_market=300.0)
        # Simulate spending down to near reserve
        pm.bankroll = 1000.0  # Reserve = 3000 * 0.30 = $900
        # Trying to enter $200 would bring bankroll to $800 < $900
        size = pm.calculate_kelly_size(edge=0.10, market_price=0.40)
        # Max available = bankroll - reserve = 1000 - 900 = $100
        assert size <= 100.0

    def test_bankroll_below_reserve_returns_zero(self):
        """If bankroll already at/below reserve, size should be 0."""
        from poly24h.position_manager import PositionManager

        pm = PositionManager(bankroll=3000.0, max_per_market=300.0)
        pm.bankroll = 890.0  # Below reserve of $900
        size = pm.calculate_kelly_size(edge=0.10, market_price=0.40)
        assert size == 0.0

    def test_cycle_budget_enforcement(self):
        """Cycle budget (30% of bankroll) limits total per-cycle investment."""
        from poly24h.position_manager import PositionManager

        pm = PositionManager(bankroll=3000.0, max_per_market=300.0)
        # Cycle budget = 3000 * 0.30 = $900
        # Simulate having spent $850 already in this cycle
        pm._cycle_invested = 850.0
        # Remaining budget = $900 - $850 = $50
        size = pm.calculate_kelly_size(edge=0.10, market_price=0.40)
        assert size <= 50.0

    def test_cycle_budget_exceeded_returns_zero(self):
        """If cycle budget fully used, returns 0."""
        from poly24h.position_manager import PositionManager

        pm = PositionManager(bankroll=3000.0, max_per_market=300.0)
        pm._cycle_invested = 910.0  # > $900 budget
        size = pm.calculate_kelly_size(edge=0.10, market_price=0.40)
        assert size == 0.0
