"""NBA Fair Value Calculator (F-021).

Calculates fair probability for NBA markets based on team win rates.
Uses simple win rate ratio formula: team_a_rate / (team_a_rate + team_b_rate).

Example:
    Lakers (60% win rate) vs Celtics (40% win rate)
    → Lakers fair probability = 0.60 / (0.60 + 0.40) = 0.60 (60%)
"""

from __future__ import annotations

import logging
from typing import Dict

logger = logging.getLogger(__name__)


# Hardcoded 2024-25 NBA team win rates (as of Feb 2025 approximate)
# Will be updated periodically or fetched from ESPN API in future
NBA_TEAM_WIN_RATES: Dict[str, float] = {
    # Eastern Conference
    "celtics": 0.70,
    "boston": 0.70,
    "boston celtics": 0.70,
    "cavaliers": 0.68,
    "cleveland": 0.68,
    "cleveland cavaliers": 0.68,
    "bucks": 0.62,
    "milwaukee": 0.62,
    "milwaukee bucks": 0.62,
    "knicks": 0.60,
    "new york": 0.60,
    "new york knicks": 0.60,
    "heat": 0.55,
    "miami": 0.55,
    "miami heat": 0.55,
    "76ers": 0.54,
    "sixers": 0.54,
    "philadelphia": 0.54,
    "philadelphia 76ers": 0.54,
    "pacers": 0.55,
    "indiana": 0.55,
    "indiana pacers": 0.55,
    "magic": 0.52,
    "orlando": 0.52,
    "orlando magic": 0.52,
    "hawks": 0.48,
    "atlanta": 0.48,
    "atlanta hawks": 0.48,
    "bulls": 0.45,
    "chicago": 0.45,
    "chicago bulls": 0.45,
    "nets": 0.40,
    "brooklyn": 0.40,
    "brooklyn nets": 0.40,
    "raptors": 0.38,
    "toronto": 0.38,
    "toronto raptors": 0.38,
    "pistons": 0.30,
    "detroit": 0.30,
    "detroit pistons": 0.30,
    "hornets": 0.32,
    "charlotte": 0.32,
    "charlotte hornets": 0.32,
    "wizards": 0.28,
    "washington": 0.28,
    "washington wizards": 0.28,
    
    # Western Conference
    "thunder": 0.72,
    "okc": 0.72,
    "oklahoma city": 0.72,
    "oklahoma city thunder": 0.72,
    "nuggets": 0.62,
    "denver": 0.62,
    "denver nuggets": 0.62,
    "timberwolves": 0.60,
    "minnesota": 0.60,
    "minnesota timberwolves": 0.60,
    "clippers": 0.58,
    "la clippers": 0.58,
    "los angeles clippers": 0.58,
    "suns": 0.55,
    "phoenix": 0.55,
    "phoenix suns": 0.55,
    "mavericks": 0.56,
    "dallas": 0.56,
    "dallas mavericks": 0.56,
    "lakers": 0.58,
    "la lakers": 0.58,
    "los angeles lakers": 0.58,
    "kings": 0.52,
    "sacramento": 0.52,
    "sacramento kings": 0.52,
    "pelicans": 0.50,
    "new orleans": 0.50,
    "new orleans pelicans": 0.50,
    "warriors": 0.50,
    "golden state": 0.50,
    "golden state warriors": 0.50,
    "rockets": 0.48,
    "houston": 0.48,
    "houston rockets": 0.48,
    "grizzlies": 0.45,
    "memphis": 0.45,
    "memphis grizzlies": 0.45,
    "jazz": 0.38,
    "utah": 0.38,
    "utah jazz": 0.38,
    "spurs": 0.35,
    "san antonio": 0.35,
    "san antonio spurs": 0.35,
    "trail blazers": 0.32,
    "blazers": 0.32,
    "portland": 0.32,
    "portland trail blazers": 0.32,
}


class NBAFairValueCalculator:
    """Calculates fair value for NBA markets based on team win rates.
    
    Usage:
        calc = NBAFairValueCalculator()
        lakers_rate = await calc.get_team_win_rate("Lakers")
        celtics_rate = await calc.get_team_win_rate("Celtics")
        fair_prob = calc.calculate_fair_probability(lakers_rate, celtics_rate)
        is_under = calc.is_undervalued(market_price=0.48, fair_prob=fair_prob)
    """
    
    def __init__(self, win_rates: Dict[str, float] | None = None):
        """Initialize with optional custom win rates dict."""
        self._win_rates = win_rates if win_rates is not None else NBA_TEAM_WIN_RATES
    
    async def get_team_win_rate(self, team_name: str) -> float:
        """Get team's season win rate (0.0 to 1.0).
        
        Args:
            team_name: Team name (case-insensitive). E.g., "Lakers", "Celtics"
        
        Returns:
            Win rate as float. Returns 0.50 for unknown teams.
        """
        normalized = team_name.lower().strip()
        
        # Try exact match first
        if normalized in self._win_rates:
            return self._win_rates[normalized]
        
        # Try partial match
        for key, rate in self._win_rates.items():
            if normalized in key or key in normalized:
                return rate
        
        # Unknown team: return neutral 0.50
        logger.warning("Unknown NBA team: %s, using default 0.50", team_name)
        return 0.50
    
    def calculate_fair_probability(
        self,
        team_a_rate: float,
        team_b_rate: float,
    ) -> float:
        """Calculate fair probability for team A to win.
        
        Uses simple ratio formula:
            fair_prob_A = team_a_rate / (team_a_rate + team_b_rate)
        
        Args:
            team_a_rate: Team A's season win rate (0.0 to 1.0)
            team_b_rate: Team B's season win rate (0.0 to 1.0)
        
        Returns:
            Fair probability for team A (0.0 to 1.0).
        """
        # Handle edge cases
        total = team_a_rate + team_b_rate
        if total <= 0:
            # Both 0% win rate: return 50/50
            return 0.50
        
        if team_a_rate <= 0:
            # Team A has 0% win rate: Team B always wins
            return 0.0
        
        if team_b_rate <= 0:
            # Team B has 0% win rate: Team A always wins
            return 1.0
        
        return team_a_rate / total
    
    def is_undervalued(
        self,
        market_price: float,
        fair_prob: float,
        margin: float = 0.05,
    ) -> bool:
        """Check if market price is undervalued relative to fair probability.
        
        A market is undervalued if:
            market_price < fair_prob - margin
        
        Args:
            market_price: Current market price (0.0 to 1.0)
            fair_prob: Calculated fair probability (0.0 to 1.0)
            margin: Safety margin (default 0.05 = 5%)
        
        Returns:
            True if undervalued (market is cheaper than fair value - margin)
        """
        threshold = fair_prob - margin
        return market_price < threshold
    
    def get_value_score(
        self,
        market_price: float,
        fair_prob: float,
    ) -> float:
        """Calculate value score: how much the market is mispriced.
        
        Positive score = undervalued (buy opportunity)
        Negative score = overvalued (avoid or sell)
        
        Args:
            market_price: Current market price
            fair_prob: Calculated fair probability
        
        Returns:
            Value score as percentage points difference.
        """
        return fair_prob - market_price
