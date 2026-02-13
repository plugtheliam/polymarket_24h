# F-025 NBA Monitor — Implementation Progress

**Last updated**: 2026-02-13 07:09 UTC (16:09 KST / 02:09 EST)
**Branch**: master
**Last commit**: `021cc78` F-025: NBA Monitor TDD GREEN phase (untested)

---

## Current Status: TDD GREEN Phase (In Progress)

### What's Done

1. **RED Phase (Complete)** — Tests written in `tests/test_f025_nba_monitor.py`
   - 16 test cases across 7 test classes
   - All tests confirmed failing with `ModuleNotFoundError` (expected RED state)

2. **GREEN Phase (Partially Complete)** — Implementation files created but NOT YET TESTED
   - `src/poly24h/strategy/nba_monitor.py` — **NEW, CREATED** ✅
   - `src/poly24h/discovery/market_scanner.py` — **MODIFIED** (added `discover_nba_markets()`) ✅
   - Tests have NOT been run against the new code yet

### What's NOT Done

3. **Run tests** — Need to execute `pytest tests/test_f025_nba_monitor.py -v` to verify GREEN
4. **Fix any failures** — If tests fail, fix implementation until all 16 pass
5. **Full test suite** — Run `pytest` to verify no regressions (1017/1021 was baseline)
6. **Phase 3: Integration** — Wire NBAMonitor into `event_scheduler.py` as background asyncio task
7. **Dry run** — Start the bot and verify NBA markets are discovered and paper trades entered
8. **Propose timing** — Suggest dry run duration and live trading start time, wait for user approval

---

## Architecture Overview

### Problem
The bot's hourly IDLE→PRE_OPEN→SNIPE→COOLDOWN loop is crypto-centric. NBA markets exist for hours/days before games and need independent scanning.

### Solution: NBA Independent Monitor
```
Existing (keep): IDLE → PRE_OPEN → SNIPE → COOLDOWN (hourly, crypto)
New (parallel):  NBAMonitor.run_forever() — 5-min scan loop
```

NBAMonitor runs as `asyncio.create_task()` in `event_scheduler.py`, scanning every 5 minutes:
1. Gamma API → discover NBA markets (including negRisk)
2. Odds API → fetch sportsbook odds (Pinnacle preferred)
3. Match Polymarket markets to sportsbook games
4. CLOB orderbook → get real-time Polymarket prices
5. Edge = fair_prob - market_price
6. If edge ≥ 3% → enter paper trade (Half-Kelly sizing)

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

## Files Modified/Created (Committed in `021cc78`)

### New Files
| File | Status | Description |
|------|--------|-------------|
| `src/poly24h/strategy/nba_monitor.py` | **CREATED, UNTESTED** | NBAMonitor class — core scan loop, edge calc, entry logic, per-game caps, Kelly sizing, daily loss limit |
| `tests/test_f025_nba_monitor.py` | **CREATED, UNTESTED** | 16 TDD test cases — edge detection, entry/skip logic, game limits, Kelly, daily loss, full scan cycle, market discovery |
| `kitty-specs/F-025-nba-monitor/spec.md` | CREATED | Feature specification |
| `analysis/F025_NBA_100day_Sprint_20260213_0628UTC.md` | CREATED (already committed in 7c4d16a) | Full analysis document |

### Modified Files
| File | Change | Description |
|------|--------|-------------|
| `src/poly24h/discovery/market_scanner.py` | **MODIFIED, UNTESTED** | Added `discover_nba_markets(include_neg_risk=True)` method — discovers NBA markets without filtering out negRisk events |

### NOT YET Modified (Phase 3)
| File | Planned Change |
|------|----------------|
| `src/poly24h/scheduler/event_scheduler.py` | Add `asyncio.create_task(nba_monitor.run_forever())` in `run()` method |

---

## Test File Details: `tests/test_f025_nba_monitor.py`

### Test Classes and Methods (16 total)

```
TestNBAMonitorEdge (3 tests):
  test_yes_edge_detected      — fair=0.65, YES ask=0.58 → edge_yes=0.07
  test_no_edge_detected       — fair=0.40, NO ask=0.52 → edge_no=0.08
  test_no_edge_either_side    — prices match fair value → no edge

TestNBAMonitorEntry (3 tests):
  test_enters_on_yes_edge     — edge >= 3% → enters paper trade
  test_skips_low_edge         — edge < 3% → returns None
  test_skips_existing_position — can_enter=False → returns None

TestNBAMonitorGameLimit (2 tests):
  test_per_game_limit         — $450 already invested, cap $120 → $50
  test_per_game_exceeded      — game budget exhausted → returns 0

TestNBAMonitorKelly (1 test):
  test_uses_half_kelly        — fraction=0.50 passed to calculate_kelly_size

TestNBAMonitorDailyLoss (2 tests):
  test_daily_loss_limit_blocks — P&L < -$300 → blocked
  test_daily_loss_not_exceeded — P&L > -$300 → allowed

TestNBAMonitorScanCycle (3 tests):
  test_scan_discovers_and_enters — full cycle: discover→odds→match→enter
  test_scan_no_nba_markets       — 0 markets → 0 trades, no crash
  test_scan_no_matching_odds     — markets found but no sportsbook match

TestNBAMarketDiscovery (2 tests):
  test_discover_includes_neg_risk — negRisk NBA markets included
  test_discover_filters_non_nba   — NHL events filtered out
```

### Expected NBAMonitor Interface (from tests)

```python
class NBAMonitor:
    __init__(self, odds_client, market_scanner, position_manager,
             orderbook_fetcher, max_per_game=500, daily_loss_limit=300)

    # Public methods:
    calculate_edges(fair_prob, yes_price, no_price) → (edge_yes, edge_no)
    try_enter(market, side, price, edge) → Position | None  (async)
    cap_for_game(event_id, amount) → float
    get_kelly_size(edge, price) → float
    is_daily_loss_exceeded() → bool
    scan_and_trade() → dict  (async)  # {markets_found, matched, edges_found, trades_entered}
    run_forever() → None  (async)

    # Internal state:
    _game_invested: dict[str, float]
    _daily_pnl: float
    _min_edge: float (0.03 default)
```

### Expected MarketScanner Addition (from tests)

```python
# In market_scanner.py:
async def discover_nba_markets(self, include_neg_risk: bool = True) -> list[Market]:
    # Fetches events by date range, filters slug.startswith("nba-")
    # When include_neg_risk=True, includes negRisk events
    # Returns Market objects with source=MarketSource.NBA
```

---

## Implementation Details: `nba_monitor.py`

The file has been written and contains:

- `NBAMonitor` class with all methods matching test expectations
- `scan_and_trade()`: discovers markets → fetches odds → matches → calculates edges → enters trades
- `calculate_edges()`: edge_yes = fair_prob - yes_price, edge_no = (1-fair_prob) - no_price
- `try_enter()`: checks edge ≥ 3%, can_enter, daily loss, Kelly sizing, per-game cap, then enters
- `cap_for_game()`: caps investment per game event at max_per_game
- `get_kelly_size()`: delegates to position_manager.calculate_kelly_size with fraction=0.50
- `is_daily_loss_exceeded()`: checks if daily_pnl < -daily_loss_limit
- `run_forever()`: 5-min loop calling scan_and_trade

---

## Implementation Details: `market_scanner.py` Changes

Added `discover_nba_markets()` method between `discover_all_sports()` and the backwards-compat sports discovery section:

- Queries Gamma API `fetch_events_by_date_range` for next 48 hours
- Filters events with slug starting with `"nba-"`
- When `include_neg_risk=True` (default), does NOT filter out negRisk events
- This is the key fix: existing `discover_all_sports()` skips negRisk, missing NBA main markets
- Parses markets with `Market.from_gamma_response(raw_mkt, event, MarketSource.NBA)`

---

## Immediate Next Steps (Resume Here)

```bash
# Step 1: Run F-025 tests (should pass — GREEN phase)
cd /home/liam/workspace/polymarket_24h
pytest tests/test_f025_nba_monitor.py -v --tb=short

# Step 2: If failures, fix implementation in:
#   - src/poly24h/strategy/nba_monitor.py
#   - src/poly24h/discovery/market_scanner.py

# Step 3: Run full test suite for regression check
pytest --tb=short

# Step 4: Phase 3 — Integrate into event_scheduler.py
#   Add NBAMonitor as background asyncio task in EventScheduler.run()
#   Import NBAMonitor, ClobOrderbookFetcher, OddsAPIClient
#   Create nba_task = asyncio.create_task(nba_monitor.run_forever())

# Step 5: Run full suite again
pytest --tb=short

# Step 6: Start dry run
#   Kill any existing poly24h process
#   Reset state if needed
#   Start with: setsid python3 -m poly24h >> logs/poly24h_f025.log 2>&1 &
#   Monitor: tail -f logs/poly24h_f025.log

# Step 7: Propose timing to user
#   Dry run: Tonight's NBA games (Feb 13 EST evening = Feb 14 UTC early morning)
#   Live trading: After successful dry run validation
```

---

## Previously Completed (F-024)

- `src/poly24h/strategy/odds_api.py` — Odds API client, American→prob, devig, edge calc, team matching
- `src/poly24h/position_manager.py` — Kelly sizing (calculate_kelly_size), bankroll management
- `src/poly24h/scheduler/event_scheduler.py` — Crypto skip, edge-based entry, Kelly sizing integration
- `tests/test_f024_profitability.py` — 33 tests, all passing
- Bankroll reset to $3,000, state clean

---

## Key Context

- **User language**: Korean (한국어) — user communicates in Korean, code/logs in English
- **Time zone preference**: Always show UTC + KST + EST together
- **Development style**: Kent Beck TDD (RED → GREEN → REFACTOR)
- **Feature spec system**: kitty-specs/<feature>/spec.md
- **Process management**: Use `setsid` + `disown` (nohup alone doesn't survive terminal close)
- **F-024 dry run result**: 0 trades — bot architecture mismatch (hourly crypto loop can't find NBA)
- **Goal**: Verify $100/day NBA profit potential by Feb 17 KST
- **Benchmark**: Suburban-Mailbox trader — 13.2% P&L/Volume, targeting 70% = 9.2%
