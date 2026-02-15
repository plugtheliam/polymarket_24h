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

## 최우선 참고사항 (Trading Context)

트레이딩 전략, 히스토리, 마일스톤, 리스크 관리 문서를 **반드시** 먼저 확인:

- **TRADING_STRATEGY.md** — 검증된 전략 벤치마크 (계정/지갑 정보, Odds API 예산)
- **TRADING_HISTORY.md** — 실험했던 전략과 설정 히스토리 (시간순 로그)
- **TRADING_MILESTONE.md** — 현재 검증 단계, 가설, 로드맵 (living document)
- **TRADING_RISK_MITIGATION.md** — 역사적 실패 패턴 및 방지 전략

**업데이트 규칙:**
- 새 feature 구현 시: 4개 파일 모두 업데이트
- Dry run 결과 시: HISTORY + MILESTONE + RISK 업데이트
- 전략 변경 시: STRATEGY 업데이트

## Key Conventions
- All async functions use `async def` + `await`
- Data models use `@dataclass` (not Pydantic)
- Prices use `float` for simplicity (Decimal for precision-critical calculations)
- All HTTP calls must handle timeouts and errors gracefully (never crash)
- Feature specs in `kitty-specs/<feature>/spec.md`

## Reference Code
- polymarket_trader: `/home/liam/workspace/polymarket_trader/src/`
- rarb-24h: `/home/liam/workspace/rarb-24h/src/rarb/`
