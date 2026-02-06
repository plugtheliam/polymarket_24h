# PRD: Polymarket 24H Arbitrage Bot

## Project Codename: poly24h

---

## 1. Overview

polymarket_trader의 검증된 실행 엔진 모듈을 기반으로, **24시간 이내 정산되는 마켓만 타겟**하는 아비트라지 봇을 구축한다.
15분 크립토 마켓을 완전히 제외하고, **1시간 크립토 + 스포츠(NBA/NHL/Tennis/Soccer/Esports)** 마켓에서 Dutch Book(YES + NO < $1.00) 및 NegRisk(다중 아웃컴) 아비트라지 기회를 자동 감지·실행한다.

### 핵심 원칙

- **24시간 이내 정산 마켓 ONLY** — 자본 잠김 최소화
- **수수료 0% 마켓 ONLY** — 15분 크립토(~3.15% 수수료) 완전 제외
- **polymarket_trader에서 검증된 모듈 재사용** — 실행 엔진, 리스크 관리, 알림
- **새로 작성** — 마켓 디스커버리, 전략 엔진, 메인 루프
- **Kent Beck TDD** — 테스트 먼저, 코드는 나중에

### 참고 소스

| 소스 | 재사용 대상 | 비고 |
|------|-------------|------|
| polymarket_trader | execution/, risk/, alerts/, websocket/, core/ | 검증된 인프라 모듈 |
| rarb-24h | market_discovery.py, market_config.py, arb_detector.py | 마켓 필터링 참고 |

### 수익 목표

| 지표 | 목표 |
|------|------|
| 일일 거래 건수 | 20-37건 |
| 건당 ROI | 1-3% |
| 건당 포지션 사이즈 | $200-$1,000 |
| 일일 수익 | $200-$900 |
| 월간 수익 | $6,000-$27,000 |
| 필요 자본 | $5,000-$15,000 |

---

## 2. Architecture

```
polymarket_24h/
├── src/poly24h/
│   ├── __init__.py
│   ├── main.py                 # 엔트리포인트 + 메인 루프
│   ├── config.py               # 설정 (환경변수, 마켓 소스 정의)
│   │
│   ├── discovery/              # 마켓 디스커버리 (NEW - RARB 참고)
│   │   ├── __init__.py
│   │   ├── gamma_client.py     # Gamma API 클라이언트
│   │   ├── market_filter.py    # 24h 정산 + 수수료 0% 필터
│   │   └── market_scanner.py   # 주기적 마켓 스캔 오케스트레이터
│   │
│   ├── strategy/               # 전략 엔진 (NEW)
│   │   ├── __init__.py
│   │   ├── dutch_book.py       # Single Condition Arb (YES+NO < $1)
│   │   ├── negrisk.py          # Multi-outcome Arb (Σ prices < $1)
│   │   └── opportunity.py      # 기회 평가 + 순위 매기기
│   │
│   ├── execution/              # 주문 실행 (COPY from polymarket_trader)
│   │   ├── __init__.py
│   │   ├── signer.py           # 트랜잭션 서명
│   │   ├── order_builder.py    # 주문 생성
│   │   └── executor.py         # 주문 실행 + 타임아웃
│   │
│   ├── risk/                   # 리스크 관리 (COPY + ADAPT)
│   │   ├── __init__.py
│   │   ├── position_manager.py # 포지션 추적
│   │   ├── loss_limiter.py     # 일일 손실 한도
│   │   └── cooldown.py         # 거래 쿨다운
│   │
│   ├── monitoring/             # 모니터링 + 알림
│   │   ├── __init__.py
│   │   ├── telegram.py         # 텔레그램 알림
│   │   ├── dashboard.py        # 콘솔 대시보드
│   │   └── metrics.py          # 성과 메트릭 수집
│   │
│   └── models/                 # 데이터 모델
│       ├── __init__.py
│       ├── market.py           # Market, MarketSource
│       └── opportunity.py      # Opportunity, ArbType
│
├── tests/
│   ├── conftest.py
│   ├── test_discovery/
│   ├── test_strategy/
│   ├── test_execution/
│   ├── test_risk/
│   └── test_integration/
│
├── scripts/
│   ├── start_bot.sh
│   └── approve_usdc.py
│
├── kitty-specs/                # spec-kitty 스펙 문서
├── .kittify/                   # spec-kitty 설정
├── PRD.md
├── CLAUDE.md
├── pyproject.toml
├── .env.example
└── README.md
```

---

## 3. Feature Breakdown (Phase별)

### Phase 1: Foundation (MVP)
1. **F-001: 데이터 모델 & 설정** — Market, Opportunity, Config 정의
2. **F-002: Gamma API 클라이언트** — Polymarket Gamma API 연동
3. **F-003: 마켓 디스커버리** — 24h 정산 마켓 필터링 (1H 크립토 + 스포츠)
4. **F-004: Dutch Book 감지** — Single Condition Arb (YES+NO < $1.00)
5. **F-005: Dry-Run 메인 루프** — 스캔 → 감지 → 로깅 (실행 없이)

### Phase 2: Execution
6. **F-006: 주문 실행 엔진** — polymarket_trader에서 복사 + 적응
7. **F-007: 포지션 관리** — 포지션 추적, PnL 계산
8. **F-008: 리스크 관리** — 일일 손실 한도, 포지션 한도, 쿨다운
9. **F-009: Live Trading 모드** — Dry-run → Live 전환

### Phase 3: Advanced
10. **F-010: NegRisk 아비트라지** — 다중 아웃컴 마켓 감지 + 실행
11. **F-011: WebSocket 실시간 가격** — HTTP 폴링 → WS 스트림
12. **F-012: 텔레그램 알림** — 기회 감지, 체결, 일일 리포트
13. **F-013: 성과 대시보드** — 콘솔 대시보드 + 메트릭

---

## 4. 마켓 소스 정의

### 4.1 1시간 크립토 (Phase 1)
- 코인: BTC, ETH, SOL, XRP
- 정산: 매시간
- 수수료: 0%
- 일일 마켓 수: ~96개
- 예상 기회: 10-15/day
- 최소 유동성: $3,000

### 4.2 스포츠 (Phase 1)
- NBA: 5-8 경기/일, 최소 유동성 $5,000
- NHL: 4-7 경기/일 (Phase 2)
- Tennis: 10-20 매치/일 (Phase 2)
- Soccer: 2-8 경기/일 (Phase 2)
- Esports: 5-15 매치/일 (Phase 2)

### 4.3 블랙리스트
- 15분 크립토 마켓 (수수료 ~3.15%)
- NegRisk 시즌 마켓 (정산일 불확실) — F-010에서 별도 처리

---

## 5. 기술 스택

- **언어**: Python 3.11+
- **비동기**: asyncio, aiohttp
- **Polymarket API**: py-clob-client, Gamma API (REST)
- **WebSocket**: websockets (Phase 3)
- **테스트**: pytest, pytest-asyncio
- **린팅**: ruff
- **환경**: python-dotenv
- **프록시**: SOCKS5 (geo-restriction 우회)
