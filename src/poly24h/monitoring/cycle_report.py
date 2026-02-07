"""Cycle end summary report — sent on IDLE phase entry.

Generates comprehensive summary of the completed sniper cycle:
- Detected opportunities count, filtered signals count
- Paper trade count, total paper investment
- Market-level price min/max summary
- Sends via Telegram alerter

Inspired by polymarket_trader's settlement_tracker.py and dryrun_pnl.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class MarketPriceStat:
    """Tracks min/max prices seen for a single market during a cycle."""

    question: str
    source: str
    min_yes_ask: float = float("inf")
    max_yes_ask: float = 0.0
    min_no_ask: float = float("inf")
    max_no_ask: float = 0.0
    signal_count: int = 0

    def update(self, yes_ask: float | None, no_ask: float | None) -> None:
        """Update with new price observation."""
        if yes_ask is not None and yes_ask > 0:
            self.min_yes_ask = min(self.min_yes_ask, yes_ask)
            self.max_yes_ask = max(self.max_yes_ask, yes_ask)
        if no_ask is not None and no_ask > 0:
            self.min_no_ask = min(self.min_no_ask, no_ask)
            self.max_no_ask = max(self.max_no_ask, no_ask)
        self.signal_count += 1


@dataclass
class CycleStats:
    """Accumulated stats for a single snipe cycle (one hourly open)."""

    cycle_start: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    cycle_end: datetime | None = None

    # Discovery
    markets_discovered: int = 0
    markets_by_source: dict[str, int] = field(default_factory=dict)

    # Signals
    total_polls: int = 0
    raw_signals: int = 0  # Before quality filter
    filtered_signals: int = 0  # After quality filter (actual opportunities)

    # Paper trades
    paper_trades: int = 0
    paper_total_invested: float = 0.0

    # Per-market price tracking
    market_stats: dict[str, MarketPriceStat] = field(default_factory=dict)

    def record_discovery(
        self, market_count: int, by_source: dict[str, int]
    ) -> None:
        """Record market discovery results."""
        self.markets_discovered = market_count
        self.markets_by_source = dict(by_source)

    def record_poll(self) -> None:
        """Record a polling iteration."""
        self.total_polls += 1

    def record_raw_signal(self) -> None:
        """Record a raw signal before quality filtering."""
        self.raw_signals += 1

    def record_filtered_signal(
        self,
        market_question: str,
        market_source: str,
        trigger_price: float,
        trigger_side: str,
        paper_size_usd: float = 10.0,
    ) -> None:
        """Record a signal that passed quality filters (opportunity)."""
        self.filtered_signals += 1
        self.paper_trades += 1
        self.paper_total_invested += paper_size_usd

        # Update market price stats
        key = market_question[:60]
        if key not in self.market_stats:
            self.market_stats[key] = MarketPriceStat(
                question=market_question[:60],
                source=market_source,
            )

        stat = self.market_stats[key]
        if trigger_side == "YES":
            stat.update(yes_ask=trigger_price, no_ask=None)
        else:
            stat.update(yes_ask=None, no_ask=trigger_price)

    def finalize(self) -> None:
        """Mark cycle as complete."""
        self.cycle_end = datetime.now(tz=timezone.utc)

    @property
    def duration_minutes(self) -> float:
        """Cycle duration in minutes."""
        end = self.cycle_end or datetime.now(tz=timezone.utc)
        return (end - self.cycle_start).total_seconds() / 60.0


def format_cycle_report(stats: CycleStats) -> str:
    """Format cycle stats into a Telegram-friendly HTML report.

    Returns:
        HTML-formatted report string.
    """
    duration = stats.duration_minutes
    source_str = ", ".join(
        f"{k}:{v}" for k, v in sorted(stats.markets_by_source.items())
    )

    lines = [
        f"📋 <b>사이클 종료 요약</b>",
        f"{'━' * 28}",
        f"⏱ Duration: {duration:.1f}분",
        f"🔍 Markets: {stats.markets_discovered}개 ({source_str})",
        f"📡 Polls: {stats.total_polls}회",
        f"",
        f"<b>시그널</b>",
        f"  Raw: {stats.raw_signals}건",
        f"  Filtered: {stats.filtered_signals}건 "
        f"(quality pass rate: {stats.filtered_signals / max(stats.raw_signals, 1) * 100:.0f}%)",
        f"",
        f"<b>Paper Trades</b>",
        f"  건수: {stats.paper_trades}건",
        f"  총 투자: ${stats.paper_total_invested:.0f}",
    ]

    # Market-level price summary (top 10 by signal count)
    if stats.market_stats:
        sorted_markets = sorted(
            stats.market_stats.values(),
            key=lambda m: m.signal_count,
            reverse=True,
        )[:10]

        lines.append("")
        lines.append(f"<b>마켓별 가격 요약 (상위 {len(sorted_markets)})</b>")
        for ms in sorted_markets:
            yes_range = ""
            if ms.min_yes_ask < float("inf"):
                yes_range = f"Y: ${ms.min_yes_ask:.3f}~${ms.max_yes_ask:.3f}"
            no_range = ""
            if ms.min_no_ask < float("inf"):
                no_range = f"N: ${ms.min_no_ask:.3f}~${ms.max_no_ask:.3f}"
            price_info = " | ".join(filter(None, [yes_range, no_range]))
            lines.append(
                f"  • {ms.question[:45]}\n"
                f"    [{ms.source}] {price_info} ({ms.signal_count}건)"
            )

    return "\n".join(lines)
