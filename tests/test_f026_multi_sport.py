"""F-026: Multi-Sport Monitor Tests.

Kent Beck TDD — RED phase first, then GREEN.
Tests cover: SportConfig, team_data, multi-sport discovery,
3-way devig, SportsMonitor, rate limiter.
"""

from __future__ import annotations

import pytest


# =============================================================================
# Phase 1: SportConfig dataclass
# =============================================================================


class TestSportConfig:
    """Test SportConfig dataclass and sport constants."""

    def test_sport_config_required_fields(self):
        """SportConfig has all required fields."""
        from poly24h.strategy.sport_config import SportConfig
        from poly24h.models.market import MarketSource

        config = SportConfig(
            name="test_sport",
            display_name="Test Sport",
            source=MarketSource.NHL,
            odds_api_sport_key="icehockey_nhl",
            series_id="10346",
            tag_id="100639",
            team_names={"bruins": ["boston bruins"]},
            slug_prefixes=["nhl"],
        )
        assert config.name == "test_sport"
        assert config.display_name == "Test Sport"
        assert config.series_id == "10346"
        assert config.is_three_way is False
        assert config.scan_interval == 300
        assert config.min_edge == 0.03
        assert config.max_per_game == 500.0

    def test_soccer_is_three_way(self):
        """Soccer configs have is_three_way=True."""
        from poly24h.strategy.sport_config import (
            BUNDESLIGA_CONFIG,
            EPL_CONFIG,
            LA_LIGA_CONFIG,
            LIGUE_1_CONFIG,
            SERIE_A_CONFIG,
            UCL_CONFIG,
        )

        for config in [BUNDESLIGA_CONFIG, SERIE_A_CONFIG, LIGUE_1_CONFIG,
                        LA_LIGA_CONFIG, EPL_CONFIG, UCL_CONFIG]:
            assert config.is_three_way is True, f"{config.name} should be 3-way"

    def test_nhl_is_two_way(self):
        """NHL is 2-way (no draw)."""
        from poly24h.strategy.sport_config import NHL_CONFIG

        assert NHL_CONFIG.is_three_way is False

    def test_nba_config_exists(self):
        """NBA config exists for backward compatibility."""
        from poly24h.strategy.sport_config import NBA_CONFIG
        from poly24h.models.market import MarketSource

        assert NBA_CONFIG.source == MarketSource.NBA
        assert NBA_CONFIG.series_id == "10345"
        assert NBA_CONFIG.odds_api_sport_key == "basketball_nba"

    def test_nhl_config(self):
        """NHL config has correct series_id and odds_api_sport_key."""
        from poly24h.strategy.sport_config import NHL_CONFIG
        from poly24h.models.market import MarketSource

        assert NHL_CONFIG.source == MarketSource.NHL
        assert NHL_CONFIG.series_id == "10346"
        assert NHL_CONFIG.odds_api_sport_key == "icehockey_nhl"
        assert "nhl" in NHL_CONFIG.slug_prefixes

    def test_bundesliga_config(self):
        """Bundesliga config is correct."""
        from poly24h.strategy.sport_config import BUNDESLIGA_CONFIG

        assert BUNDESLIGA_CONFIG.series_id == "10194"
        assert BUNDESLIGA_CONFIG.odds_api_sport_key == "soccer_germany_bundesliga"
        assert BUNDESLIGA_CONFIG.is_three_way is True

    def test_all_configs_have_unique_names(self):
        """All sport configs have unique name fields."""
        from poly24h.strategy.sport_config import ALL_SPORT_CONFIGS

        names = [c.name for c in ALL_SPORT_CONFIGS]
        assert len(names) == len(set(names)), f"Duplicate names: {names}"

    def test_all_configs_have_unique_series_ids(self):
        """All sport configs have unique series_ids."""
        from poly24h.strategy.sport_config import ALL_SPORT_CONFIGS

        series_ids = [c.series_id for c in ALL_SPORT_CONFIGS]
        assert len(series_ids) == len(set(series_ids)), f"Duplicate series_ids: {series_ids}"

    def test_get_enabled_sport_configs_default(self):
        """get_enabled_sport_configs returns all when POLY24H_SPORTS not set."""
        import os
        from poly24h.strategy.sport_config import get_enabled_sport_configs

        # Remove env var if set
        old = os.environ.pop("POLY24H_SPORTS", None)
        try:
            configs = get_enabled_sport_configs()
            assert len(configs) >= 1
        finally:
            if old is not None:
                os.environ["POLY24H_SPORTS"] = old

    def test_get_enabled_sport_configs_filtered(self):
        """get_enabled_sport_configs filters by POLY24H_SPORTS env var."""
        import os
        from poly24h.strategy.sport_config import get_enabled_sport_configs

        old = os.environ.get("POLY24H_SPORTS")
        os.environ["POLY24H_SPORTS"] = "nhl,bundesliga"
        try:
            configs = get_enabled_sport_configs()
            names = [c.name for c in configs]
            assert "nhl" in names
            assert "bundesliga" in names
            assert "nba" not in names
        finally:
            if old is None:
                del os.environ["POLY24H_SPORTS"]
            else:
                os.environ["POLY24H_SPORTS"] = old

    def test_soccer_min_edge_higher(self):
        """Soccer configs default to higher min_edge (0.05)."""
        from poly24h.strategy.sport_config import BUNDESLIGA_CONFIG

        assert BUNDESLIGA_CONFIG.min_edge >= 0.05


# =============================================================================
# Phase 2: Team Data
# =============================================================================


class TestTeamData:
    """Test team name mappings for all sports."""

    def test_nhl_team_count(self):
        """NHL has 32 teams."""
        from poly24h.strategy.team_data import NHL_TEAM_NAMES

        assert len(NHL_TEAM_NAMES) == 32

    def test_bundesliga_team_count(self):
        """Bundesliga has 18 teams."""
        from poly24h.strategy.team_data import BUNDESLIGA_TEAM_NAMES

        assert len(BUNDESLIGA_TEAM_NAMES) == 18

    def test_epl_team_count(self):
        """EPL has 20 teams."""
        from poly24h.strategy.team_data import EPL_TEAM_NAMES

        assert len(EPL_TEAM_NAMES) == 20

    def test_serie_a_team_count(self):
        """Serie A has 20 teams."""
        from poly24h.strategy.team_data import SERIE_A_TEAM_NAMES

        assert len(SERIE_A_TEAM_NAMES) == 20

    def test_ligue_1_team_count(self):
        """Ligue 1 has 18 teams."""
        from poly24h.strategy.team_data import LIGUE_1_TEAM_NAMES

        assert len(LIGUE_1_TEAM_NAMES) == 18

    def test_la_liga_team_count(self):
        """La Liga has 20 teams."""
        from poly24h.strategy.team_data import LA_LIGA_TEAM_NAMES

        assert len(LA_LIGA_TEAM_NAMES) == 20

    def test_nba_team_names_moved(self):
        """NBA team names accessible from team_data module."""
        from poly24h.strategy.team_data import NBA_TEAM_NAMES

        assert len(NBA_TEAM_NAMES) == 30

    def test_nhl_has_common_teams(self):
        """NHL includes well-known teams."""
        from poly24h.strategy.team_data import NHL_TEAM_NAMES

        assert "bruins" in NHL_TEAM_NAMES
        assert "maple_leafs" in NHL_TEAM_NAMES
        assert "rangers" in NHL_TEAM_NAMES
        assert "penguins" in NHL_TEAM_NAMES

    def test_bundesliga_has_common_teams(self):
        """Bundesliga includes well-known teams."""
        from poly24h.strategy.team_data import BUNDESLIGA_TEAM_NAMES

        assert "bayern" in BUNDESLIGA_TEAM_NAMES
        assert "dortmund" in BUNDESLIGA_TEAM_NAMES
        assert "leverkusen" in BUNDESLIGA_TEAM_NAMES

    def test_epl_has_common_teams(self):
        """EPL includes well-known teams."""
        from poly24h.strategy.team_data import EPL_TEAM_NAMES

        assert "arsenal" in EPL_TEAM_NAMES
        assert "liverpool" in EPL_TEAM_NAMES
        assert "man_city" in EPL_TEAM_NAMES
        assert "man_utd" in EPL_TEAM_NAMES
        assert "chelsea" in EPL_TEAM_NAMES

    def test_no_duplicate_aliases_within_sport(self):
        """No alias appears twice within the same sport's team names."""
        from poly24h.strategy.team_data import (
            NHL_TEAM_NAMES,
            BUNDESLIGA_TEAM_NAMES,
            EPL_TEAM_NAMES,
            SERIE_A_TEAM_NAMES,
            LIGUE_1_TEAM_NAMES,
            LA_LIGA_TEAM_NAMES,
        )

        for sport_name, team_names in [
            ("NHL", NHL_TEAM_NAMES),
            ("Bundesliga", BUNDESLIGA_TEAM_NAMES),
            ("EPL", EPL_TEAM_NAMES),
            ("Serie A", SERIE_A_TEAM_NAMES),
            ("Ligue 1", LIGUE_1_TEAM_NAMES),
            ("La Liga", LA_LIGA_TEAM_NAMES),
        ]:
            all_aliases = []
            for canonical, aliases in team_names.items():
                for alias in aliases:
                    all_aliases.append(alias.lower())
            dupes = [a for a in all_aliases if all_aliases.count(a) > 1]
            assert len(dupes) == 0, f"{sport_name} has duplicate aliases: {set(dupes)}"

    def test_each_team_has_at_least_two_aliases(self):
        """Every team has at least canonical name and one alias."""
        from poly24h.strategy.team_data import NHL_TEAM_NAMES, EPL_TEAM_NAMES

        for canonical, aliases in NHL_TEAM_NAMES.items():
            assert len(aliases) >= 2, f"NHL {canonical} needs at least 2 aliases"

        for canonical, aliases in EPL_TEAM_NAMES.items():
            assert len(aliases) >= 2, f"EPL {canonical} needs at least 2 aliases"

    def test_ucl_team_names(self):
        """UCL team names cover major European clubs."""
        from poly24h.strategy.team_data import UCL_TEAM_NAMES

        # UCL should include top clubs from multiple leagues
        assert len(UCL_TEAM_NAMES) >= 20
        # Check a few known UCL regulars
        assert "real_madrid" in UCL_TEAM_NAMES
        assert "barcelona" in UCL_TEAM_NAMES
        assert "bayern" in UCL_TEAM_NAMES
        assert "liverpool" in UCL_TEAM_NAMES


# =============================================================================
# Phase 3: GammaClient + MarketScanner generalization
# =============================================================================


class TestMultiSportDiscovery:
    """Test generic game event discovery by series_id."""

    @pytest.mark.asyncio
    async def test_fetch_game_events_by_series(self):
        """GammaClient.fetch_game_events_by_series() uses series_id param."""
        from unittest.mock import AsyncMock, MagicMock

        from poly24h.discovery.gamma_client import GammaClient

        gamma = GammaClient()
        gamma._session = MagicMock()

        mock_events = [
            {"slug": "nhl-bos-tor-2026-02-14", "ended": False, "markets": []},
        ]
        gamma._get_list = AsyncMock(return_value=mock_events)

        events = await gamma.fetch_game_events_by_series("10346", tag_id="100639")
        assert len(events) == 1

        # Verify series_id was passed
        call_args = gamma._get_list.call_args
        params = call_args[0][1]  # second positional arg
        assert params["series_id"] == "10346"
        assert params["tag_id"] == "100639"

    @pytest.mark.asyncio
    async def test_fetch_game_events_by_series_no_tag_id(self):
        """series_id without tag_id still works (some sports have no tag)."""
        from unittest.mock import AsyncMock, MagicMock

        from poly24h.discovery.gamma_client import GammaClient

        gamma = GammaClient()
        gamma._session = MagicMock()
        gamma._get_list = AsyncMock(return_value=[])

        events = await gamma.fetch_game_events_by_series("10194", tag_id=None)
        assert events == []

        call_args = gamma._get_list.call_args
        params = call_args[0][1]
        assert params["series_id"] == "10194"
        assert "tag_id" not in params

    @pytest.mark.asyncio
    async def test_fetch_nba_game_events_is_wrapper(self):
        """Existing fetch_nba_game_events delegates to fetch_game_events_by_series."""
        from unittest.mock import AsyncMock, MagicMock

        from poly24h.discovery.gamma_client import GammaClient

        gamma = GammaClient()
        gamma._session = MagicMock()
        gamma.fetch_game_events_by_series = AsyncMock(return_value=[{"slug": "nba-test"}])

        events = await gamma.fetch_nba_game_events()
        gamma.fetch_game_events_by_series.assert_called_once()

    @pytest.mark.asyncio
    async def test_discover_sport_markets_nhl(self):
        """discover_sport_markets returns markets for NHL config."""
        from datetime import datetime, timedelta, timezone
        from unittest.mock import AsyncMock, MagicMock

        from poly24h.discovery.market_scanner import MarketScanner
        from poly24h.models.market import MarketSource
        from poly24h.strategy.sport_config import NHL_CONFIG

        gamma = MagicMock()
        nhl_event = {
            "slug": "nhl-bos-tor-2026-02-14",
            "enableNegRisk": True,
            "negRiskAugmented": True,
            "endDate": (datetime.now(tz=timezone.utc) + timedelta(hours=12)).isoformat(),
            "markets": [
                {
                    "id": "nhl_m1",
                    "question": "Bruins vs. Maple Leafs",
                    "outcomePrices": '[\"0.55\",\"0.45\"]',
                    "clobTokenIds": '[\"yt1\",\"nt1\"]',
                    "volume": "10000",
                    "liquidity": "5000",
                    "endDate": (datetime.now(tz=timezone.utc) + timedelta(hours=12)).isoformat(),
                    "active": True,
                    "closed": False,
                    "acceptingOrders": True,
                },
            ],
        }
        gamma.fetch_game_events_by_series = AsyncMock(return_value=[nhl_event])

        scanner = MarketScanner(gamma)
        markets = await scanner.discover_sport_markets(NHL_CONFIG)
        assert len(markets) >= 1
        assert markets[0].source == MarketSource.NHL

    @pytest.mark.asyncio
    async def test_discover_sport_markets_soccer(self):
        """discover_sport_markets returns SOCCER markets for Bundesliga."""
        from datetime import datetime, timedelta, timezone
        from unittest.mock import AsyncMock, MagicMock

        from poly24h.discovery.market_scanner import MarketScanner
        from poly24h.models.market import MarketSource
        from poly24h.strategy.sport_config import BUNDESLIGA_CONFIG

        gamma = MagicMock()
        bun_event = {
            "slug": "bun-bay-dor-2026-02-14",
            "enableNegRisk": True,
            "negRiskAugmented": True,
            "endDate": (datetime.now(tz=timezone.utc) + timedelta(hours=12)).isoformat(),
            "markets": [
                {
                    "id": "bun_m1",
                    "question": "Will Bayern Munich win?",
                    "outcomePrices": '[\"0.65\",\"0.35\"]',
                    "clobTokenIds": '[\"yt1\",\"nt1\"]',
                    "volume": "500000",
                    "liquidity": "250000",
                    "endDate": (datetime.now(tz=timezone.utc) + timedelta(hours=12)).isoformat(),
                    "active": True,
                    "closed": False,
                    "acceptingOrders": True,
                },
            ],
        }
        gamma.fetch_game_events_by_series = AsyncMock(return_value=[bun_event])

        scanner = MarketScanner(gamma)
        markets = await scanner.discover_sport_markets(BUNDESLIGA_CONFIG)
        assert len(markets) >= 1
        assert markets[0].source == MarketSource.SOCCER

    @pytest.mark.asyncio
    async def test_discover_nba_markets_still_works(self):
        """Existing discover_nba_markets remains backward-compatible."""
        from datetime import datetime, timedelta, timezone
        from unittest.mock import AsyncMock, MagicMock

        from poly24h.discovery.market_scanner import MarketScanner
        from poly24h.models.market import MarketSource

        gamma = MagicMock()
        nba_event = {
            "slug": "nba-lal-bos-2026-02-14",
            "enableNegRisk": True,
            "negRiskAugmented": True,
            "endDate": (datetime.now(tz=timezone.utc) + timedelta(hours=12)).isoformat(),
            "markets": [
                {
                    "id": "m1",
                    "question": "Lakers vs. Celtics",
                    "outcomePrices": '[\"0.55\",\"0.45\"]',
                    "clobTokenIds": '[\"yt1\",\"nt1\"]',
                    "volume": "50000",
                    "liquidity": "30000",
                    "endDate": (datetime.now(tz=timezone.utc) + timedelta(hours=12)).isoformat(),
                    "active": True,
                    "closed": False,
                    "acceptingOrders": True,
                },
            ],
        }
        gamma.fetch_nba_game_events = AsyncMock(return_value=[nba_event])

        scanner = MarketScanner(gamma)
        markets = await scanner.discover_nba_markets(include_neg_risk=True)
        assert len(markets) >= 1
        assert markets[0].source == MarketSource.NBA


# =============================================================================
# Phase 4: OddsAPIClient multi-sport + 3-way soccer
# =============================================================================


class TestOddsAPIMultiSport:
    """Test multi-sport odds fetching and 3-way devig."""

    def test_devig_three_way(self):
        """devig_three_way normalizes 3 probabilities to sum to 1.0."""
        from poly24h.strategy.odds_api import devig_three_way

        # Example: 40% + 30% + 40% = 110% overround
        fair_h, fair_d, fair_a = devig_three_way(0.40, 0.30, 0.40)
        assert abs(fair_h + fair_d + fair_a - 1.0) < 0.001
        assert abs(fair_h - 0.40 / 1.10) < 0.001
        assert abs(fair_d - 0.30 / 1.10) < 0.001

    def test_devig_three_way_edge_case(self):
        """devig_three_way handles zero total gracefully."""
        from poly24h.strategy.odds_api import devig_three_way

        fair_h, fair_d, fair_a = devig_three_way(0.0, 0.0, 0.0)
        # Should return equal thirds or handle gracefully
        assert fair_h + fair_d + fair_a > 0

    @pytest.mark.asyncio
    async def test_fetch_odds_generic(self):
        """fetch_odds(sport_config) fetches odds for any sport."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from poly24h.strategy.odds_api import OddsAPIClient
        from poly24h.strategy.sport_config import NHL_CONFIG

        client = OddsAPIClient(api_key="test")
        client._fetch_json = AsyncMock(return_value=[
            {
                "id": "g1",
                "home_team": "Boston Bruins",
                "away_team": "Toronto Maple Leafs",
                "commence_time": "2026-02-14T00:00:00Z",
                "bookmakers": [
                    {
                        "key": "pinnacle",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Boston Bruins", "price": -150},
                                    {"name": "Toronto Maple Leafs", "price": 130},
                                ],
                            },
                        ],
                    },
                ],
            },
        ])

        games = await client.fetch_odds(NHL_CONFIG)
        assert len(games) == 1
        assert games[0].home_team == "Boston Bruins"

    @pytest.mark.asyncio
    async def test_fetch_odds_uses_sport_key(self):
        """fetch_odds uses sport_config.odds_api_sport_key in URL."""
        from unittest.mock import AsyncMock

        from poly24h.strategy.odds_api import OddsAPIClient
        from poly24h.strategy.sport_config import BUNDESLIGA_CONFIG

        client = OddsAPIClient(api_key="test")
        client._fetch_json = AsyncMock(return_value=[])

        await client.fetch_odds(BUNDESLIGA_CONFIG)

        # Check URL contains sport key
        call_args = client._fetch_json.call_args
        url = call_args[0][0]
        assert "soccer_germany_bundesliga" in url

    @pytest.mark.asyncio
    async def test_per_sport_cache_isolation(self):
        """Each sport has independent cache."""
        from unittest.mock import AsyncMock

        from poly24h.strategy.odds_api import OddsAPIClient
        from poly24h.strategy.sport_config import BUNDESLIGA_CONFIG, NHL_CONFIG

        client = OddsAPIClient(api_key="test", cache_ttl=300)
        client._fetch_json = AsyncMock(return_value=[])

        # Fetch NHL → cached
        await client.fetch_odds(NHL_CONFIG)
        # Fetch Bundesliga → separate cache, should call API again
        await client.fetch_odds(BUNDESLIGA_CONFIG)

        assert client._fetch_json.call_count == 2

    def test_get_fair_prob_three_way_home_win(self):
        """3-way fair prob for 'Will X win?' uses home win probability."""
        from unittest.mock import MagicMock

        from poly24h.strategy.odds_api import GameOdds, MarketOdds, OddsAPIClient
        from poly24h.strategy.sport_config import BUNDESLIGA_CONFIG

        game = GameOdds(
            game_id="g1",
            home_team="Bayern Munich",
            away_team="Borussia Dortmund",
            commence_time="2026-02-14T15:30:00Z",
            h2h=MarketOdds(outcomes=[
                {"name": "Bayern Munich", "price": -200},
                {"name": "Draw", "price": 350},
                {"name": "Borussia Dortmund", "price": 400},
            ]),
        )

        market = MagicMock()
        market.question = "Will Bayern Munich win?"
        market.id = "m1"

        client = OddsAPIClient()
        prob = client.get_fair_prob_for_market(market, [game], sport_config=BUNDESLIGA_CONFIG)
        # Bayern -200 implied = 0.667, should be devigged and > 0.5
        assert prob is not None
        assert prob > 0.5

    def test_get_fair_prob_three_way_draw(self):
        """3-way fair prob for 'Draw?' uses draw probability."""
        from unittest.mock import MagicMock

        from poly24h.strategy.odds_api import GameOdds, MarketOdds, OddsAPIClient
        from poly24h.strategy.sport_config import BUNDESLIGA_CONFIG

        game = GameOdds(
            game_id="g1",
            home_team="Bayern Munich",
            away_team="Borussia Dortmund",
            commence_time="2026-02-14T15:30:00Z",
            h2h=MarketOdds(outcomes=[
                {"name": "Bayern Munich", "price": -200},
                {"name": "Draw", "price": 350},
                {"name": "Borussia Dortmund", "price": 400},
            ]),
        )

        market = MagicMock()
        market.question = "Will Bayern Munich vs Borussia Dortmund end in a Draw?"
        market.id = "m2"

        client = OddsAPIClient()
        prob = client.get_fair_prob_for_market(market, [game], sport_config=BUNDESLIGA_CONFIG)
        assert prob is not None
        # Draw at +350 implied = 100/450 ≈ 0.222, devigged similar
        assert 0.1 < prob < 0.4

    def test_totals_line_mismatch_returns_none(self):
        """O/U market returns None when Polymarket line != Odds API line."""
        from unittest.mock import MagicMock

        from poly24h.strategy.odds_api import GameOdds, MarketOdds, OddsAPIClient
        from poly24h.strategy.sport_config import BUNDESLIGA_CONFIG

        game = GameOdds(
            game_id="g1",
            home_team="Bayern Munich",
            away_team="Borussia Dortmund",
            commence_time="2026-02-14T15:30:00Z",
            h2h=MarketOdds(outcomes=[
                {"name": "Bayern Munich", "price": -200},
                {"name": "Draw", "price": 350},
                {"name": "Borussia Dortmund", "price": 400},
            ]),
            totals=MarketOdds(outcomes=[
                {"name": "Over", "price": -110, "point": 3.5},
                {"name": "Under", "price": -110, "point": 3.5},
            ]),
        )

        # Polymarket has O/U 1.5 but Odds API has O/U 3.5 → should return None
        market = MagicMock()
        market.question = "Bayern Munich vs Borussia Dortmund: O/U 1.5"
        market.id = "m_ou_mismatch"

        client = OddsAPIClient()
        prob = client.get_fair_prob_for_market(market, [game], sport_config=BUNDESLIGA_CONFIG)
        assert prob is None

    def test_totals_line_match_returns_prob(self):
        """O/U market returns fair prob when lines match."""
        from unittest.mock import MagicMock

        from poly24h.strategy.odds_api import GameOdds, MarketOdds, OddsAPIClient
        from poly24h.strategy.sport_config import BUNDESLIGA_CONFIG

        game = GameOdds(
            game_id="g1",
            home_team="Bayern Munich",
            away_team="Borussia Dortmund",
            commence_time="2026-02-14T15:30:00Z",
            h2h=MarketOdds(outcomes=[
                {"name": "Bayern Munich", "price": -200},
                {"name": "Draw", "price": 350},
                {"name": "Borussia Dortmund", "price": 400},
            ]),
            totals=MarketOdds(outcomes=[
                {"name": "Over", "price": -110, "point": 2.5},
                {"name": "Under", "price": -110, "point": 2.5},
            ]),
        )

        # Lines match: both 2.5
        market = MagicMock()
        market.question = "Bayern Munich vs Borussia Dortmund: O/U 2.5"
        market.id = "m_ou_match"

        client = OddsAPIClient()
        prob = client.get_fair_prob_for_market(market, [game], sport_config=BUNDESLIGA_CONFIG)
        assert prob is not None
        assert 0.3 < prob < 0.7  # -110/-110 devigs to ~0.5


# =============================================================================
# Phase 5: SportsMonitor
# =============================================================================


class TestSportsMonitor:
    """Test generic SportsMonitor."""

    @pytest.mark.asyncio
    async def test_sports_monitor_scan_and_trade(self):
        """SportsMonitor.scan_and_trade() uses sport_config for discovery + odds."""
        from unittest.mock import AsyncMock, MagicMock

        from poly24h.strategy.sports_monitor import SportsMonitor
        from poly24h.strategy.sport_config import NHL_CONFIG

        scanner = MagicMock()
        scanner.discover_sport_markets = AsyncMock(return_value=[])
        scanner.client = MagicMock()
        scanner.client.open = AsyncMock()

        odds_client = MagicMock()
        odds_client.fetch_odds = AsyncMock(return_value=[])

        monitor = SportsMonitor(
            sport_config=NHL_CONFIG,
            odds_client=odds_client,
            market_scanner=scanner,
            position_manager=MagicMock(),
            orderbook_fetcher=MagicMock(),
        )

        stats = await monitor.scan_and_trade()
        assert stats["markets_found"] == 0
        scanner.discover_sport_markets.assert_called_once_with(NHL_CONFIG)

    @pytest.mark.asyncio
    async def test_sports_monitor_uses_config_min_edge(self):
        """SportsMonitor uses sport_config.min_edge."""
        from unittest.mock import MagicMock

        from poly24h.strategy.sports_monitor import SportsMonitor
        from poly24h.strategy.sport_config import BUNDESLIGA_CONFIG

        monitor = SportsMonitor(
            sport_config=BUNDESLIGA_CONFIG,
            odds_client=MagicMock(),
            market_scanner=MagicMock(),
            position_manager=MagicMock(),
            orderbook_fetcher=MagicMock(),
        )

        assert monitor._min_edge == 0.05  # Bundesliga config

    @pytest.mark.asyncio
    async def test_nba_monitor_backward_compat(self):
        """NBAMonitor still works as before (subclass of SportsMonitor)."""
        from unittest.mock import AsyncMock, MagicMock

        from poly24h.strategy.nba_monitor import NBAMonitor

        pm = MagicMock()
        monitor = NBAMonitor(
            odds_client=MagicMock(),
            market_scanner=MagicMock(),
            position_manager=pm,
            orderbook_fetcher=MagicMock(),
        )

        # Core methods still work
        edge_yes, edge_no = monitor.calculate_edges(0.65, 0.58, 0.42)
        assert abs(edge_yes - 0.07) < 0.001


# =============================================================================
# Phase 6: Rate Limiter
# =============================================================================


class TestOddsRateLimiter:
    """Test Odds API rate limiting."""

    def test_can_fetch_when_budget_available(self):
        """can_fetch returns True when budget is available."""
        from poly24h.strategy.odds_rate_limiter import OddsAPIRateLimiter

        limiter = OddsAPIRateLimiter(monthly_budget=500)
        assert limiter.can_fetch("nhl") is True

    def test_cannot_fetch_when_emergency_reserve(self):
        """can_fetch returns False when remaining < emergency threshold."""
        from poly24h.strategy.odds_rate_limiter import OddsAPIRateLimiter

        limiter = OddsAPIRateLimiter(monthly_budget=500, emergency_reserve=50)
        limiter.record_fetch("nhl", remaining=30)
        assert limiter.can_fetch("nhl") is False

    def test_record_fetch_tracks_remaining(self):
        """record_fetch updates remaining count."""
        from poly24h.strategy.odds_rate_limiter import OddsAPIRateLimiter

        limiter = OddsAPIRateLimiter(monthly_budget=500)
        limiter.record_fetch("nhl", remaining=480)
        assert limiter.remaining == 480

    def test_can_fetch_respects_min_interval(self):
        """can_fetch returns False if called too soon for same sport."""
        import time
        from poly24h.strategy.odds_rate_limiter import OddsAPIRateLimiter

        limiter = OddsAPIRateLimiter(monthly_budget=500, min_interval=300)
        limiter.record_fetch("nhl", remaining=480)

        # Immediately after → should be False
        assert limiter.can_fetch("nhl") is False

        # Different sport → should be True
        assert limiter.can_fetch("bundesliga") is True
