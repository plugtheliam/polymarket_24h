# Feature Specification: Market Open Sniper

**Feature Branch**: `017-market-open-sniper`
**Created**: 2026-02-06
**Status**: Draft

## Context

1시간 크립토 마켓은 매시간 새로 열림. 오픈 직후(0-30초)에 가격이 50/50($0.50/$0.50)에서 시작하는데,
실제 BTC/ETH 가격 방향을 이미 알 수 있는 경우 저가에 매수할 수 있음.

polymarket_trader의 핵심 기능:
- `opportunity_detector.py` — 마켓 오픈 초기 저가 감지
- `predictive_timer.py` — 다음 마켓 오픈 시간 예측
- `pre_connection.py` — 마켓 오픈 전 WebSocket 연결 준비

### 1H 마켓 오픈 패턴
- 매시간 정각에 새 마켓 오픈 (예: 9AM ET, 10AM ET, ...)
- 오픈 직후 YES/NO 모두 $0.50 근처
- Binance BTC/ETH 가격이 이미 Up/Down 방향을 나타내는 경우 한쪽이 $0.45 이하로 내려감
- 이 순간 저가 매수 → 마켓 종료 시 $1.00으로 정산 → 수익

## User Scenarios & Testing

### User Story 1 - Market Open Timing (Priority: P1)

다음 마켓 오픈 시간을 예측하고 준비할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** 현재 14:35 UTC, **When** next_market_open(), **Then** 15:00 UTC (다음 정시)
2. **Given** 현재 14:59 UTC, **When** next_market_open(), **Then** 15:00 UTC (1분 후)
3. **Given** 마켓 오픈 30초 전, **When** is_pre_open_window(), **Then** True
4. **Given** 마켓 오픈 2분 전, **When** is_pre_open_window(), **Then** False

---

### User Story 2 - Early Price Detection (Priority: P1)

마켓 오픈 직후 저가 기회를 감지할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** 오픈 10초 후, yes_ask=$0.42, **When** detect_snipe(), **Then** SniperOpp(side=YES, price=0.42, confidence=HIGH)
2. **Given** 오픈 10초 후, yes_ask=$0.50, no_ask=$0.50, **When** detect_snipe(), **Then** None (방향 불확실)
3. **Given** 오픈 60초 후, yes_ask=$0.42, **When** detect_snipe(), **Then** SniperOpp(confidence=LOW) (시간 지남)
4. **Given** threshold=$0.45, yes_ask=$0.46, **When** detect_snipe(), **Then** None (임계값 미달)

---

### User Story 3 - Binance Price Signal (Priority: P2)

Binance BTC/ETH/SOL/XRP 실시간 가격을 참조하여 방향을 예측할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** BTC 현재가 > 마켓 오픈 시점 가격 (상승 중), **When** signal(), **Then** UP 추천
2. **Given** BTC 현재가 < 마켓 오픈 시점 가격 (하락 중), **When** signal(), **Then** DOWN 추천
3. **Given** 가격 변동 < 0.1%, **When** signal(), **Then** NEUTRAL (확실하지 않음)

---

### User Story 4 - Snipe Execution (Priority: P1)

감지된 기회에 즉시 주문을 제출해야 한다.

**Acceptance Scenarios**:

1. **Given** SniperOpp(YES, $0.42), budget=$500, **When** execute_snipe(), **Then** YES 매수 주문 ($0.42, ~1190 shares)
2. **Given** dry_run=True, **When** execute_snipe(), **Then** 시뮬레이션만
3. **Given** 오더북 깊이 부족 (ask size < 100), **When** execute, **Then** 가능한 만큼만 매수

### Edge Cases

- 마켓 오픈이 지연되는 경우 → 대기 후 재시도
- 여러 코인 마켓이 동시 오픈 → 가장 큰 기회 우선
- 오픈 직후 가격이 빠르게 정상화 → 속도가 핵심 (1-5초 내 감지+실행)

## Requirements

- **FR-001**: MarketOpenTimer — next_open(), is_pre_open_window(), countdown()
- **FR-002**: OpenSniperDetector — detect_snipe(market, orderbook, threshold) → Optional[SniperOpportunity]
- **FR-003**: BinancePriceSignal — get_signal(coin, open_price, current_price) → UP/DOWN/NEUTRAL (P2)
- **FR-004**: SniperExecutor — execute_snipe(opportunity, budget, dry_run) → result
- **FR-005**: 마켓 오픈 30초 전 준비 시작 (pre-connection)
- **FR-006**: 오픈 후 60초까지만 스나이핑 시도 (이후 Accumulation으로 전환)

### Reference Code (polymarket_trader)
- `src/sniper/opportunity_detector.py` — OpportunityDetector, SniperOpportunity
- `src/sniper/predictive_timer.py` — 오픈 타이밍 예측
- `src/sniper/pre_connection.py` — 사전 연결

## Success Criteria

- **SC-001**: 타이밍 계산 정확도 — 매시 정각 오픈 예측
- **SC-002**: mock 오더북으로 스나이핑 감지 + 실행 테스트
- **SC-003**: 기존 테스트 깨지지 않음
