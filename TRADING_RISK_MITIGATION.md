# Trading Risk Mitigation

## Historical Failure Patterns

### Pattern 1: 3-Way Devig Inaccuracy (F-026) 🔴 CRITICAL
**증상:**
- 무승부 확률 완전 오판 (30.7% edge 계산 → 실제 0% 승률)
- 5건 정산, -$241.99 (-100% ROI)

**실패 사례:**
```
Hoffenheim vs Freiburg (Draw)
- Entry: YES @ $0.25
- Calculated edge: 30.7%
- Outcome: Hoffenheim 3-0 승 → -$50 loss
```

**근본 원인:**
1. **Overround 제거 수식 부정확:**
   ```python
   # WRONG: Additive normalization
   def normalize_three_way(home, draw, away):
       total = home + draw + away
       return home/total, draw/total, away/total
   ```
   - 문제: 확률 편향 제거 실패, multiplicative overround 미고려
2. **Soft bookmaker odds:**
   - Unibet odds ≠ true probability (house bias)
   - Sharp bookmaker (Pinnacle) 필요
3. **Stale market filter 없음:**
   - Jan 13 end_date 마켓에 Feb 13에 진입
   - `end_date > now` 필터 누락

**예방 전략 (Code-level):**
```python
def validate_devig_output(home_prob, draw_prob, away_prob):
    """3-way devig 결과 검증"""
    total = home_prob + draw_prob + away_prob

    # 확률 합 = 1.0
    assert 0.99 < total < 1.01, f"Invalid probability sum: {total}"

    # 무승부 확률 현실적 범위 (5-45%)
    assert 0.05 < draw_prob < 0.45, f"Unrealistic draw prob: {draw_prob}"

    # 각 확률 > 0
    assert all(p > 0 for p in [home_prob, draw_prob, away_prob])

    return True

def filter_stale_markets(markets):
    """과거 end_date 마켓 필터링"""
    now = datetime.now(timezone.utc)
    valid = [m for m in markets if m.end_date > now]

    stale_count = len(markets) - len(valid)
    if stale_count > 0:
        logger.warning(f"Filtered {stale_count} stale markets")

    return valid

def use_sharp_odds_only(odds_response):
    """Sharp bookmaker만 사용"""
    SHARP_BOOKS = ["pinnacle"]  # Pinnacle only
    return [
        book for book in odds_response["bookmakers"]
        if book["key"] in SHARP_BOOKS
    ]
```

**예방 전략 (Process-level):**
1. ✅ Academic paper 검증 (multiplicative devig 방법)
2. ✅ Pinnacle sharp odds only (soft bookmaker 제외)
3. ✅ 2-way markets 먼저 100+ trades 검증
4. ✅ Stale market filter 필수
5. ✅ Sanity checks (확률 범위, edge 범위)

**Status:** 🔴 ACTIVE — 3-way devig 완전 중단, 2-way 검증 후 재설계

**Risk Level:** 🔴 CRITICAL
**Impact:** -$241.99 (-100% ROI)
**Probability:** 100% (if not mitigated)

---

### Pattern 2: Stale Market Entry (F-026) 🟡 HIGH
**증상:**
- 과거 end_date 마켓에 진입 (Jan 13 markets in Feb 13)
- 이미 정산된 마켓 또는 취소된 마켓

**실패 사례:**
```
Market end_date: 2026-01-13 00:00:00 UTC
Entry time: 2026-02-13 10:30:00 UTC
→ 과거 마켓 진입
```

**근본 원인:**
- Gamma API market discovery에 `end_date > now` 필터 누락
- Polymarket에 stale markets 잔존 (정산 전 archived)

**예방 전략 (Code-level):**
```python
def filter_stale_markets(markets):
    """end_date > now 필터링"""
    now = datetime.now(timezone.utc)
    valid_markets = []

    for market in markets:
        # end_date parsing (ISO 8601)
        end_date = datetime.fromisoformat(
            market["end_date"].replace("Z", "+00:00")
        )

        if end_date > now:
            valid_markets.append(market)
        else:
            logger.debug(
                f"Filtered stale market: {market['question']} "
                f"(end_date={end_date})"
            )

    return valid_markets

# Integration in market discovery
async def discover_markets(sport: str):
    raw_markets = await gamma_api.fetch_markets(sport)
    valid_markets = filter_stale_markets(raw_markets)
    logger.info(f"Discovered {len(valid_markets)}/{len(raw_markets)} valid markets")
    return valid_markets
```

**예방 전략 (Process-level):**
1. ✅ `end_date > now` 필터 필수
2. ✅ Market discovery 시 로그 확인 (filtered count)
3. ✅ Dry run에서 end_date 검증

**Status:** ✅ FIXED — F-026 이후 필터 추가

**Risk Level:** 🟡 HIGH
**Impact:** Wasted capital, invalid trades
**Probability:** 0% (mitigated)

---

### Pattern 3: Bankroll Depletion 🟡 HIGH
**증상:**
- 초기 자본: $3,000 → 현재: $900 (-70%)
- 9일 만에 70% 손실

**실패 원인:**
1. **F-026 Soccer 3-way:** -$241.99 (-100% ROI)
2. **검증되지 않은 전략 과다 진입:** NBA 62 trades (미정산)
3. **Position size 과다:** Max $100/position (초기 자본 대비 3.3%)

**예방 전략 (Code-level):**
```python
# Position sizing with bankroll management
MAX_ENTRIES_PER_CYCLE = 10  # 한 스캔당 최대 진입 수
RESERVE_RATIO = 0.30  # 30% 예비 자본
CYCLE_BUDGET_RATIO = 0.30  # 한 스캔당 bankroll의 30%

def calculate_max_position_size(bankroll: float):
    """Bankroll 대비 position size 계산"""
    available = bankroll * (1 - RESERVE_RATIO)
    cycle_budget = available * CYCLE_BUDGET_RATIO
    max_per_position = cycle_budget / MAX_ENTRIES_PER_CYCLE

    # Cap at $50 per position
    return min(max_per_position, 50.0)

def check_bankroll_threshold(bankroll: float):
    """Bankroll threshold 체크"""
    if bankroll < 500:
        logger.critical(f"🚨 EMERGENCY: Bankroll < $500 ({bankroll})")
        raise BankrollEmergency("Stop all trading")

    if bankroll < 1000:
        logger.warning(f"⚠️  Bankroll < $1,000 ({bankroll}) - Conservative mode")
        return "conservative"

    return "normal"

# Integration in trade entry
async def enter_position(market, side, price):
    bankroll = await get_current_bankroll()
    mode = check_bankroll_threshold(bankroll)

    if mode == "conservative":
        # 검증된 전략만 (crypto paired entry)
        if market.sport != "crypto":
            logger.info("Conservative mode: Skip non-crypto")
            return None

    max_size = calculate_max_position_size(bankroll)
    # ... execute trade
```

**예방 전략 (Process-level):**
1. ✅ Bankroll < $500 → 모든 트레이딩 중단
2. ✅ Bankroll < $1,000 → 검증된 전략만 (crypto paired entry)
3. ✅ Position size 동적 조정 (bankroll 대비 1-2%)
4. ✅ 일일 loss limit: -5% of bankroll

**Status:** 🟡 ACTIVE — Conservative mode 적용 중

**Risk Level:** 🟡 HIGH
**Impact:** $2,100 loss (-70%)
**Probability:** 30% (if not mitigated)

---

### Pattern 4: Odds API Budget Depletion 🟢 MITIGATED
**증상:**
- 초기: 6 requests/scan (unsustainable)
- 예산: 500 requests 한도

**실패 원인:**
- 각 sport마다 individual API call (NHL, Bundesliga, Serie A → 3 sports × 2 = 6 requests)
- Staggered scan으로 중복 fetch

**예방 전략 (FIXED in F-026):**
```python
# BEFORE: 6 requests/scan
for sport in ["nhl", "bundesliga", "seriea"]:
    for team in ["home", "away"]:
        odds = await odds_api.fetch(sport, team)  # 6 requests

# AFTER: 2 requests/scan
sports_batch = ["nhl", "soccer_germany_bundesliga", "soccer_italy_serie_a"]
odds_bulk = await odds_api.fetch_batch(sports_batch)  # 1 request
# ... process odds

# Emergency reserve check
async def check_odds_api_budget():
    remaining = await odds_api.get_remaining_requests()

    if remaining < 50:
        logger.critical(f"🚨 Odds API budget < 50 ({remaining})")
        raise OddsAPIEmergency("Stop all API fetches")

    if remaining < 100:
        logger.warning(f"⚠️  Odds API budget < 100 ({remaining})")
        # Use cached odds only
        return "cache_only"

    return "normal"
```

**예방 전략 (Process-level):**
1. ✅ Batch fetch (6 → 2 requests/scan)
2. ✅ Emergency reserve: remaining < 50 → stop
3. ✅ Cache-only mode: remaining < 100
4. ✅ 일일 모니터링 (remaining count)

**Status:** 🟢 RESOLVED — F-026에서 최적화 완료

**Risk Level:** 🟢 MITIGATED
**Impact:** Minimal (488/500 remaining)
**Probability:** 5% (with mitigation)

---

### Pattern 5: Duplicate Entry Bug (F-023) 🟢 RESOLVED
**증상:**
- Spread/Over-Under 마켓 중복 진입
- 동일 event에 여러 positions

**실패 원인:**
- Market type 필터링 누락
- Spread markets는 moneyline과 별도 마켓으로 인식

**예방 전략 (FIXED in F-023):**
```python
# Market type restriction
RESTRICTED_TYPES = ["Over/Under", "Spread"]

def filter_moneyline_only(markets):
    """Moneyline markets만 허용"""
    return [
        m for m in markets
        if not any(rt in m["question"] for rt in RESTRICTED_TYPES)
    ]

# Integration in market discovery
async def discover_nba_markets():
    raw_markets = await gamma_api.fetch_markets("nba")
    moneyline_markets = filter_moneyline_only(raw_markets)
    logger.info(
        f"Filtered {len(raw_markets) - len(moneyline_markets)} "
        f"non-moneyline markets"
    )
    return moneyline_markets
```

**Status:** 🟢 RESOLVED — F-023에서 수정 완료

**Risk Level:** 🟢 RESOLVED
**Impact:** None (fixed)
**Probability:** 0% (fixed)

---

## Emergency Protocols

### Protocol 1: Bankroll < $500 🚨 CRITICAL
**트리거:**
- Current bankroll < $500

**액션:**
1. 즉시 모든 신규 진입 중단
2. 기존 포지션 정산 대기 (forced close 없음)
3. 손실 원인 분석 (로그, 트레이드 히스토리)
4. Dry run 모드로 전환 (live trading 중단)

**복구 조건:**
- Bankroll > $1,000 (추가 입금 또는 정산 수익)
- Root cause 분석 완료
- 검증된 전략만 재개 (crypto paired entry)

**예시 코드:**
```python
async def emergency_stop():
    logger.critical("🚨 EMERGENCY PROTOCOL 1: Bankroll < $500")

    # Stop all monitors
    await stop_all_monitors()

    # Log all open positions
    positions = await position_manager.get_all_positions()
    logger.info(f"Open positions: {len(positions)}")

    # Wait for settlements
    logger.info("Waiting for settlements... (manual intervention required)")

    # Analyze losses
    await analyze_loss_sources()
```

---

### Protocol 2: Win Rate < 30% over 50 Trades 🟡 HIGH
**트리거:**
- Win rate < 30% after 50 settled trades

**액션:**
1. 즉시 live trading 일시 중단
2. Dry run 모드로 전환 (paper trading)
3. Fair value model 재검증
4. Strategy backtesting (과거 데이터)

**복구 조건:**
- Dry run에서 win rate > 40% over 30 trades
- Model validation 통과
- User approval for live resume

**예시 코드:**
```python
async def check_win_rate_protocol():
    stats = await get_trade_stats(settled_only=True)

    if stats["total_trades"] >= 50 and stats["win_rate"] < 0.30:
        logger.warning(
            f"🟡 PROTOCOL 2: Win rate {stats['win_rate']:.1%} < 30%"
        )

        # Switch to dry run
        await set_mode("dry_run")

        # Re-validate model
        await revalidate_fair_value_model()

        logger.info("Switched to dry run mode - manual approval required")
```

---

### Protocol 3: Odds API Budget < 50 🟡 HIGH
**트리거:**
- Remaining requests < 50

**액션:**
1. 즉시 모든 Odds API fetch 중단
2. Cache-only mode 전환 (stale odds 허용)
3. Odds API budget 구매 또는 대기

**복구 조건:**
- Budget > 100 (refill)
- 또는 다음 달 1일 (reset)

**예시 코드:**
```python
async def check_odds_api_protocol():
    remaining = await odds_api.get_remaining_requests()

    if remaining < 50:
        logger.critical(f"🚨 PROTOCOL 3: Odds API budget < 50 ({remaining})")

        # Block all fetches
        await odds_api.set_mode("blocked")

        # Use cached odds only
        logger.info("Using cached odds only - API fetches blocked")

        return "blocked"

    elif remaining < 100:
        logger.warning(f"⚠️  Odds API budget < 100 ({remaining})")
        return "cache_only"

    return "normal"
```

---

## Risk Monitoring Checklist

### Daily Checks
- [ ] Bankroll > $500 (CRITICAL threshold)
- [ ] Odds API budget > 50 (CRITICAL threshold)
- [ ] Win rate > 30% (if 50+ trades)
- [ ] No losing streaks > 5 consecutive

### Weekly Checks
- [ ] Bankroll trend (growth vs depletion)
- [ ] Strategy performance (crypto vs sports)
- [ ] Odds API usage (sustainable vs excessive)
- [ ] Open positions count (< 30)

### Monthly Checks
- [ ] Overall ROI (target: > 0%)
- [ ] Win rate (target: > 45%)
- [ ] Bankroll growth (target: +20% MoM)
- [ ] Failure pattern review (new patterns?)

---

## Mitigation Status Summary

| Pattern | Risk Level | Status | Impact | Mitigation |
|---------|-----------|--------|--------|------------|
| 3-Way Devig | 🔴 CRITICAL | ACTIVE | -$241.99 | Strategy halted, 2-way first |
| Stale Markets | 🟡 HIGH | FIXED | None | Filter implemented |
| Bankroll Depletion | 🟡 HIGH | ACTIVE | -$2,100 | Conservative mode |
| Odds API Budget | 🟢 LOW | MITIGATED | None | 6→2 req/scan |
| Duplicate Entry | 🟢 LOW | RESOLVED | None | Market type filter |

**Overall Risk:** 🟡 MODERATE (Bankroll depletion primary concern)
