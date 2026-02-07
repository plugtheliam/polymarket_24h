"""Arbitrage order builder — Opportunity → (YES Order, NO Order).

아비트라지 기회를 실제 주문 쌍으로 변환.

Phase 4 enhancements:
- GTD (Good-Til-Date) order expiration support
- Nonce generation for unique order IDs
- Slippage protection (max acceptable spread)
- Minimum order size validation
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from poly24h.models.opportunity import Opportunity

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum order size in shares (Polymarket CLOB requirement)
MIN_ORDER_SIZE_SHARES = 1.0

# Default order expiration: 5 minutes (GTD)
DEFAULT_EXPIRATION_SECONDS = 300


@dataclass
class Order:
    """A single limit order for the CLOB.

    Phase 4: Enhanced with expiration, nonce, and fee fields
    for real CLOB submission.
    """

    token_id: str
    side: str        # "BUY" (arb bot only buys)
    price: float     # per-share price
    size: float      # number of shares
    total_cost: float  # size * price
    # Phase 4 additions:
    nonce: str = ""             # Unique order identifier
    expiration: int = 0         # Unix timestamp for GTD orders (0 = GTC)
    fee_rate_bps: str = "0"     # Fee rate in basis points

    def to_clob_payload(self) -> dict:
        """Convert to CLOB API payload format.

        Returns:
            Dict ready for CLOB order submission.
        """
        payload: dict = {
            "tokenID": self.token_id,
            "side": self.side,
            "price": str(self.price),
            "size": str(self.size),
            "feeRateBps": self.fee_rate_bps,
        }
        if self.nonce:
            payload["nonce"] = self.nonce
        if self.expiration > 0:
            payload["expiration"] = str(self.expiration)
        return payload


class ArbOrderBuilder:
    """Build YES + NO order pairs from an Opportunity.

    Phase 4 enhancements:
    - GTD order expiration (default 5 minutes)
    - Slippage protection: reject if spread too tight
    - Minimum order size enforcement
    - Nonce generation for unique orders

    Args:
        expiration_seconds: GTD expiration in seconds (0 = GTC).
        min_spread: Minimum required spread to build orders.
        min_order_size: Minimum shares per order.
    """

    _nonce_counter: int = 0

    def __init__(
        self,
        expiration_seconds: int = DEFAULT_EXPIRATION_SECONDS,
        min_spread: float = 0.005,
        min_order_size: float = MIN_ORDER_SIZE_SHARES,
    ):
        self.expiration_seconds = expiration_seconds
        self.min_spread = min_spread
        self.min_order_size = min_order_size

    def generate_nonce(self) -> str:
        """Generate unique nonce (timestamp + counter)."""
        ts_ms = int(time.time() * 1000)
        ArbOrderBuilder._nonce_counter += 1
        return str(ts_ms * 1000 + (ArbOrderBuilder._nonce_counter % 1000))

    def calculate_expiration(self) -> int:
        """Calculate GTD expiration timestamp. 0 means GTC."""
        if self.expiration_seconds <= 0:
            return 0
        return int(time.time()) + self.expiration_seconds

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

        # Phase 4: Slippage protection — check spread hasn't evaporated
        spread = 1.0 - (yes_price + no_price)
        if spread < self.min_spread:
            raise ValueError(
                f"Spread too thin for safe execution: "
                f"spread={spread:.4f} < min_spread={self.min_spread:.4f}"
            )

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

        # Phase 4: Minimum order size enforcement
        if shares < self.min_order_size:
            raise ValueError(
                f"Order too small: {shares:.2f} shares < "
                f"minimum {self.min_order_size:.2f}"
            )

        # Phase 4: Generate nonces and expiration
        expiration = self.calculate_expiration()

        yes_order = Order(
            token_id=opportunity.market.yes_token_id,
            side="BUY",
            price=yes_price,
            size=shares,
            total_cost=shares * yes_price,
            nonce=self.generate_nonce(),
            expiration=expiration,
        )

        no_order = Order(
            token_id=opportunity.market.no_token_id,
            side="BUY",
            price=no_price,
            size=shares,
            total_cost=shares * no_price,
            nonce=self.generate_nonce(),
            expiration=expiration,
        )

        logger.info(
            "Built arb orders: %d shares @ YES=$%.4f NO=$%.4f "
            "(total $%.2f, spread=$%.4f, exp=%d)",
            shares, yes_price, no_price,
            yes_order.total_cost + no_order.total_cost,
            spread, expiration,
        )

        return yes_order, no_order
