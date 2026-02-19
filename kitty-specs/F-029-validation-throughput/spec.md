# F-029: Validation Throughput Optimization

## Summary
48H 검증 속도 향상을 위해 `max_entries_per_cycle`을 env var로 외부화하고 검증 설정 업데이트.

## Motivation
- 현재 max_entries_per_cycle=10 하드코딩 → 스캔당 10건만 진입
- 51개 edge 발견해도 18건만 진입 (35% 전환율)
- 48H 내 30건 이상 정산 필요한데 현재 ~12건 예상
- 병목 해소로 일일 35-40건, 48H 정산 46-53건 목표

## Requirements

### R1: max_entries_per_cycle env var
- `POLY24H_MAX_ENTRIES_PER_CYCLE` env var로 오버라이드
- 기본값 10 유지 (하위 호환)
- event_scheduler.py에서 PositionManager 생성 시 전달

### R2: Validation config 업데이트
- bankroll: $5,000 (paper)
- daily cap: $3,000
- max per market: $50
- max entries per cycle: 30
- daily loss limit: $1,500

## Test Cases (Kent Beck TDD)

### Red Phase
```python
def test_entries_per_cycle_from_env():
    """env var로 cycle 진입 제한 오버라이드."""

def test_entries_per_cycle_default():
    """env var 미설정 시 기본값 10."""
```

## Implementation
- File: `src/poly24h/scheduler/event_scheduler.py` (1줄 추가)
- Config: `.env.sports_validation` 업데이트
- Test: `tests/test_validation_throughput.py`

## Acceptance Criteria
- [ ] 모든 테스트 통과
- [ ] 기존 test_daily_cap + test_settlement_priority 통과
- [ ] 드라이런 첫 스캔에서 진입 >20건 확인
