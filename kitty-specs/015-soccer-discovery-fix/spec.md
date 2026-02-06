# Feature Specification: Soccer Discovery Fix + Multi-Sport Expansion

**Feature Branch**: `015-soccer-discovery-fix`
**Created**: 2026-02-06
**Status**: Draft

## Context

현재 soccer discovery가 0 마켓 반환. 원인: NBA와 soccer가 같은 date range 쿼리를 사용하되
별도 호출하므로 중복 데이터를 가져오고, slug 매칭에서 soccer prefix가 제대로 걸리지 않음.
실제 Polymarket 데이터 확인 결과 EPL/Bundesliga/La Liga/EFL/SPL 경기가 다수 존재.

해결: 모든 스포츠를 하나의 date range 쿼리로 통합 → slug prefix로 분류.

## User Scenarios & Testing

### User Story 1 - Unified Sports Discovery (Priority: P1)

하나의 date range 쿼리로 모든 스포츠 경기를 가져온 후 slug prefix로 분류해야 한다.

**Acceptance Scenarios**:

1. **Given** nba+soccer 모두 enabled, **When** discover_all(), **Then** 하나의 date range 쿼리 후 slug로 분류
2. **Given** slug=epl-lee-not-2026-02-06, **When** 분류, **Then** MarketSource.SOCCER
3. **Given** slug=nba-mia-bos-2026-02-06, **When** 분류, **Then** MarketSource.NBA
4. **Given** slug=super-bowl-champion (패턴 불일치), **When** 분류, **Then** 무시

---

### User Story 2 - Liquidity Filter by Sport (Priority: P1)

스포츠별로 다른 최소 유동성 기준을 적용해야 한다.

**Acceptance Scenarios**:

1. **Given** NBA min_liq=$5000, soccer min_liq=$1000, **When** 필터링, **Then** 각각 다른 기준 적용
2. **Given** EPL 경기 liq=$400K, **When** 필터, **Then** 통과
3. **Given** SPL 경기 liq=$800, **When** min_liq=$1000, **Then** 제외

## Requirements

- **FR-001**: discover_all_sports() — 하나의 date range 쿼리로 전체 스포츠 경기 조회
- **FR-002**: slug prefix → MarketSource 매핑 (기존 GAME_SLUG_PREFIXES 사용)
- **FR-003**: 소스별 min_liquidity_usd 적용
- **FR-004**: 기존 discover_sports(sport) API도 유지 (호환성)

## Success Criteria

- **SC-001**: 실제 API로 soccer 경기 발견 (EPL/Bundesliga/La Liga/EFL)
- **SC-002**: NBA + soccer 합쳐서 80+ 마켓 발견
- **SC-003**: 기존 테스트 깨지지 않음
