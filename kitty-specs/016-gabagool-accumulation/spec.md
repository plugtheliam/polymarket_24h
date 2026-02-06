# Feature Specification: Gabagool-Style Accumulation Strategy

**Feature Branch**: `016-gabagool-accumulation`
**Created**: 2026-02-06
**Status**: Draft

## Context

Dutch Book 아비트라지(YES+NO<$1)는 Polymarket에서 거의 불가능 — 마켓메이커가 양쪽에 1틱 스프레드를 깔아 합이 항상 $1.01.

polymarket_trader의 Gabagool22 전략 핵심:
1. **Dual-Sided Accumulation**: 양쪽(UP/DOWN) 모두 저가에 지정가 매수 → 균형 포지션 구축
2. **ΔCPP Optimization**: Cost Per Pair를 최소화하는 방향으로 매수 측 선택
3. **CTF Merge**: YES+NO 쌍이 모이면 $1.00으로 병합 → 확정 수익
4. **Spread Filter**: ask_sum < max_spread(1.02)일 때만 축적

1H 마켓에 적응:
- 15분 마켓과 달리 1시간의 여유 → 더 patient한 주문 가능
- 매시간 새 마켓 → 마켓 오픈 초기 미스프라이싱 포착
- 수수료 0% → 마진 전체가 수익

### Reference Code
- `polymarket_trader/src/sniper/micro_gabagool.py` — DualSidedAccumulator (747줄)
- `polymarket_trader/src/sniper/micro_gabagool_engine.py` — MicroGabagoolEngine (233줄)
- `polymarket_trader/src/sniper/merge_manager.py` — MergeManager (587줄)
- `polymarket_trader/src/sniper/ctf_merger.py` — CTF merge (626줄)

## User Scenarios & Testing

### User Story 1 - Dual-Sided Accumulator (Priority: P1)

양쪽(YES/NO)에 지정가 주문을 배치하여 균형 포지션을 구축할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** yes_ask=0.52, no_ask=0.50 (sum=1.02), **When** tick(), **Then** NO 측 매수 추천 (더 싼 쪽)
2. **Given** yes_shares=10, no_shares=5 (불균형), **When** tick(), **Then** NO 측 매수 추천 (균형 복원)
3. **Given** yes_ask=0.55, no_ask=0.55 (sum=1.10), **When** tick(), **Then** None (스프레드 초과, 대기)
4. **Given** 양쪽 10쌍 축적 (CPP=0.98), **When** should_merge(), **Then** True (수익 확정 가능)

---

### User Story 2 - CPP (Cost Per Pair) 최적화 (Priority: P1)

매수 측 선택 시 전체 포지션의 CPP를 최소화하는 방향으로 결정해야 한다.

**Acceptance Scenarios**:

1. **Given** current_cpp=0.97, yes_ask=0.49 → projected_cpp=0.965, no_ask=0.51 → projected_cpp=0.975, **When** tick(), **Then** YES 측 (ΔCPP가 더 낮음)
2. **Given** CPP 동일, yes_shares < no_shares, **When** tick(), **Then** YES (균형 복원 우선)
3. **Given** CPP 동일, 균형, yes_ask < no_ask, **When** tick(), **Then** YES (더 싸니까)

---

### User Story 3 - Merge Trigger (Priority: P1)

YES+NO 쌍이 충분히 모이면 merge(병합)하여 수익을 확정할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** yes=20, no=20 (20쌍), CPP=0.97, **When** check_merge(), **Then** merge 가능, 예상 수익=$0.60 (20 × $0.03)
2. **Given** yes=20, no=15 (15쌍만 가능), **When** check_merge(), **Then** 15쌍 merge 가능
3. **Given** CPP=1.01, **When** check_merge(), **Then** merge 불가 (손실)
4. **Given** dry_run=True, **When** merge(), **Then** 시뮬레이션만 (실제 onchain 호출 없음)

---

### User Story 4 - Market Lifecycle (Priority: P1)

1시간 마켓의 수명 주기에 맞춰 전략을 조정해야 한다.

**Acceptance Scenarios**:

1. **Given** 마켓 오픈 직후 (0-5분), **When** phase 확인, **Then** AGGRESSIVE (적극 축적)
2. **Given** 중반 (5-45분), **When** phase 확인, **Then** NORMAL (ΔCPP 기반 축적)
3. **Given** 마감 임박 (45-55분), **When** phase 확인, **Then** PASSIVE (신규 매수 중단, merge만)
4. **Given** 마감 5분 전, **When** phase 확인, **Then** CLOSE_ONLY (미체결 취소, merge)

### Edge Cases

- 오더북이 한쪽만 있는 경우 → 다른 쪽만 매수 (비대칭 축적)
- 가격이 급변하는 경우 → max_spread 필터로 보호
- merge 실패 시 → 재시도 1회, 그래도 실패 시 정산 대기
- 두 마켓에 동시 진입 시 자본 관리

## Requirements

- **FR-001**: AccumulationStrategy — tick(orderbook) → Optional[Side], ΔCPP 기반
- **FR-002**: AccumulatedPosition — yes_shares, no_shares, yes_cost, no_cost, cpp 추적
- **FR-003**: MergeChecker — should_merge(position) → bool, merge 수익 계산
- **FR-004**: MarketPhaseDetector — 마켓 잔여 시간 기반 phase 분류 (AGGRESSIVE/NORMAL/PASSIVE/CLOSE_ONLY)
- **FR-005**: AccumulationConfig — max_spread, order_size, min_merge_pairs, target_cpp
- **FR-006**: 기존 pipeline에 통합 가능한 인터페이스
- **FR-007**: dry_run 모드에서 전체 시뮬레이션

## Success Criteria

- **SC-001**: mock 오더북으로 축적 → merge 전체 사이클 테스트
- **SC-002**: CPP 최적화 로직 — 항상 CPP가 낮아지는 방향으로 매수
- **SC-003**: 기존 356 테스트 깨지지 않음
- **SC-004**: phase 기반 행동 전환 테스트
