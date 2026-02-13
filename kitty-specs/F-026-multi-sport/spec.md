# F-026: Multi-Sport Monitor

## Goal
Generalize NBAMonitor to SportsMonitor supporting NHL + 6 European soccer leagues.

## Key Components
1. `SportConfig` dataclass — per-sport configuration
2. `team_data.py` — team name mappings for all sports
3. Generic discovery: `fetch_game_events_by_series()`, `discover_sport_markets()`
4. Generic odds: `fetch_odds(sport_config)`, `devig_three_way()`
5. `SportsMonitor` — parameterized version of NBAMonitor
6. `OddsAPIRateLimiter` — budget management (488 remaining)
7. Multi-monitor launch in `main.py`

## Sports
- NHL: series_id=10346, `ice_hockey_nhl`, 2-way
- Bundesliga: series_id=10194, `soccer_germany_bundesliga`, 3-way
- Serie A: series_id=10203, `soccer_italy_serie_a`, 3-way
- Ligue 1: series_id=10195, `soccer_france_ligue_one`, 3-way
- La Liga: series_id=10193, `soccer_spain_la_liga`, 3-way
- EPL: series_id=10188, `soccer_epl`, 3-way
- UCL: series_id=10204, `soccer_uefa_champs_league`, 3-way

## Backward Compatibility
- NBAMonitor becomes SportsMonitor subclass
- All existing F-025 tests must pass unchanged
