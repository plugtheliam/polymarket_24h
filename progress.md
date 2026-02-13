# F-025 NBA Monitor — Implementation Progress

**Last updated**: 2026-02-13 08:00 UTC (17:00 KST / 03:00 EST)
**Branch**: master
**Last commit**: `eae9ae5` F-025: Fix NBA discovery using series_id=10345 API

---

## Current Status: Implementation COMPLETE, Dry Run Active

### All Implementation Done

1. **RED Phase (Complete)** — 16 tests written, all failed as expected
2. **GREEN Phase (Complete)** — All 16 tests passing
3. **Integration (Complete)** — NBAMonitor runs as parallel asyncio task in main.py
4. **NBA Discovery Fixed** — Using `series_id=10345` + `tag_id=100639` API
5. **Bot Running** — PID active, discovering 88 NBA markets from 2 game events
6. **Full Test Suite**: 1032/1037 passed (5 pre-existing failures, 0 new regressions)

### Current Dry Run Status

- **Bot is RUNNING** as background process via `setsid`
- **NBA Markets**: 88 found from 2 game events ✅
- **Odds API**: Returns 0 games — **NBA All-Star Break** (Feb 14-16, no regular season games)
- **Trades**: 0 (expected — no sportsbook odds to compare against)
- **Log file**: `logs/poly24h_f025.log`

### Blocking Issue: NBA All-Star Break

The Odds API shows `basketball_nba` as inactive (only `basketball_nba_championship_winner` active). Regular season resumes around **Feb 20 UTC** (Feb 20 KST / Feb 20 EST). The NBAMonitor will automatically start matching when games resume.

---

## Critical Discovery: Polymarket Sports API

The standard Gamma API event search (`end_date_min`/`end_date_max`) does NOT return NBA game events. They use a **hidden parameter**:

```
GET https://gamma-api.polymarket.com/events?series_id=10345&tag_id=100639&active=true&closed=false
```

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `series_id` | `10345` | NBA 2026 series (undocumented) |
| `tag_id` | `100639` | Game bets only (excludes futures like Champion/MVP) |
| `active` | `true` | Only active events |
| `closed` | `false` | Exclude settled events |

**Discovery source**: `GET https://gamma-api.polymarket.com/sports` returns sport metadata including series IDs.

### NBA Game Event Structure

Each game event (e.g., `nba-dal-lal-2026-02-12`) contains:
- **39-68 markets** per game: moneyline, spread, O/U, 1H lines, player props
- **Sports metadata**: `gameId`, `eventDate`, `startTime`, `teams`, `score`, `live`, `ended`
- **Slug pattern**: `nba-{away}-{home}-YYYY-MM-DD`

---

## Architecture

```
Main Loop (hourly):  IDLE → PRE_OPEN → SNIPE → COOLDOWN (crypto, disabled)
NBA Monitor (5-min):  NBAMonitor.run_forever() — parallel asyncio task
```

### Scan Cycle Flow
1. `gamma_client.fetch_nba_game_events()` → NBA game events (series_id=10345)
2. `odds_api.fetch_nba_odds()` → sportsbook odds (Pinnacle)
3. Match Polymarket markets to sportsbook games by team name
4. `fetcher.fetch_best_asks()` → real-time Polymarket CLOB prices
5. `calculate_edges(fair_prob, yes_price, no_price)` → edge detection
6. If edge ≥ 3% → `try_enter()` → Half-Kelly paper trade

### Key Parameters
| Parameter | Value |
|-----------|-------|
| Scan interval | 300s (5 min) |
| Min edge | 3% |
| Kelly fraction | 0.50 (Half-Kelly) |
| Max per game | $500 |
| Daily loss limit | $300 |
| Bankroll | $3,000 |

---

## Commits (Chronological)

| Hash | Description |
|------|-------------|
| `7c4d16a` | F-024/F-025: Sportsbook odds arbitrage + NBA monitor plan |
| `021cc78` | F-025: NBA Monitor TDD GREEN phase (tests + impl) |
| `913d0cb` | F-025: NBAMonitor integration into main.py |
| `eae9ae5` | F-025: Fix NBA discovery using series_id=10345 API |

---

## Files Created/Modified

### New Files
| File | Description |
|------|-------------|
| `src/poly24h/strategy/nba_monitor.py` | NBAMonitor class — 5-min scan loop, edge calc, entry, Kelly, daily loss |
| `tests/test_f025_nba_monitor.py` | 16 TDD tests — all passing |
| `kitty-specs/F-025-nba-monitor/spec.md` | Feature specification |
| `analysis/F025_NBA_100day_Sprint_20260213_0628UTC.md` | Full analysis document |

### Modified Files
| File | Change |
|------|--------|
| `src/poly24h/discovery/gamma_client.py` | Added `fetch_nba_game_events()` using series_id=10345 |
| `src/poly24h/discovery/market_scanner.py` | `discover_nba_markets()` uses new NBA-specific endpoint |
| `src/poly24h/main.py` | NBAMonitor launched as parallel `asyncio.create_task()` |

---

## Immediate Next Steps (Resume Here)

### Option A: Wait for All-Star Break to End
NBA regular season resumes ~Feb 20. The bot is running and will automatically start working when games return. Monitor with:
```bash
tail -f logs/poly24h_f025.log | grep "NBA SCAN"
```

### Option B: Expand to Other Sports
While waiting for NBA, could add support for other active sports on Polymarket (Winter Olympics has 39 markets). The same `series_id` approach works for other leagues via `GET /sports`.

### Option C: NBA Futures Arbitrage
NBA Champion/MVP/Conference markets are active (30+ markets each). Different strategy — longer-term, no game-level sportsbook comparison.

### When NBA Resumes (~Feb 20):
1. Verify bot discovers new game events automatically
2. Check Odds API returns game odds (should activate when games are scheduled)
3. Monitor for edge detection and paper trade entries
4. After 1-2 days of paper trading, propose live trading timing to user

---

## Key Context

- **User language**: Korean (한국어) — user communicates in Korean, code/logs in English
- **Time zone preference**: Always show UTC + KST + EST together
- **Development style**: Kent Beck TDD (RED → GREEN → REFACTOR)
- **Feature spec system**: kitty-specs/<feature>/spec.md
- **Process management**: Use `setsid` + `disown` (nohup alone doesn't survive terminal close)
- **Goal**: Verify $100/day NBA profit potential by Feb 17 KST (delayed by All-Star Break)
- **Benchmark**: Suburban-Mailbox trader — 13.2% P&L/Volume, targeting 70% = 9.2%
- **Odds API key**: In `.env`, 488 requests remaining (500/month plan)
- **Position state**: $2,700 bankroll, $300 invested, 1 active position
