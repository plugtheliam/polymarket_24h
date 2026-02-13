# F-024: 수익성 개선 — 저위험 고빈도 전략 전환

## Context

F-023 드라이런 결과: 31건 트레이드에서 **-$300 P&L**. 근본 원인은 **엣지 없는 진입**:
- NBA: 하드코딩된 시즌 승률(2024-25)로 fair value 계산 → 실제 스포츠북 라인 대비 부정확
- Crypto: 모멘텀/RSI 기반 → 체계적 YES(Up) 편향, 0/2 승률
- 포지션 사이징: $100 고정, Kelly criterion 없음 → 2사이클 만에 뱅크롤 $0

**목표**: $3,000 자본으로 시작, 일 $30-60 수익 목표, 72시간 내 검증
**핵심 전략 전환**: "약한 내부 모델 기반 방향성 베팅" → "외부 스포츠북 라인 대비 차익 탐지"

---

## 리서치 핵심 발견

### 시장 구조
| 마켓 | 수수료 | 결산 | 회전율 | 경쟁도 |
|------|--------|------|--------|--------|
| NBA (Spread/O-U/ML) | **0%** | 게임 종료 후 2-3시간 | 하루 10-15게임 | 중간 |
| Crypto Hourly | 0% (1시간) | 매시간 | 24회/일 | **매우 높음 (봇)** |
| Crypto 15min | 테이커 수수료 | 15분 | 96회/일 | 극한 |

### 수익 전략 (연구 결과 기반 우선순위)
1. **스포츠북 라인 비교 차익** — NBA 0% 수수료 + 실시간 오즈 API = 가장 높은 엣지
2. **유동성 공급 (Market Making)** — 80-200% APY, 저위험
3. **속도 기반 크립토** — 봇 경쟁 치열, 인프라 필요

### 상위 트레이더 분석 (0x876426...)
- $641K P&L / $10.6M 거래량 (6.0% 수익률)
- 63개 마켓에 집중 (전문화)
- 추정 전략: 정보 차익 + 마켓메이킹 하이브리드

---

## 구현 계획 (우선순위 순서)

### Phase 1: NBA 스포츠북 오즈 기반 Fair Value (최우선)

**문제**: 현재 `nba_fair_value.py`의 정적 승률은 Spread/O-U에 대한 fair value를 전혀 제공하지 못함
**해결**: The Odds API로 실시간 Pinnacle/DraftKings 라인을 가져와 implied probability로 변환

#### 1-1. 새 파일: `src/poly24h/strategy/odds_api.py`

```python
class OddsAPIClient:
    """The Odds API (https://the-odds-api.com/) 클라이언트"""

    async def fetch_nba_odds(self) -> list[GameOdds]:
        """NBA 전체 게임의 실시간 오즈 가져오기
        - 소스: Pinnacle (가장 샤프), DraftKings, FanDuel
        - 마켓: h2h(머니라인), spreads, totals
        - 무료 티어: 500 req/월 → PRE_OPEN마다 1회 = 24회/일 × 30일 = 720회
          → 유료 플랜 필요 or 캐시 적극 활용
        """

    def american_to_prob(self, odds: int) -> float:
        """미국식 오즈 → implied probability 변환
        +150 → 1/(1+1.5) = 0.40
        -200 → 200/(200+100) = 0.667
        """

    def devig(self, prob_a: float, prob_b: float) -> tuple[float, float]:
        """오버라운드 제거 (Pinnacle vig ~2%)
        raw: YES 52% + NO 52% = 104%
        devigged: YES 50% + NO 50% = 100%
        방법: multiplicative devig (prob / sum_probs)
        """

    def match_to_polymarket(self, game: GameOdds, markets: list[Market]) -> list[MatchedOdds]:
        """스포츠북 라인 ↔ Polymarket 마켓 매칭
        - "Mavericks -3.5" ↔ "Spread: Mavericks (-3.5)"
        - "O/U 216.5" ↔ "Mavericks vs. Spurs: O/U 216.5"
        - 라인값 정확 매칭 (소수점까지)
        """
```

**API 선택**: The Odds API (무료 500 req/월, 유료 $25/월 10K req)
- Pinnacle = 가장 샤프한 오즈 (2% vig, 시장 기준선)

#### 1-2. `nba_fair_value.py` 리팩토링

정적 승률 → 실시간 스포츠북 오즈. Spread/O-U 마켓도 정확한 fair value 가능.

#### 1-3. 엣지 기반 진입 조건 (`event_scheduler.py`)

현재: `market_price < fair_prob - 0.05` (5% 고정 마진)
변경: `edge = fair_prob - market_price`, `min_edge = 0.03`

### Phase 2: 포지션 사이징 — Kelly Criterion ($3,000 뱅크롤)

- Quarter-Kelly 기반 동적 사이징
- 최소 $10, 최대 min($300, bankroll * 0.10)
- 사이클당 총 투자: bankroll * 0.30

### Phase 3: Crypto 방향성 베팅 비활성화

- 모멘텀 기반 모델 체계적 YES 편향 → 비활성화
- 자본을 NBA에 집중
- 마켓메이킹은 F-025로 분리

### Phase 4: 뱅크롤 관리 강화

- max_cycle_budget_ratio = 0.30
- min_bankroll_reserve = 0.30
- max_single_position_ratio = 0.10

---

## 수익성 시뮬레이션 ($3,000 뱅크롤)

```
가정:
- 하루 10-15 NBA 게임 → ~40-60개 마켓 (ML/Spread/O-U)
- Polymarket vs Pinnacle 가격 차이 3%+ 발견: ~5-10건/일
- 평균 엣지: 5% (devigged prob vs Polymarket price)
- Quarter-Kelly 사이징: ~$30-60/건

기대 수익:
- 건당 EV: $45 × 0.05 / 0.45 ≈ $5.0
- 일 5건 진입: $25/일 (보수적)
- 일 10건 진입: $50/일 (낙관적)

72시간 검증 기준:
- 3일간 15-30건 NBA 트레이드 실행
- 엣지 3%+ 마켓에서 55%+ 승률 검증
- 뱅크롤 $3,000 → $3,075+ (양의 누적 P&L)
```
