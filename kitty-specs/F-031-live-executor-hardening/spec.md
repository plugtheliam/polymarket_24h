# F-031: Production-Ready Sports Live Executor Hardening

## Problem

`SportExecutor` (F-030) submits orders but lacks production safety:
1. No order fill confirmation — position recorded without knowing if order filled
2. No timeout — CLOB API hang blocks entire sports_monitor
3. No kill switch integration — orders continue after loss limit exceeded
4. No slippage tracking — no comparison of expected vs actual fill price
5. No retry — single attempt then give up on network error
6. Wrong sequence — position recorded BEFORE order confirmed (phantom positions)

## Solution

### sport_executor.py Enhancements
- **Order polling**: `_poll_order_status()` — poll `get_order()` every 500ms until FILLED or timeout
- **Order cancel**: `_cancel_order()` — cancel unfilled GTC orders with 2x retry
- **Retry logic**: 3 attempts (1 + 2 retries) with 0.5s backoff
- **Slippage tracking**: Return `expected_price`, `fill_price`, `slippage_pct` in result
- **Kill switch**: Check `kill_switch.is_active` before submitting
- **Timeout**: 10s timeout on all CLOB API calls
- **Response validation**: Handle non-dict responses gracefully

### sports_monitor.py Fix
- **Order-first sequence**: Submit order → confirm fill → record position
- On order failure, return None (no phantom position)

### main.py Wire
- Pass existing `kill_switch` instance to `SportExecutor.from_env()`

## Files Changed
| File | Change |
|------|--------|
| `src/poly24h/execution/sport_executor.py` | Polling, cancel, retry, slippage, kill switch, timeout |
| `src/poly24h/strategy/sports_monitor.py` | Fix position/order sequence |
| `src/poly24h/main.py` | Pass kill_switch to executor |
| `tests/test_sport_executor.py` | 6 new TDD tests |

## Test Plan
| # | Test | Validates |
|---|------|-----------|
| 1 | test_poll_order_filled | get_order() polling returns FILLED status |
| 2 | test_poll_order_timeout_cancels | Timeout triggers cancel_order() |
| 3 | test_retry_on_failure | First attempt fails, retry succeeds |
| 4 | test_kill_switch_blocks_order | Kill switch active prevents submission |
| 5 | test_slippage_calculated | Expected vs fill price delta tracked |
| 6 | test_response_validation_non_dict | Non-dict CLOB response handled safely |

## Acceptance Criteria
- [ ] All 6 new tests pass
- [ ] All 5 existing sport_executor tests pass
- [ ] All existing test suites pass (daily_cap, settlement_priority, validation_throughput)
- [ ] Dry-run path unaffected (no executor calls in dry_run)
- [ ] Kill switch blocks live orders when active
