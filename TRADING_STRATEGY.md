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

### Strategy 2: NBA Sportsbook Arbitrage ⚠️ PARTIAL
**메커니즘:**
- Odds API (sharp sportsbooks) vs Polymarket
- 2-way devig (home/away 확률 정규화)
- Fair value 대비 5%+ edge 조건

**현재 상태:**
- F-025로 구현 완료
- NBA All-Star Break (Feb 14-17)로 미검증
- 62 포지션 진입, 아직 미정산

**다음 검증:**
- 2026-02-18 (All-Star Break 종료 후)
- 목표: 30+ trades, 40%+ win rate

**설정:**
- Sports: NBA (moneyline only)
- Min edge: 5%
- Max $50/position

**보류 이유:**
- 경기 일정 공백으로 충분한 샘플 확보 불가

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

**현재 권장 전략 (2026-02-15):**
1. ✅ **Crypto Paired Entry** — 유일하게 검증된 전략, 계속 사용
2. ⚠️ **NBA 2-way** — Feb 18 이후 검증 대기
3. ❌ **3-way Soccer** — 중단, 2-way 50+ trades 성공 후 재고

**다음 검증 단계:**
1. NBA/NHL 2-way arbitrage 먼저 검증 (50+ trades)
2. 검증 성공 시 3-way devig 재설계
3. Academic paper 기반 devig 수식 재검증

**Bankroll 복구 우선순위:**
- 현재 $900 → 목표 $5,000
- 검증된 crypto paired entry 중심 운영
- 실험적 전략은 bankroll > $2,000 후 재개
