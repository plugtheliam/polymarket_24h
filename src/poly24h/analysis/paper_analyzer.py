"""Paper trade analysis tool — reads JSONL files and generates P&L reports.

Supports three data sources:
1. paper_trades/*.jsonl — Single-side paper trades (sniper entries)
2. paper_trades/paired_*.jsonl — Paired entry (YES+NO) paper trades
3. paper_trades/market_stats_*.jsonl — Per-market opportunity logs

Usage:
    python -m poly24h --mode analyze
    python -m poly24h --mode analyze --date 2026-02-07
    python -m poly24h --mode analyze --days 7
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TradeSummary:
    """Aggregated P&L summary."""

    total_trades: int = 0
    total_cost: float = 0.0
    total_payout: float = 0.0
    total_pnl: float = 0.0
    wins: int = 0
    losses: int = 0
    open_trades: int = 0
    avg_price: float = 0.0
    max_loss: float = 0.0
    max_gain: float = 0.0
    best_roi_pct: float = 0.0
    worst_roi_pct: float = 0.0

    @property
    def win_rate(self) -> float:
        settled = self.wins + self.losses
        return self.wins / settled if settled > 0 else 0.0

    @property
    def avg_pnl(self) -> float:
        settled = self.wins + self.losses
        return self.total_pnl / settled if settled > 0 else 0.0

    @property
    def settled_count(self) -> int:
        return self.wins + self.losses


@dataclass
class DailySummary:
    """Daily P&L breakdown."""

    date: str
    trades: int = 0
    cost: float = 0.0
    pnl: float = 0.0
    wins: int = 0
    losses: int = 0
    open_count: int = 0


@dataclass
class MarketSummary:
    """Per-market/source P&L breakdown."""

    name: str
    trades: int = 0
    cost: float = 0.0
    pnl: float = 0.0
    wins: int = 0
    losses: int = 0
    avg_price: float = 0.0


@dataclass
class AssetSummary:
    """Per-asset (coin) P&L breakdown."""

    symbol: str
    total_signals: int = 0
    paired_signals: int = 0
    single_signals: int = 0
    avg_trigger_price: float = 0.0
    min_trigger_price: float = float("inf")
    max_trigger_price: float = 0.0


@dataclass
class AnalysisResult:
    """Complete analysis result."""

    overall: TradeSummary = field(default_factory=TradeSummary)
    paired: TradeSummary = field(default_factory=TradeSummary)
    by_date: list[DailySummary] = field(default_factory=list)
    by_market: list[MarketSummary] = field(default_factory=list)
    by_asset: list[AssetSummary] = field(default_factory=list)
    date_range: str = ""
    files_read: int = 0


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class PaperTradeAnalyzer:
    """Reads paper trade JSONL files and generates comprehensive P&L analysis.

    Args:
        data_dir: Path to paper_trades directory.
    """

    def __init__(self, data_dir: str = "data/paper_trades"):
        self.data_dir = Path(data_dir)

    def analyze(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        days: int | None = None,
    ) -> AnalysisResult:
        """Run full analysis across the specified date range.

        Args:
            start_date: Start date (inclusive). Default: earliest file.
            end_date: End date (inclusive). Default: today.
            days: If set, analyze last N days (overrides start_date).

        Returns:
            AnalysisResult with all breakdowns.
        """
        now = datetime.now(tz=timezone.utc)

        if end_date is None:
            end_date = now

        if days is not None:
            start_date = now - timedelta(days=days - 1)

        # Collect all relevant files
        single_trades = self._load_single_trades(start_date, end_date)
        paired_trades = self._load_paired_trades(start_date, end_date)
        market_stats = self._load_market_stats(start_date, end_date)

        files_read = (
            len(self._find_files("", start_date, end_date))
            + len(self._find_files("paired_", start_date, end_date))
            + len(self._find_files("market_stats_", start_date, end_date))
        )

        result = AnalysisResult(files_read=files_read)

        # Overall single trade summary
        result.overall = self._summarize_single_trades(single_trades)

        # Paired trade summary
        result.paired = self._summarize_paired_trades(paired_trades)

        # By-date breakdown
        result.by_date = self._by_date_breakdown(single_trades, paired_trades)

        # By-market breakdown
        result.by_market = self._by_market_breakdown(single_trades, paired_trades)

        # By-asset breakdown from market_stats
        result.by_asset = self._by_asset_breakdown(market_stats)

        # Date range label
        dates = sorted(
            set(
                self._extract_date(t.get("timestamp", ""))
                for t in single_trades + paired_trades
                if t.get("timestamp")
            )
        )
        if dates:
            result.date_range = f"{dates[0]} ~ {dates[-1]}"
        else:
            result.date_range = "No data"

        return result

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------

    def _find_files(
        self,
        prefix: str,
        start_date: datetime | None,
        end_date: datetime | None,
    ) -> list[Path]:
        """Find JSONL files matching prefix and date range."""
        if not self.data_dir.exists():
            return []

        files = []
        for f in sorted(self.data_dir.glob(f"{prefix}*.jsonl")):
            # Extract date from filename
            name = f.stem
            if prefix:
                date_part = name[len(prefix):]
            else:
                date_part = name

            try:
                file_date = datetime.strptime(date_part, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue

            if start_date and file_date.date() < start_date.date():
                continue
            if end_date and file_date.date() > end_date.date():
                continue

            files.append(f)

        return files

    def _load_jsonl(self, file_path: Path) -> list[dict]:
        """Load all JSON lines from a file."""
        records = []
        try:
            with open(file_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Error reading %s: %s", file_path, e)
        return records

    def _load_single_trades(
        self,
        start_date: datetime | None,
        end_date: datetime | None,
    ) -> list[dict]:
        """Load single-side paper trades (YYYY-MM-DD.jsonl)."""
        files = self._find_files("", start_date, end_date)
        # Filter out files that start with "paired_" or "market_stats_"
        files = [
            f for f in files
            if not f.stem.startswith("paired_") and not f.stem.startswith("market_stats_")
        ]
        all_trades = []
        for f in files:
            all_trades.extend(self._load_jsonl(f))
        return all_trades

    def _load_paired_trades(
        self,
        start_date: datetime | None,
        end_date: datetime | None,
    ) -> list[dict]:
        """Load paired entry paper trades (paired_YYYY-MM-DD.jsonl)."""
        files = self._find_files("paired_", start_date, end_date)
        all_trades = []
        for f in files:
            all_trades.extend(self._load_jsonl(f))
        return all_trades

    def _load_market_stats(
        self,
        start_date: datetime | None,
        end_date: datetime | None,
    ) -> list[dict]:
        """Load market stats records (market_stats_YYYY-MM-DD.jsonl)."""
        files = self._find_files("market_stats_", start_date, end_date)
        all_records = []
        for f in files:
            all_records.extend(self._load_jsonl(f))
        return all_records

    # ------------------------------------------------------------------
    # Summaries
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_date(timestamp: str) -> str:
        """Extract YYYY-MM-DD from ISO timestamp."""
        if not timestamp:
            return "unknown"
        return timestamp[:10]

    def _summarize_single_trades(self, trades: list[dict]) -> TradeSummary:
        """Build overall summary from single-side paper trades."""
        s = TradeSummary()
        prices = []

        for t in trades:
            s.total_trades += 1
            cost = t.get("cost", 0.0)
            s.total_cost += cost
            status = t.get("status", "open")
            pnl = t.get("pnl", 0.0)
            payout = t.get("payout", 0.0)
            price = t.get("price", 0.0)

            if price > 0:
                prices.append(price)

            if status == "settled":
                s.total_pnl += pnl
                s.total_payout += payout
                if pnl > 0:
                    s.wins += 1
                    s.max_gain = max(s.max_gain, pnl)
                    roi = (pnl / cost * 100) if cost > 0 else 0
                    s.best_roi_pct = max(s.best_roi_pct, roi)
                elif pnl < 0:
                    s.losses += 1
                    s.max_loss = min(s.max_loss, pnl)
                    roi = (pnl / cost * 100) if cost > 0 else 0
                    s.worst_roi_pct = min(s.worst_roi_pct, roi)
                else:
                    # Break-even counts as win
                    s.wins += 1
            else:
                s.open_trades += 1

        if prices:
            s.avg_price = sum(prices) / len(prices)

        return s

    def _summarize_paired_trades(self, trades: list[dict]) -> TradeSummary:
        """Build summary from paired entry paper trades."""
        s = TradeSummary()
        prices = []

        for t in trades:
            s.total_trades += 1
            cost = t.get("cost_usd", 0.0)
            s.total_cost += cost
            guaranteed_profit = t.get("guaranteed_profit", 0.0)
            status = t.get("status", "open")
            actual_pnl = t.get("actual_pnl", 0.0)
            total_cost = t.get("total_cost", 0.0)

            if total_cost > 0:
                prices.append(total_cost)

            if status == "settled":
                s.total_pnl += actual_pnl
                if actual_pnl >= 0:
                    s.wins += 1
                else:
                    s.losses += 1
            else:
                s.open_trades += 1
                # For open paired trades, guaranteed_profit is the expected P&L
                s.total_pnl += guaranteed_profit
                s.max_gain = max(s.max_gain, guaranteed_profit)
                roi = t.get("roi_pct", 0.0)
                s.best_roi_pct = max(s.best_roi_pct, roi)

        if prices:
            s.avg_price = sum(prices) / len(prices)

        return s

    def _by_date_breakdown(
        self,
        single_trades: list[dict],
        paired_trades: list[dict],
    ) -> list[DailySummary]:
        """Break down trades by date."""
        by_date: dict[str, DailySummary] = {}

        for t in single_trades:
            d = self._extract_date(t.get("timestamp", ""))
            if d not in by_date:
                by_date[d] = DailySummary(date=d)
            ds = by_date[d]
            ds.trades += 1
            ds.cost += t.get("cost", 0.0)
            status = t.get("status", "open")
            if status == "settled":
                pnl = t.get("pnl", 0.0)
                ds.pnl += pnl
                if pnl > 0:
                    ds.wins += 1
                elif pnl < 0:
                    ds.losses += 1
            else:
                ds.open_count += 1

        for t in paired_trades:
            d = self._extract_date(t.get("timestamp", ""))
            if d not in by_date:
                by_date[d] = DailySummary(date=d)
            ds = by_date[d]
            ds.trades += 1
            ds.cost += t.get("cost_usd", 0.0)
            ds.pnl += t.get("guaranteed_profit", 0.0)
            status = t.get("status", "open")
            if status != "settled":
                ds.open_count += 1

        return sorted(by_date.values(), key=lambda x: x.date)

    def _by_market_breakdown(
        self,
        single_trades: list[dict],
        paired_trades: list[dict],
    ) -> list[MarketSummary]:
        """Break down trades by market source."""
        by_source: dict[str, MarketSummary] = {}

        for t in single_trades:
            source = t.get("market_source", "unknown")
            if source not in by_source:
                by_source[source] = MarketSummary(name=source)
            ms = by_source[source]
            ms.trades += 1
            ms.cost += t.get("cost", 0.0)
            if t.get("status") == "settled":
                pnl = t.get("pnl", 0.0)
                ms.pnl += pnl
                if pnl > 0:
                    ms.wins += 1
                elif pnl < 0:
                    ms.losses += 1

        for t in paired_trades:
            source = t.get("market_source", "unknown")
            if source not in by_source:
                by_source[source] = MarketSummary(name=source)
            ms = by_source[source]
            ms.trades += 1
            ms.cost += t.get("cost_usd", 0.0)
            ms.pnl += t.get("guaranteed_profit", 0.0)

        return sorted(by_source.values(), key=lambda x: -x.trades)

    def _by_asset_breakdown(self, market_stats: list[dict]) -> list[AssetSummary]:
        """Break down signals by asset symbol from market_stats."""
        by_asset: dict[str, AssetSummary] = {}

        for rec in market_stats:
            symbol = rec.get("asset_symbol", "") or "OTHER"
            if symbol not in by_asset:
                by_asset[symbol] = AssetSummary(symbol=symbol)
            a = by_asset[symbol]
            a.total_signals += 1

            if rec.get("is_paired"):
                a.paired_signals += 1
            else:
                a.single_signals += 1

            price = rec.get("trigger_price", 0.0)
            if price > 0:
                a.min_trigger_price = min(a.min_trigger_price, price)
                a.max_trigger_price = max(a.max_trigger_price, price)

        # Compute averages
        for symbol, a in by_asset.items():
            prices = [
                r.get("trigger_price", 0.0)
                for r in market_stats
                if (r.get("asset_symbol", "") or "OTHER") == symbol
                and r.get("trigger_price", 0.0) > 0
            ]
            if prices:
                a.avg_trigger_price = sum(prices) / len(prices)

            # Fix inf sentinel
            if a.min_trigger_price == float("inf"):
                a.min_trigger_price = 0.0

        return sorted(by_asset.values(), key=lambda x: -x.total_signals)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_analysis_report(result: AnalysisResult) -> str:
    """Format analysis result into a human-readable report.

    Returns:
        Multi-line string report.
    """
    lines = []

    # Header
    lines.append("=" * 60)
    lines.append("  📊 Paper Trade Analysis Report")
    lines.append(f"  Period: {result.date_range}")
    lines.append(f"  Files analyzed: {result.files_read}")
    lines.append("=" * 60)

    # Overall single trades
    s = result.overall
    lines.append("")
    lines.append("📈 Single-Side Trades (Sniper)")
    lines.append("-" * 40)
    lines.append(f"  Total trades:    {s.total_trades}")
    lines.append(f"  Open (unsettled): {s.open_trades}")
    lines.append(f"  Settled:         {s.settled_count}")
    lines.append(f"  Wins/Losses:     {s.wins}/{s.losses}")
    lines.append(f"  Win rate:        {s.win_rate * 100:.1f}%")
    lines.append(f"  Total cost:      ${s.total_cost:,.2f}")
    lines.append(f"  Total P&L:       ${s.total_pnl:+,.2f}")
    lines.append(f"  Avg P&L/trade:   ${s.avg_pnl:+,.2f}")
    lines.append(f"  Avg entry price: ${s.avg_price:.4f}")
    lines.append(f"  Max gain:        ${s.max_gain:+,.2f}")
    lines.append(f"  Max loss:        ${s.max_loss:+,.2f}")

    # Paired trades
    p = result.paired
    if p.total_trades > 0:
        lines.append("")
        lines.append("🔗 Paired Entry Trades (YES+NO)")
        lines.append("-" * 40)
        lines.append(f"  Total trades:      {p.total_trades}")
        lines.append(f"  Open (unsettled):  {p.open_trades}")
        lines.append(f"  Total cost:        ${p.total_cost:,.2f}")
        lines.append(f"  Guaranteed profit: ${p.total_pnl:+,.4f}")
        lines.append(f"  Best ROI:          {p.best_roi_pct:.2f}%")
        lines.append(f"  Avg pair cost:     ${p.avg_price:.4f}")

    # Daily breakdown
    if result.by_date:
        lines.append("")
        lines.append("📅 Daily Breakdown")
        lines.append("-" * 40)
        lines.append(
            f"  {'Date':<12} {'Trades':>6} {'Cost':>10} "
            f"{'P&L':>10} {'W/L':>6} {'Open':>5}"
        )
        for d in result.by_date:
            lines.append(
                f"  {d.date:<12} {d.trades:>6} ${d.cost:>9,.2f} "
                f"${d.pnl:>+9,.2f} {d.wins}/{d.losses:>3} {d.open_count:>5}"
            )

    # By market source
    if result.by_market:
        lines.append("")
        lines.append("🎯 By Market Source")
        lines.append("-" * 40)
        for m in result.by_market:
            win_rate = m.wins / (m.wins + m.losses) * 100 if (m.wins + m.losses) > 0 else 0
            lines.append(
                f"  {m.name:<20} {m.trades:>5} trades | "
                f"${m.cost:>8,.2f} cost | "
                f"${m.pnl:>+8,.2f} P&L | "
                f"{win_rate:.0f}% WR"
            )

    # By asset
    if result.by_asset:
        lines.append("")
        lines.append("🪙 By Asset (from market stats)")
        lines.append("-" * 40)
        for a in result.by_asset:
            paired_str = f" (paired: {a.paired_signals})" if a.paired_signals > 0 else ""
            price_range = ""
            if a.min_trigger_price > 0 and a.max_trigger_price > 0:
                price_range = (
                    f" | ${a.min_trigger_price:.3f}~${a.max_trigger_price:.3f}"
                    f" (avg ${a.avg_trigger_price:.3f})"
                )
            lines.append(
                f"  {a.symbol:<8} {a.total_signals:>5} signals{paired_str}{price_range}"
            )

    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)
