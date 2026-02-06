"""Market and MarketSource data models."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class MarketSource(Enum):
    """마켓 소스 카테고리."""

    HOURLY_CRYPTO = "hourly_crypto"
    NBA = "nba"
    NHL = "nhl"
    TENNIS = "tennis"
    SOCCER = "soccer"
    ESPORTS = "esports"


@dataclass
class Market:
    """A single Polymarket binary market."""

    id: str
    question: str
    source: MarketSource
    yes_token_id: str
    no_token_id: str
    yes_price: float
    no_price: float
    liquidity_usd: float
    end_date: datetime
    event_id: str
    event_title: str

    @property
    def total_cost(self) -> float:
        """YES + NO 가격 합."""
        return self.yes_price + self.no_price

    @property
    def spread(self) -> float:
        """1.0 - total_cost. 양수면 아비트라지 기회."""
        return 1.0 - self.total_cost

    @property
    def is_expired(self) -> bool:
        """정산 시간이 지났는지 확인."""
        return datetime.now(tz=timezone.utc) >= self.end_date

    @staticmethod
    def from_gamma_response(
        raw_mkt: dict,
        event: dict,
        source: MarketSource,
    ) -> Optional[Market]:
        """Gamma API raw dict → Market 객체. 파싱 실패 시 None."""
        outcome_prices = raw_mkt.get("outcomePrices")
        clob_token_ids = raw_mkt.get("clobTokenIds")

        if not outcome_prices or not clob_token_ids:
            return None

        # Gamma API는 JSON 문자열로 반환할 수 있음
        if isinstance(outcome_prices, str):
            try:
                outcome_prices = json.loads(outcome_prices)
            except (json.JSONDecodeError, TypeError):
                return None

        if isinstance(clob_token_ids, str):
            try:
                clob_token_ids = json.loads(clob_token_ids)
            except (json.JSONDecodeError, TypeError):
                return None

        if len(outcome_prices) < 2 or len(clob_token_ids) < 2:
            return None

        # endDate: 마켓 우선, 이벤트 폴백
        end_date_str = raw_mkt.get("endDate") or event.get("endDate", "")
        if not end_date_str:
            return None

        try:
            end_date = datetime.fromisoformat(
                end_date_str.replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            return None

        return Market(
            id=str(raw_mkt.get("id", "")),
            question=raw_mkt.get("question", ""),
            source=source,
            yes_token_id=str(clob_token_ids[0]),
            no_token_id=str(clob_token_ids[1]),
            yes_price=float(outcome_prices[0]),
            no_price=float(outcome_prices[1]),
            liquidity_usd=float(raw_mkt.get("liquidity", 0) or 0),
            end_date=end_date,
            event_id=str(event.get("id", "")),
            event_title=event.get("title", ""),
        )
