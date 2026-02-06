# Feature Specification: Gamma API Client

**Feature Branch**: `002-gamma-client`
**Created**: 2026-02-06
**Status**: Draft

## User Scenarios & Testing

### User Story 1 - Fetch Events by Tag (Priority: P1)

Gamma API에서 태그(crypto, nba, nhl 등)별로 이벤트를 조회할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** tag="crypto", **When** fetch_events() 호출, **Then** crypto 태그의 active 이벤트 리스트 반환
2. **Given** API 응답 200, **When** 파싱, **Then** 각 이벤트의 markets 배열 포함
3. **Given** API 타임아웃, **When** 15초 초과, **Then** 빈 리스트 반환 + 에러 로깅

---

### User Story 2 - Fetch Orderbook (Priority: P1)

특정 마켓의 오더북을 조회하여 실제 매수 가능 가격을 확인할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** token_id, **When** fetch_orderbook() 호출, **Then** bids/asks 리스트 반환
2. **Given** 오더북 데이터, **When** best_ask() 호출, **Then** 가장 낮은 ask 가격 반환
3. **Given** 빈 오더북, **When** best_ask() 호출, **Then** None 반환

### Edge Cases

- Gamma API rate limit (429) → exponential backoff
- 네트워크 오류 → 재시도 3회
- 잘못된 JSON 응답 → graceful 처리

## Requirements

- **FR-001**: GammaClient는 aiohttp 세션을 관리하며 async context manager를 지원해야 한다
- **FR-002**: fetch_events(tag, limit)로 이벤트 조회
- **FR-003**: fetch_orderbook(token_id)로 오더북 조회
- **FR-004**: 자동 재시도 (최대 3회, exponential backoff)
- **FR-005**: 타임아웃 15초
- **FR-006**: 모든 HTTP 에러를 로깅하고 빈 결과 반환 (크래시 방지)

## Success Criteria

- **SC-001**: mock 응답으로 100% 테스트 가능
- **SC-002**: 네트워크 에러 시 절대 크래시하지 않음
