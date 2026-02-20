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

---

## Phase 4: Low-Risk High-Volume Implementation (Feb 15)

### Sports Strategy Suite Implementation (2026-02-15)
**Feature:** Multi-strategy sports arbitrage system
**Status:** ✅ Implementation Complete
**Bankroll:** $900 → Target $2,200 (4 weeks)

**New Strategies Implemented:**

1. **Settlement Window Arbitrage**
   - File: `src/poly24h/strategy/settlement_sniper.py`
   - Target: Markets 90-120 min before settlement
   - Entry: Liquidity <$500, edge >8% (vs normal 5%)
   - Max position: $30
   - Expected: 3-5 trades/day at 10-15% ROI
   - **Rationale**: Market makers exit early, creating temporary mispricings

2. **Power Method 3-Way Devig**
   - File: `src/poly24h/strategy/odds_api.py` (devig_three_way_power)
   - Method: Clarke et al. (2017) - p_devigged = (p_raw^k) / Σ(p_all^k)
   - Parameter: k=1.15 (empirically optimal)
   - Bookmaker: Pinnacle only (sharp, ~2% vig vs Unibet ~5%)
   - Validation: Probability bounds (draw 5-45%, home/away 10-90%)
   - **PREREQUISITE**: 50+ successful 2-way trades before enabling

3. **Adaptive Edge Threshold**
   - File: `src/poly24h/strategy/sport_config.py` (adaptive_edge_calibration)
   - Mechanism: Rolling 20-trade window
   - Logic: if actual > predicted → lower threshold, vice versa
   - Bounds: 0.5× to 2.0× base threshold
   - **Purpose**: Auto-adapt to market conditions, prevent overfitting

4. **Tennis Expansion (ATP/WTA)**
   - Files: `sport_config.py` (TENNIS_ATP_CONFIG, TENNIS_WTA_CONFIG)
   - Min edge: 4% (less data than NBA)
   - Max position: $40
   - Expected: 5-10 trades/day
   - **Rationale**: Frequent events, 2-way markets (simpler than soccer)

5. **Esports Expansion (LoL/CS2/Dota2)**
   - Files: `sport_config.py` (ESPORTS_LOL_CONFIG, ESPORTS_CS2_CONFIG)
   - Min edge: 6% (inefficient market, higher variance)
   - Max position: $30 (thin markets)
   - Expected: 2-3 trades/day (tournament-dependent)
   - **Rationale**: 24/7 availability, young market (inefficient pricing)

**Risk Filters Added:**

1. **Stale Market Filter**
   - File: `src/poly24h/discovery/gamma_client.py` (filter_stale_markets)
   - Logic: Reject markets with end_date < now + 1H
   - **Prevents**: Entering Jan 13 markets on Feb 13 (F-026 error)

2. **Orderbook Depth Filtering**
   - File: `src/poly24h/strategy/orderbook_scanner.py` (calculate_orderbook_metrics)
   - Metrics: bid_ask_spread, book_depth_usd, price_impact_100
   - Filters: spread <3%, depth >$200, impact <2%
   - **Purpose**: Avoid thin markets with high slippage

3. **Probability Bounds Validation**
   - File: `src/poly24h/strategy/odds_api.py` (validate_three_way_probs)
   - Bounds: draw 5-45%, home/away 10-90%, sum ~1.0
   - **Prevents**: Unrealistic 30.7% draw edge scenarios (F-026 failure)

**Scripts Created:**

1. `scripts/analyze_nba_validation.py`
   - Purpose: Analyze 82 pending NBA positions after Feb 18 settlement
   - Metrics: Win rate, edge accuracy, per-market-type performance
   - Decision tree: >60% scale up, 52-60% cautious, <52% pause

2. `scripts/daily_performance_report.py`
   - Purpose: Daily dashboard tracking
   - Outputs: Trades/strategy, win rate, ROI, bankroll trajectory
   - Targets: 30+ trades/day, 50%+ win rate, $2,200 bankroll

**Expected Timeline:**
- Week 1 (Feb 15-21): NBA validation + quick wins → $1,100 (+$200)
- Week 2 (Feb 22-28): Settlement sniper + orderbook → $1,400 (+$300)
- Week 3 (Mar 1-7): Power 3-way + tennis → $1,800 (+$400)
- Week 4 (Mar 8-14): Esports + scaling → $2,200 (+$400)

**Key Architectural Changes:**

1. **SportConfig Enhancements**
   - Added adaptive edge tracking (rolling window)
   - Added _base_min_edge, _edge_history, _history_size
   - Method: adaptive_edge_calibration(), record_edge_result()

2. **SportsMonitor Integration**
   - Settlement sniper optional (enable_settlement_sniper flag)
   - Stale market filtering (1H buffer)
   - Orderbook depth filtering (optional, can be disabled)

3. **Team Data Expansion**
   - Added TENNIS_PLAYER_NAMES (ATP/WTA top players)
   - Added ESPORTS_TEAM_NAMES (LoL, CS2, Dota2 orgs)
   - Separated mappings: LOL_TEAM_NAMES, CS2_TEAM_NAMES, etc.

**Files Modified:**
- `src/poly24h/discovery/gamma_client.py`: Stale filter, buffer validation
- `src/poly24h/strategy/odds_api.py`: Power devig, bounds validation, Pinnacle-only
- `src/poly24h/strategy/sport_config.py`: Adaptive edge, tennis/esports configs
- `src/poly24h/strategy/sports_monitor.py`: Settlement sniper integration
- `src/poly24h/strategy/orderbook_scanner.py`: Depth metrics, liquidity filtering
- `src/poly24h/strategy/settlement_sniper.py`: NEW - settlement arbitrage
- `src/poly24h/strategy/team_data.py`: Tennis players, esports teams

**Odds API Budget:**
- Current: 488/500 remaining
- Week 1 usage estimate: ~50 requests (NBA/NHL validation)
- Week 2-4 usage: ~150 requests (multi-sport expansion)
- Expected remaining after 4 weeks: >280/500 (sustainable)

---

## Phase 5: Strategy Overhaul (Feb 19-20)

### F-032: Strategy Overhaul — Kill Spread/O-U (2026-02-20)
**실험 목적:**
- 2/19 NBA 드라이런 결과 분석 후 전략 근본 재편

**드라이런 결과 (2026-02-19):**
- 13 NBA 포지션 진입 ($309.66 투자)
- **1W-10L, -$164.84 손실 (ROI -42~-73%)**

**상세 결과:**
| Market | Side | Price | Size | Outcome | P&L |
|--------|------|-------|------|---------|-----|
| Spread: Rockets (-2.5) | NO | 0.43 | $13.23 | Rockets won by 11 → NO wins | +$17.54 |
| Nets vs Cavs: O/U 228.5 | NO | 0.47 | $38.85 | Total 178 < 228.5 → NO wins | +$43.81 |
| Spread: Cavaliers (-13.5) | NO | 0.41 | $16.13 | Cavs won by 30 → NO loses | -$16.13 |
| Spread: 76ers (-3.5) | YES | 0.43 | $15.12 | Hawks won → YES loses | -$15.12 |
| Pacers vs Wizards | NO | 0.43 | $28.65 | Pacers won → NO loses | -$28.65 |
| Pacers vs Wizards: O/U 234.5 | YES | 0.47 | $8.89 | Total 183 < 234.5 → YES loses | -$8.89 |
| Spread: Rockets (-3.5) | NO | 0.47 | $15.17 | Rockets won by 11 → NO wins | +$17.10 (overlapping) |
| Spread: Cavaliers (-14.5) | NO | 0.44 | $23.85 | Cavs won by 30 → NO loses | -$23.85 |
| Spread: 76ers (-2.5) | YES | 0.46 | $21.78 | Hawks won → YES loses | -$21.78 |
| Pacers vs Wizards: O/U 235.5 | YES | 0.44 | $50.00 | Total 183 < 235.5 → YES loses | -$50.00 |
| Spread: Pacers (-4.5) | YES | 0.45 | $15.83 | Pacers won by 1 → YES loses | -$15.83 |
| Spread: Knicks (-2.5) | NO | 0.45 | $27.34 | (halftime when analyzed) | TBD |
| Pistons vs Knicks: O/U 221.5 | NO | 0.45 | $34.82 | (halftime when analyzed) | TBD |

**근본 원인 분석 (인터넷 리서치):**
1. Polymarket 지갑의 7.6%만 수익 (0.04%가 전체 수익의 70%)
2. 스포츠북 devig odds ≠ Polymarket spread/O-U 가격
3. 캘리브레이션 > 정확도 (ROI +110% vs -35%)
4. 아비트라지 $40M+ 문서화, 73%는 sub-100ms 봇

**전략 변경 (F-032):**
1. ✅ F-032a: Spread/O-U 완전 차단 (odds_api.py returns None)
2. ✅ F-032b: Sports Paired Scanner (CPP < 0.96 아비트라지)
3. ✅ F-032c: Moneyline Validation Gate (20건 dry-run 필수)
4. ✅ Crypto Paired Entry 파이프라인 활성 확인

**테스트:** 21건 pass (9 new + 12 existing)

---

## Next Experiments

### 1. Week 1: NBA Validation + Quick Wins (Feb 15-21)
- Run analyze_nba_validation.py after Feb 18 settlements
- Monitor adaptive edge calibration (first 20 trades)
- NHL 2-way validation (10+ trades)
- Target: $900 → $1,100

### 2. Week 2: Settlement Sniper + Orderbook (Feb 22-28)
- Paper trade settlement sniper for 3 days
- Enable live if profitable (>10% avg ROI)
- Monitor orderbook filtering effectiveness (slippage reduction)
- Target: $1,100 → $1,400

### 3. Week 3: Power 3-Way + Tennis (Mar 1-7)
- PREREQUISITE: 50+ 2-way trades, 55%+ win rate
- Enable Power 3-way soccer (Bundesliga, Serie A)
- Enable tennis live (ATP/WTA)
- Target: $1,400 → $1,800

### 4. Week 4: Esports + Scaling (Mar 8-14)
- Enable esports when tournaments active
- Scale to 30+ trades/day
- Performance review + optimization
- Target: $1,800 → $2,200
