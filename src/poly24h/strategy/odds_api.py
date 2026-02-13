"""The Odds API client for real-time sportsbook odds (F-024/F-026).

Fetches sportsbook odds from The Odds API, converts American odds to implied
probabilities, removes bookmaker overround (devig), and matches sportsbook
lines to Polymarket markets for edge detection.

F-026: Multi-sport support with per-sport caching, 3-way soccer devig,
and parameterized team matching.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp

from poly24h.models.market import MarketSource

logger = logging.getLogger(__name__)

# NBA team name aliases for fuzzy matching
NBA_TEAM_NAMES: dict[str, list[str]] = {
    "lakers": ["los angeles lakers", "lakers", "la lakers"],
    "celtics": ["boston celtics", "celtics", "boston"],
    "warriors": ["golden state warriors", "warriors", "golden state"],
    "bucks": ["milwaukee bucks", "bucks", "milwaukee"],
    "heat": ["miami heat", "heat", "miami"],
    "suns": ["phoenix suns", "suns", "phoenix"],
    "nuggets": ["denver nuggets", "nuggets", "denver"],
    "76ers": ["philadelphia 76ers", "76ers", "sixers", "philadelphia"],
    "nets": ["brooklyn nets", "nets", "brooklyn"],
    "bulls": ["chicago bulls", "bulls", "chicago"],
    "knicks": ["new york knicks", "knicks", "new york"],
    "clippers": ["los angeles clippers", "clippers", "la clippers"],
    "mavericks": ["dallas mavericks", "mavericks", "dallas"],
    "hawks": ["atlanta hawks", "hawks", "atlanta"],
    "grizzlies": ["memphis grizzlies", "grizzlies", "memphis"],
    "timberwolves": ["minnesota timberwolves", "timberwolves", "minnesota"],
    "thunder": ["oklahoma city thunder", "thunder", "okc", "oklahoma city"],
    "cavaliers": ["cleveland cavaliers", "cavaliers", "cleveland", "cavs"],
    "pelicans": ["new orleans pelicans", "pelicans", "new orleans"],
    "rockets": ["houston rockets", "rockets", "houston"],
    "kings": ["sacramento kings", "kings", "sacramento"],
    "raptors": ["toronto raptors", "raptors", "toronto"],
    "pacers": ["indiana pacers", "pacers", "indiana"],
    "magic": ["orlando magic", "magic", "orlando"],
    "pistons": ["detroit pistons", "pistons", "detroit"],
    "hornets": ["charlotte hornets", "hornets", "charlotte"],
    "wizards": ["washington wizards", "wizards", "washington"],
    "spurs": ["san antonio spurs", "spurs", "san antonio"],
    "jazz": ["utah jazz", "jazz", "utah"],
    "blazers": ["portland trail blazers", "trail blazers", "blazers", "portland"],
}

# Reverse lookup: full name → canonical short name
_FULL_TO_CANONICAL: dict[str, str] = {}
for canonical, aliases in NBA_TEAM_NAMES.items():
    for alias in aliases:
        _FULL_TO_CANONICAL[alias.lower()] = canonical


def american_to_prob(odds: int) -> float:
    """Convert American odds to implied probability.

    +150 → 1/(1+1.5) = 0.40
    -200 → 200/(200+100) = 0.6667
    +100 → 0.50
    """
    if odds > 0:
        return 100.0 / (odds + 100.0)
    else:
        return abs(odds) / (abs(odds) + 100.0)


def devig(prob_a: float, prob_b: float) -> tuple[float, float]:
    """Remove bookmaker overround (multiplicative devig).

    Raw: 52% + 52% = 104%
    Devigged: 50% + 50% = 100%
    """
    total = prob_a + prob_b
    if total <= 0:
        return (0.5, 0.5)
    return (prob_a / total, prob_b / total)


def devig_three_way(
    prob_home: float, prob_draw: float, prob_away: float,
) -> tuple[float, float, float]:
    """Remove bookmaker overround for 3-way markets (soccer).

    Normalizes home/draw/away probabilities to sum to 1.0.
    """
    total = prob_home + prob_draw + prob_away
    if total <= 0:
        return (1 / 3, 1 / 3, 1 / 3)
    return (prob_home / total, prob_draw / total, prob_away / total)


def build_team_lookup(team_names: dict[str, list[str]]) -> dict[str, str]:
    """Build reverse lookup: alias → canonical name."""
    lookup: dict[str, str] = {}
    for canonical, aliases in team_names.items():
        for alias in aliases:
            lookup[alias.lower()] = canonical
    return lookup


def normalize_team_generic(name: str, lookup: dict[str, str]) -> Optional[str]:
    """Normalize a team name using a given lookup table."""
    name_lower = name.lower().strip()
    if name_lower in lookup:
        return lookup[name_lower]
    for full_name, canonical in lookup.items():
        if full_name in name_lower or name_lower in full_name:
            return canonical
    return None


def find_teams_in_text_generic(text: str, lookup: dict[str, str]) -> list[str]:
    """Find all team canonical names in text using a given lookup."""
    text_lower = text.lower()
    found = []
    entries = sorted(lookup.items(), key=lambda x: len(x[0]), reverse=True)
    for full_name, canonical in entries:
        if full_name in text_lower and canonical not in found:
            found.append(canonical)
    return found


def calculate_edge(market_price: float, fair_prob: float) -> float:
    """Calculate edge: fair_prob - market_price.

    NBA has 0% fees so no fee adjustment needed.
    Positive = undervalued (buy opportunity).
    """
    return fair_prob - market_price


def should_skip_crypto_directional(source: MarketSource) -> bool:
    """F-024 Phase 3: Skip crypto directional betting.

    Crypto momentum indicators produce systematic YES bias.
    Disable until market making strategy is implemented.
    """
    return source == MarketSource.HOURLY_CRYPTO


def _normalize_team(name: str) -> Optional[str]:
    """Normalize a team name to canonical short form."""
    name_lower = name.lower().strip()
    if name_lower in _FULL_TO_CANONICAL:
        return _FULL_TO_CANONICAL[name_lower]
    # Try substring match for partial names
    for full_name, canonical in _FULL_TO_CANONICAL.items():
        if full_name in name_lower or name_lower in full_name:
            return canonical
    return None


def _find_teams_in_text(text: str) -> list[str]:
    """Find all NBA team canonical names mentioned in text."""
    text_lower = text.lower()
    found = []
    # Check full names first (longest first for proper matching)
    entries = sorted(_FULL_TO_CANONICAL.items(), key=lambda x: len(x[0]), reverse=True)
    for full_name, canonical in entries:
        if full_name in text_lower and canonical not in found:
            found.append(canonical)
    return found


@dataclass
class MarketOdds:
    """Odds for a single market type (h2h, spreads, or totals)."""
    outcomes: list[dict]  # [{"name": str, "price": int, "point": float?}]


@dataclass
class GameOdds:
    """Odds for a single NBA game across market types."""
    game_id: str
    home_team: str
    away_team: str
    commence_time: str
    h2h: Optional[MarketOdds] = None
    spreads: Optional[MarketOdds] = None
    totals: Optional[MarketOdds] = None


@dataclass
class MatchedOdds:
    """A matched sportsbook line ↔ Polymarket market."""
    market_id: str
    market_type: str  # "moneyline", "spread", "totals"
    fair_prob: float  # Devigged probability for YES side
    sportsbook_odds: dict  # Raw odds data


class OddsAPIClient:
    """Client for The Odds API (https://the-odds-api.com/)."""

    BASE_URL = "https://api.the-odds-api.com/v4/sports"
    SPORT_KEY = "basketball_nba"
    # Preferred bookmakers (Pinnacle is sharpest)
    PREFERRED_BOOKS = ["pinnacle", "draftkings", "fanduel"]

    def __init__(
        self,
        api_key: str = "",
        cache_ttl: int = 300,
    ):
        self._api_key = api_key or os.environ.get("ODDS_API_KEY", "")
        self._cache_ttl = cache_ttl
        # Legacy single cache (NBA backward compat)
        self._cache: Optional[list[GameOdds]] = None
        self._cache_time: float = 0.0
        # F-026: Per-sport cache
        self._sport_caches: dict[str, tuple[list[GameOdds], float]] = {}
        # Track remaining requests from API response header
        self._last_remaining: int | None = None

    async def _fetch_json(self, url: str, params: dict) -> list[dict]:
        """Fetch JSON from API endpoint."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "Odds API error: %s %s",
                            resp.status, await resp.text(),
                        )
                        return []
                    data = await resp.json()
                    remaining = resp.headers.get("x-requests-remaining", "?")
                    logger.info("Odds API: %d games, requests remaining: %s", len(data), remaining)
                    try:
                        self._last_remaining = int(remaining)
                    except (ValueError, TypeError):
                        pass
                    return data
        except Exception as e:
            logger.error("Odds API fetch failed: %s", e)
            return []

    async def fetch_nba_odds(
        self,
        markets: str = "h2h,spreads,totals",
        bookmakers: str = "",
    ) -> list[GameOdds]:
        """Fetch NBA odds from The Odds API.

        Returns cached data if within TTL.
        """
        now = time.time()
        if self._cache is not None and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        if not bookmakers:
            bookmakers = ",".join(self.PREFERRED_BOOKS)

        url = f"{self.BASE_URL}/{self.SPORT_KEY}/odds"
        params = {
            "apiKey": self._api_key,
            "regions": "us",
            "markets": markets,
            "bookmakers": bookmakers,
            "oddsFormat": "american",
        }

        try:
            raw = await self._fetch_json(url, params)
        except Exception:
            return self._cache or []

        games = []
        for item in raw:
            game = self._parse_game(item)
            if game:
                games.append(game)

        self._cache = games
        self._cache_time = now
        return games

    async def fetch_odds(
        self,
        sport_config,
        markets: str = "h2h,spreads,totals",
    ) -> list[GameOdds]:
        """Fetch odds for any sport using SportConfig.

        Uses per-sport cache for isolation between sports.
        Does not filter by bookmaker at the API level — _parse_game
        handles preferred bookmaker selection from all available.
        """
        sport_key = sport_config.odds_api_sport_key
        now = time.time()

        # Check per-sport cache
        if sport_key in self._sport_caches:
            cached_games, cached_time = self._sport_caches[sport_key]
            if (now - cached_time) < self._cache_ttl:
                return cached_games

        url = f"{self.BASE_URL}/{sport_key}/odds"
        params = {
            "apiKey": self._api_key,
            "regions": "us,eu",
            "markets": markets,
            "oddsFormat": "american",
        }

        try:
            raw = await self._fetch_json(url, params)
        except Exception:
            if sport_key in self._sport_caches:
                return self._sport_caches[sport_key][0]
            return []

        games = []
        for item in raw:
            game = self._parse_game(item)
            if game:
                games.append(game)

        self._sport_caches[sport_key] = (games, now)
        return games

    def _parse_game(self, item: dict) -> Optional[GameOdds]:
        """Parse a single game from API response."""
        bookmakers = item.get("bookmakers", [])
        if not bookmakers:
            return None

        # Pick best available bookmaker (prefer Pinnacle)
        book = None
        for pref in self.PREFERRED_BOOKS:
            for b in bookmakers:
                if b.get("key") == pref:
                    book = b
                    break
            if book:
                break
        if not book:
            book = bookmakers[0]

        h2h = None
        spreads = None
        totals = None

        for mkt in book.get("markets", []):
            key = mkt.get("key")
            outcomes = mkt.get("outcomes", [])
            if key == "h2h":
                h2h = MarketOdds(outcomes=outcomes)
            elif key == "spreads":
                spreads = MarketOdds(outcomes=outcomes)
            elif key == "totals":
                totals = MarketOdds(outcomes=outcomes)

        return GameOdds(
            game_id=item.get("id", ""),
            home_team=item.get("home_team", ""),
            away_team=item.get("away_team", ""),
            commence_time=item.get("commence_time", ""),
            h2h=h2h,
            spreads=spreads,
            totals=totals,
        )

    def match_to_polymarket(
        self,
        game: GameOdds,
        markets: list,
    ) -> list[MatchedOdds]:
        """Match sportsbook game odds to Polymarket markets.

        Matching logic:
        - Find teams in Polymarket question text
        - Match market type (moneyline, spread, O/U)
        - For spread/totals, match the line value
        """
        home_canonical = _normalize_team(game.home_team)
        away_canonical = _normalize_team(game.away_team)

        if not home_canonical or not away_canonical:
            return []

        matched = []
        for market in markets:
            q = market.question.lower()
            teams_in_q = _find_teams_in_text(q)

            # Must have at least one team from this game
            if home_canonical not in teams_in_q and away_canonical not in teams_in_q:
                continue

            # Determine market type
            market_type = self._detect_polymarket_type(q)
            if market_type is None:
                continue  # Unsupported market type (e.g., BTTS)

            if market_type == "moneyline" and game.h2h:
                fair_prob = self._calc_h2h_fair_prob(
                    game.h2h, game.home_team, home_canonical, away_canonical, q,
                )
                if fair_prob is not None:
                    matched.append(MatchedOdds(
                        market_id=market.id,
                        market_type="moneyline",
                        fair_prob=fair_prob,
                        sportsbook_odds={"h2h": game.h2h.outcomes},
                    ))

            elif market_type == "spread" and game.spreads:
                fair_prob = self._calc_spread_fair_prob(
                    game.spreads, game.home_team, home_canonical, away_canonical, q,
                )
                if fair_prob is not None:
                    matched.append(MatchedOdds(
                        market_id=market.id,
                        market_type="spread",
                        fair_prob=fair_prob,
                        sportsbook_odds={"spreads": game.spreads.outcomes},
                    ))

            elif market_type == "totals" and game.totals:
                fair_prob = self._calc_totals_fair_prob(game.totals, q)
                if fair_prob is not None:
                    matched.append(MatchedOdds(
                        market_id=market.id,
                        market_type="totals",
                        fair_prob=fair_prob,
                        sportsbook_odds={"totals": game.totals.outcomes},
                    ))

        return matched

    @staticmethod
    def _detect_polymarket_type(question_lower: str) -> str | None:
        """Detect Polymarket market type from question text.

        Returns None for market types we can't price (e.g., BTTS).
        """
        if "o/u" in question_lower or "over/under" in question_lower or "total" in question_lower:
            return "totals"
        if "spread" in question_lower:
            return "spread"
        # BTTS (Both Teams to Score) — Odds API doesn't return these in standard query
        if "both teams" in question_lower or "btts" in question_lower:
            return None
        return "moneyline"

    def _calc_h2h_fair_prob(
        self,
        h2h: MarketOdds,
        home_full: str,
        home_canonical: str,
        away_canonical: str,
        question_lower: str,
    ) -> Optional[float]:
        """Calculate devigged probability for moneyline market.

        Returns the fair prob for the YES side of the Polymarket market.
        The YES side is typically the first team mentioned.
        """
        if len(h2h.outcomes) < 2:
            return None

        # Get implied probs from American odds
        prob_a = american_to_prob(h2h.outcomes[0]["price"])
        prob_b = american_to_prob(h2h.outcomes[1]["price"])
        fair_a, fair_b = devig(prob_a, prob_b)

        # Determine which outcome maps to YES (first team in question)
        teams_in_q = _find_teams_in_text(question_lower)
        if not teams_in_q:
            return None

        first_team = teams_in_q[0]
        home_name = _normalize_team(h2h.outcomes[0]["name"])
        away_name = _normalize_team(h2h.outcomes[1]["name"])

        if first_team == home_name:
            return fair_a
        elif first_team == away_name:
            return fair_b
        else:
            # Fallback: first outcome = home team fair prob
            return fair_a

    def _calc_spread_fair_prob(
        self,
        spreads: MarketOdds,
        home_full: str,
        home_canonical: str,
        away_canonical: str,
        question_lower: str,
    ) -> Optional[float]:
        """Calculate devigged probability for spread market."""
        if len(spreads.outcomes) < 2:
            return None

        # Extract line from question (e.g., "(-3.5)" or "(-7)")
        line_match = re.search(r'\(([+-]?\d+\.?\d*)\)', question_lower)
        if not line_match:
            # Try without parens
            line_match = re.search(r'[+-]\d+\.?\d*', question_lower)

        prob_a = american_to_prob(spreads.outcomes[0]["price"])
        prob_b = american_to_prob(spreads.outcomes[1]["price"])
        fair_a, fair_b = devig(prob_a, prob_b)

        # Find which team's spread is referenced
        teams_in_q = _find_teams_in_text(question_lower)
        if not teams_in_q:
            return fair_a

        first_team = teams_in_q[0]
        spread_team_0 = _normalize_team(spreads.outcomes[0].get("name", ""))
        spread_team_1 = _normalize_team(spreads.outcomes[1].get("name", ""))

        if first_team == spread_team_0:
            return fair_a
        elif first_team == spread_team_1:
            return fair_b
        return fair_a

    def _calc_totals_fair_prob(
        self,
        totals: MarketOdds,
        question_lower: str,
    ) -> Optional[float]:
        """Calculate devigged probability for totals (O/U) market.

        YES side = Over for Polymarket O/U markets.
        Verifies the line (point value) matches between Polymarket and Odds API.
        """
        if len(totals.outcomes) < 2:
            return None

        # Extract Polymarket line from question (e.g., "O/U 2.5" → 2.5)
        line_match = re.search(r'o/u\s+(\d+\.?\d*)', question_lower)
        if not line_match:
            line_match = re.search(r'over/under\s+(\d+\.?\d*)', question_lower)
        poly_line = float(line_match.group(1)) if line_match else None

        # Find Over/Under outcomes
        over_prob = None
        under_prob = None
        odds_api_line = None
        for outcome in totals.outcomes:
            if outcome["name"].lower() == "over":
                over_prob = american_to_prob(outcome["price"])
                odds_api_line = outcome.get("point")
            elif outcome["name"].lower() == "under":
                under_prob = american_to_prob(outcome["price"])
                if odds_api_line is None:
                    odds_api_line = outcome.get("point")

        if over_prob is None or under_prob is None:
            return None

        # Verify lines match — reject if Polymarket and Odds API have different lines
        if poly_line is not None and odds_api_line is not None:
            if abs(poly_line - odds_api_line) > 0.01:
                logger.debug(
                    "O/U line mismatch: Polymarket=%.1f, OddsAPI=%.1f — skipping",
                    poly_line, odds_api_line,
                )
                return None

        fair_over, fair_under = devig(over_prob, under_prob)
        # YES = Over in Polymarket
        return fair_over

    def get_fair_prob_for_market(
        self,
        market,
        games: list[GameOdds],
        sport_config=None,
    ) -> Optional[float]:
        """Get the fair probability for a Polymarket market.

        Tries all available games to find a match.
        When sport_config is provided, uses its team_names for matching.
        For 3-way sports (soccer), handles draw markets.
        Returns None if no match found.
        """
        if sport_config is not None:
            # Use generic matching with sport-specific team names
            return self._get_fair_prob_generic(market, games, sport_config)

        # Legacy NBA path (no sport_config)
        for game in games:
            matches = self.match_to_polymarket(game, [market])
            if matches:
                return matches[0].fair_prob
        return None

    def _get_fair_prob_generic(
        self,
        market,
        games: list[GameOdds],
        sport_config,
    ) -> Optional[float]:
        """Get fair probability using sport-specific team lookup.

        Routes to appropriate handler based on market type and sport type.
        """
        if sport_config.is_three_way:
            return self._get_fair_prob_three_way(market, games, sport_config)

        # 2-way sport (NHL, NBA with sport_config)
        lookup = build_team_lookup(sport_config.team_names)
        q = market.question.lower()
        teams_in_q = find_teams_in_text_generic(q, lookup)
        market_type = self._detect_polymarket_type(q)
        if market_type is None:
            return None  # Unsupported market type (e.g., BTTS)

        for game in games:
            home_canonical = normalize_team_generic(game.home_team, lookup)
            away_canonical = normalize_team_generic(game.away_team, lookup)

            if not home_canonical or not away_canonical:
                continue

            if home_canonical not in teams_in_q and away_canonical not in teams_in_q:
                continue

            if market_type == "spread":
                if game.spreads:
                    return self._calc_spread_fair_prob_generic(
                        game.spreads, home_canonical, away_canonical, q, lookup,
                    )
                continue  # Don't fall through to moneyline for spread markets

            if market_type == "totals":
                if game.totals:
                    return self._calc_totals_fair_prob(game.totals, q)
                continue  # Don't fall through to moneyline for O/U markets

            # Moneyline (2-way) — only reached when market_type == "moneyline"
            if not game.h2h or len(game.h2h.outcomes) < 2:
                continue

            prob_a = american_to_prob(game.h2h.outcomes[0]["price"])
            prob_b = american_to_prob(game.h2h.outcomes[1]["price"])
            fair_a, fair_b = devig(prob_a, prob_b)

            home_name = normalize_team_generic(game.h2h.outcomes[0]["name"], lookup)
            away_name = normalize_team_generic(game.h2h.outcomes[1]["name"], lookup)

            if teams_in_q:
                first_team = teams_in_q[0]
                if first_team == home_name or first_team == home_canonical:
                    return fair_a
                elif first_team == away_name or first_team == away_canonical:
                    return fair_b

            return fair_a

        return None

    def _get_fair_prob_three_way(
        self,
        market,
        games: list[GameOdds],
        sport_config,
    ) -> Optional[float]:
        """Get fair probability for 3-way soccer market.

        Handles moneyline (3-way devig), spread, and totals.
        Only moneyline uses 3-way devig; spread/totals use standard 2-way.
        """
        lookup = build_team_lookup(sport_config.team_names)
        q = market.question.lower()
        teams_in_q = find_teams_in_text_generic(q, lookup)

        # Detect market type first
        market_type = self._detect_polymarket_type(q)
        if market_type is None:
            return None  # Unsupported market type (e.g., BTTS)

        for game in games:
            home_canonical = normalize_team_generic(game.home_team, lookup)
            away_canonical = normalize_team_generic(game.away_team, lookup)

            if not home_canonical or not away_canonical:
                continue

            # Check if this game matches the market question
            if home_canonical not in teams_in_q and away_canonical not in teams_in_q:
                continue

            # Spread markets → use standard 2-way devig
            if market_type == "spread":
                if game.spreads:
                    return self._calc_spread_fair_prob_generic(
                        game.spreads, home_canonical, away_canonical, q, lookup,
                    )
                continue  # Don't fall through to moneyline for spread markets

            # Totals (O/U) markets → use standard 2-way devig
            if market_type == "totals":
                if game.totals:
                    return self._calc_totals_fair_prob(game.totals, q)
                continue  # Don't fall through to moneyline for O/U markets

            # Moneyline / Draw → 3-way devig (only reached when market_type == "moneyline")
            if not game.h2h or len(game.h2h.outcomes) < 2:
                continue

            outcomes = game.h2h.outcomes
            is_three = len(outcomes) >= 3

            if is_three:
                prob_home = american_to_prob(outcomes[0]["price"])
                prob_draw = american_to_prob(outcomes[1]["price"])
                prob_away = american_to_prob(outcomes[2]["price"])
                fair_home, fair_draw, fair_away = devig_three_way(
                    prob_home, prob_draw, prob_away,
                )

                is_draw = "draw" in q
                if is_draw:
                    return fair_draw

                home_name = normalize_team_generic(outcomes[0]["name"], lookup)
                away_name = normalize_team_generic(outcomes[2]["name"], lookup)

                if teams_in_q:
                    first_team = teams_in_q[0]
                    if first_team == home_canonical or first_team == home_name:
                        return fair_home
                    elif first_team == away_canonical or first_team == away_name:
                        return fair_away

                return fair_home
            else:
                prob_a = american_to_prob(outcomes[0]["price"])
                prob_b = american_to_prob(outcomes[1]["price"])
                fair_a, fair_b = devig(prob_a, prob_b)

                home_name = normalize_team_generic(outcomes[0]["name"], lookup)
                if teams_in_q and teams_in_q[0] == away_canonical:
                    return fair_b
                return fair_a

        return None

    def _calc_spread_fair_prob_generic(
        self,
        spreads: MarketOdds,
        home_canonical: str,
        away_canonical: str,
        question_lower: str,
        lookup: dict[str, str],
    ) -> Optional[float]:
        """Calculate spread fair prob using generic team lookup.

        Verifies the spread line matches between Polymarket and Odds API.
        """
        if len(spreads.outcomes) < 2:
            return None

        # Extract Polymarket spread line from question (e.g., "(-3.5)" or "(+7)")
        line_match = re.search(r'\(([+-]?\d+\.?\d*)\)', question_lower)
        poly_line = float(line_match.group(1)) if line_match else None

        # Check Odds API spread line
        odds_api_line = spreads.outcomes[0].get("point")
        if poly_line is not None and odds_api_line is not None:
            if abs(poly_line - odds_api_line) > 0.01:
                logger.debug(
                    "Spread line mismatch: Polymarket=%.1f, OddsAPI=%.1f — skipping",
                    poly_line, odds_api_line,
                )
                return None

        prob_a = american_to_prob(spreads.outcomes[0]["price"])
        prob_b = american_to_prob(spreads.outcomes[1]["price"])
        fair_a, fair_b = devig(prob_a, prob_b)

        teams_in_q = find_teams_in_text_generic(question_lower, lookup)
        if not teams_in_q:
            return fair_a

        first_team = teams_in_q[0]
        spread_team_0 = normalize_team_generic(spreads.outcomes[0].get("name", ""), lookup)
        spread_team_1 = normalize_team_generic(spreads.outcomes[1].get("name", ""), lookup)

        if first_team == spread_team_0:
            return fair_a
        elif first_team == spread_team_1:
            return fair_b
        return fair_a
