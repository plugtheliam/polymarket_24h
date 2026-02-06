"""NegRisk multi-outcome arbitrage strategy.

모든 아웃컴 YES를 매수하여 보장된 $1.00 정산 수익을 확보.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from poly24h.execution.order_builder import Order
from poly24h.models.negrisk import NegRiskMarket, NegRiskOpportunity


def detect_negrisk_arb(
    negrisk_market: NegRiskMarket,
    min_spread: float = 0.02,
) -> Optional[NegRiskOpportunity]:
    """NegRisk 아비트라지 기회 감지.

    Args:
        negrisk_market: 다중 아웃컴 마켓.
        min_spread: 최소 마진 (기본 2%).

    Returns:
        NegRiskOpportunity if found, None otherwise.
    """
    # 빈 아웃컴 → 기회 없음
    if not negrisk_market.outcomes:
        return None

    # 가격 0인 아웃컴이 있으면 스킵 (모든 아웃컴을 매수해야 하므로)
    for outcome in negrisk_market.outcomes:
        if outcome.price <= 0:
            return None

    total_prob = negrisk_market.total_prob
    threshold = 1.0 - min_spread

    # total_prob >= threshold이면 기회 없음
    if total_prob >= threshold:
        return None

    margin = negrisk_market.margin
    roi_pct = negrisk_market.roi_pct

    return NegRiskOpportunity(
        negrisk_market=negrisk_market,
        margin=margin,
        roi_pct=roi_pct,
        recommended_size_usd=0.0,  # RiskManager가 채움
        detected_at=datetime.now(tz=timezone.utc),
    )


def build_negrisk_orders(
    opportunity: NegRiskOpportunity,
    budget: float,
) -> list[Order]:
    """NegRisk 아비트라지 주문 생성 — 모든 아웃컴 YES 매수.

    Args:
        opportunity: 감지된 NegRisk 기회.
        budget: 최대 투자 금액 (USD).

    Returns:
        각 아웃컴에 대한 YES BUY 주문 리스트.

    Raises:
        ValueError: budget <= 0.
    """
    if budget <= 0:
        raise ValueError(f"Invalid budget: {budget}")

    outcomes = opportunity.negrisk_market.outcomes
    total_prob = opportunity.negrisk_market.total_prob

    # 유동성 제약: 최소 유동성 기준으로 사이즈 축소
    min_liquidity = min(o.liquidity_usd for o in outcomes)
    effective_budget = min(budget, min_liquidity)

    # shares = budget / total_prob (동일 shares를 모든 아웃컴에 매수)
    shares = effective_budget / total_prob

    orders: list[Order] = []
    for outcome in outcomes:
        order = Order(
            token_id=outcome.token_id,
            side="BUY",
            price=outcome.price,
            size=shares,
            total_cost=shares * outcome.price,
        )
        orders.append(order)

    return orders
