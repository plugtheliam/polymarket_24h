"""Paired Entry strategy — buy both YES and NO when combined cost < $1.00.

Inspired by polymarket_trader's check_paired_opportunity() (Feature 049).

When YES best_ask + NO best_ask < 1.0, buying both sides simultaneously
guarantees a profit at settlement, regardless of outcome.

Example:
    YES ask = $0.45, NO ask = $0.50 → total $0.95
    Guaranteed payout = $1.00 → profit = $0.05/share (5.26% ROI)

This is a risk-free arbitrage when:
1. Both sides have sufficient liquidity
2. Execution is atomic (both fills succeed)
3. Spread exceeds fee threshold

Phase 3: Paper trading simulation only (dry_run mode).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from poly24h.models.market import Market

logger = logging.getLogger(__name__)


@dataclass
class PairedEntryOpportunity:
    """Detected paired entry opportunity.

    Attributes:
        market: Target market.
        yes_ask: YES side best ask price.
        no_ask: NO side best ask price.
        total_cost: yes_ask + no_ask.
        spread: 1.0 - total_cost (guaranteed profit per share).
        roi_pct: spread / total_cost × 100.
        yes_size: Shares available at YES best ask.
        no_size: Shares available at NO best ask.
        max_shares: Min of available shares on both sides.
        detected_at: Timestamp of detection.
        source: How this was detected ('ws_cache', 'http_poll', 'orderbook').
    """

    market: Market
    yes_ask: float
    no_ask: float
    total_cost: float
    spread: float
    roi_pct: float
    yes_size: float = 0.0
    no_size: float = 0.0
    max_shares: float = 0.0
    detected_at: datetime = None  # type: ignore[assignment]
    source: str = "http_poll"

    def __post_init__(self):
        if self.detected_at is None:
            self.detected_at = datetime.now(tz=timezone.utc)

    @property
    def potential_profit_usd(self) -> float:
        """Potential profit in USD if max_shares are filled."""
        return self.spread * self.max_shares

    def to_dict(self) -> dict:
        """Serialize for JSONL logging."""
        return {
            "market_id": self.market.id,
            "market_question": self.market.question,
            "market_source": self.market.source.value,
            "event_title": self.market.event_title,
            "yes_ask": self.yes_ask,
            "no_ask": self.no_ask,
            "total_cost": self.total_cost,
            "spread": self.spread,
            "roi_pct": self.roi_pct,
            "yes_size": self.yes_size,
            "no_size": self.no_size,
            "max_shares": self.max_shares,
            "potential_profit_usd": self.potential_profit_usd,
            "source": self.source,
            "detected_at": self.detected_at.isoformat(),
        }


class PairedEntryDetector:
    """Detect paired entry opportunities.

    Checks if YES_ask + NO_ask < max_combined_cost for a market.
    Both sides must be above min_price to filter garbage signals.

    Args:
        max_combined_cost: Maximum combined cost (default 0.98 = 2% margin).
        min_price: Minimum price for either side (filters $0.001 garbage).
        min_spread: Minimum spread (margin) required.
        min_size_usd: Minimum liquidity (shares × price) on each side.
    """

    def __init__(
        self,
        max_combined_cost: float = 0.98,
        min_price: float = 0.02,
        min_spread: float = 0.015,
        min_size_usd: float = 5.0,
    ):
        self.max_combined_cost = max_combined_cost
        self.min_price = min_price
        self.min_spread = min_spread
        self.min_size_usd = min_size_usd

    def detect(
        self,
        market: Market,
        yes_ask: float,
        no_ask: float,
        yes_size: float = 0.0,
        no_size: float = 0.0,
        source: str = "http_poll",
    ) -> PairedEntryOpportunity | None:
        """Check if paired entry opportunity exists.

        Args:
            market: Target market.
            yes_ask: YES best ask price.
            no_ask: NO best ask price.
            yes_size: Shares at YES best ask.
            no_size: Shares at NO best ask.
            source: Detection source for logging.

        Returns:
            PairedEntryOpportunity if found, None otherwise.
        """
        # Validate prices
        if yes_ask <= 0 or no_ask <= 0:
            return None

        # Filter garbage prices
        if yes_ask < self.min_price or no_ask < self.min_price:
            return None

        total_cost = yes_ask + no_ask
        spread = 1.0 - total_cost

        # Combined cost must be below threshold
        if total_cost >= self.max_combined_cost:
            return None

        # Spread must exceed minimum
        if spread <= self.min_spread:
            return None

        # Calculate ROI
        roi_pct = (spread / total_cost) * 100.0

        # Determine max executable shares
        max_shares = 0.0
        if yes_size > 0 and no_size > 0:
            max_shares = min(yes_size, no_size)

            # Check minimum liquidity (optional — only if sizes provided)
            yes_value = yes_ask * yes_size
            no_value = no_ask * no_size
            if yes_value < self.min_size_usd or no_value < self.min_size_usd:
                return None

        return PairedEntryOpportunity(
            market=market,
            yes_ask=yes_ask,
            no_ask=no_ask,
            total_cost=total_cost,
            spread=spread,
            roi_pct=roi_pct,
            yes_size=yes_size,
            no_size=no_size,
            max_shares=max_shares,
            source=source,
        )


@dataclass
class PairedPaperTrade:
    """Paper trade record for paired entry simulation."""

    market_id: str
    market_question: str
    market_source: str
    yes_ask: float
    no_ask: float
    total_cost: float
    spread: float
    roi_pct: float
    shares: float  # Shares bought on each side
    cost_usd: float  # total_cost × shares
    guaranteed_profit: float  # spread × shares
    source: str
    timestamp: str
    status: str = "open"  # "open" or "settled"
    actual_pnl: float = 0.0  # After settlement

    def to_dict(self) -> dict:
        return {
            "market_id": self.market_id,
            "market_question": self.market_question,
            "market_source": self.market_source,
            "yes_ask": self.yes_ask,
            "no_ask": self.no_ask,
            "total_cost": self.total_cost,
            "spread": self.spread,
            "roi_pct": self.roi_pct,
            "shares": self.shares,
            "cost_usd": self.cost_usd,
            "guaranteed_profit": self.guaranteed_profit,
            "source": self.source,
            "timestamp": self.timestamp,
            "status": self.status,
            "actual_pnl": self.actual_pnl,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PairedPaperTrade:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class PairedEntrySimulator:
    """Paper trading simulator for paired entry opportunities.

    Simulates buying both sides and calculates guaranteed profit.
    Logs all trades to JSONL file.

    Args:
        paper_size_usd: Fixed USD amount per paper trade (default $20).
        data_dir: Directory for JSONL output.
    """

    def __init__(
        self,
        paper_size_usd: float = 20.0,
        data_dir: str = "data/paper_trades",
    ):
        self.paper_size_usd = paper_size_usd
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._trades: list[PairedPaperTrade] = []
        self._total_cost: float = 0.0
        self._total_guaranteed_profit: float = 0.0

    def simulate_trade(
        self, opp: PairedEntryOpportunity,
    ) -> PairedPaperTrade:
        """Simulate a paired entry paper trade.

        Args:
            opp: Detected paired entry opportunity.

        Returns:
            PairedPaperTrade record.
        """
        # Calculate shares from fixed paper budget
        shares = self.paper_size_usd / opp.total_cost
        cost = self.paper_size_usd
        guaranteed_profit = opp.spread * shares

        trade = PairedPaperTrade(
            market_id=opp.market.id,
            market_question=opp.market.question,
            market_source=opp.market.source.value,
            yes_ask=opp.yes_ask,
            no_ask=opp.no_ask,
            total_cost=opp.total_cost,
            spread=opp.spread,
            roi_pct=opp.roi_pct,
            shares=shares,
            cost_usd=cost,
            guaranteed_profit=guaranteed_profit,
            source=opp.source,
            timestamp=opp.detected_at.isoformat(),
        )

        self._trades.append(trade)
        self._total_cost += cost
        self._total_guaranteed_profit += guaranteed_profit

        # Log to JSONL
        self._append_to_jsonl(trade)

        logger.info(
            "[PAIRED-PAPER] %s | cost=$%.4f (Y:$%.4f+N:$%.4f) "
            "| %.0f shares | profit=$%.4f (%.2f%%) | %s",
            opp.market.question[:50],
            opp.total_cost, opp.yes_ask, opp.no_ask,
            shares, guaranteed_profit, opp.roi_pct,
            opp.source,
        )

        return trade

    def _append_to_jsonl(self, trade: PairedPaperTrade) -> None:
        """Append trade to today's JSONL file."""
        now = datetime.now(tz=timezone.utc)
        file_path = self.data_dir / f"paired_{now.strftime('%Y-%m-%d')}.jsonl"
        with open(file_path, "a") as f:
            f.write(json.dumps(trade.to_dict()) + "\n")

    def get_summary(self) -> dict:
        """Get paper trading summary."""
        return {
            "total_trades": len(self._trades),
            "total_cost": round(self._total_cost, 2),
            "total_guaranteed_profit": round(self._total_guaranteed_profit, 4),
            "avg_roi_pct": (
                sum(t.roi_pct for t in self._trades) / len(self._trades)
                if self._trades else 0.0
            ),
        }
