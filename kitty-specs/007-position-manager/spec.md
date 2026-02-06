# Feature Specification: Position Manager

**Feature Branch**: `007-position-manager`
**Created**: 2026-02-06
**Status**: Draft

## User Scenarios & Testing

### User Story 1 - Position Tracking (Priority: P1)

마켓별 YES/NO 포지션을 추적하고 잔고 상태를 확인할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** 빈 포지션, **When** add_position(market_id, YES, 100 shares, $0.45), **Then** 해당 마켓 YES=100, cost=$45
2. **Given** YES=100, NO=80, **When** balanced_pairs 확인, **Then** 80쌍 (둘 중 적은 수)
3. **Given** YES=100@$0.45, NO=100@$0.40, **When** locked_profit 계산, **Then** $15 (100 × ($1.00 - $0.85))
4. **Given** 마켓 정산 완료, **When** settle(market_id, winner=YES), **Then** YES shares × $1.00 정산 + 포지션 제거

---

### User Story 2 - Multi-Market Portfolio (Priority: P1)

여러 마켓에 걸친 전체 포트폴리오를 관리할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** 3개 마켓에 포지션, **When** total_invested 확인, **Then** 전체 투자 합계
2. **Given** 포트폴리오, **When** total_locked_profit 확인, **Then** 모든 마켓 locked profit 합계
3. **Given** 포트폴리오, **When** active_positions() 확인, **Then** 0이 아닌 포지션만 반환

---

### User Story 3 - PnL Calculation (Priority: P1)

실현/미실현 손익을 계산할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** YES=100@$0.45 매수 후 정산 YES 승리, **When** PnL 계산, **Then** 실현 수익 = $55 (100×$1 - $45)
2. **Given** YES=100@$0.45, NO=100@$0.40 아비트라지, **When** 정산, **Then** 실현 수익 = $15 (어느 쪽이든)
3. **Given** 미정산 포지션, **When** unrealized_pnl(current_yes=0.50, current_no=0.45), **Then** 현재가 기준 평가

### Edge Cases

- 같은 마켓에 여러 번 진입 (평균 단가 계산)
- 포지션 없는 마켓에 settle 호출 → 무시
- 음수 shares 방지

## Requirements

- **FR-001**: PositionTracker는 마켓별 YES/NO shares, cost 추적
- **FR-002**: balanced_pairs = min(yes_shares, no_shares)
- **FR-003**: locked_profit = balanced_pairs × ($1.00 - avg_yes_cost - avg_no_cost)
- **FR-004**: PortfolioManager는 여러 PositionTracker를 관리
- **FR-005**: settle(market_id, winner) → 실현 PnL 계산 + 포지션 제거
- **FR-006**: 전체 투자액, 전체 locked profit, 전체 실현 PnL 조회

## Success Criteria

- **SC-001**: polymarket_trader의 position/tracker.py 로직 참고하되 단순화
- **SC-002**: 아비트라지 시나리오 (YES+NO 매수 → 정산) E2E 테스트
- **SC-003**: 부동소수점 정밀도 문제 없음
