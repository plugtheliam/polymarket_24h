"""Paper trade settlement tracker — resolves trades via Gamma API.

After market end_date passes:
1. Query Gamma API for resolved outcome
2. Determine winning side (YES/NO)
3. Calculate P&L: winning_shares × $1.00 - cost
4. Update running P&L and log daily summary

Inspired by polymarket_trader's settlement_tracker.py and dryrun_pnl.py.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import aiohttp

logger = logging.getLogger(__name__)

Winner = Literal["YES", "NO", "pending", "unknown"]

GAMMA_API_URL = "https://gamma-api.polymarket.com"


@dataclass
class PaperTrade:
    """A single paper trade record."""

    market_id: str
    market_question: str
    market_source: str
    side: str  # "YES" or "NO"
    price: float
    shares: float  # paper_size / price
    cost: float  # paper_size
    timestamp: str
    end_date: str  # Market end date (ISO format)
    status: str = "open"  # "open", "settled", "expired"
    winner: str = ""  # "YES", "NO", or empty
    payout: float = 0.0
    pnl: float = 0.0

    def to_dict(self) -> dict:
        return {
            "market_id": self.market_id,
            "market_question": self.market_question,
            "market_source": self.market_source,
            "side": self.side,
            "price": self.price,
            "shares": self.shares,
            "cost": self.cost,
            "timestamp": self.timestamp,
            "end_date": self.end_date,
            "status": self.status,
            "winner": self.winner,
            "payout": self.payout,
            "pnl": self.pnl,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PaperTrade:
        return cls(
            market_id=data["market_id"],
            market_question=data.get("market_question", ""),
            market_source=data.get("market_source", ""),
            side=data["side"],
            price=data["price"],
            shares=data["shares"],
            cost=data["cost"],
            timestamp=data["timestamp"],
            end_date=data.get("end_date", ""),
            status=data.get("status", "open"),
            winner=data.get("winner", ""),
            payout=data.get("payout", 0.0),
            pnl=data.get("pnl", 0.0),
        )


@dataclass
class SettlementSummary:
    """Summary of settlement operations."""

    total_open: int = 0
    total_settled: int = 0
    total_expired: int = 0  # Past end_date but not resolved yet
    newly_settled: int = 0
    cumulative_pnl: float = 0.0
    wins: int = 0
    losses: int = 0

    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses
        return self.wins / total if total > 0 else 0.0


class PaperSettlementTracker:
    """Tracks paper trades and resolves them via Gamma API.

    Stores trades in JSONL files: data/paper_trades/YYYY-MM-DD.jsonl
    """

    def __init__(self, data_dir: str = "data/paper_trades"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._cumulative_pnl: float = 0.0
        self._wins: int = 0
        self._losses: int = 0
        self._recorded_market_ids: set[str] = set()  # Dedup: prevent duplicate JSONL writes

    def _get_file_path(self, date: datetime | None = None) -> Path:
        if date is None:
            date = datetime.now(tz=timezone.utc)
        return self.data_dir / f"{date.strftime('%Y-%m-%d')}.jsonl"

    def _load_recorded_ids(self, date: datetime | None = None) -> None:
        """Load already-recorded market IDs from today's file for dedup."""
        if self._recorded_market_ids:
            return  # Already loaded
        file_path = self._get_file_path(date)
        if not file_path.exists():
            return
        try:
            with open(file_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        mid = data.get("market_id", "")
                        if mid:
                            self._recorded_market_ids.add(mid)
        except Exception as e:
            logger.warning("Failed to load recorded IDs: %s", e)

    def record_trade(self, trade: PaperTrade) -> None:
        """Append a new paper trade to today's file (with dedup)."""
        # Dedup: skip if already recorded for this market
        self._load_recorded_ids()
        if trade.market_id in self._recorded_market_ids:
            logger.debug(
                "[PAPER-TRADE] SKIP duplicate: %s already recorded",
                trade.market_question[:40],
            )
            return

        self._recorded_market_ids.add(trade.market_id)
        file_path = self._get_file_path()
        with open(file_path, "a") as f:
            f.write(json.dumps(trade.to_dict()) + "\n")
        logger.info(
            "[PAPER-TRADE] %s %s@$%.4f $%.2f | %s",
            trade.side, trade.market_question[:40],
            trade.price, trade.cost, trade.market_source,
        )

    def load_trades(self, date: datetime | None = None) -> list[PaperTrade]:
        """Load all trades for a given date."""
        file_path = self._get_file_path(date)
        if not file_path.exists():
            return []
        trades = []
        with open(file_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    trades.append(PaperTrade.from_dict(json.loads(line)))
        return trades

    def _save_trades(self, trades: list[PaperTrade], date: datetime | None = None) -> None:
        """Overwrite trades file for a given date."""
        file_path = self._get_file_path(date)
        with open(file_path, "w") as f:
            for trade in trades:
                f.write(json.dumps(trade.to_dict()) + "\n")

    async def query_market_result(self, market_id: str) -> Winner:
        """Query Gamma API for market settlement.

        Returns "YES", "NO", "pending", or "unknown".
        """
        url = f"{GAMMA_API_URL}/markets/{market_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "[SETTLEMENT] API error for %s: %d", market_id, resp.status
                        )
                        return "unknown"

                    data = await resp.json()
                    if not data:
                        return "unknown"

                    # Check if closed
                    closed = data.get("closed", False)
                    if not closed:
                        return "pending"

                    # Check outcomePrices — winner has price ~1.0
                    outcome_prices = data.get("outcomePrices")
                    if outcome_prices:
                        if isinstance(outcome_prices, str):
                            outcome_prices = json.loads(outcome_prices)
                        if len(outcome_prices) >= 2:
                            yes_price = float(outcome_prices[0])
                            no_price = float(outcome_prices[1])
                            if yes_price >= 0.99:
                                return "YES"
                            if no_price >= 0.99:
                                return "NO"

                    return "unknown"

        except Exception as exc:
            logger.warning("[SETTLEMENT] Query error for %s: %s", market_id, exc)
            return "unknown"

    def settle_trade(self, trade: PaperTrade, winner: Winner) -> float:
        """Calculate P&L for a settled trade.

        Returns the P&L amount.
        """
        if winner not in ("YES", "NO"):
            return 0.0

        # If our bet side matches the winner, we win
        if trade.side == winner:
            # Winning: shares × $1.00 - cost
            payout = trade.shares * 1.0
            pnl = payout - trade.cost
        else:
            # Losing: we get $0, lose our cost
            payout = 0.0
            pnl = -trade.cost

        trade.status = "settled"
        trade.winner = winner
        trade.payout = payout
        trade.pnl = pnl

        return pnl

    async def check_and_settle(
        self, date: datetime | None = None, grace_minutes: int = 5,
    ) -> SettlementSummary:
        """Check all open trades for settlement.

        Iterates through today's trades, queries expired markets,
        updates P&L, and returns summary.

        Args:
            date: Date to check (default: today).
            grace_minutes: Wait this many minutes past end_date before querying.
                Gives Polymarket time to resolve the market.
        """
        now = datetime.now(tz=timezone.utc)
        trades = self.load_trades(date)
        summary = SettlementSummary()
        newly_settled = 0

        for trade in trades:
            if trade.status == "settled":
                summary.total_settled += 1
                self._cumulative_pnl += trade.pnl
                if trade.pnl > 0:
                    summary.wins += 1
                    self._wins += 1
                elif trade.pnl < 0:
                    summary.losses += 1
                    self._losses += 1
                continue

            # Check if past end_date
            try:
                end_dt = datetime.fromisoformat(
                    trade.end_date.replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                summary.total_open += 1
                continue

            if now < end_dt:
                summary.total_open += 1
                continue

            # Grace period: wait a few minutes for market to resolve
            from datetime import timedelta
            grace_dt = end_dt + timedelta(minutes=grace_minutes)
            if now < grace_dt:
                summary.total_expired += 1
                continue

            # Past end_date + grace — try to settle
            winner = await self.query_market_result(trade.market_id)

            if winner in ("YES", "NO"):
                pnl = self.settle_trade(trade, winner)
                self._cumulative_pnl += pnl
                newly_settled += 1
                summary.total_settled += 1

                if pnl > 0:
                    summary.wins += 1
                    self._wins += 1
                elif pnl < 0:
                    summary.losses += 1
                    self._losses += 1

                logger.info(
                    "[SETTLEMENT] %s → %s | P&L: $%.2f | %s",
                    trade.market_question[:40], winner, pnl,
                    trade.side,
                )
            elif winner == "pending":
                summary.total_expired += 1
            else:
                summary.total_expired += 1

        # Save updated trades
        if newly_settled > 0:
            self._save_trades(trades, date)

        summary.newly_settled = newly_settled
        summary.cumulative_pnl = self._cumulative_pnl
        return summary

    def format_settlement_report(self, summary: SettlementSummary) -> str:
        """Format settlement summary for Telegram."""
        lines = [
            f"💰 <b>Paper Trade 정산</b>",
            f"{'━' * 28}",
            f"Open: {summary.total_open}건",
            f"Settled: {summary.total_settled}건 (신규 {summary.newly_settled}건)",
            f"Expired (미결산): {summary.total_expired}건",
            f"",
            f"Wins: {summary.wins} | Losses: {summary.losses}",
            f"Win Rate: {summary.win_rate * 100:.1f}%",
            f"Cumulative P&L: <b>${summary.cumulative_pnl:+.2f}</b>",
        ]
        return "\n".join(lines)

    @property
    def cumulative_pnl(self) -> float:
        return self._cumulative_pnl

    @property
    def wins(self) -> int:
        return self._wins

    @property
    def losses(self) -> int:
        return self._losses
