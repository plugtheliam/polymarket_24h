# Feature Specification: NegRisk Multi-Outcome Arbitrage

**Feature Branch**: `010-negrisk-arb`
**Created**: 2026-02-06
**Status**: Draft

## User Scenarios & Testing

### User Story 1 - Multi-Outcome Market Discovery (Priority: P1)

NegRisk 다중 아웃컴 마켓(3개+ 선택지)을 발견할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** enableNegRisk=true인 이벤트, **When** discover_negrisk_markets(), **Then** 이벤트 내 모든 outcome 마켓을 그룹화하여 반환
2. **Given** 이벤트 내 outcomes=[A:45¢, B:25¢, C:15¢, D:8¢, E:2¢], **When** 파싱, **Then** NegRiskMarket(outcomes=5개, total_prob=0.95) 생성
3. **Given** 24h 이내 정산 아닌 NegRisk 마켓, **When** 필터링, **Then** 제외 (장기 시즌 마켓 등)

---

### User Story 2 - NegRisk Arb Detection (Priority: P1)

모든 아웃컴 YES 가격 합 < $1.00인 경우를 감지할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** outcomes=[0.45, 0.25, 0.15, 0.08, 0.02] (합=0.95), **When** detect_negrisk_arb(), **Then** Opportunity(margin=0.05, roi=5.26%)
2. **Given** outcomes=[0.50, 0.30, 0.21] (합=1.01), **When** detect_negrisk_arb(), **Then** None (기회 없음)
3. **Given** min_spread=0.02, outcomes 합=0.99, **When** detect(), **Then** None (마진 1% < min_spread)
4. **Given** 한 아웃컴의 가격=0, **When** detect(), **Then** 해당 아웃컴 제외하고 나머지로 판단

---

### User Story 3 - NegRisk Order Building (Priority: P1)

NegRisk 아비트라지를 위해 모든 아웃컴의 YES를 매수하는 주문을 생성할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** 5개 아웃컴 NegRisk 기회 + budget=$1000, **When** build_negrisk_orders(), **Then** 5개 YES 매수 주문 생성, 동일 shares 수
2. **Given** shares=100, prices=[0.45, 0.25, 0.15, 0.08, 0.02], **When** 총 비용 계산, **Then** $95 (100 × 0.95)
3. **Given** 한 아웃컴 유동성 부족, **When** build_negrisk_orders(), **Then** 유동성 기준으로 전체 사이즈 축소

### Edge Cases

- 아웃컴 수가 2개인 NegRisk (실질적으로 single condition과 동일) → single condition으로 처리
- 아웃컴 가격이 모두 0인 마켓 → 스킵
- 일부 아웃컴만 유동성 있는 경우 → 전체 스킵 (모든 아웃컴 매수 필요)
- Gamma API에서 NegRisk 마켓 구조가 일반 마켓과 다름 (이벤트 단위 그룹핑)

## Requirements

- **FR-001**: NegRiskMarket 모델 — event_id, outcomes list, total_prob, margin
- **FR-002**: NegRiskOutcome 모델 — market_id, question, token_id, price, liquidity
- **FR-003**: discover_negrisk_markets() — NegRisk 이벤트를 그룹화된 마켓으로 반환
- **FR-004**: detect_negrisk_arb(negrisk_market, min_spread) → Optional[NegRiskOpportunity]
- **FR-005**: build_negrisk_orders(opportunity, budget) → list[Order] (모든 아웃컴 YES)
- **FR-006**: 기존 MarketScanner.discover_all()에 NegRisk 스캔 통합

## Success Criteria

- **SC-001**: NegRisk 감지 + 주문 생성 E2E 테스트
- **SC-002**: 기존 single condition 테스트 깨지지 않음
- **SC-003**: 경계값 (합=1.0, 합>1.0, 2개 아웃컴 등) 완전 커버
