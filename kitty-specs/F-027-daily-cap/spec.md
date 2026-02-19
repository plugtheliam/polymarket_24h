# F-027: Daily Deployment Cap

## Summary
일일 총 자본 배치 금액 상한을 PositionManager에 추가. 검증 단계에서 $100/day, 확장 단계에서 $3,000/day 등 단계별 자본 통제.

## Motivation
- 현재 PositionManager에는 per-market cap과 cycle budget ratio만 존재
- 일일 총 배치 금액 하드캡이 없어 하루에 과다 배치 가능
- 48H 수익성 검증을 위해 일 $100 상한 필수

## Requirements

### R1: Daily deployment tracking
- `max_daily_deployment_usd` 파라미터 추가 (기본값: 0.0 = 무제한)
- `_daily_deployed` 내부 카운터로 당일 배치 금액 추적
- 자정 UTC 자동 리셋

### R2: Entry gate
- `enter_position()` 호출 시 daily cap 초과 여부 체크
- 초과 시 진입 차단 + 로그 기록
- 부분 진입 허용: 잔여 한도 내에서 축소 진입

### R3: State persistence
- `save_state()` / `load_state()`에 daily tracking 포함
- 봇 재시작 시 당일 배치 금액 유지

## Test Cases (Kent Beck TDD)

### Red Phase
```python
# test_daily_cap.py
def test_daily_cap_allows_within_limit():
    """$100 한도 내에서 진입 허용."""
    pm = PositionManager(bankroll=1000, max_per_market=20, max_daily_deployment_usd=100)
    pos = pm.enter_position("mkt1", "Q?", "YES", 0.50, "2026-02-20T00:00:00Z")
    assert pos is not None

def test_daily_cap_blocks_over_limit():
    """$100 한도 초과 시 진입 차단."""
    pm = PositionManager(bankroll=1000, max_per_market=20, max_daily_deployment_usd=100)
    for i in range(5):  # 5 × $20 = $100
        pm.enter_position(f"mkt{i}", "Q?", "YES", 0.50, "2026-02-20T00:00:00Z")
    pos = pm.enter_position("mkt5", "Q?", "YES", 0.50, "2026-02-20T00:00:00Z")
    assert pos is None  # 차단

def test_daily_cap_resets_at_midnight():
    """자정 UTC 리셋 후 재진입 허용."""

def test_daily_cap_zero_means_unlimited():
    """max_daily_deployment_usd=0 → 무제한."""

def test_daily_cap_partial_entry():
    """잔여 한도 $15일 때 $20 요청 → $15로 축소 진입."""

def test_daily_cap_persists_in_state():
    """save_state/load_state에서 daily tracking 유지."""
```

## Implementation
- File: `src/poly24h/position_manager.py`
- Test: `tests/test_daily_cap.py`

## Acceptance Criteria
- [ ] 모든 테스트 통과
- [ ] `ruff check` 통과
- [ ] 기존 테스트 깨지지 않음
