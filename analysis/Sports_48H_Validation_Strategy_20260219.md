# Sports 48H Validation Strategy — 2026-02-19

## Context

### Problem
- Bankroll: $900 (초기 $3,000 대비 -70%)
- 검증된 스포츠 전략 없음 (crypto만 검증됨, 다른 봇이 담당)
- 3-way soccer devig 실패 (-100% ROI)
- NBA 82 포지션 미정산 (All-Star Break 종료, Feb 18 경기 재개)

### Goal
1. **48H 내**: Paper trading으로 수익성 검증 (스포츠 마켓, 24H 이내 정산, 일 ROI 2.5-5%)
2. **96H 내**: 라이브 트레이딩에서 일 ROI 2.5-5% 달성
3. **검증 단계**: 일 투입 자본 $100
4. **확장 단계**: $1,000-$3,000/day

### Key Insight: 2-Way vs 3-Way
- **2-way devig** (NBA/NHL): 단순 확률 정규화, 수학적으로 안정 → 이번 검증 대상
- **3-way devig** (soccer): F-026에서 실패, Power method으로 교체했으나 미검증 → 후순위

---

## Phase 1: Paper Validation (Hour 0-48)

### Step 1.1: 일일 자본 배치 상한 구현
- PositionManager에 `max_daily_deployment_usd` 필드 추가
- 자정 UTC 자동 리셋
- `enter_position()` 내부에서 daily cap 체크

### Step 1.2: 검증용 설정
| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Daily deployment | $100 | 검증 단계 자본 제한 |
| Max per market | $20 | 5-10 trades × $10-20 each |
| Min edge | 3% (NBA/NHL) | sport_config.py 기본값 유지 |
| Max entries/cycle | 3 | 과다 진입 방지 |
| Daily loss limit | $50 | deployed의 50% |

### Step 1.3: 기존 NBA 82포지션 분석
NBA All-Star Break 종료(Feb 18)로 기존 포지션 정산 중. 이 데이터가 첫 번째 검증 자료.

### Step 1.4: 예상 거래량
| Sport | Games/Day | Trades/Day | Avg Size | Daily Deploy |
|-------|-----------|------------|----------|-------------|
| NBA | 5-8 | 3-5 | $18 | $54-90 |
| NHL | 5-7 | 2-3 | $15 | $30-45 |
| **Total** | 10-15 | **5-8** | $17 | **$85-100** |

### Step 1.5: 48H 판정 기준
| Metric | Pass | Marginal | Fail |
|--------|------|----------|------|
| Win rate | >55% | 48-55% | <48% |
| ROI (2일 평균) | >3% | 2-3% | <2% |
| Trades/day | >5 | 3-5 | <3 |
| Edge accuracy | ±2% | ±3% | >±3% |

---

## Phase 2: Live Trading (Hour 48-96)

### 라이브 전환 체크리스트
- [ ] Preflight PASS (자격 증명 + 잔고)
- [ ] USDC 잔고 >= $200
- [ ] CLOB order submission 코드 확인
- [ ] Paper trading Phase 1 PASS
- [ ] 테스트 주문 $1 성공 (수동)

### 96H 판정 기준
| Metric | Target | Acceptable | Abort |
|--------|--------|------------|-------|
| Live win rate | >55% | 48-55% | <45% |
| Live ROI/day | >3% | 2.5-3% | <2% |
| Slippage | <1% | 1-2% | >3% |
| Fill rate | >90% | 80-90% | <80% |

---

## Phase 3: Scaling (Day 5+)

### $100 → $500/day (Week 2)
- 트리거: 20+ live trades, win rate >52%, ROI >2.5%
- 추가: Tennis (ATP/WTA) 활성화

### $500 → $1,000-$3,000/day (Week 3-4)
- 트리거: 50+ live trades, win rate >50%, bankroll > $1,500
- 추가: Settlement sniper, Soccer 3-way (Power method), Esports

---

## Risk & Abort Conditions

| Condition | Action |
|-----------|--------|
| Paper win rate < 45% after 20 trades | Phase 1 실패 → 전략 재검토 |
| Live slippage > 3% | Orderbook depth filtering 활성화 |
| Daily loss > $50 | 자동 중단 |
| Bankroll < $500 | Emergency Protocol 1 |
| Odds API budget < 100 | Emergency Protocol 3 (cache only) |

---

## 핵심 전략
NBA/NHL 2-way moneyline arbitrage (Odds API vs Polymarket)
- 2-way devig는 수학적으로 안정 (3-way 실패와 별개)
- $100/day × ROI 3-5% = $3-5/day 수익
- 검증 후 스케일링으로 $30-150/day 목표
