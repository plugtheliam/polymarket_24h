# Feature Specification: Dry-Run Main Loop

**Feature Branch**: `005-dry-run-loop`
**Created**: 2026-02-06
**Status**: Draft

## User Scenarios & Testing

### User Story 1 - Scan-Detect-Log Cycle (Priority: P1)

메인 루프가 주기적으로 마켓을 스캔하고, 아비트라지 기회를 감지하고, 결과를 로깅할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** 봇 시작, **When** 첫 사이클 실행, **Then** 마켓 스캔 → 기회 감지 → 콘솔 출력
2. **Given** 기회 3개 감지, **When** 로깅, **Then** 각 기회의 마켓명, ROI, margin, 유동성 출력
3. **Given** 기회 없음, **When** 사이클 완료, **Then** "No opportunities found" 로깅 + 다음 사이클 대기
4. **Given** scan_interval=60초, **When** 사이클 완료, **Then** 60초 후 다음 사이클

---

### User Story 2 - Graceful Startup & Shutdown (Priority: P1)

봇이 안전하게 시작하고 종료할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** python -m poly24h, **When** 시작, **Then** 배너 출력 + 설정 요약 + 첫 스캔 시작
2. **Given** SIGINT (Ctrl+C), **When** 수신, **Then** 현재 사이클 완료 후 graceful 종료
3. **Given** dry_run=True (기본), **When** 기회 감지, **Then** "DRY RUN" 라벨 + 실행하지 않음

---

### User Story 3 - CLI Arguments (Priority: P2)

커맨드라인으로 주요 설정을 오버라이드할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** --interval 30, **When** 시작, **Then** 30초 스캔 간격
2. **Given** --sources crypto,nba, **When** 시작, **Then** 해당 소스만 스캔
3. **Given** --live, **When** 시작, **Then** dry_run=False (Phase 2에서 실행 엔진 연결)

### Edge Cases

- 마켓 디스커버리 API 실패 시 → 에러 로깅 후 다음 사이클 대기 (크래시 없음)
- 모든 소스가 빈 결과 → 정상 처리
- 매우 짧은 interval (1초) → 최소 10초 강제

## Requirements

- **FR-001**: 메인 루프는 asyncio 기반 무한 루프
- **FR-002**: 각 사이클: discover_all() → detect_all() → log_results()
- **FR-003**: 시작 시 ASCII 배너 + 설정 요약 출력
- **FR-004**: SIGINT/SIGTERM 시 graceful shutdown
- **FR-005**: --interval, --sources, --live CLI 옵션
- **FR-006**: 기본값: interval=60, sources=all_enabled, dry_run=True

## Success Criteria

- **SC-001**: 봇이 시작 → 스캔 → 결과 출력까지 E2E 동작
- **SC-002**: mock API로 전체 사이클 테스트 가능
- **SC-003**: Ctrl+C로 깔끔하게 종료
