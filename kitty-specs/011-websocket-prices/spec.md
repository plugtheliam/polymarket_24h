# Feature Specification: WebSocket Real-Time Prices

**Feature Branch**: `011-websocket-prices`
**Created**: 2026-02-06
**Status**: Draft

## User Scenarios & Testing

### User Story 1 - WebSocket Connection (Priority: P1)

Polymarket WebSocket에 연결하여 실시간 오더북 업데이트를 수신할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** 마켓 리스트, **When** subscribe(market_ids), **Then** 해당 마켓들의 가격 업데이트 스트림 수신 시작
2. **Given** 연결 끊김, **When** 감지, **Then** 자동 재연결 (최대 5회, exponential backoff)
3. **Given** 구독 중, **When** unsubscribe(market_id), **Then** 해당 마켓 업데이트 중단

---

### User Story 2 - Price Cache (Priority: P1)

WebSocket에서 받은 최신 가격을 캐시하여 즉시 조회할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** WS 업데이트 수신(market_id, yes=0.45, no=0.40), **When** get_price(market_id), **Then** (0.45, 0.40) 반환
2. **Given** 업데이트 없는 마켓, **When** get_price(market_id), **Then** None 반환
3. **Given** 30초 이상 업데이트 없음, **When** is_stale(market_id), **Then** True

---

### User Story 3 - Scanner Integration (Priority: P1)

기존 HTTP 폴링 방식과 WebSocket 방식을 선택적으로 사용할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** ws_enabled=True, **When** 스캔 사이클, **Then** WS 캐시에서 가격 조회 (HTTP 호출 없음)
2. **Given** ws_enabled=False (기본), **When** 스캔 사이클, **Then** 기존 HTTP 폴링 방식 유지
3. **Given** WS 연결 실패, **When** 폴백, **Then** HTTP 폴링으로 자동 전환

### Edge Cases

- WebSocket 메시지 형식 변경 → graceful 파싱 실패 처리
- 대량 마켓 구독 (100+) → 메모리 관리
- 가격 0이나 비정상 값 → 필터링

## Requirements

- **FR-001**: PriceWebSocket 클래스 — websockets 라이브러리 사용, async context manager
- **FR-002**: subscribe(token_ids), unsubscribe(token_ids)
- **FR-003**: 자동 재연결 (max 5회, backoff 1s→2s→4s→8s→16s)
- **FR-004**: PriceCache — in-memory dict, get_price(), is_stale(), last_update
- **FR-005**: MarketScanner에 use_websocket 옵션 추가
- **FR-006**: WS 실패 시 HTTP 폴백

## Success Criteria

- **SC-001**: mock WebSocket으로 연결/구독/수신/재연결 테스트
- **SC-002**: 기존 HTTP 방식 테스트 깨지지 않음
- **SC-003**: WS↔HTTP 전환 테스트
