"""Opportunity and ArbType data models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from poly24h.models.market import Market


class ArbType(Enum):
    """아비트라지 유형."""

    SINGLE_CONDITION = "single_condition"  # YES + NO < $1.00
    NEGRISK = "negrisk"                    # 다중 아웃컴 Σprices < $1.00


@dataclass
class Opportunity:
    """감지된 아비트라지 기회."""

    market: Market
    arb_type: ArbType
    yes_price: float
    no_price: float
    total_cost: float       # yes + no
    margin: float           # 1.0 - total_cost
    roi_pct: float          # margin / total_cost * 100
    recommended_size_usd: float
    detected_at: datetime
