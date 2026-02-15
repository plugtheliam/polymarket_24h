# Trading Experiment History

## Timeline Format
[날짜] Feature ID — 실험 내용 → 결과

---

## Phase 1: Foundation (Feb 6-10)
**목표:** 기본 인프라 구축

**Feature 구현:**
- F-001~F-013: CLOB integration, Market discovery, Position tracking
- F-014~F-020: Order execution, Settlement monitoring, Error handling

**결과:**
- ✅ 기본 시스템 안정화
- ✅ pytest 테스트 커버리지 확보
- ✅ Dry run 환경 구축

---

## Phase 2: Fair Value Experiments (Feb 11)

### F-021: Fair Value Success (2026-02-11)
**실험 목적:**
- Paired entry (CPP < $0.94) vs Fair value (edge-based) 성능 비교

**설정:**
- Strategy: Paired entry + Fair value fallback
- Bankroll: $1,000
- Max position: $100
- Markets: Crypto (1H), NBA (pregame)

**실험 결과:** ✅ SUCCESS
- **Crypto (24 trades):**
  - 11W-4L-9미정산
  - +$995.42 (+11.57% ROI)
  - 46% 승률
- **NBA (62 trades):**
  - 미정산 (All-Star Break)

**핵심 발견:**
1. Paired entry > Fair value (안정적 수익)
2. Crypto 1H markets가 가장 효율적
3. NBA는 정산 지연으로 검증 보류

**설정 아카이브:**
```bash
# .env (F-021)
POSITION_SIZE_USD=100
MIN_EDGE_THRESHOLD=0.05
CPP_THRESHOLD=0.94
SPORTS=crypto,nba
```

---

## Phase 3: Multi-Sport Expansion (Feb 12-13)

### F-024: NBA Discovery Bugfix (2026-02-12)
**문제:**
- Gamma API slug 변경 (2024-25 → 2025-26 season)
- NBA markets 0건 발견

**해결:**
- Season slug 자동 감지 로직 추가
- Spread/Over-Under 마켓 필터링

**결과:** ✅ FIXED
- F-025에서 NBA markets 정상 발견

---

### F-025: NBA Sportsbook Integration (2026-02-12)
**실험 목적:**
- Odds API 기반 NBA arbitrage 검증

**설정:**
- Sports: NBA (moneyline only)
- Odds source: Pinnacle, Draftkings
- Min edge: 5%
- Max position: $50

**현재 상태:** ⚠️ IN PROGRESS
- 62 포지션 진입
- All-Star Break (Feb 14-17)로 미정산
- 다음 검증: Feb 18

**차단 요인:**
- NBA 경기 일정 공백

---

### F-026: Multi-Sport Monitor (2026-02-13 10:00 UTC)
**실험 목적:**
- Multi-sport arbitrage 확장 (NHL 2-way, Soccer 3-way)

**설정:**
```bash
# .env (F-026)
SPORTS=nhl,bundesliga,seriea
MIN_EDGE_NHL=0.03
MIN_EDGE_SOCCER=0.05
SCAN_INTERVAL_SECONDS=300
STAGGER_INTERVAL_SECONDS=60
MAX_POSITION_USD=50
```

**3-way Devig 로직:**
```python
# src/poly24h/sports_monitor.py:224
def normalize_three_way(home_prob, draw_prob, away_prob):
    total = home_prob + draw_prob + away_prob
    return home_prob/total, draw_prob/total, away_prob/total
```

**Odds API 설정:**
- NHL: 2 requests/scan (h2h for both teams)
- Soccer: 2 requests/scan (h2h for both teams)
- Total: 6 requests/scan → 2 requests/scan (최적화)

**실험 결과:** ❌ CRITICAL FAILURE

**포지션 진입:**
- 21 positions total
  - 10 NHL (2-way)
  - 11 Soccer (3-way: Bundesliga 6, Serie A 5)

**정산 결과 (5건):**
| Market | Entry | Price | Edge | Outcome | P&L |
|--------|-------|-------|------|---------|-----|
| Hoffenheim vs Freiburg (Draw) | YES | $0.25 | 30.7% | Hoffenheim 3-0 승 | -$50.00 |
| Milan vs Sassuolo (Milan) | NO | $0.39 | 23.8% | Milan 2-1 승 | -$50.00 |
| Lazio vs Hellas Verona (Lazio) | YES | $0.27 | 17.0% | Lazio 0-2 패 | -$50.00 |
| Freiburg vs Hoffenheim (Freiburg) | YES | $0.41 | 7.3% | Freiburg 0-3 패 | -$50.00 |
| Hellas Verona vs Lazio (Draw) | YES | $0.28 | 6.8% | Hellas 2-0 승 | -$41.99 |

**Total:** 5W-0L, -$241.99 (-100% ROI)

**실패 분석:**
1. **Overround 제거 수식 부정확:**
   - Hoffenheim 무승부 확률: 30.7% edge 계산 → 실제 3-0 승
   - p_i / sum(p_all) 방식이 확률 편향 제거 실패
2. **Soft bookmaker odds:**
   - Unibet odds 사용 (sharp가 아님)
   - Pinnacle sharp odds로 전환 필요
3. **Stale market filter 없음:**
   - 일부 markets의 end_date가 Jan 13 (과거)
   - end_date > now 필터 누락
4. **무승부 확률 검증 없음:**
   - 30.7% edge = 비현실적 (일반적으로 5-15%)
   - Sanity check 누락

**교훈:**
1. 3-way devig 수식 재검증 필요 (academic paper 참조)
2. Stale market filter 추가: `end_date > datetime.now(timezone.utc)`
3. Pinnacle sharp odds only
4. 확률 범위 검증: `0.05 < draw_prob < 0.45`
5. 2-way markets 먼저 100+ trades 검증 후 3-way 재시도

**Odds API 예산 영향:**
- 드라이런 중 12 requests 사용
- 488/500 remaining (충분)

---

## Key Learnings

### 1. Paired Entry > Fair Value
- Crypto paired entry: +11.57% ROI (검증됨)
- Fair value: 미검증

### 2. 2-Way First, Then 3-Way
- 2-way arbitrage 검증 필수
- 3-way는 복잡도 높음 (수식 검증 필요)

### 3. Sharp Odds Only
- Soft bookmaker (Unibet) = 편향된 확률
- Pinnacle sharp odds 권장

### 4. Stale Market Filter Critical
- end_date > now 필수
- 과거 마켓 진입 방지

### 5. Sanity Checks Save Money
- 확률 범위 검증 (0.05-0.45 for draw)
- Edge threshold 현실적 설정 (5-15%)

---

## Settings Archive

### F-021 (Crypto Success)
```bash
POSITION_SIZE_USD=100
MIN_EDGE_THRESHOLD=0.05
CPP_THRESHOLD=0.94
SPORTS=crypto,nba
```

### F-026 (Multi-Sport Failure)
```bash
SPORTS=nhl,bundesliga,seriea
MIN_EDGE_NHL=0.03
MIN_EDGE_SOCCER=0.05
SCAN_INTERVAL_SECONDS=300
MAX_POSITION_USD=50
ODDS_API_REGIONS=us
ODDS_API_BOOKMAKERS=pinnacle,draftkings,fanduel,unibet
```

---

## Next Experiments

### 1. NBA 2-Way Validation (Feb 18+)
- F-025 재개
- 목표: 30+ trades, 40%+ win rate

### 2. NHL 2-Way Validation
- F-026 NHL 포지션 정산 대기
- 목표: 20+ trades, 45%+ win rate

### 3. 3-Way Devig 재설계 (보류)
- 2-way 50+ trades 성공 후
- Academic paper 기반 수식 재검증
- Pinnacle only + stale filter + sanity checks
