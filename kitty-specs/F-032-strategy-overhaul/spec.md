# F-032: Strategy Overhaul — Kill Spread/O-U, Paired Entry Expansion

## Problem
2/19 NBA dry-run: 1W-10L, ROI -42~-73% ($309 invested → -$165 confirmed loss).
Sportsbook devig odds for spread/O-U markets have NO correlation to Polymarket prices.
The "fair value" approach produced illusory edges that don't exist.

## Solution
1. **F-032a**: Block all spread/O-U market entries (return None for fair value)
2. **F-032b**: Add SportsPairedScanner — scan sports markets for CPP < 0.96 arbitrage
3. **F-032c**: Add MoneylineValidationGate — require 20+ dry-run trades before live moneyline

## Requirements

### R1: Spread/O-U Block (F-032a)
- `_get_fair_prob_generic()` returns None for spread/totals market types
- `_get_fair_prob_three_way()` returns None for spread/totals market types
- Moneyline markets continue to work normally

### R2: Sports Paired Scanner (F-032b)
- Scan all sports markets for YES+NO CPP < threshold (default 0.96)
- No fair value needed — pure market structure arbitrage
- Fetch both token orderbooks, check if best_ask_yes + best_ask_no < threshold
- Enter paired positions (both YES and NO) when opportunity found
- Minimum liquidity check per side

### R3: Moneyline Validation Gate (F-032c)
- Block moneyline entries until 20+ dry-run trades completed
- Require positive ROI (>= 0%) from dry-run trades
- Require win rate >= 48%
- Track trade history in JSON file

## Test Plan
- `pytest tests/test_spread_ou_block.py -v` — 3 tests
- `pytest tests/test_sports_paired_scanner.py -v` — 3 tests
- `pytest tests/test_moneyline_gate.py -v` — 3 tests
- `pytest` — all existing tests pass

## Files Changed
- `src/poly24h/strategy/odds_api.py` — spread/totals block
- `src/poly24h/strategy/sports_monitor.py` — market type filter + gate
- `src/poly24h/strategy/sports_paired_scanner.py` — NEW
- `src/poly24h/strategy/moneyline_gate.py` — NEW
- `src/poly24h/main.py` — wire SportsPairedScanner
