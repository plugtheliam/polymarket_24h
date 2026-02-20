"""F-032c: Moneyline Validation Gate.

Blocks moneyline entries until sufficient dry-run history proves the strategy
is profitable. Requires:
- MIN_TRADES (20) completed trades
- MIN_WIN_RATE (48%) win rate
- MIN_ROI (0%) positive ROI

Trade history stored in JSON file for persistence across restarts.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_FILE = "data/moneyline_validation_history.json"


class MoneylineValidationGate:
    """Gate that blocks moneyline entries until validated by dry-run results."""

    MIN_TRADES = 20
    MIN_WIN_RATE = 0.48
    MIN_ROI = 0.0  # Must be non-negative

    def __init__(self, history_file: str = DEFAULT_HISTORY_FILE):
        self._history_file = Path(history_file)
        self._trades: list[dict] = []
        self._load()

    def _load(self) -> None:
        """Load trade history from JSON file."""
        if self._history_file.exists():
            try:
                with open(self._history_file) as f:
                    self._trades = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load moneyline history: %s", e)
                self._trades = []

    def _save(self) -> None:
        """Save trade history to JSON file."""
        self._history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._history_file, "w") as f:
            json.dump(self._trades, f, indent=2)

    def record_trade(self, won: bool, pnl: float, market_id: str = "") -> None:
        """Record a completed moneyline trade result."""
        self._trades.append({
            "won": won,
            "pnl": pnl,
            "market_id": market_id,
        })
        self._save()

    def is_validated(self) -> bool:
        """Check if moneyline strategy has been validated.

        Requires:
        - At least MIN_TRADES trades
        - Win rate >= MIN_WIN_RATE
        - Total ROI >= MIN_ROI (non-negative)
        """
        if len(self._trades) < self.MIN_TRADES:
            return False

        wins = sum(1 for t in self._trades if t.get("won"))
        win_rate = wins / len(self._trades)
        if win_rate < self.MIN_WIN_RATE:
            return False

        total_pnl = sum(t.get("pnl", 0.0) for t in self._trades)
        if total_pnl < self.MIN_ROI:
            return False

        return True

    @property
    def stats(self) -> dict:
        """Return current validation stats."""
        total = len(self._trades)
        wins = sum(1 for t in self._trades if t.get("won"))
        total_pnl = sum(t.get("pnl", 0.0) for t in self._trades)
        return {
            "total_trades": total,
            "wins": wins,
            "win_rate": wins / total if total > 0 else 0.0,
            "total_pnl": total_pnl,
            "validated": self.is_validated(),
            "remaining": max(0, self.MIN_TRADES - total),
        }
