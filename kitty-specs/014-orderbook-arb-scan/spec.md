# Feature Specification: Orderbook-Based Arbitrage Scanning

**Feature Branch**: `014-orderbook-arb-scan`
**Created**: 2026-02-06
**Status**: Draft

## Context

현재 Dutch Book 감지가 Gamma API mid-price (YES+NO=1.00) 기준이라 기회가 0.
실제 아비트라지는 **CLOB 오더북 best ask** 기준으로 찾아야 함.
polymarket_trader의 검증된 패턴을 차용:
- `spread_detector.py` — SpreadDetector, SpreadOpportunity
- `orderbook_source.py` — OrderbookSource Protocol
- `http_orderbook_source.py` — CLOB API 오더북 조회

## User Scenarios & Testing

### User Story 1 - CLOB Orderbook Fetch (Priority: P1)

각 마켓의 YES/NO 토큰에 대해 CLOB API에서 오더북을 조회할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** Market(yes_token_id, no_token_id), **When** fetch_orderbook_pair(), **Then** (yes_book, no_book) 반환
2. **Given** yes_book, **When** best_ask(book), **Then** 최저 ask 가격 반환
3. **Given** 빈 오더북, **When** best_ask(), **Then** None 반환
4. **Given** CLOB API 에러, **When** fetch, **Then** None 반환 + 로깅

---

### User Story 2 - Orderbook Spread Detection (Priority: P1)

YES best_ask + NO best_ask < $1.00인 경우 아비트라지 기회를 감지해야 한다.

**Acceptance Scenarios**:

1. **Given** yes_ask=0.48, no_ask=0.50 (sum=0.98), **When** detect_orderbook_arb(), **Then** Opportunity(margin=0.02, roi=2.04%)
2. **Given** yes_ask=0.51, no_ask=0.50 (sum=1.01), **When** detect, **Then** None (기회 없음)
3. **Given** min_spread=0.015, sum=0.99 (margin=0.01), **When** detect, **Then** None (마진 부족)
4. **Given** 한쪽 오더북 비어있음, **When** detect, **Then** None (best_ask 없음)

---

### User Story 3 - Batch Orderbook Scan (Priority: P1)

여러 마켓을 배치로 스캔하여 기회를 효율적으로 찾아야 한다.

**Acceptance Scenarios**:

1. **Given** 143개 마켓, **When** scan_orderbooks_batch(markets), **Then** 오더북 조회 + 기회 감지 + 순위 정렬
2. **Given** rate limit 고려, **When** 배치 스캔, **Then** 동시 요청 최대 5개 (semaphore)
3. **Given** 일부 실패, **When** 배치 스캔, **Then** 실패 건 스킵, 나머지 결과 반환

---

### User Story 4 - Main Loop Integration (Priority: P1)

메인 루프에서 mid-price 스캔 후 오더북 스캔도 수행해야 한다.

**Acceptance Scenarios**:

1. **Given** 스캔 사이클, **When** enable_orderbook_scan=True, **Then** discover → mid_price_detect → **orderbook_scan** → log
2. **Given** 기회 발견, **When** 로깅, **Then** "[OB]" 라벨 + yes_ask, no_ask, margin, ROI 출력
3. **Given** enable_orderbook_scan=False (기본), **When** 사이클, **Then** mid-price만 (기존 동작 유지)

### Edge Cases

- CLOB API rate limit → semaphore (동시 5개) + exponential backoff
- 오더북 asks 배열이 비어있을 때 → skip
- best_ask 가격이 0일 때 → skip
- asks 정렬 순서가 API마다 다를 수 있음 → 항상 수동 정렬

## Requirements

- **FR-001**: ClobOrderbookFetcher — CLOB API에서 토큰별 오더북 조회
- **FR-002**: fetch_pair(yes_token, no_token) → (yes_best_ask, no_best_ask) | None
- **FR-003**: OrderbookArbDetector — best_ask 기반 spread 감지
- **FR-004**: detect(yes_ask, no_ask, min_spread) → Optional[Opportunity]
- **FR-005**: scan_batch(markets, concurrency=5) → list[Opportunity]
- **FR-006**: --orderbook CLI 플래그 또는 config로 활성화
- **FR-007**: 기존 mid-price detect_all()은 변경 없이 유지

### Reference Code (polymarket_trader)

- `src/sniper/spread_detector.py` — SpreadDetector.detect_spread() 패턴
- `src/sniper/http_orderbook_source.py` — CLOB API 호출 패턴
- `src/sniper/orderbook_result.py` — 결과 타입
- `src/sniper/orderbook_source.py` — OrderbookSource Protocol

## Success Criteria

- **SC-001**: mock CLOB 오더북으로 전체 파이프라인 테스트
- **SC-002**: 기존 317 테스트 깨지지 않음
- **SC-003**: 실제 CLOB API로 143개 마켓 배치 스캔 가능 (E2E)
