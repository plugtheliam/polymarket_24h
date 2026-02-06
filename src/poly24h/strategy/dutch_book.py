"""Dutch Book (Single Condition) arbitrage detector.

A Dutch Book arb exists when YES_ask + NO_ask < 1.0
Buying both guarantees $1.00 payout at settlement.
Profit = 1.0 - total_cost.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from poly24h.models.market import Market
from poly24h.models.opportunity import ArbType, Opportunity


def detect_single_condition(
    market: Market,
    min_spread: float = 0.01,
) -> Optional[Opportunity]:
    """
    Dutch Book 기회 감지.

    Args:
        market: 바이너리 마켓
        min_spread: 최소 마진 (기본 1%)

    Returns:
        Opportunity if found, None otherwise
    """
    yes_price = market.yes_price
    no_price = market.no_price

    # 유효하지 않은 가격 스킵
    if yes_price <= 0 or no_price <= 0:
        return None

    total_cost = yes_price + no_price
    threshold = 1.0 - min_spread

    # total_cost가 threshold 이상이면 기회 없음
    if total_cost >= threshold:
        return None

    margin = 1.0 - total_cost
    roi_pct = (margin / total_cost) * 100.0

    return Opportunity(
        market=market,
        arb_type=ArbType.SINGLE_CONDITION,
        yes_price=yes_price,
        no_price=no_price,
        total_cost=total_cost,
        margin=margin,
        roi_pct=roi_pct,
        recommended_size_usd=0.0,  # Phase 2 RiskManager가 채움
        detected_at=datetime.now(tz=timezone.utc),
    )
