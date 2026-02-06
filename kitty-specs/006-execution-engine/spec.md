# Feature Specification: Order Execution Engine

**Feature Branch**: `006-execution-engine`
**Created**: 2026-02-06
**Status**: Draft

## User Scenarios & Testing

### User Story 1 - Order Building (Priority: P1)

감지된 Opportunity를 실제 주문(YES 매수 + NO 매수)으로 변환할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** Opportunity(yes=0.45, no=0.40, size=$200), **When** build_arb_orders(), **Then** YES 매수 주문($0.45, ~222 shares) + NO 매수 주문($0.40, ~250 shares) 생성
2. **Given** Opportunity + max_position_usd=100, **When** build_arb_orders(), **Then** 포지션 사이즈가 $100으로 제한
3. **Given** 주문 생성, **When** to_clob_order(), **Then** py-clob-client 호환 형식 반환

---

### User Story 2 - Order Execution (Priority: P1)

생성된 주문을 Polymarket CLOB API에 제출하고 결과를 추적할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** YES+NO 주문 쌍, **When** execute_arb(), **Then** 두 주문을 순차 제출 + 결과 반환
2. **Given** YES 주문 성공 + NO 주문 실패, **When** execute_arb(), **Then** 부분 실패 상태 반환 + 로깅
3. **Given** API 타임아웃, **When** 10초 초과, **Then** 타임아웃 에러 반환 (크래시 없음)
4. **Given** dry_run=True, **When** execute_arb(), **Then** 실제 API 호출 없이 시뮬레이션 결과 반환

---

### User Story 3 - Order Tracking (Priority: P2)

제출된 주문의 상태(pending/filled/cancelled/expired)를 추적할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** 주문 제출 완료, **When** track_order(order_id), **Then** 현재 상태 반환
2. **Given** 10초 후 미체결, **When** 타임아웃, **Then** 자동 취소 시도

### Edge Cases

- CLOB API rate limit (429) → 재시도 with backoff
- 네트워크 에러 → graceful 처리, 부분 실행 상태 기록
- 잔액 부족 → 에러 반환, 주문 미제출
- YES는 체결됐는데 NO 체결 전 가격 변동 → 부분 실행 리포팅

## Requirements

- **FR-001**: OrderBuilder는 Opportunity → (YES Order, NO Order) 변환
- **FR-002**: 주문 사이즈 = min(opportunity.recommended_size, max_position_usd) / price
- **FR-003**: OrderExecutor는 CLOB API에 주문 제출 (py-clob-client 사용)
- **FR-004**: dry_run 모드에서는 API 호출 없이 mock 결과 반환
- **FR-005**: 모든 API 에러는 로깅 + graceful 처리
- **FR-006**: 주문 타임아웃 10초, 초과 시 자동 취소

## Success Criteria

- **SC-001**: mock CLOB API로 전체 실행 파이프라인 테스트 가능
- **SC-002**: dry_run 모드에서 실제 API 호출 0건
- **SC-003**: 부분 실패 시나리오 테스트 커버
