"""NegRisk multi-outcome market models.

NegRisk 다중 아웃컴 마켓: 하나의 이벤트에 3개+ 선택지가 있고,
모든 YES 가격 합이 $1.00 미만이면 아비트라지 기회.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class NegRiskOutcome:
    """NegRisk 이벤트의 개별 아웃컴 (개별 바이너리 마켓)."""

    market_id: str
    question: str
    token_id: str  # YES token
    price: float
    liquidity_usd: float


@dataclass
class NegRiskMarket:
    """NegRisk 이벤트 전체 — 여러 아웃컴 그룹."""

    event_id: str
    event_title: str
    outcomes: list[NegRiskOutcome]

    @property
    def total_prob(self) -> float:
        """모든 아웃컴 YES 가격 합."""
        return sum(o.price for o in self.outcomes)

    @property
    def margin(self) -> float:
        """1.0 - total_prob. 양수면 아비트라지 기회."""
        return 1.0 - self.total_prob

    @property
    def roi_pct(self) -> float:
        """ROI = margin / total_prob * 100. 아웃컴 없으면 0."""
        tp = self.total_prob
        if tp <= 0:
            return 0.0
        return (self.margin / tp) * 100.0


@dataclass
class NegRiskOpportunity:
    """감지된 NegRisk 아비트라지 기회."""

    negrisk_market: NegRiskMarket
    margin: float
    roi_pct: float
    recommended_size_usd: float
    detected_at: datetime
