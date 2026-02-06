# Feature Specification: Dutch Book Arbitrage Detector

**Feature Branch**: `004-dutch-book-detector`
**Created**: 2026-02-06
**Status**: Draft

## User Scenarios & Testing

### User Story 1 - Single Condition Arb Detection (Priority: P1)

바이너리 마켓에서 YES + NO < $1.00인 Dutch Book 기회를 감지할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** Market(yes=0.45, no=0.40), **When** detect(), **Then** Opportunity(margin=0.15, roi=17.6%) 반환
2. **Given** Market(yes=0.50, no=0.50), **When** detect(), **Then** None 반환 (마진 없음)
3. **Given** Market(yes=0.50, no=0.51), **When** detect(), **Then** None 반환 (합 > $1.00)
4. **Given** min_spread=0.02, Market(yes=0.49, no=0.50), **When** detect(), **Then** None (마진 1% < min_spread 2%)

---

### User Story 2 - Orderbook-Based Detection (Priority: P2)

Gamma API 가격이 아닌 실제 오더북의 best ask 기준으로 기회를 평가할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** Gamma 가격 yes=0.45/no=0.40이지만 오더북 best_ask yes=0.48/no=0.43, **When** detect_from_orderbook(), **Then** 오더북 기준(0.91, margin=0.09)으로 평가
2. **Given** 오더북에 ask가 없음, **When** detect_from_orderbook(), **Then** None 반환

---

### User Story 3 - Opportunity Ranking (Priority: P1)

여러 기회를 발견했을 때 최적 순서로 정렬할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** 3개 기회(ROI: 5%, 12%, 8%), **When** rank_opportunities(), **Then** [12%, 8%, 5%] 순서
2. **Given** ROI 동일, 유동성 차이, **When** rank(), **Then** 유동성 높은 것 우선
3. **Given** 빈 리스트, **When** rank(), **Then** 빈 리스트

### Edge Cases

- 가격이 정확히 0인 마켓 (division by zero 방지)
- 음수 가격 마켓 → 스킵
- 가격 합이 정확히 1.0 → 기회 아님

## Requirements

- **FR-001**: detect_single_condition(market, min_spread) → Optional[Opportunity]
- **FR-002**: margin = 1.0 - (yes_price + no_price)
- **FR-003**: roi_pct = (margin / total_cost) * 100
- **FR-004**: min_spread 미만이면 None 반환
- **FR-005**: 가격이 0 이하이면 None 반환
- **FR-006**: rank_opportunities(list) → ROI 내림차순, 유동성 내림차순 정렬

## Success Criteria

- **SC-001**: RARB의 arb_detector.py 로직 + 오더북 기반 확장
- **SC-002**: 경계값 테스트 100% (0, 1.0, 음수, min_spread 경계)
- **SC-003**: 부동소수점 정밀도 문제 없음 (Decimal 사용 고려)
