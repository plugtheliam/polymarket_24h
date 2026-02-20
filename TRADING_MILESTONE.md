# Trading Milestones

## Current Position
**Phase:** 5 (Strategy Overhaul — Paired Entry Focus)
**Status:** 🟡 REBUILDING — F-032 전략 재편 완료, 드라이런 대기
**Date:** 2026-02-20
**Bankroll:** ~$4,690 (paper), $900 (real, 초기 $3,000 대비 -70%)
**Odds API Budget:** ~480/500 remaining

**F-032 전략 재편 완료 (2026-02-20):**
1. ✅ F-032a: Spread/O-U 완전 차단 (fair value returns None)
2. ✅ F-032b: Sports Paired Scanner (CPP < 0.96 아비트라지)
3. ✅ F-032c: Moneyline Validation Gate (20건 dry-run 필수)
4. ✅ Crypto Paired Entry 파이프라인 활성 확인
5. ✅ F-031: Production-Ready Live Executor (polling, retry, kill switch)

**2/19 드라이런 교훈:**
- 1W-10L, -$165, ROI -42~-73%
- Spread/O-U에서 sportsbook devig ≠ Polymarket 가격
- Paired entry (시장 중립)만이 개인 트레이더의 현실적 에지

**다음 액션:**
- Day 1-3: 드라이런 재시작 (paired entry only)
- Day 3: GO/NO-GO 판단 (크립토 페어드 10+건 ROI > 3%)
- Day 5: 라이브 승인 판단 (15+건 ROI > 2%)

---

## Hypothesis Validation Stages

### Stage 1: 2-Way Arbitrage (Crypto) ✅ VALIDATED
**가설:**
Paired entry (CPP < $0.94)가 crypto 1H markets에서 안정적 수익 제공

**검증 조건:**
- [x] 20+ trades
- [x] 40%+ win rate
- [x] Positive ROI over 24H period

**검증 결과 (2026-02-11, F-021):**
- **Trades:** 24 (BTCUSD, ETHUSD 1H)
- **Win rate:** 46% (11W-4L-9미정산)
- **ROI:** +$995.42 (+11.57%)
- ✅ **가설 확인**

**핵심 발견:**
- Paired entry가 fair value보다 안정적
- 시장 중립 포지션으로 방향성 리스크 제거
- 높은 유동성 시장에서 효과적

**다음 단계:**
2-way sports arbitrage (NBA, NHL) 검증

---

### Stage 2: Sports Directional (Sportsbook Devig) ❌ FAILED
**가설:**
Sportsbook arbitrage (Odds API vs Polymarket)가 sports 2-way markets에서 edge 제공

**검증 결과 (2026-02-19, F-029 드라이런):**
- **NBA:** 13 positions, 1W-10L, -$164.84 (-42~-73% ROI)
- ❌ **가설 거부** — sportsbook devig odds ≠ Polymarket prices for spread/O-U

**실패 근본 원인:**
1. Devig 확률(~0.50)은 Polymarket 가격(0.41-0.47)과 무관
2. "edge 7%"는 환상 (실제 에지 없음)
3. 리서치: 지갑의 7.6%만 수익, 캘리브레이션 > 정확도

**교정 조치 (F-032):**
- Spread/O-U 완전 차단
- Moneyline 검증 게이트 추가 (20건 dry-run 필수)
- Paired entry로 전환 (시장 중립 아비트라지)

---

### Stage 2b: Sports Paired Entry 🆕 IN PROGRESS
**가설:**
YES+NO CPP < 0.96인 스포츠 마켓에서 시장 중립 아비트라지 가능

**검증 조건:**
- [ ] 10+ trades 실행
- [ ] 평균 ROI > 2%
- [ ] 단일 거래 손실 < 뱅크롤 5%

**현재 상태:** 구현 완료, 드라이런 대기

---

### Stage 3: 3-Way Soccer Arbitrage ❌ FAILED
**가설:**
3-way devig (home/draw/away)가 무승부 마켓에서 edge 제공

**검증 결과 (2026-02-13, F-026):**
- **Trades:** 11 positions (Bundesliga 6, Serie A 5)
- **Settled:** 5건
- **Win rate:** 0% (0W-5L)
- **ROI:** -$241.99 (-100%)
- ❌ **가설 거부**

**실패 사례:**
1. Hoffenheim vs Freiburg (Draw YES @ $0.25, 30.7% edge) → Hoffenheim 3-0 승
2. Milan vs Sassuolo (Milan NO @ $0.39, 23.8% edge) → Milan 2-1 승
3. Lazio vs Hellas Verona (Lazio YES @ $0.27, 17% edge) → Lazio 0-2 패

**실패 원인:**
1. **Overround 제거 수식 부정확:**
   - 현재: `p_i / sum(p_all)` (additive normalization)
   - 문제: 확률 편향 제거 실패, 무승부 확률 과대평가
2. **Soft bookmaker odds:**
   - Unibet odds 사용 (sharp가 아님)
   - Sharp bookmaker (Pinnacle) 필요
3. **Stale market filter 없음:**
   - Jan 13 end_date 마켓에 Feb 13에 진입
   - `end_date > now` 필터 누락
4. **확률 범위 검증 없음:**
   - 30.7% draw edge = 비현실적 (일반적 5-15%)
   - Sanity check 누락

**교정 계획:**
- [ ] 3-way devig 수학적 검증 (academic paper 참조)
- [ ] Pinnacle sharp odds only
- [ ] Stale market filter 추가: `end_date > datetime.now(timezone.utc)`
- [ ] 확률 범위 검증: `0.05 < draw_prob < 0.45`
- [ ] **전제 조건:** 2-way arbitrage 50+ trades 성공 후 재시도

**Status:** 🔴 BLOCKED
**Retry Condition:** Stage 2 완료 + 2-way 50+ trades positive ROI

---

## Roadmap

### Q1 2026 Goals
- [x] Validate crypto paired entry (✅ Feb 11)
- [ ] Validate NBA/NHL 2-way (⚠️ BLOCKED until Feb 18)
- [ ] 50+ total trades, 45% win rate
- [ ] Grow bankroll to $5,000 (현재 $900)

### Q1 2026 Revised Timeline
**Week 1 (Feb 6-11):**
- ✅ Foundation + Crypto validation

**Week 2 (Feb 12-18):**
- ⚠️ Multi-sport expansion (partial)
- 🔴 Soccer 3-way failure (-$241.99)
- ⏸️ NBA All-Star Break

**Week 3 (Feb 15-21): NBA Validation + Quick Wins** 🆕
- ✅ Stale market filter (prevent Jan 13 market entry)
- ✅ Probability bounds validation (30.7% draw → rejected)
- ✅ Adaptive edge threshold (auto-calibration)
- 🎯 NBA validation analysis (82 positions after Feb 18)
- 🎯 NHL monitoring (10+ trades)
- Expected: $900 → $1,100 (+$200)

**Week 4 (Feb 22-28): Settlement Sniper + Orderbook Filtering** 🆕
- ✅ Settlement sniper implemented (90-120 min window, 8%+ edge)
- ✅ Orderbook depth metrics (spread, depth, price impact)
- 🎯 Paper trade settlement sniper (3 days)
- 🎯 Enable live if paper profitable
- Expected: $1,100 → $1,400 (+$300)

**Week 5 (Mar 1-7): Power 3-Way + Tennis** 🆕
- ✅ Power Method devig (k=1.15, Pinnacle-only)
- ✅ Tennis configs (ATP/WTA, min_edge=4%)
- 🎯 PREREQUISITE: 50+ 2-way trades, 55%+ win rate
- 🎯 Enable 3-way soccer + tennis live
- Expected: $1,400 → $1,800 (+$400)

**Week 6 (Mar 8-14): Multi-Sport Scaling** 🆕
- ✅ Esports configs (LoL/CS2, min_edge=6%)
- 🎯 Scale to 30+ trades/day
- 🎯 Performance review + optimization
- Expected: $1,800 → $2,200 (+$400)

### Q2 2026 Goals (Conditional)
- [ ] 3-way devig 재설계 (Stage 2 성공 시)
- [ ] Bankroll $5,000+ 달성
- [ ] Odds API 비용 최적화 (< 5 requests/scan)

---

## Risk Assessment

### Critical Risks 🔴
1. **Bankroll Depletion:** $900 remaining (-70% from initial)
   - **Mitigation:** Crypto paired entry only (검증된 전략)
   - **Threshold:** < $500 → stop all trading
2. **3-Way Devig Inaccuracy:** -100% ROI on soccer
   - **Mitigation:** 완전 중단, 2-way 검증 후 재설계

### High Risks 🟡
1. **NBA Validation Delay:** All-Star Break로 미검증
   - **Mitigation:** Feb 18 재개 대기
2. **Odds API Budget:** 488/500 remaining
   - **Mitigation:** 6→2 requests/scan 최적화 완료

### Mitigated Risks 🟢
1. **Duplicate Entry Bug:** ✅ FIXED (F-023)
2. **Stale Market Entry:** ✅ FIXED (F-026)
3. **Odds API Cost:** ✅ OPTIMIZED (6→2 requests)

---

## Success Criteria

### Stage 2 Validation (Target: Feb 25)
- [ ] NBA: 30+ trades, 40%+ win rate, positive ROI
- [ ] NHL: 20+ trades, 40%+ win rate, positive ROI
- [ ] Combined: 50+ trades, 45%+ win rate

### Bankroll Recovery (Target: Mar 4)
- [ ] Bankroll > $2,000 (현재 $900)
- [ ] Win rate > 45% over 100+ trades
- [ ] No losing streaks > 5 consecutive losses

### Stage 3 Retry Conditions (No Timeline)
- [ ] Stage 2 완료 (NBA+NHL validated)
- [ ] 2-way trades > 50, positive ROI
- [ ] Academic paper 기반 devig 검증
- [ ] Stale filter + sanity checks 구현

---

## Historical Checkpoints

### Checkpoint 1: Crypto Validation ✅
- **Date:** 2026-02-11
- **Result:** +$995.42 (+11.57% ROI)
- **Status:** SUCCESS

### Checkpoint 2: Multi-Sport Expansion ❌
- **Date:** 2026-02-13
- **Result:** -$241.99 (-100% ROI on soccer)
- **Status:** FAILED (3-way), PENDING (2-way)

### Checkpoint 3: NBA/NHL 2-Way (Target: Feb 25)
- **Date:** TBD
- **Result:** TBD
- **Status:** IN PROGRESS
