# Feature Specification: Live Trading Mode

**Feature Branch**: `009-live-trading`
**Created**: 2026-02-06
**Status**: Draft

## User Scenarios & Testing

### User Story 1 - Pipeline Integration (Priority: P1)

Dry-run 메인 루프에 실행 엔진 + 리스크 관리를 연결하여 실제 거래가 가능해야 한다.

**Acceptance Scenarios**:

1. **Given** --live 모드, **When** 기회 감지, **Then** risk_check → build_orders → execute → track_position 파이프라인 실행
2. **Given** --live 모드 + risk 거부, **When** 기회 감지, **Then** 주문 미제출 + 거부 사유 로깅
3. **Given** dry_run 모드 (기본), **When** 기회 감지, **Then** 시뮬레이션만 (API 호출 0건)

---

### User Story 2 - Trade Logging (Priority: P1)

모든 거래(시도/성공/실패)를 구조화된 로그로 기록해야 한다.

**Acceptance Scenarios**:

1. **Given** 거래 성공, **When** 로깅, **Then** 마켓명, 가격, 수량, ROI, PnL 기록
2. **Given** 거래 실패, **When** 로깅, **Then** 실패 사유 + 마켓 상태 기록
3. **Given** 1 사이클 완료, **When** 리포트, **Then** 스캔 수, 기회 수, 실행 수, PnL 요약

---

### User Story 3 - Session Summary (Priority: P2)

봇 종료 시 세션 요약을 출력해야 한다.

**Acceptance Scenarios**:

1. **Given** Ctrl+C로 종료, **When** shutdown, **Then** 총 사이클, 총 기회, 총 거래, 총 PnL, 활성 포지션 출력
2. **Given** 활성 포지션 존재, **When** 종료, **Then** "WARNING: N active positions remain" 경고

### Edge Cases

- 봇 시작 시 기존 포지션 확인 (CLOB API에서 로드)
- 실행 중 SIGINT → 현재 주문 완료 후 종료
- 두 기회가 동시에 같은 마켓 → 중복 진입 방지

## Requirements

- **FR-001**: TradingPipeline 클래스가 scan → detect → risk_check → execute → track 통합
- **FR-002**: --live 플래그로 dry_run/live 전환
- **FR-003**: TradeLogger가 모든 거래 이벤트를 구조화 기록
- **FR-004**: CycleSummary로 매 사이클 결과 요약
- **FR-005**: SessionSummary로 종료 시 전체 요약
- **FR-006**: 동일 마켓 중복 진입 방지 (이미 포지션 있으면 스킵)

## Success Criteria

- **SC-001**: mock CLOB API로 전체 파이프라인 E2E 테스트
- **SC-002**: dry_run ↔ live 전환이 깔끔하게 동작
- **SC-003**: 부분 실패, 리스크 거부 등 모든 시나리오 테스트
