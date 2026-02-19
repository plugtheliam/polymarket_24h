# F-030: Sports Live Executor

## Summary
스포츠 단일 사이드(YES or NO) 라이브 오더 실행. py-clob-client를 통한 CLOB limit order 제출 + 슬리피지 로깅.

## Motivation
- executor.py는 현재 placeholder — `_execute_live()`가 로그만 남기고 실제 오더 미제출
- 7일 검증 로드맵 Day 1 (Feb 20)에 마이크로 라이브 시작 필수
- 스포츠는 단일 사이드 진입 (크립토 paired와 다름)

## Requirements

### R1: SportExecutor 클래스
- ClobClient 초기화 (env vars: POLYMARKET_PRIVATE_KEY, API_KEY, API_SECRET, API_PASSPHRASE, FUNDER)
- `submit_order(token_id, side, price, size)` → order_id or None
- dry_run=True 시 CLOB 호출 없이 시뮬레이션 (기존 동작 유지)

### R2: sports_monitor 연동
- sports_monitor.try_enter()에서 dry_run=False 시 CLOB 오더 제출
- 오더 실패 시 포지션 기록하지 않음
- market 객체에서 token_id 추출 (yes_token_id / no_token_id)

### R3: 슬리피지 로깅
- expected_price vs fill 결과 로깅
- `[SLIPPAGE]` 로그 태그

## Test Cases (Kent Beck TDD)

### Red Phase
```python
def test_submit_order_calls_clob():
    """live 모드에서 ClobClient.create_order + post_order 호출."""

def test_dry_run_skips_clob():
    """dry_run=True 시 ClobClient 미호출."""

def test_failed_order_returns_none():
    """CLOB 에러 시 None 반환, 크래시 없음."""

def test_slippage_logged():
    """오더 제출 시 슬리피지 로그 기록."""
```

## Implementation
- File: `src/poly24h/execution/sport_executor.py` (신규)
- Modified: `src/poly24h/strategy/sports_monitor.py` (executor 연동)
- Modified: `src/poly24h/scheduler/event_scheduler.py` (executor 생성)
- Test: `tests/test_sport_executor.py`

## Acceptance Criteria
- [ ] 모든 테스트 통과
- [ ] dry_run 모드 기존 동작 유지 (기존 테스트 통과)
- [ ] ClobClient mock으로 라이브 경로 검증
