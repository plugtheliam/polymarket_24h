"""Per-market detailed opportunity logging and statistics.

Phase 3: Tracks which markets (BTC/ETH/SOL/XRP) produce the most
opportunities and at what times, to optimize sniper timing.

Data is stored in JSONL files: data/paper_trades/market_stats_YYYY-MM-DD.jsonl

Statistics tracked:
- Opportunity count per market/asset
- Time distribution: seconds after market open when opportunities appear
- Price distribution: min/max/avg prices seen
- Source breakdown: ws_cache vs http_poll detection
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class OpportunityRecord:
    """Single opportunity detection record for logging."""

    market_id: str
    market_question: str
    market_source: str  # hourly_crypto, nba, soccer, etc.
    asset_symbol: str  # BTC, ETH, SOL, XRP, or "" for non-crypto
    trigger_side: str  # YES, NO
    trigger_price: float
    spread: float  # YES+NO spread (may be 0 if not available)
    seconds_since_open: float  # Seconds after market open
    detection_source: str  # ws_cache, http_poll, orderbook
    is_paired: bool  # True if part of paired entry opportunity
    timestamp: str  # ISO format

    def to_dict(self) -> dict:
        return {
            "market_id": self.market_id,
            "market_question": self.market_question,
            "market_source": self.market_source,
            "asset_symbol": self.asset_symbol,
            "trigger_side": self.trigger_side,
            "trigger_price": self.trigger_price,
            "spread": self.spread,
            "seconds_since_open": self.seconds_since_open,
            "detection_source": self.detection_source,
            "is_paired": self.is_paired,
            "timestamp": self.timestamp,
        }


def extract_asset_symbol(question: str) -> str:
    """Extract asset symbol (BTC, ETH, SOL, XRP) from market question.

    Examples:
        "Will BTC be above $100,000..." → "BTC"
        "Will ETH go up in the next 1 hour?" → "ETH"
        "Lakers vs Celtics" → ""
    """
    question_upper = question.upper()
    for symbol in ("BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "MATIC"):
        if symbol in question_upper:
            return symbol
    return ""


class MarketOpportunityLogger:
    """Logs and analyzes per-market opportunity data.

    Writes to JSONL and maintains in-memory stats.
    """

    def __init__(self, data_dir: str = "data/paper_trades"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._records: list[OpportunityRecord] = []
        # In-memory aggregation
        self._by_asset: dict[str, list[OpportunityRecord]] = defaultdict(list)
        self._by_second: dict[int, int] = defaultdict(int)  # second → count

    def record(
        self,
        market_id: str,
        market_question: str,
        market_source: str,
        trigger_side: str,
        trigger_price: float,
        spread: float = 0.0,
        seconds_since_open: float = 0.0,
        detection_source: str = "http_poll",
        is_paired: bool = False,
    ) -> OpportunityRecord:
        """Record an opportunity detection event.

        Args:
            market_id: Polymarket market ID.
            market_question: Market question text.
            market_source: Source category (hourly_crypto, nba, etc.).
            trigger_side: "YES" or "NO".
            trigger_price: Price that triggered the signal.
            spread: Combined YES+NO spread if known.
            seconds_since_open: Time since market open.
            detection_source: How detected (ws_cache, http_poll, orderbook).
            is_paired: Whether this is part of a paired entry.

        Returns:
            Created OpportunityRecord.
        """
        now = datetime.now(tz=timezone.utc)
        asset = extract_asset_symbol(market_question)

        rec = OpportunityRecord(
            market_id=market_id,
            market_question=market_question,
            market_source=market_source,
            asset_symbol=asset,
            trigger_side=trigger_side,
            trigger_price=trigger_price,
            spread=spread,
            seconds_since_open=seconds_since_open,
            detection_source=detection_source,
            is_paired=is_paired,
            timestamp=now.isoformat(),
        )

        self._records.append(rec)
        self._by_asset[asset or "OTHER"].append(rec)
        self._by_second[int(seconds_since_open)] += 1

        # Write to JSONL
        self._append_to_jsonl(rec, now)

        return rec

    def _append_to_jsonl(self, rec: OpportunityRecord, now: datetime) -> None:
        """Append record to today's market stats JSONL."""
        file_path = self.data_dir / f"market_stats_{now.strftime('%Y-%m-%d')}.jsonl"
        with open(file_path, "a") as f:
            f.write(json.dumps(rec.to_dict()) + "\n")

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_asset_summary(self) -> dict[str, dict]:
        """Get opportunity count and stats grouped by asset symbol.

        Returns dict like:
        {
            "BTC": {"count": 15, "avg_price": 0.42, "min_price": 0.35},
            "ETH": {"count": 8, "avg_price": 0.44, ...},
        }
        """
        summary: dict[str, dict] = {}
        for asset, records in self._by_asset.items():
            prices = [r.trigger_price for r in records]
            summary[asset] = {
                "count": len(records),
                "avg_price": sum(prices) / len(prices) if prices else 0,
                "min_price": min(prices) if prices else 0,
                "max_price": max(prices) if prices else 0,
                "yes_count": sum(1 for r in records if r.trigger_side == "YES"),
                "no_count": sum(1 for r in records if r.trigger_side == "NO"),
                "paired_count": sum(1 for r in records if r.is_paired),
            }
        return summary

    def get_time_distribution(self) -> dict[int, int]:
        """Get opportunity count by second-after-open.

        Returns dict like {0: 3, 1: 5, 2: 8, ...} showing how many
        opportunities were detected at each second after market open.
        """
        return dict(sorted(self._by_second.items()))

    def get_peak_seconds(self, top_n: int = 5) -> list[tuple[int, int]]:
        """Get the top N seconds with most opportunities.

        Returns list of (second, count) tuples, sorted by count descending.
        """
        return sorted(
            self._by_second.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:top_n]

    def get_source_breakdown(self) -> dict[str, int]:
        """Get opportunity count by detection source.

        Returns dict like {"ws_cache": 20, "http_poll": 45, "orderbook": 5}.
        """
        breakdown: dict[str, int] = defaultdict(int)
        for rec in self._records:
            breakdown[rec.detection_source] += 1
        return dict(breakdown)

    def format_stats_report(self) -> str:
        """Format a human-readable stats report.

        Returns:
            Multi-line string with asset summary and timing info.
        """
        lines = [
            "📊 <b>마켓별 기회 통계</b>",
            f"{'━' * 28}",
            f"총 기회: {len(self._records)}건",
            "",
        ]

        # Asset breakdown
        asset_summary = self.get_asset_summary()
        if asset_summary:
            lines.append("<b>자산별</b>")
            for asset, stats in sorted(
                asset_summary.items(), key=lambda x: -x[1]["count"]
            ):
                lines.append(
                    f"  {asset}: {stats['count']}건 "
                    f"(Y:{stats['yes_count']}/N:{stats['no_count']}) "
                    f"avg=${stats['avg_price']:.3f} "
                    f"[${stats['min_price']:.3f}~${stats['max_price']:.3f}]"
                )
                if stats["paired_count"] > 0:
                    lines.append(f"    ↳ paired: {stats['paired_count']}건")

        # Time distribution
        peak = self.get_peak_seconds(top_n=5)
        if peak:
            lines.append("")
            lines.append("<b>시간대별 피크 (정시 기준)</b>")
            for sec, count in peak:
                bar = "█" * min(count, 20)
                lines.append(f"  T+{sec:3d}s: {count:3d}건 {bar}")

        # Source breakdown
        sources = self.get_source_breakdown()
        if sources:
            lines.append("")
            lines.append("<b>감지 소스</b>")
            for src, count in sorted(sources.items(), key=lambda x: -x[1]):
                lines.append(f"  {src}: {count}건")

        return "\n".join(lines)

    def load_from_jsonl(self, date: datetime | None = None) -> list[OpportunityRecord]:
        """Load records from JSONL file for analysis.

        Args:
            date: Date to load (default: today).

        Returns:
            List of OpportunityRecord objects.
        """
        if date is None:
            date = datetime.now(tz=timezone.utc)
        file_path = self.data_dir / f"market_stats_{date.strftime('%Y-%m-%d')}.jsonl"
        if not file_path.exists():
            return []

        records = []
        with open(file_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    records.append(OpportunityRecord(**data))
        return records
