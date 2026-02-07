"""Tests for NBA Fair Value Calculator (F-021).

TDD Red Phase: Write tests before implementation.
"""

from __future__ import annotations

import pytest

from poly24h.strategy.nba_fair_value import NBAFairValueCalculator


class TestNBAFairValueCalculator:
    """Tests for NBAFairValueCalculator."""

    def test_calculate_fair_probability_lakers_vs_celtics(self) -> None:
        """Lakers 60% win rate vs Celtics 40% → Lakers fair prob = 0.60."""
        calc = NBAFairValueCalculator()
        
        # Lakers 60%, Celtics 40%
        lakers_rate = 0.60
        celtics_rate = 0.40
        
        fair_prob = calc.calculate_fair_probability(lakers_rate, celtics_rate)
        
        # Lakers fair probability: 0.60 / (0.60 + 0.40) = 0.60
        assert fair_prob == pytest.approx(0.60, abs=0.01)

    def test_calculate_fair_probability_dominant_team(self) -> None:
        """70% vs 30% win rate → dominant team gets 0.70 fair prob."""
        calc = NBAFairValueCalculator()
        
        team_a_rate = 0.70
        team_b_rate = 0.30
        
        fair_prob = calc.calculate_fair_probability(team_a_rate, team_b_rate)
        
        assert fair_prob == pytest.approx(0.70, abs=0.01)

    def test_calculate_fair_probability_equal_teams(self) -> None:
        """Equal win rates → 50/50 fair prob."""
        calc = NBAFairValueCalculator()
        
        fair_prob = calc.calculate_fair_probability(0.50, 0.50)
        
        assert fair_prob == pytest.approx(0.50, abs=0.01)

    def test_calculate_fair_probability_edge_case_zero(self) -> None:
        """Edge case: one team 0% win rate."""
        calc = NBAFairValueCalculator()
        
        # Team A: 0.80, Team B: 0.00
        fair_prob = calc.calculate_fair_probability(0.80, 0.00)
        
        # Should return 1.0 (Team A always wins) or handle gracefully
        assert fair_prob >= 0.99 or fair_prob == 1.0

    def test_is_undervalued_yes(self) -> None:
        """Market price $0.48 vs fair prob 0.60 with margin 0.05 → undervalued."""
        calc = NBAFairValueCalculator()
        
        market_price = 0.48
        fair_prob = 0.60
        margin = 0.05
        
        # 0.48 < 0.60 - 0.05 = 0.55 → True
        assert calc.is_undervalued(market_price, fair_prob, margin) is True

    def test_is_undervalued_no(self) -> None:
        """Market price $0.58 vs fair prob 0.60 with margin 0.05 → not undervalued."""
        calc = NBAFairValueCalculator()
        
        market_price = 0.58
        fair_prob = 0.60
        margin = 0.05
        
        # 0.58 > 0.60 - 0.05 = 0.55 → False
        assert calc.is_undervalued(market_price, fair_prob, margin) is False

    def test_is_undervalued_at_boundary(self) -> None:
        """Market price exactly at fair_prob - margin → not undervalued (strict <)."""
        calc = NBAFairValueCalculator()
        
        market_price = 0.55
        fair_prob = 0.60
        margin = 0.05
        
        # 0.55 = 0.60 - 0.05 → False (not strictly less than)
        assert calc.is_undervalued(market_price, fair_prob, margin) is False

    def test_is_undervalued_default_margin(self) -> None:
        """Default margin should be 0.05."""
        calc = NBAFairValueCalculator()
        
        # 0.48 < 0.60 - 0.05 = 0.55 → True
        assert calc.is_undervalued(0.48, 0.60) is True
        
        # 0.56 > 0.55 → False
        assert calc.is_undervalued(0.56, 0.60) is False


class TestNBAFairValueCalculatorTeamData:
    """Tests for team win rate fetching."""

    @pytest.mark.asyncio
    async def test_get_team_win_rate_returns_float(self) -> None:
        """Team win rate should return a float between 0 and 1."""
        calc = NBAFairValueCalculator()
        
        # Using hardcoded fallback data (no network call)
        rate = await calc.get_team_win_rate("Lakers")
        
        assert isinstance(rate, float)
        assert 0.0 <= rate <= 1.0

    @pytest.mark.asyncio
    async def test_get_team_win_rate_unknown_team(self) -> None:
        """Unknown team should return default 0.50."""
        calc = NBAFairValueCalculator()
        
        rate = await calc.get_team_win_rate("UnknownTeam123")
        
        assert rate == pytest.approx(0.50, abs=0.01)

    @pytest.mark.asyncio
    async def test_get_team_win_rate_case_insensitive(self) -> None:
        """Team name lookup should be case-insensitive."""
        calc = NBAFairValueCalculator()
        
        rate1 = await calc.get_team_win_rate("Lakers")
        rate2 = await calc.get_team_win_rate("lakers")
        rate3 = await calc.get_team_win_rate("LAKERS")
        
        assert rate1 == rate2 == rate3


class TestNBAFairValueIntegration:
    """Integration tests for NBA fair value workflow."""

    @pytest.mark.asyncio
    async def test_full_workflow_lakers_vs_celtics(self) -> None:
        """Full workflow: get win rates → calculate fair prob → check undervalued."""
        calc = NBAFairValueCalculator()
        
        lakers_rate = await calc.get_team_win_rate("Lakers")
        celtics_rate = await calc.get_team_win_rate("Celtics")
        
        fair_prob = calc.calculate_fair_probability(lakers_rate, celtics_rate)
        
        # Market selling Lakers YES at $0.40 with fair prob > 0.50 should be undervalued
        market_price = 0.40
        is_under = calc.is_undervalued(market_price, fair_prob, margin=0.05)
        
        # If Lakers have higher win rate than Celtics, $0.40 should be undervalued
        if lakers_rate > celtics_rate:
            assert fair_prob > 0.50
            if fair_prob > 0.45:  # 0.40 < fair_prob - 0.05
                assert is_under is True

    def test_detect_undervalued_with_market_data(self) -> None:
        """Simulate detecting undervalued market from real-ish data."""
        calc = NBAFairValueCalculator()
        
        # Simulate: Lakers (good team) vs weak team
        # Lakers win rate 65%, opponent 35%
        fair_prob = calc.calculate_fair_probability(0.65, 0.35)
        assert fair_prob == pytest.approx(0.65, abs=0.01)
        
        # Market price $0.50 for Lakers YES
        # Fair value is 0.65, so $0.50 is undervalued (0.50 < 0.65 - 0.05 = 0.60)
        assert calc.is_undervalued(0.50, fair_prob, margin=0.05) is True
        
        # Market price $0.62 → not undervalued (0.62 > 0.60)
        assert calc.is_undervalued(0.62, fair_prob, margin=0.05) is False
