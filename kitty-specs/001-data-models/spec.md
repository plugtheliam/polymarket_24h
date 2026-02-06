# Feature Specification: Data Models & Configuration

**Feature Branch**: `001-data-models`
**Created**: 2026-02-06
**Status**: Draft

## User Scenarios & Testing

### User Story 1 - Market Data Model (Priority: P1)

봇이 Polymarket의 다양한 마켓(1H 크립토, NBA, NHL 등)을 일관된 데이터 구조로 표현할 수 있어야 한다.

**Why this priority**: 모든 다른 컴포넌트(디스커버리, 전략, 실행)가 이 모델에 의존

**Independent Test**: Market 객체를 생성하고 속성에 접근하여 올바른 값을 반환하는지 검증

**Acceptance Scenarios**:

1. **Given** Gamma API의 raw market dict, **When** Market.from_gamma_response()로 파싱, **Then** 모든 필드(id, question, yes_price, no_price, liquidity, end_date, source)가 올바르게 설정
2. **Given** Market 객체, **When** total_cost 프로퍼티 접근, **Then** yes_price + no_price 반환
3. **Given** Market 객체, **When** spread 프로퍼티 접근, **Then** 1.0 - total_cost 반환
4. **Given** 정산 시간이 지난 마켓, **When** is_expired 확인, **Then** True 반환

---

### User Story 2 - Opportunity Data Model (Priority: P1)

감지된 아비트라지 기회를 구조화된 객체로 표현하여 평가·비교·실행할 수 있어야 한다.

**Why this priority**: 전략 엔진과 실행 엔진의 인터페이스

**Acceptance Scenarios**:

1. **Given** Market + 감지 파라미터, **When** Opportunity 생성, **Then** margin, roi_pct, recommended_size가 올바르게 계산
2. **Given** 여러 Opportunity, **When** 정렬, **Then** ROI 기준 내림차순 정렬

---

### User Story 3 - Configuration (Priority: P1)

마켓 소스 정의, API 키, 리스크 파라미터 등을 환경변수와 설정 파일로 관리할 수 있어야 한다.

**Why this priority**: 모든 모듈이 설정에 의존

**Acceptance Scenarios**:

1. **Given** .env 파일에 POLYMARKET_API_KEY 설정, **When** Config 로드, **Then** api_key 필드에 값 반영
2. **Given** MARKET_SOURCES 설정, **When** enabled된 소스만 필터, **Then** hourly_crypto와 nba만 반환
3. **Given** 환경변수 미설정, **When** Config 로드, **Then** 합리적 기본값 사용 + dry_run=True

### Edge Cases

- outcome_prices가 JSON 문자열로 올 수 있음 (Gamma API 특성)
- clobTokenIds가 JSON 문자열로 올 수 있음
- end_date가 없는 마켓은 건너뛰어야 함
- 음수 가격이나 0 가격 마켓 필터링

## Requirements

### Functional Requirements

- **FR-001**: Market 모델은 id, question, source, yes_token_id, no_token_id, yes_price, no_price, liquidity_usd, end_date, event_id, event_title 필드를 가져야 한다
- **FR-002**: MarketSource enum은 HOURLY_CRYPTO, NBA, NHL, TENNIS, SOCCER, ESPORTS를 포함해야 한다
- **FR-003**: ArbType enum은 SINGLE_CONDITION, NEGRISK를 포함해야 한다
- **FR-004**: Opportunity 모델은 market, arb_type, yes_price, no_price, total_cost, margin, roi_pct, recommended_size_usd, detected_at을 가져야 한다
- **FR-005**: Config는 환경변수와 기본값으로 초기화 가능해야 한다
- **FR-006**: MARKET_SOURCES 딕셔너리는 각 소스별 enabled, min_liquidity_usd, min_spread, fee 설정을 포함해야 한다
- **FR-007**: 15분 크립토 마켓 블랙리스트 패턴이 정의되어야 한다

### Key Entities

- **Market**: Polymarket의 단일 바이너리 마켓. YES/NO 토큰 ID, 가격, 유동성, 정산일
- **Opportunity**: 감지된 아비트라지 기회. 마진, ROI, 추천 사이즈
- **MarketSource**: 마켓의 출처 카테고리 (hourly_crypto, nba, ...)
- **ArbType**: 아비트라지 유형 (single_condition, negrisk)
- **Config**: 봇 전체 설정. API 키, 마켓 소스, 리스크 파라미터

## Success Criteria

- **SC-001**: 모든 모델 클래스가 타입 힌팅과 함께 정의됨
- **SC-002**: Gamma API 응답을 Market으로 100% 변환 가능
- **SC-003**: 테스트 커버리지 95%+
