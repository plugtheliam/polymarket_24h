# poly24h Development Guidelines

## Project Overview
Polymarket 24H Settlement Arbitrage Bot — targets 1-hour crypto and sports markets with 0% fee.
Based on polymarket_trader's execution engine + RARB's market discovery patterns.

## Tech Stack
- Python 3.11+ / asyncio / aiohttp
- py-clob-client (Polymarket CLOB API)
- Gamma API (REST, no auth required for reads)
- pytest / pytest-asyncio / aioresponses (testing)
- ruff (linting)

## Project Structure
```
src/poly24h/          # Main package
tests/                # Test files
kitty-specs/          # Feature specifications
scripts/              # Utility scripts
```

## Commands
```bash
cd /home/liam/workspace/polymarket_24h
pip install -e ".[dev]"          # Install with dev deps
pytest                            # Run all tests
pytest tests/test_models.py       # Run specific test
ruff check src/ tests/            # Lint
```

## Development Style: Kent Beck TDD
1. **Red**: Write a failing test first
2. **Green**: Write minimal code to pass
3. **Refactor**: Clean up while keeping tests green

## Key Conventions
- All async functions use `async def` + `await`
- Data models use `@dataclass` (not Pydantic)
- Prices use `float` for simplicity (Decimal for precision-critical calculations)
- All HTTP calls must handle timeouts and errors gracefully (never crash)
- Feature specs in `kitty-specs/<feature>/spec.md`

## Reference Code
- polymarket_trader: `/home/liam/workspace/polymarket_trader/src/`
- rarb-24h: `/home/liam/workspace/rarb-24h/src/rarb/`
