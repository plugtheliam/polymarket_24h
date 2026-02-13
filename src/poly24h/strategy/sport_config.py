"""Sport configuration for multi-sport monitor (F-026).

Each sport has a SportConfig dataclass with all parameters needed
for discovery, odds fetching, and trading.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from poly24h.models.market import MarketSource
from poly24h.strategy.team_data import (
    BUNDESLIGA_TEAM_NAMES,
    EPL_TEAM_NAMES,
    LA_LIGA_TEAM_NAMES,
    LIGUE_1_TEAM_NAMES,
    NBA_TEAM_NAMES,
    NHL_TEAM_NAMES,
    SERIE_A_TEAM_NAMES,
    UCL_TEAM_NAMES,
)


@dataclass
class SportConfig:
    """Per-sport configuration for SportsMonitor."""

    name: str                          # "nhl", "bundesliga"
    display_name: str                  # "NHL", "Bundesliga"
    source: MarketSource               # MarketSource.NHL, MarketSource.SOCCER
    odds_api_sport_key: str            # "ice_hockey_nhl"
    series_id: str                     # "10346"
    tag_id: str | None                 # "100639"
    team_names: dict[str, list[str]]   # canonical -> aliases
    slug_prefixes: list[str]           # ["nhl"], ["bun"]
    is_three_way: bool = False         # soccer = True
    scan_interval: int = 300
    min_edge: float = 0.03
    max_per_game: float = 500.0


# =============================================================================
# Sport Constants
# =============================================================================

NBA_CONFIG = SportConfig(
    name="nba",
    display_name="NBA",
    source=MarketSource.NBA,
    odds_api_sport_key="basketball_nba",
    series_id="10345",
    tag_id="100639",
    team_names=NBA_TEAM_NAMES,
    slug_prefixes=["nba"],
    is_three_way=False,
    min_edge=0.03,
)

NHL_CONFIG = SportConfig(
    name="nhl",
    display_name="NHL",
    source=MarketSource.NHL,
    odds_api_sport_key="icehockey_nhl",
    series_id="10346",
    tag_id="100639",
    team_names=NHL_TEAM_NAMES,
    slug_prefixes=["nhl"],
    is_three_way=False,
    min_edge=0.03,
)

BUNDESLIGA_CONFIG = SportConfig(
    name="bundesliga",
    display_name="Bundesliga",
    source=MarketSource.SOCCER,
    odds_api_sport_key="soccer_germany_bundesliga",
    series_id="10194",
    tag_id=None,
    team_names=BUNDESLIGA_TEAM_NAMES,
    slug_prefixes=["bun"],
    is_three_way=True,
    min_edge=0.05,
)

SERIE_A_CONFIG = SportConfig(
    name="serie_a",
    display_name="Serie A",
    source=MarketSource.SOCCER,
    odds_api_sport_key="soccer_italy_serie_a",
    series_id="10203",
    tag_id=None,
    team_names=SERIE_A_TEAM_NAMES,
    slug_prefixes=["ser"],
    is_three_way=True,
    min_edge=0.05,
)

LIGUE_1_CONFIG = SportConfig(
    name="ligue_1",
    display_name="Ligue 1",
    source=MarketSource.SOCCER,
    odds_api_sport_key="soccer_france_ligue_one",
    series_id="10195",
    tag_id=None,
    team_names=LIGUE_1_TEAM_NAMES,
    slug_prefixes=["lig"],
    is_three_way=True,
    min_edge=0.05,
)

LA_LIGA_CONFIG = SportConfig(
    name="la_liga",
    display_name="La Liga",
    source=MarketSource.SOCCER,
    odds_api_sport_key="soccer_spain_la_liga",
    series_id="10193",
    tag_id=None,
    team_names=LA_LIGA_TEAM_NAMES,
    slug_prefixes=["lal"],
    is_three_way=True,
    min_edge=0.05,
)

EPL_CONFIG = SportConfig(
    name="epl",
    display_name="EPL",
    source=MarketSource.SOCCER,
    odds_api_sport_key="soccer_epl",
    series_id="10188",
    tag_id=None,
    team_names=EPL_TEAM_NAMES,
    slug_prefixes=["epl"],
    is_three_way=True,
    min_edge=0.05,
)

UCL_CONFIG = SportConfig(
    name="ucl",
    display_name="UCL",
    source=MarketSource.SOCCER,
    odds_api_sport_key="soccer_uefa_champs_league",
    series_id="10204",
    tag_id=None,
    team_names=UCL_TEAM_NAMES,
    slug_prefixes=["ucl"],
    is_three_way=True,
    min_edge=0.05,
)

# All configured sports
ALL_SPORT_CONFIGS: list[SportConfig] = [
    NBA_CONFIG,
    NHL_CONFIG,
    BUNDESLIGA_CONFIG,
    SERIE_A_CONFIG,
    LIGUE_1_CONFIG,
    LA_LIGA_CONFIG,
    EPL_CONFIG,
    UCL_CONFIG,
]

# Lookup by name
_CONFIG_BY_NAME: dict[str, SportConfig] = {c.name: c for c in ALL_SPORT_CONFIGS}


def get_enabled_sport_configs() -> list[SportConfig]:
    """Get list of enabled sport configs based on POLY24H_SPORTS env var.

    If POLY24H_SPORTS is not set, returns all configs.
    If set, returns only configs whose names are in the comma-separated list.

    Examples:
        POLY24H_SPORTS=nhl,bundesliga → [NHL_CONFIG, BUNDESLIGA_CONFIG]
        POLY24H_SPORTS not set → all configs
    """
    env = os.environ.get("POLY24H_SPORTS", "").strip()
    if not env:
        return list(ALL_SPORT_CONFIGS)

    names = [n.strip().lower() for n in env.split(",") if n.strip()]
    return [_CONFIG_BY_NAME[n] for n in names if n in _CONFIG_BY_NAME]
