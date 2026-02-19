# F-031: Production-Ready Sports Live Executor

## Context

현재 `sport_executor.py`(F-030)는 ClobClient를 통한 기본 오더 제출만 구현. 라이브 실행에 필수적인 안전장치가 없음:

1. **오더 확인 미검증** — 제출 후 체결 여부를 확인하지 않음. position_manager에는 "100주 매수 완료"로 기록되지만 실제 체결이 안 됐을 수 있음 → **정산 시 전액 손실**
2. **타임아웃 없음** — CLOB API가 느리면 sports_monitor 전체 스레드가 블록
3. **킬 스위치 미연동** — 일일 손실 한도 초과해도 오더 계속 제출
4. **슬리피지 미추적** — 기대 가격 vs 실제 체결가 비교 없음
5. **재시도 없음** — 네트워크 오류 시 단일 시도 후 포기
6. **포지션 순서 오류** — 포지션 기록(line 244) → 오더 제출(line 256). 오더 실패해도 포지션 이미 기록됨

**참조**: `polymarket_trader`의 성숙한 패턴 (timeout_executor.py, tracker.py, rapid_fire_engine.py)

---

## 구현 계획

### 1. sport_executor.py 강화

**파일**: `src/poly24h/execution/sport_executor.py`

#### 1-1. 오더 확인 폴링 (Critical)
```python
def _poll_order_status(self, order_id: str, timeout_sec: float = 30.0) -> dict:
    """Poll ClobClient.get_order() until filled or timeout."""
    # 500ms 간격, max timeout_sec
    # 반환: {"status": "FILLED"|"OPEN"|"CANCELLED", "size_matched": float, "avg_price": float}
```
- `ClobClient.get_order(order_id)` 사용 (polymarket_trader timeout_executor.py:204-240 참조)
- `size_matched` 필드에서 실제 체결량 확인
- timeout 시 `cancel_order()` 호출

#### 1-2. 오더 취소
```python
def _cancel_order(self, order_id: str) -> bool:
    """Cancel pending GTC order."""
    # ClobClient.cancel(order_id) — 2회 재시도
```
- polymarket_trader timeout_executor.py:242-278 참조

#### 1-3. 재시도 로직
```python
def submit_order(self, ..., max_retries: int = 2) -> dict:
    # 3회 시도 (1 + 2 retry), 0.5s 백오프
    # 응답 검증: isinstance(response, dict) + success 필드 확인
```
- polymarket_trader rapid_fire_engine.py:12303-12325 응답 검증 패턴

#### 1-4. 슬리피지 추적
```python
def submit_order(self, ...) -> dict:
    # 반환값에 추가: "expected_price", "fill_price", "slippage_pct"
    # >2% 시 WARNING 로그
```

#### 1-5. 킬 스위치 연동
```python
def __init__(self, ..., kill_switch=None):
    self._kill_switch = kill_switch

def _submit_live(self, ...):
    if self._kill_switch and self._kill_switch.is_active:
        return {"success": False, "error": "kill_switch_active"}
```

#### 1-6. 타임아웃 보호
- 모든 CLOB API 호출을 10초 타임아웃으로 감쌈
- `socket.setdefaulttimeout()` 또는 try/except TimeoutError

### 2. sports_monitor.py 수정 — 포지션 순서 수정

**파일**: `src/poly24h/strategy/sports_monitor.py`

**현재 (잘못된 순서)**:
```
position = self._pm.enter_position(...)  # 1. 포지션 기록
if self._executor:
    order_result = self._executor.submit_order(...)  # 2. 오더 제출
```

**수정 (올바른 순서)**:
```
# 1. 라이브: 오더 먼저 제출
if self._executor and not self._executor.dry_run:
    order_result = self._executor.submit_order(...)
    if not order_result["success"]:
        return None  # 오더 실패 → 포지션 미기록
    actual_price = order_result.get("fill_price", price)
    actual_shares = order_result.get("size_matched", 0)

# 2. 포지션 기록 (오더 성공 확인 후)
position = self._pm.enter_position(...)
```

### 3. main.py — 킬 스위치 전달

**파일**: `src/poly24h/main.py`

```python
sport_executor = SportExecutor.from_env(
    dry_run=config.dry_run,
    kill_switch=kill_switch,  # 기존 kill_switch 인스턴스 전달
)
```

---

## TDD 테스트 계획

**파일**: `tests/test_sport_executor.py` (기존 5건 + 신규 6건)

| # | 테스트 | 검증 |
|---|--------|------|
| 1 | test_poll_order_filled | get_order() 폴링 → FILLED 상태 반환 |
| 2 | test_poll_order_timeout | 30초 내 미체결 → cancel 호출 |
| 3 | test_retry_on_failure | 첫 시도 실패 → 재시도 성공 |
| 4 | test_kill_switch_blocks | 킬 스위치 활성 시 오더 미제출 |
| 5 | test_slippage_calculated | 기대가격 vs 체결가격 차이 기록 |
| 6 | test_response_validation | non-dict 응답 처리 (crash 없음) |

---

## 변경 파일 요약

| 파일 | 변경 | 유형 |
|------|------|------|
| `src/poly24h/execution/sport_executor.py` | 폴링, 취소, 재시도, 슬리피지, 킬스위치, 타임아웃 | 수정 |
| `src/poly24h/strategy/sports_monitor.py` | 포지션/오더 순서 수정 | 수정 |
| `src/poly24h/main.py` | 킬스위치 전달 | 수정 (1줄) |
| `tests/test_sport_executor.py` | 신규 6건 TDD 테스트 | 수정 |
| `kitty-specs/F-031-live-executor-hardening/spec.md` | 스펙 | 신규 |

---

## 검증

1. `pytest tests/test_sport_executor.py -v` — 11건 전체 통과
2. `pytest tests/test_daily_cap.py tests/test_settlement_priority.py tests/test_validation_throughput.py -v` — 기존 13건 통과
3. 현재 페이퍼 드라이런 재시작하여 dry_run 경로 정상 동작 확인
4. mock ClobClient로 라이브 경로의 폴링/취소/재시도 검증
