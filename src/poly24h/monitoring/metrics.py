"""Performance metrics collection and aggregation.

거래 메트릭 수집 → 통계 집계 (avg ROI, win rate, PnL, 소스별 분포).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime


@dataclass
class TradeMetric:
    """단일 거래 메트릭."""

    timestamp: datetime
    market_source: str
    roi_pct: float
    cost: float
    profit: float
    success: bool


class MetricsCollector:
    """거래 메트릭 수집기."""

    def __init__(self):
        self._trades: list[TradeMetric] = []

    def record_trade(self, metric: TradeMetric) -> None:
        """거래 메트릭 기록."""
        self._trades.append(metric)

    def get_stats(self) -> dict:
        """전체 통계 집계.

        Returns:
            dict with avg_roi, win_rate, total_pnl, total_trades, by_source.
        """
        total = len(self._trades)
        if total == 0:
            return {
                "total_trades": 0,
                "avg_roi": 0.0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "by_source": {},
            }

        wins = sum(1 for t in self._trades if t.success)
        total_pnl = sum(t.profit for t in self._trades)
        avg_roi = sum(t.roi_pct for t in self._trades) / total

        # 소스별 집계
        by_source: dict[str, dict] = defaultdict(
            lambda: {"count": 0, "pnl": 0.0, "wins": 0}
        )
        for t in self._trades:
            by_source[t.market_source]["count"] += 1
            by_source[t.market_source]["pnl"] += t.profit
            if t.success:
                by_source[t.market_source]["wins"] += 1

        return {
            "total_trades": total,
            "avg_roi": avg_roi,
            "win_rate": (wins / total) * 100.0,
            "total_pnl": total_pnl,
            "by_source": dict(by_source),
        }

    def hourly_summary(self) -> list[dict]:
        """시간당 요약 리스트.

        Returns:
            list of dicts: [{hour, count, pnl, avg_roi}, ...]
        """
        if not self._trades:
            return []

        # 시간별 그룹핑
        hourly: dict[str, list[TradeMetric]] = defaultdict(list)
        for t in self._trades:
            hour_key = t.timestamp.strftime("%Y-%m-%d %H:00")
            hourly[hour_key].append(t)

        result = []
        for hour, trades in sorted(hourly.items()):
            count = len(trades)
            pnl = sum(t.profit for t in trades)
            avg_roi = sum(t.roi_pct for t in trades) / count
            result.append({
                "hour": hour,
                "count": count,
                "pnl": pnl,
                "avg_roi": avg_roi,
            })

        return result

    def reset(self) -> None:
        """메트릭 초기화."""
        self._trades.clear()
