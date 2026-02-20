"""F-032a: Spread/O-U fair value block tests.

Kent Beck TDD — Red phase first.
Sportsbook devig odds for spread/O-U have no correlation to Polymarket prices.
These market types must return None for fair value.
"""

from unittest.mock import MagicMock

import pytest

from poly24h.strategy.odds_api import OddsAPIClient, GameOdds, MarketOdds


def _make_market(question: str, market_id: str = "123"):
    """Create a minimal mock market for testing."""
    m = MagicMock()
    m.id = market_id
    m.question = question
    return m


def _make_game_with_all_markets():
    """Create a GameOdds with h2h, spreads, and totals."""
    return GameOdds(
        game_id="game1",
        home_team="Houston Rockets",
        away_team="Charlotte Hornets",
        commence_time="2026-02-20T00:00:00Z",
        h2h=MarketOdds(outcomes=[
            {"name": "Houston Rockets", "price": -150},
            {"name": "Charlotte Hornets", "price": +130},
        ]),
        spreads=MarketOdds(outcomes=[
            {"name": "Houston Rockets", "price": -110, "point": -3.5},
            {"name": "Charlotte Hornets", "price": -110, "point": 3.5},
        ]),
        totals=MarketOdds(outcomes=[
            {"name": "Over", "price": -110, "point": 220.5},
            {"name": "Under", "price": -110, "point": 220.5},
        ]),
    )


class TestSpreadBlock:
    """Spread markets must return None fair value."""

    def test_spread_returns_none_fair_value(self):
        """Spread market → _get_fair_prob_generic returns None."""
        client = OddsAPIClient(api_key="test")
        market = _make_market("Spread: Rockets (-3.5)")
        game = _make_game_with_all_markets()

        # Use a sport config mock (2-way sport like NBA)
        sport_config = MagicMock()
        sport_config.is_three_way = False
        sport_config.team_names = {
            "rockets": ["houston rockets", "rockets", "houston"],
            "hornets": ["charlotte hornets", "hornets", "charlotte"],
        }

        result = client._get_fair_prob_generic(market, [game], sport_config)
        assert result is None, f"Spread should return None, got {result}"


class TestOUBlock:
    """O/U (totals) markets must return None fair value."""

    def test_ou_returns_none_fair_value(self):
        """O/U market → _get_fair_prob_generic returns None."""
        client = OddsAPIClient(api_key="test")
        market = _make_market("Rockets vs. Hornets: O/U 220.5")
        game = _make_game_with_all_markets()

        sport_config = MagicMock()
        sport_config.is_three_way = False
        sport_config.team_names = {
            "rockets": ["houston rockets", "rockets", "houston"],
            "hornets": ["charlotte hornets", "hornets", "charlotte"],
        }

        result = client._get_fair_prob_generic(market, [game], sport_config)
        assert result is None, f"O/U should return None, got {result}"


class TestMoneylineStillWorks:
    """Moneyline markets must continue to return fair values."""

    def test_moneyline_still_returns_fair_value(self):
        """Moneyline market → still returns a valid fair prob."""
        client = OddsAPIClient(api_key="test")
        market = _make_market("Rockets vs. Hornets")
        game = _make_game_with_all_markets()

        sport_config = MagicMock()
        sport_config.is_three_way = False
        sport_config.team_names = {
            "rockets": ["houston rockets", "rockets", "houston"],
            "hornets": ["charlotte hornets", "hornets", "charlotte"],
        }

        result = client._get_fair_prob_generic(market, [game], sport_config)
        assert result is not None, "Moneyline should return a fair prob"
        assert 0.0 < result < 1.0, f"Fair prob should be between 0 and 1, got {result}"
