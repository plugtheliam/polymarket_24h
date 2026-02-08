# Feature Specification: Realistic Dry-Run with Position Management

**Feature Branch**: `018-realistic-dryrun`
**Created**: 2026-02-08
**Status**: Draft
**Priority**: P0 (Blocking live trading validation)

## Problem Statement

현재 드라이런 시뮬레이션은 **모든 시그널에 대해 가상 트레이드를 생성**하고 있음.
- 1개 마켓 (BTC 6PM ET) → 500개 가상 정산 발생
- 실제로는 1개 마켓 = 최대 1~2개 포지션이어야 함
- 이로 인해 P&L 통계가 비현실적 (4시간에 +$27,000?)

## Goal

드라이런이 **실제 라이브 트레이딩과 동일한 환경**을 시뮬레이션하도록 개선:
1. 포지션 관리 (마켓당 최대 1개)
2. 자본 관리 (bankroll, max per market)
3. 중복 진입 방지
4. 정산은 실제 포지션 기반만

---

## User Scenarios & Testing

### User Story 1 - Single Position Per Market (Priority: P1)

**"하나의 마켓에는 하나의 포지션만 잡을 수 있다"**

**Acceptance Scenarios**:

1. **Given** BTC 6PM ET 마켓에 NO 포지션 보유
   **When** 같은 마켓에 YES 시그널 발생
   **Then** 시그널 스킵 (이미 포지션 있음 로그)

2. **Given** 빈 포트폴리오
   **When** BTC 6PM ET NO 시그널 발생 (threshold 만족)
   **Then** 포지션 생성 + paper trade 기록

3. **Given** BTC 6PM ET NO 포지션 보유
   **When** 마켓 정산 (NO 승리)
   **Then** 포지션 청산 + P&L 기록 + 다음 마켓 진입 가능

---

### User Story 2 - Capital Management (Priority: P1)

**"실제 자본처럼 bankroll을 관리한다"**

**Acceptance Scenarios**:

1. **Given** bankroll=$1000, max_per_market=$100
   **When** 시그널 발생
   **Then** $100 베팅 (bankroll 잔액 확인 후)

2. **Given** bankroll=$50, max_per_market=$100
   **When** 시그널 발생
   **Then** $50 베팅 (잔액 한도)

3. **Given** bankroll=$0
   **When** 시그널 발생
   **Then** 스킵 (자본 부족)

4. **Given** 포지션 정산 +$15
   **When** 정산 완료
   **Then** bankroll += $15

---

### User Story 3 - Realistic Settlement Tracking (Priority: P1)

**"정산은 실제 포지션 기반으로만"**

**Acceptance Scenarios**:

1. **Given** 5개 마켓에 각 1개 포지션 (5개 total)
   **When** 정산 사이클
   **Then** 최대 5건 정산 (시그널 수백 개 아님)

2. **Given** 드라이런 1시간 경과 (1개 정산 마켓)
   **When** 통계 확인
   **Then** 정산 1건, P&L = 해당 포지션 결과만

---

### User Story 4 - State Persistence (Priority: P2)

**"드라이런 중지 후 재시작해도 포지션 유지"**

**Acceptance Scenarios**:

1. **Given** 3개 활성 포지션
   **When** 봇 재시작
   **Then** 3개 포지션 복원 (state.json)

2. **Given** state.json에 오래된 포지션
   **When** 정산 완료된 마켓
   **Then** 해당 포지션 정산 처리

---

## Requirements

### Functional Requirements

- **FR-001**: PositionManager 클래스 - 활성 포지션 추적
- **FR-002**: 마켓당 최대 1개 포지션 (config로 조정 가능)
- **FR-003**: Bankroll 관리 - 진입 시 차감, 정산 시 반영
- **FR-004**: max_per_market 한도 적용
- **FR-005**: 중복 마켓 진입 시 스킵 + 로깅
- **FR-006**: 정산 시 활성 포지션 목록에서만 처리
- **FR-007**: State 파일로 포지션 영속화 (poly24h_positions.json)

### Non-Functional Requirements

- **NFR-001**: 기존 시그널 감지 로직 유지 (변경 없음)
- **NFR-002**: 로그 포맷 유지 (SETTLEMENT, SIGNAL 등)
- **NFR-003**: 15분 리포트에 활성 포지션 수 포함

---

## Technical Design

### New Classes

```python
@dataclass
class Position:
    market_id: str
    market_question: str
    side: str  # "YES" or "NO"
    entry_price: float
    size_usd: float
    shares: float
    entry_time: str
    end_date: str
    status: str = "open"  # "open", "settled"

class PositionManager:
    def __init__(self, bankroll: float, max_per_market: float):
        self.bankroll = bankroll
        self.max_per_market = max_per_market
        self._positions: dict[str, Position] = {}  # market_id -> Position
    
    def can_enter(self, market_id: str) -> bool:
        """Check if we can enter this market."""
        if market_id in self._positions:
            return False  # Already have position
        if self.bankroll < 1.0:
            return False  # Not enough capital
        return True
    
    def enter_position(self, market: Market, side: str, price: float) -> Position:
        """Create a new position."""
        size = min(self.max_per_market, self.bankroll)
        shares = size / price
        pos = Position(...)
        self._positions[market.id] = pos
        self.bankroll -= size
        return pos
    
    def settle_position(self, market_id: str, winner: str) -> float:
        """Settle a position and return P&L."""
        pos = self._positions.get(market_id)
        if not pos:
            return 0.0
        
        if pos.side == winner:
            payout = pos.shares * 1.0
            pnl = payout - pos.size_usd
        else:
            pnl = -pos.size_usd
        
        self.bankroll += pos.size_usd + pnl
        del self._positions[market_id]
        return pnl
```

### Integration Points

1. `event_scheduler.py` - _generate_sniper_signals() 수정
   - 시그널 생성 후 PositionManager.can_enter() 체크
   - can_enter=False면 스킵

2. `settlement.py` - settle_open_trades() 수정
   - PositionManager._positions에서만 정산

3. `__main__.py` - 시작 시 PositionManager 초기화
   - State 파일 로드

---

## Success Criteria

- **SC-001**: 4시간 드라이런 후 정산 건수 < 20건 (4마켓 × 4시간 = 16건 예상)
- **SC-002**: 활성 포지션 수 = 마켓 수 이하
- **SC-003**: Bankroll 추적이 정확함 (초기값 - 진입 + 정산)
- **SC-004**: 같은 마켓 중복 진입 0건

---

## Test Plan

### Unit Tests

```python
def test_position_manager_single_position_per_market():
    pm = PositionManager(bankroll=1000, max_per_market=100)
    pm.enter_position(market_id="btc_6pm", side="NO", price=0.45)
    assert not pm.can_enter("btc_6pm")  # Already have position
    assert pm.can_enter("btc_7pm")  # Different market OK

def test_position_manager_bankroll_limit():
    pm = PositionManager(bankroll=50, max_per_market=100)
    pos = pm.enter_position(market_id="btc_6pm", side="NO", price=0.45)
    assert pos.size_usd == 50  # Limited by bankroll
    assert pm.bankroll == 0

def test_settlement_updates_bankroll():
    pm = PositionManager(bankroll=1000, max_per_market=100)
    pm.enter_position(market_id="btc_6pm", side="NO", price=0.40)
    # bankroll = 900
    pnl = pm.settle_position("btc_6pm", winner="NO")
    # Won: shares=250, payout=$250, pnl=+$150
    assert pnl == 150
    assert pm.bankroll == 1150
```

### Integration Tests

```python
def test_dryrun_realistic_settlement_count():
    """4 hours of dryrun should produce ~16 settlements max."""
    # Run dryrun for simulated 4 hours
    # Assert total_settlements < 20
```
