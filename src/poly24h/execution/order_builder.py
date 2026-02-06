"""Arbitrage order builder — Opportunity → (YES Order, NO Order).

아비트라지 기회를 실제 주문 쌍으로 변환.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from poly24h.models.opportunity import Opportunity

logger = logging.getLogger(__name__)


@dataclass
class Order:
    """A single limit order for the CLOB."""

    token_id: str
    side: str        # "BUY" (arb bot only buys)
    price: float     # per-share price
    size: float      # number of shares
    total_cost: float  # size * price


class ArbOrderBuilder:
    """Build YES + NO order pairs from an Opportunity."""

    def build_arb_orders(
        self,
        opportunity: Opportunity,
        max_position_usd: float | None = None,
    ) -> tuple[Order, Order]:
        """Opportunity → (YES Order, NO Order).

        Args:
            opportunity: 감지된 아비트라지 기회.
            max_position_usd: 최대 포지션 사이즈 (USD).
                None이면 opportunity.recommended_size_usd 사용.

        Returns:
            (yes_order, no_order) 튜플.

        Raises:
            ValueError: 유효하지 않은 입력 (0 가격, 음수 예산 등).
        """
        yes_price = opportunity.yes_price
        no_price = opportunity.no_price

        # 가격 유효성
        if yes_price <= 0 or no_price <= 0:
            raise ValueError(f"Invalid price: yes={yes_price}, no={no_price}")

        # 예산 결정
        if max_position_usd is not None:
            budget = max_position_usd
        else:
            budget = opportunity.recommended_size_usd
        if budget <= 0:
            raise ValueError(f"Invalid position size: {budget}")

        # min(budget, recommended) when max_position given
        if max_position_usd is not None:
            budget = min(budget, opportunity.recommended_size_usd)

        # 동일 shares 수를 양쪽에 매수 (balanced arb)
        # total = shares * (yes_price + no_price) = budget
        total_cost_per_pair = yes_price + no_price
        shares = budget / total_cost_per_pair

        yes_order = Order(
            token_id=opportunity.market.yes_token_id,
            side="BUY",
            price=yes_price,
            size=shares,
            total_cost=shares * yes_price,
        )

        no_order = Order(
            token_id=opportunity.market.no_token_id,
            side="BUY",
            price=no_price,
            size=shares,
            total_cost=shares * no_price,
        )

        logger.info(
            "Built arb orders: %d shares @ YES=$%.4f NO=$%.4f (total $%.2f)",
            shares, yes_price, no_price, yes_order.total_cost + no_order.total_cost,
        )

        return yes_order, no_order
