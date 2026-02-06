# Feature Specification: Performance Dashboard

**Feature Branch**: `013-dashboard`
**Created**: 2026-02-06
**Status**: Draft

## User Scenarios & Testing

### User Story 1 - Console Dashboard (Priority: P1)

매 사이클마다 콘솔에 실시간 성과 대시보드를 출력할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** 사이클 완료, **When** render_dashboard(), **Then** 아래 정보 포함:
   - 현재 시간, 업타임, 모드 (DRY/LIVE)
   - 사이클 #, 스캔된 마켓 수, 발견된 기회 수
   - 활성 포지션 요약 (마켓명, 매수가, 예상 수익)
   - 세션 PnL (실현 + 미실현)
   - 리스크 상태 (일일 손실 잔여, 쿨다운 상태)
2. **Given** 터미널 출력, **When** 렌더링, **Then** ANSI 컬러 + 박스 그리기로 가독성 확보
3. **Given** 기회 없는 사이클, **When** 렌더링, **Then** "Waiting for opportunities..." 표시

---

### User Story 2 - Metrics Collection (Priority: P1)

성과 메트릭을 지속적으로 수집할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** 거래 실행, **When** record_trade(), **Then** 거래 시간, ROI, 비용, 마켓 유형 기록
2. **Given** 메트릭 수집 중, **When** get_stats(), **Then** 평균 ROI, 승률, 마켓별 분포 반환
3. **Given** 1시간 데이터, **When** hourly_summary(), **Then** 시간당 거래 수, PnL, 평균 ROI

---

### User Story 3 - Startup Banner (Priority: P2)

기존 배너를 확장하여 설정 요약 + 리스크 파라미터를 표시해야 한다.

**Acceptance Scenarios**:

1. **Given** 봇 시작, **When** 배너 출력, **Then** 모드, 소스, 리스크 한도, 스캔 간격 표시
2. **Given** --live 모드, **When** 배너, **Then** "⚡ LIVE TRADING" 경고 강조 표시

### Edge Cases

- 터미널 폭이 좁은 경우 → 컴팩트 모드
- 매우 많은 활성 포지션 (20+) → 상위 10개만 표시 + "... and N more"
- 메트릭 데이터 없는 초기 상태

## Requirements

- **FR-001**: MetricsCollector — 거래별 메트릭 수집 + 집계
- **FR-002**: DashboardRenderer — 콘솔 대시보드 렌더링 (ANSI colors)
- **FR-003**: 매 사이클 후 대시보드 자동 출력 (main loop 통합)
- **FR-004**: get_stats() — 평균 ROI, 승률, 총 PnL, 마켓별 분포
- **FR-005**: hourly_summary() — 시간당 요약
- **FR-006**: 향상된 배너 (설정 요약 + 리스크 파라미터)

## Success Criteria

- **SC-001**: 대시보드 렌더링 출력 검증 (문자열 포함 체크)
- **SC-002**: 메트릭 수집 + 집계 정확도 테스트
- **SC-003**: 기존 main loop 테스트 깨지지 않음
