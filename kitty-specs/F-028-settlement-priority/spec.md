# F-028: Settlement Priority Sorting

## Summary
24H 이내 정산 마켓에 자본을 우선 배치. `scan_and_trade()`에서 마켓을 `end_date` 오름차순 정렬.

## Motivation
- 현재 마켓은 Gamma API `startDate` 순으로 순회
- $100 일일 한도가 Mar 31 정산(시즌 종료) 마켓에 먼저 소진
- 실제 오늘 경기(24H 이내 정산) 마켓에 자본 부족
- 드라이런 결과: Mavericks vs. Bucks (Mar 31) $40 선배치 → 단기 마켓 자본 부족

## Requirements

### R1: Settlement priority sort
- `scan_and_trade()`에서 `filter_stale_markets()` 후 `end_date` 오름차순 정렬
- 정산이 가까운 마켓이 먼저 edge 체크 + 진입 시도
- 기존 min_edge, Kelly sizing 로직 변경 없음

### R2: No regression
- 기존 F-027 daily cap 동작 유지
- stale market filter (< 1H) 유지

## Test Cases (Kent Beck TDD)

### Red Phase
```python
def test_settlement_priority_24h_first():
    """24H 마켓이 30일 마켓보다 먼저 진입."""

def test_settlement_priority_preserves_edge_filter():
    """정렬 후에도 min_edge 필터 유지."""

def test_settlement_priority_with_daily_cap():
    """daily cap $40일 때 24H 마켓 2개 우선 진입, 30일 마켓 차단."""
```

## Implementation
- File: `src/poly24h/strategy/sports_monitor.py` (1줄 추가)
- Test: `tests/test_settlement_priority.py`

## Acceptance Criteria
- [ ] 모든 테스트 통과
- [ ] 기존 test_daily_cap.py 통과
- [ ] ruff check 통과
- [ ] 드라이런에서 24H 마켓 우선 진입 확인
