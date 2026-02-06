"""Opportunity ranking and evaluation."""

from __future__ import annotations

from poly24h.models.opportunity import Opportunity


def rank_opportunities(opportunities: list[Opportunity]) -> list[Opportunity]:
    """기회를 ROI 내림차순, 유동성 내림차순으로 정렬.

    Returns new list (원본 불변).
    """
    return sorted(
        opportunities,
        key=lambda o: (o.roi_pct, o.market.liquidity_usd),
        reverse=True,
    )
