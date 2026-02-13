# F-026 Multi-Sport Monitor — Implementation Progress

**Last updated**: 2026-02-13 09:30 UTC (18:30 KST / 04:30 EST)
**Branch**: master
**Last commit**: (pending — F-026 implementation)

---

## Current Status: F-026 Implementation COMPLETE

### F-026 TDD Summary

1. **Step 1: SportConfig + team_data.py** — 24 tests GREEN
   - `SportConfig` dataclass with 8 sport constants (NBA, NHL, 6 soccer leagues)
   - Team name mappings: NHL (32), Bundesliga (18), EPL (20), Serie A (20), Ligue 1 (18), La Liga (20), UCL (36)
   - `get_enabled_sport_configs()` — env-based sport selection via `POLY24H_SPORTS`

2. **Step 2: GammaClient + MarketScanner generalization** — 6 tests GREEN
   - `fetch_game_events_by_series(series_id, tag_id)` — generic version
   - `discover_sport_markets(sport_config)` — generic version
   - `fetch_nba_game_events()` remains as backward-compatible wrapper

3. **Step 3: OddsAPIClient multi-sport + 3-way soccer** — 7 tests GREEN
   - `devig_three_way()` — 3-way overround removal for soccer
   - `fetch_odds(sport_config)` — per-sport cache isolation
   - `get_fair_prob_for_market(market, games, sport_config=None)` — 3-way draw support
   - `build_team_lookup()`, `normalize_team_generic()`, `find_teams_in_text_generic()` — parameterized

4. **Step 4: SportsMonitor + Rate Limiter + main.py** — 7 tests GREEN
   - `SportsMonitor` — parameterized by `SportConfig` (replaces NBAMonitor for multi-sport)
   - `OddsAPIRateLimiter` — shared budget management (500/month, emergency reserve)
   - `main.py` — multi-monitor launch with staggered start (60s intervals)

### Test Results
- **F-026 new tests**: 44/44 GREEN
- **F-025 backward compat**: 16/16 GREEN
- **Full suite**: 1076 passed / 5 pre-existing failures / 0 new regressions

---

## Supported Sports

| Sport | series_id | Odds API Key | Type | Min Edge |
|-------|-----------|-------------|------|----------|
| NBA | 10345 | `basketball_nba` | 2-way | 3% |
| NHL | 10346 | `ice_hockey_nhl` | 2-way | 3% |
| Bundesliga | 10194 | `soccer_germany_bundesliga` | 3-way | 5% |
| Serie A | 10203 | `soccer_italy_serie_a` | 3-way | 5% |
| Ligue 1 | 10195 | `soccer_france_ligue_one` | 3-way | 5% |
| La Liga | 10193 | `soccer_spain_la_liga` | 3-way | 5% |
| EPL | 10188 | `soccer_epl` | 3-way | 5% |
| UCL | 10204 | `soccer_uefa_champs_league` | 3-way | 5% |

## Architecture

```
Main Loop (hourly):  IDLE → PRE_OPEN → SNIPE → COOLDOWN (crypto)
Sport Monitors (5-min each):
  SportsMonitor(NBA_CONFIG)  → discover + fetch odds + edge detect
  SportsMonitor(NHL_CONFIG)  → started +60s
  SportsMonitor(BUNDESLIGA)  → started +120s
  ... (staggered 60s apart)
Rate Limiter: shared OddsAPIRateLimiter (500/month budget)
```

### Scan Cycle Flow (per sport)
1. `scanner.discover_sport_markets(config)` → Polymarket game events via series_id
2. `rate_limiter.can_fetch(sport_name)` → budget check
3. `odds_client.fetch_odds(config)` → sportsbook odds (Pinnacle)
4. `odds_client.get_fair_prob_for_market(market, games, sport_config)` → fair value
5. `fetcher.fetch_best_asks()` → real-time CLOB prices
6. `calculate_edges()` → edge detection
7. If edge >= min_edge → `try_enter()` → Half-Kelly paper trade

---

## Files Created/Modified (F-026)

### New Files
| File | Description |
|------|-------------|
| `src/poly24h/strategy/sport_config.py` | SportConfig dataclass + 8 sport constants |
| `src/poly24h/strategy/team_data.py` | Team name mappings for 7 sports + UCL |
| `src/poly24h/strategy/sports_monitor.py` | SportsMonitor — parameterized NBAMonitor |
| `src/poly24h/strategy/odds_rate_limiter.py` | Odds API rate limiter |
| `tests/test_f026_multi_sport.py` | 44 TDD tests |
| `kitty-specs/F-026-multi-sport/spec.md` | Feature specification |

### Modified Files
| File | Change |
|------|--------|
| `src/poly24h/strategy/odds_api.py` | `devig_three_way()`, `fetch_odds()`, per-sport cache, 3-way fair prob |
| `src/poly24h/discovery/gamma_client.py` | `fetch_game_events_by_series()` generic, NBA wrapper |
| `src/poly24h/discovery/market_scanner.py` | `discover_sport_markets(sport_config)` generic |
| `src/poly24h/main.py` | Multi-monitor launch with staggered start |

---

## Configuration

### POLY24H_SPORTS Environment Variable
Controls which sports are monitored:
```bash
# All sports (default if not set)
POLY24H_SPORTS=

# Specific sports
POLY24H_SPORTS=nhl,bundesliga,serie_a

# Just NHL during testing
POLY24H_SPORTS=nhl
```

### Odds API Budget Management
- 488 requests remaining / 500 monthly
- Rate limiter enforces per-sport min_interval (300s default)
- Emergency reserve: blocks all fetches when remaining < 50
- Recommended: start with 2-3 sports to conserve budget

---

## Immediate Next Steps

### Dry Run Deployment
1. Kill existing bot: `pkill -9 -f poly24h`
2. Set sports: `export POLY24H_SPORTS=nhl,bundesliga,serie_a`
3. Start: `setsid python3 -m poly24h --mode sniper > logs/poly24h_f026.log 2>&1 &`
4. Monitor: `tail -f logs/poly24h_f026.log | grep "SCAN\|ENTRY\|EDGE"`

### Verification Checklist
- [ ] Bot discovers NHL game events via series_id=10346
- [ ] Bot discovers European soccer game events
- [ ] Odds API returns odds for NHL / soccer
- [ ] Team name matching works (Polymarket ↔ Odds API)
- [ ] 3-way devig produces correct fair values for soccer
- [ ] Rate limiter tracks remaining requests
- [ ] Per-sport cache isolation (no cross-contamination)
- [ ] Edge detection and paper trade entry

---

## Key Context

- **User language**: Korean (한국어) — user communicates in Korean, code/logs in English
- **Time zone preference**: Always show UTC + KST + EST together
- **Development style**: Kent Beck TDD (RED → GREEN → REFACTOR)
- **Feature spec system**: kitty-specs/<feature>/spec.md
- **Process management**: Use `setsid` + `disown` (nohup alone doesn't survive terminal close)
- **Odds API key**: In `.env`, 488 requests remaining (500/month plan)
- **Position state**: $2,700 bankroll, $300 invested, 1 active position
