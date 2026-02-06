# Feature Specification: Risk Management

**Feature Branch**: `008-risk-management`
**Created**: 2026-02-06
**Status**: Draft

## User Scenarios & Testing

### User Story 1 - Daily Loss Limit (Priority: P1)

일일 손실이 설정된 한도를 초과하면 거래를 중단해야 한다.

**Acceptance Scenarios**:

1. **Given** daily_loss_limit=$500, 현재 손실=$400, **When** check_risk(), **Then** approved=True
2. **Given** daily_loss_limit=$500, 현재 손실=$500, **When** check_risk(), **Then** approved=False, reason="daily loss limit"
3. **Given** 자정 경과, **When** check_risk(), **Then** 일일 손실 리셋

---

### User Story 2 - Position Size Limit (Priority: P1)

단일 마켓 및 전체 포트폴리오의 포지션 사이즈를 제한해야 한다.

**Acceptance Scenarios**:

1. **Given** max_position_usd=$1000, 현재 마켓 포지션=$800, **When** 추가 $300 진입 시도, **Then** $200만 허용
2. **Given** max_total_exposure=$5000, 현재 전체=$4500, **When** $1000 진입 시도, **Then** $500만 허용
3. **Given** 포지션 한도 초과, **When** check_risk(), **Then** approved=False

---

### User Story 3 - Cooldown (Priority: P2)

연속 손실 시 자동으로 거래를 일시 중지해야 한다.

**Acceptance Scenarios**:

1. **Given** consecutive_loss_limit=3, 연속 2회 손실, **When** check_risk(), **Then** approved=True
2. **Given** 연속 3회 손실, **When** check_risk(), **Then** approved=False, cooldown_seconds=300
3. **Given** 쿨다운 만료, **When** check_risk(), **Then** approved=True + 카운터 리셋

---

### User Story 4 - Risk Controller (Priority: P1)

모든 리스크 체크를 통합하여 단일 승인/거부 결과를 반환해야 한다.

**Acceptance Scenarios**:

1. **Given** 모든 체크 통과, **When** check_risk(opportunity), **Then** RiskResult(approved=True)
2. **Given** 하나라도 실패, **When** check_risk(opportunity), **Then** RiskResult(approved=False, reasons=[...])
3. **Given** dry_run 모드, **When** check_risk(), **Then** 체크는 실행하되 항상 approved=True (로깅용)

### Edge Cases

- 동시에 여러 기회 발견 시 전체 노출 한도 확인
- 리스크 체크 중 포지션 데이터 변경 → 스냅샷 기반 체크
- 설정 값이 0인 경우 (무제한으로 처리)

## Requirements

- **FR-001**: DailyLossLimiter — 일일 실현 손실 추적 + 한도 체크
- **FR-002**: PositionSizeLimiter — 마켓별/전체 포지션 사이즈 제한
- **FR-003**: CooldownManager — 연속 손실 시 거래 일시 중지
- **FR-004**: RiskController — 모든 리스크 모듈 통합, 단일 체크 결과 반환
- **FR-005**: 모든 거부 사유는 로깅
- **FR-006**: dry_run 모드에서는 체크 실행하되 거부하지 않음

## Success Criteria

- **SC-001**: polymarket_trader의 risk/ 모듈 참고하되 24h 마켓에 맞게 단순화
- **SC-002**: 모든 리스크 시나리오 개별 + 통합 테스트
- **SC-003**: 경계값 테스트 (한도 정확히 도달, 0, 음수 등)
