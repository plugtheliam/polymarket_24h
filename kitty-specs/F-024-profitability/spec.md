# F-024: Profitability Improvement — Sportsbook Odds Arbitrage

## Summary
Replace static NBA fair value model with real-time sportsbook odds from The Odds API.
Add Kelly Criterion position sizing, disable crypto directional betting, strengthen bankroll management.

## Phases

### Phase 1: The Odds API + NBA Fair Value (Priority)
- New `odds_api.py`: fetch NBA odds, american→prob, devig, match to Polymarket
- Refactor `nba_fair_value.py`: use OddsAPIClient instead of static win rates
- Edge-based entry: min 3% edge (was 5% fixed margin)

### Phase 2: Kelly Criterion Sizing
- `position_manager.py`: `calculate_kelly_size()` with Quarter-Kelly
- Min $10, max min($300, 10% bankroll), cycle budget 30%

### Phase 3: Crypto Disable
- Skip HOURLY_CRYPTO directional entries in `event_scheduler.py`
- Focus capital on NBA

### Phase 4: Bankroll Management
- 30% reserve, 30% cycle budget, 10% single position cap

## Test Plan
- `tests/test_f024_profitability.py` — all phases
- Kent Beck TDD: Red → Green → Refactor per phase

## Config
- `ODDS_API_KEY` in `.env` (already available)
- Starting bankroll: $3,000
