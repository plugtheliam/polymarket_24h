# F-025: NBA Independent Monitor — Sportsbook Arbitrage

## Summary
Create an independent NBA monitoring loop that runs parallel to the hourly crypto sniper.
Continuously scans Polymarket NBA markets, compares to sportsbook odds, and enters paper trades when edge >= 3%.

## Architecture
- New `nba_monitor.py`: 5-min scan loop, independent of hourly cycle
- Extend `market_scanner.py`: `discover_nba_markets()` with negRisk support
- Extend `odds_api.py`: Polymarket CLOB price fetching
- Integrate into `event_scheduler.py`: background asyncio task

## Key Parameters
- Scan interval: 300s (5 min)
- Min edge: 3%
- Kelly fraction: 0.50 (Half-Kelly)
- Max per game: $500
- Daily loss limit: $300
- Bankroll: $3,000

## Test Plan
- `tests/test_f025_nba_monitor.py` — Kent Beck TDD
