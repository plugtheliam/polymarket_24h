# Feature Specification: Market Discovery & Filtering

**Feature Branch**: `003-market-discovery`
**Created**: 2026-02-06
**Status**: Draft

## User Scenarios & Testing

### User Story 1 - Hourly Crypto Discovery (Priority: P1)

1시간 크립토 마켓(BTC, ETH, SOL, XRP)을 자동으로 발견하고 15분 마켓을 제외할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** Gamma API에 crypto 태그 이벤트, **When** discover_hourly_crypto(), **Then** "1 hour"/"hourly" 패턴 매칭 마켓만 반환
2. **Given** "15 min", "15-minute" 포함 마켓, **When** 필터링, **Then** 블랙리스트로 제외
3. **Given** 유동성 $2,000 마켓, **When** 최소 유동성 $3,000, **Then** 제외
4. **Given** 정산 시간 25시간 후 마켓, **When** 24h 필터, **Then** 제외

---

### User Story 2 - Sports Market Discovery (Priority: P1)

NBA, NHL 등 스포츠 마켓을 발견하되 시즌/챔피언 마켓(NegRisk)은 제외할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** Gamma API에 nba 태그 이벤트, **When** discover_sports("nba"), **Then** 개별 경기 마켓 반환
2. **Given** enableNegRisk=true인 시즌 마켓, **When** 필터링, **Then** 제외 (Phase 3에서 별도 처리)
3. **Given** closed=true 마켓, **When** 필터링, **Then** 제외

---

### User Story 3 - Unified Scanner (Priority: P1)

모든 enabled된 소스를 한 번에 스캔하여 통합된 마켓 리스트를 반환할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** hourly_crypto=enabled, nba=enabled, nhl=disabled, **When** discover_all(), **Then** 크립토+NBA 마켓만 반환
2. **Given** 중복 마켓(같은 market_id), **When** 스캔, **Then** 중복 제거
3. **Given** 모든 소스 disabled, **When** discover_all(), **Then** 빈 리스트 반환

### Edge Cases

- Gamma API가 outcomePrices를 JSON 문자열로 반환할 수 있음
- clobTokenIds도 JSON 문자열일 수 있음
- 일부 마켓에 endDate가 없을 수 있음 → 이벤트의 endDate로 폴백
- 마켓이 active이지만 오더북이 빈 경우

## Requirements

- **FR-001**: MarketScanner는 MARKET_SOURCES 설정 기반으로 enabled된 소스만 스캔
- **FR-002**: 1시간 크립토: HOURLY_CRYPTO_PATTERNS 매칭 + BLACKLIST_PATTERNS 제외
- **FR-003**: 스포츠: 24h 이내 정산 + NegRisk 시즌 마켓 제외
- **FR-004**: 모든 마켓은 min_liquidity_usd 이상이어야 함
- **FR-005**: 모든 마켓은 active=true, closed=false이어야 함
- **FR-006**: discover_all()은 모든 소스를 병렬로 스캔해야 함

## Success Criteria

- **SC-001**: RARB의 market_discovery.py 로직을 100% 커버
- **SC-002**: 15분 크립토 마켓이 절대 통과하지 않음 (블랙리스트 테스트)
- **SC-003**: mock Gamma API 응답으로 전체 파이프라인 테스트 가능
