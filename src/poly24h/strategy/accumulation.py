"""F-016: Gabagool-Style Dual-Sided Accumulation Strategy.

Gabagool22 전략 핵심을 poly24h 1시간 마켓에 적응:
1. Dual-Sided Accumulation: YES/NO 양쪽 저가 매수 → 균형 포지션 구축
2. ΔCPP Optimization: Cost Per Pair를 최소화하는 방향으로 매수 측 선택
3. CTF Merge: YES+NO 쌍이 모이면 $1.00으로 병합 → 확정 수익
4. Spread Filter: ask_sum < max_spread일 때만 축적

Reference: polymarket_trader/src/sniper/micro_gabagool.py (DualSidedAccumulator)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AccumulationConfig:
    """축적 전략 설정."""

    max_spread: float = 1.02       # ask_sum 최대값 (이상이면 대기)
    order_size: float = 50.0       # 1회 주문 금액 ($)
    min_merge_pairs: int = 5       # merge 최소 쌍 수
    target_cpp: float = 0.98       # 목표 CPP (이하면 merge)


@dataclass
class AccumulatedPosition:
    """양쪽 축적 포지션 추적.

    yes_shares/no_shares: 보유 수량
    yes_cost/no_cost: 총 매수 비용 ($)
    """

    market_id: str
    yes_shares: float = 0.0
    no_shares: float = 0.0
    yes_cost: float = 0.0
    no_cost: float = 0.0

    @property
    def paired_shares(self) -> float:
        """min(yes, no) — merge 가능한 쌍 수."""
        return min(self.yes_shares, self.no_shares)

    @property
    def cpp(self) -> float:
        """Cost Per Pair = (yes_cost + no_cost) / paired_shares.

        paired_shares == 0이면 inf 반환.
        """
        paired = self.paired_shares
        if paired <= 0:
            return float("inf")
        return (self.yes_cost + self.no_cost) / paired

    @property
    def merge_profit(self) -> float:
        """paired_shares × (1.0 - cpp) — merge 시 수익.

        paired_shares == 0이면 0.0 반환.
        """
        paired = self.paired_shares
        if paired <= 0:
            return 0.0
        return paired * (1.0 - self.cpp)

    def projected_cpp_after_buy(
        self, side: str, shares: float, price: float
    ) -> float:
        """side 매수 후 예상 CPP 계산.

        Args:
            side: 'yes' or 'no'
            shares: 매수 수량
            price: 매수 가격

        Returns:
            projected CPP. paired가 0이면 inf.
        """
        new_cost = shares * price
        if side == "yes":
            new_yes_shares = self.yes_shares + shares
            new_yes_cost = self.yes_cost + new_cost
            new_no_shares = self.no_shares
            new_no_cost = self.no_cost
        else:
            new_yes_shares = self.yes_shares
            new_yes_cost = self.yes_cost
            new_no_shares = self.no_shares + shares
            new_no_cost = self.no_cost + new_cost

        paired = min(new_yes_shares, new_no_shares)
        if paired <= 0:
            return float("inf")
        return (new_yes_cost + new_no_cost) / paired

    def add(self, side: str, shares: float, price: float) -> None:
        """포지션 추가.

        Args:
            side: 'yes' or 'no'
            shares: 수량
            price: 가격

        Raises:
            ValueError: side가 'yes' 또는 'no'가 아닌 경우.
        """
        if side == "yes":
            self.yes_shares += shares
            self.yes_cost += shares * price
        elif side == "no":
            self.no_shares += shares
            self.no_cost += shares * price
        else:
            raise ValueError(f"Invalid side: {side!r}. Must be 'yes' or 'no'.")


class AccumulationStrategy:
    """Gabagool22-style dual-sided accumulation with ΔCPP optimization.

    Algorithm (tick):
    1. ask_sum = yes_ask + no_ask
    2. If ask_sum >= max_spread: return None (WAIT)
    3. Calculate projected_cpp for each side
    4. Choose side with LOWER projected_cpp (ΔCPP optimization)
    5. Tie-breaker: underweight side, then cheaper side
    """

    def __init__(self, config: AccumulationConfig | None = None) -> None:
        self.config = config or AccumulationConfig()

    def tick(
        self,
        position: AccumulatedPosition,
        yes_ask: float,
        no_ask: float,
    ) -> str | None:
        """매수 측 결정.

        Returns 'yes', 'no', or None (대기).
        """
        # Step 1-2: Spread filter
        ask_sum = yes_ask + no_ask
        if ask_sum >= self.config.max_spread:
            return None

        # Step 3: Calculate shares from order_size
        yes_shares_to_buy = self.config.order_size / yes_ask if yes_ask > 0 else 0
        no_shares_to_buy = self.config.order_size / no_ask if no_ask > 0 else 0

        # Step 4: ΔCPP optimization — projected_cpp 비교
        projected_yes = position.projected_cpp_after_buy(
            "yes", yes_shares_to_buy, yes_ask
        )
        projected_no = position.projected_cpp_after_buy(
            "no", no_shares_to_buy, no_ask
        )

        # 이미 포지션이 있을 때만 ΔCPP 비교 (빈 포지션이면 tie-breaker로)
        if position.yes_shares > 0 or position.no_shares > 0:
            if projected_yes < projected_no:
                return "yes"
            if projected_no < projected_yes:
                return "no"

        # Step 5: Tie-breaker 1 — underweight side
        if position.yes_shares < position.no_shares:
            return "yes"
        if position.no_shares < position.yes_shares:
            return "no"

        # Step 5: Tie-breaker 2 — cheaper side
        if yes_ask < no_ask:
            return "yes"
        if no_ask < yes_ask:
            return "no"

        # 완전 동일: yes 우선
        return "yes"

    def should_merge(self, position: AccumulatedPosition) -> bool:
        """merge 가능 여부: paired >= min_merge_pairs AND cpp < 1.0."""
        paired = position.paired_shares
        if paired < self.config.min_merge_pairs:
            return False
        if position.cpp >= 1.0:
            return False
        return True

    def merge_profit(self, position: AccumulatedPosition) -> float:
        """예상 merge 수익 = paired_shares × (1.0 - cpp)."""
        return position.merge_profit


class MarketPhaseDetector:
    """1시간 마켓의 수명 주기 기반 phase 분류.

    minutes_remaining 기준:
    - AGGRESSIVE: > 55min (마켓 오픈 직후 0-5분)
    - NORMAL: 15-55min (5-45분)
    - PASSIVE: 5-15min (45-55분, 정확히는 5 이상 15 미만)
    - CLOSE_ONLY: < 5min (마감 임박)
    """

    @staticmethod
    def get_phase(minutes_remaining: float) -> str:
        """잔여 시간 기반 phase 반환."""
        if minutes_remaining > 55:
            return "AGGRESSIVE"
        if minutes_remaining >= 15:
            return "NORMAL"
        if minutes_remaining >= 5:
            return "PASSIVE"
        return "CLOSE_ONLY"

    @staticmethod
    def should_accumulate(phase: str) -> bool:
        """AGGRESSIVE or NORMAL일 때만 축적."""
        return phase in ("AGGRESSIVE", "NORMAL")

    @staticmethod
    def should_merge(phase: str) -> bool:
        """merge는 언제든 가능."""
        return True
