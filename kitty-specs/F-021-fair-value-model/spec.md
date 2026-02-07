# Feature Specification: Fair Value Model

**Feature ID**: F-021
**Created**: 2025-02-07
**Status**: Draft

## Context

현재 저평가 판단은 단순 threshold 기반 ($0.48 이하면 기회).
이를 실제 데이터 기반 Fair Value Model로 업그레이드:

1. **NBA**: 팀 시즌 승률 기반 공정 확률 계산
2. **크립토 1H**: RSI, 볼린저 밴드 기반 기술적 분석

### 왜 필요한가?

- NBA: Lakers vs Celtics 경기에서 Lakers 승률 60%, Celtics 40%라면
  Lakers YES가 $0.48에 거래되어도 Fair Value $0.60 대비 **저평가**
- 크립토: BTC RSI 70 (과매수) + 가격이 볼린저 상단 근처면
  "BTC will go UP?" YES는 **고평가** (반전 가능성)

## User Scenarios & Testing

### User Story 1 - NBA Fair Value (Priority: P1)

NBA 팀 승률 기반으로 공정 확률을 계산할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** Lakers 승률 60%, Celtics 승률 40%  
   **When** calculate_fair_probability(0.60, 0.40)  
   **Then** Lakers Fair Prob ≈ 0.60 (60% / 100%)

2. **Given** Lakers 승률 70%, Celtics 승률 30%  
   **When** calculate_fair_probability(0.70, 0.30)  
   **Then** Lakers Fair Prob ≈ 0.70

3. **Given** 마켓 가격 $0.48, Fair Prob 0.60, margin 0.05  
   **When** is_undervalued(0.48, 0.60, 0.05)  
   **Then** True (0.48 < 0.60 - 0.05 = 0.55)

4. **Given** 마켓 가격 $0.58, Fair Prob 0.60, margin 0.05  
   **When** is_undervalued(0.58, 0.60, 0.05)  
   **Then** False (0.58 > 0.55)

---

### User Story 2 - Crypto Technical Analysis (Priority: P1)

RSI와 볼린저 밴드 기반으로 1H 크립토 마켓의 공정 확률을 계산할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** RSI 14-period 계산용 14개 close 데이터  
   **When** calculate_rsi([...14 closes...], period=14)  
   **Then** 0 ≤ RSI ≤ 100

2. **Given** RSI = 25 (과매도), price near BB lower  
   **When** calculate_fair_probability(rsi=25, ...)  
   **Then** UP fair prob > 0.50 (반등 예상)

3. **Given** RSI = 75 (과매수), price near BB upper  
   **When** calculate_fair_probability(rsi=75, ...)  
   **Then** UP fair prob < 0.50 (하락 예상)

4. **Given** RSI = 50 (중립), price at BB mid  
   **When** calculate_fair_probability(rsi=50, ...)  
   **Then** UP fair prob ≈ 0.50 (방향 불확실)

---

### User Story 3 - Binance OHLCV Fetch (Priority: P1)

바이낸스에서 1H 캔들 데이터를 가져올 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** symbol="BTCUSDT", interval="1h", limit=20  
   **When** fetch_binance_ohlcv(...)  
   **Then** 20개의 OHLCV 데이터 반환

2. **Given** 네트워크 오류  
   **When** fetch_binance_ohlcv(...)  
   **Then** 빈 리스트 반환 + 에러 로깅

---

### User Story 4 - Undervalued Detection (Priority: P1)

Fair Value 대비 저평가 여부를 판단할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** side="YES", market_price=0.40, fair_prob=0.55, margin=0.05  
   **When** is_undervalued(...)  
   **Then** True (YES가 저평가)

2. **Given** side="NO", market_price=0.40, fair_prob=0.55, margin=0.05  
   **When** is_undervalued(...)  
   **Then** False (NO의 Fair prob = 0.45, 0.40 < 0.45 - 0.05는 아님... 실제로는 True)
   
   → NO의 Fair prob = 1 - 0.55 = 0.45
   → margin 적용: 0.45 - 0.05 = 0.40
   → 0.40 ≤ 0.40 → True (경계선)

## Requirements

### NBA Fair Value Calculator

```python
class NBAFairValueCalculator:
    async def get_team_win_rate(self, team_name: str) -> float
        """팀 시즌 승률 조회 (0.0 ~ 1.0)"""
    
    def calculate_fair_probability(
        self, team_a_rate: float, team_b_rate: float
    ) -> float:
        """두 팀의 승률 기반 공정 확률 계산
        
        공식: team_a_rate / (team_a_rate + team_b_rate)
        """
    
    def is_undervalued(
        self, market_price: float, fair_prob: float, margin: float = 0.05
    ) -> bool:
        """market_price < fair_prob - margin 이면 저평가"""
```

### Crypto Fair Value Calculator

```python
class CryptoFairValueCalculator:
    async def fetch_binance_ohlcv(
        self, symbol: str, interval: str = "1h", limit: int = 20
    ) -> list[dict]:
        """바이낸스에서 OHLCV 데이터 가져오기"""
    
    def calculate_rsi(
        self, closes: list[float], period: int = 14
    ) -> float:
        """RSI 계산 (0-100)"""
    
    def calculate_bollinger_bands(
        self, closes: list[float], period: int = 20, std_dev: int = 2
    ) -> tuple[float, float, float]:
        """볼린저 밴드 계산 (lower, middle, upper)"""
    
    def calculate_fair_probability(
        self, rsi: float, price: float, bb_lower: float, bb_upper: float
    ) -> float:
        """기술적 분석 기반 UP 확률 계산
        
        - RSI < 30 (과매도) + price near bb_lower → UP 확률 증가
        - RSI > 70 (과매수) + price near bb_upper → UP 확률 감소
        """
    
    def is_undervalued(
        self, side: str, market_price: float, fair_prob: float, margin: float = 0.05
    ) -> bool:
        """side 기준 저평가 여부 판단
        
        side="YES" (UP): market_price < fair_prob - margin
        side="NO" (DOWN): market_price < (1 - fair_prob) - margin
        """
```

### Integration Points

1. **PRE_OPEN phase**: 마켓 발견 시 Fair Value 계산 후 저장
2. **SNIPE phase**: `is_undervalued()` 로 필터링 (기존 threshold 대체)
3. **Dynamic margin**: 기존 `DynamicThreshold` 활용

## Data Sources

- **NBA**: ESPN API (공개) 또는 하드코딩 fallback
- **Binance**: Public Klines API (인증 불필요)
  - `GET /api/v3/klines?symbol=BTCUSDT&interval=1h&limit=20`

## Files to Create

1. `src/poly24h/strategy/nba_fair_value.py`
2. `src/poly24h/strategy/crypto_fair_value.py`
3. `src/poly24h/feeds/binance_client.py` (optional, 기존 없으면 생성)
4. `tests/test_nba_fair_value.py`
5. `tests/test_crypto_fair_value.py`

## Success Criteria

- **SC-001**: NBA 공정 확률 계산 정확도 (유닛 테스트)
- **SC-002**: RSI, BB 계산 정확도 (표준 공식 대비 검증)
- **SC-003**: 기존 739 테스트 통과
- **SC-004**: PRE_OPEN + SNIPE 통합 동작 확인
