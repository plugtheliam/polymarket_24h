# Trading Strategy Benchmarks

## Account Information
- Wallet: 0x710ea4982DE9eea268bB5d33894FA02461eE7dc0
- 초기 자본: $3,000 → 현재: $900 (-70%)
- Odds API 예산: 488/500 remaining (2026-02-15 기준)

## Benchmark Strategies

### Strategy 1: Hourly Crypto Paired Entry ✅ PROVEN
**메커니즘:**
- Combined Purchase Price (CPP) < $0.94 조건
- YES + NO 동시 진입으로 시장 중립 포지션
- 1H 정산 마켓만 대상

**검증 성과 (2026-02-11):**
- 24 trades 진입
- 11W-4L (46% 승률, 9건 미정산)
- +$995.42 수익 (+11.57% ROI)

**설정:**
- Max $100/position
- Markets: BTCUSD, ETHUSD (1H)
- Entry threshold: CPP < $0.94

**교훈:**
- 가장 안정적이고 검증된 전략
- 시장 중립적 접근으로 방향성 리스크 최소화
- 높은 유동성 시장에서 효과적

---

### Strategy 2: NBA Sportsbook Directional ❌ FAILED
**메커니즘:**
- Odds API (sharp sportsbooks) vs Polymarket
- 2-way devig (home/away 확률 정규화)
- Fair value 대비 3-5%+ edge 조건

**최종 결과 (2026-02-19 드라이런):**
- 13 positions 진입 (spread/O-U/moneyline)
- **1W-10L** (-$164.84, ROI -42~-73%)
- 유일한 승리: O/U 228.5 Under (Nets-Cavs total 178)

**실패 근본 원인 (F-032 분석):**
1. 스포츠북 devig odds ≠ Polymarket 가격 (spread/O-U)
2. "fair=0.50 vs price=0.43 → edge 7%"는 환상적 에지
3. 검증 없는 진입 (피드백 루프 부재)

**F-032 조치:**
- Spread/O-U 완전 차단 (fair value returns None)
- MoneylineValidationGate 추가 (20건 dry-run 필수)
- 검증 전까지 moneyline도 차단

---

### Strategy 4: Sports Paired Entry 🆕 NEW (F-032b)
**메커니즘:**
- 모든 스포츠 마켓에서 YES+NO CPP < 0.96 아비트라지
- Fair value 불필요 — 순수 시장 구조 차익
- YES@0.45 + NO@0.48 = CPP 0.93 → $0.07/share 보장 수익

**설정:**
- CPP threshold: 0.96
- Min price: $0.02 (garbage filter)
- Markets: NBA, NHL (모든 타입)

**상태:** 🆕 구현 완료, 드라이런 대기

---

### Strategy 3: 3-Way Soccer Devig ❌ FAILED
**메커니즘:**
- 3-way markets (home/draw/away)
- Overround 제거: p_i / sum(p_all)
- Odds API (Unibet, Pinnacle) vs Polymarket

**실패 결과 (2026-02-13 F-026):**
- 21 포지션 진입 (10 NHL 2-way, 11 soccer 3-way)
- 5건 정산: **-$241.99 (-100% ROI)**
- 실패 사례:
  1. Hoffenheim vs Freiburg: 무승부 YES @ $0.25 (30.7% edge 계산) → Hoffenheim 3-0 승
  2. Milan vs Sassuolo: Milan 승 NO @ $0.39 (23.8% edge) → Milan 2-1 승
  3. Lazio vs Hellas Verona: Lazio 승 YES @ $0.27 (17% edge) → Lazio 0-2 패

**실패 원인 분석:**
1. **Overround 제거 수식 부정확:**
   - 현재: p_i / sum(p_all) (additive normalization)
   - 필요: multiplicative devig 또는 학술적 검증된 방법
2. **Soft bookmaker odds 편향:**
   - Unibet odds ≠ true probability
   - Sharp bookmaker (Pinnacle) only 필요
3. **Stale market filter 없음:**
   - Jan 13 end_date 마켓에 Feb 13에 진입
   - end_date > now 필터 누락
4. **무승부 확률 범위 검증 없음:**
   - 현실적 범위 (5-45%) 체크 없음

**교훈:**
- 2-way markets에서 50+ trades 성공 후 재시도
- Academic paper로 devig 수식 검증 필수
- Pinnacle sharp odds only
- Stale market filter + 확률 범위 검증 추가

---

## External Data Sources

### Odds API
- 제공자: https://the-odds-api.com
- 사용처: Sportsbook arbitrage (NBA, NHL, Soccer)
- 비용: $0.01/request
- 예산: 488/500 remaining (F-026에서 6→2 requests/scan 최적화)

### Gamma API
- 제공자: Polymarket (https://gamma-api.polymarket.com)
- 사용처: Market discovery, orderbook fetch
- 인증: 불필요 (public read)
- Rate limit: 없음 (자체 throttle: 5s interval)

### CLOB API
- 제공자: Polymarket CLOB
- 사용처: Order execution
- 인증: Private key 서명 필요
- Wallet: 0x710ea4982DE9eea268bB5d33894FA02461eE7dc0

---

## Strategy Selection Guidelines

**현재 권장 전략 (2026-02-20, F-032 이후):**
1. ✅ **Crypto Paired Entry** — 유일하게 검증된 전략, 주력 (CPP < 0.94)
2. 🆕 **Sports Paired Entry** — CPP < 0.96 아비트라지 (F-032b)
3. 🚫 **Spread/O-U** — 완전 차단 (F-032a)
4. 🔒 **Moneyline 방향** — 20건 dry-run 검증 후 활성화 (F-032c)
5. ⏸️ **Settlement Sniper / Tennis / Esports** — 보류

**새로 구현된 전략 (2026-02-15):**
1. **Settlement Window Arbitrage**: 마켓 정산 90-120분 전 유동성 감소 시점 타겟
   - Edge threshold: 8% (vs normal 5%)
   - Max position: $30 (thin liquidity)
   - Expected: 3-5 trades/day at 10-15% ROI

2. **Power Method 3-Way Devig**: 학술적으로 검증된 devig 방법
   - Formula: p_devigged = (p_raw^k) / Σ(p_all^k), k=1.15
   - Pinnacle sharp odds only (not Unibet/soft bookmakers)
   - Probability bounds validation (draw: 5-45%, home/away: 10-90%)
   - PREREQUISITE: 50+ successful 2-way trades

3. **Adaptive Edge Threshold**: 실제 vs 예측 edge 기반 자동 조정
   - 20 trades rolling window로 accuracy 추적
   - If actual > predicted → lower threshold
   - If actual < predicted → raise threshold

4. **Tennis Expansion**: ATP/WTA 2-way arbitrage
   - Min edge: 4% (less data than NBA)
   - Max position: $40
   - Expected: 5-10 trades/day

5. **Esports Expansion**: LoL, CS2, Dota 2
   - Min edge: 6% (inefficient market)
   - Max position: $30 (thin markets)
   - Expected: 2-3 trades/day (tournament-dependent)

**개선된 리스크 필터:**
1. ✅ **Stale Market Filter**: end_date < now + 1H 진입 차단
2. ✅ **Orderbook Depth Filtering**: spread <3%, depth >$200, impact <2%
3. ✅ **Probability Bounds Validation**: 비현실적 edge 차단 (30.7% draw 방지)

**다음 검증 단계:**
1. Week 1 (Feb 15-21): NBA validation + stale filter + adaptive edge
2. Week 2 (Feb 22-28): Settlement sniper + orderbook filtering
3. Week 3 (Mar 1-7): Power 3-way + Tennis (PREREQUISITE: 50+ 2-way trades)
4. Week 4 (Mar 8-14): Esports + multi-sport scaling (30+ trades/day target)

**Bankroll 복구 로드맵:**
- 현재 $900 → Week 1: $1,100 → Week 2: $1,400 → Week 3: $1,800 → Week 4: $2,200
- 목표: 4주 내 $900 → $2,200 (+144%)
- 검증된 전략 중심 운영, 실험적 전략은 bankroll > $1,400 후 재개
