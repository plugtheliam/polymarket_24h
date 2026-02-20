"""F-032c: Moneyline Validation Gate TDD tests.

Kent Beck TDD — Red phase first.
MoneylineValidationGate blocks moneyline entries until 20+ dry-run trades
are completed with positive ROI and acceptable win rate.
"""

import json
import tempfile
from pathlib import Path

import pytest


class TestGateBlocksBefore20Trades:
    """Gate blocks when fewer than 20 trades."""

    def test_gate_blocks_before_20_trades(self):
        """Less than 20 trades → is_validated() returns False."""
        from poly24h.strategy.moneyline_gate import MoneylineValidationGate

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            # 10 trades, all wins
            trades = [
                {"won": True, "pnl": 5.0} for _ in range(10)
            ]
            json.dump(trades, f)
            f.flush()

            gate = MoneylineValidationGate(history_file=f.name)
            assert gate.is_validated() is False


class TestGateAllowsAfterPositiveValidation:
    """Gate allows when 20+ trades with positive ROI."""

    def test_gate_allows_after_positive_validation(self):
        """20+ trades with positive ROI → is_validated() returns True."""
        from poly24h.strategy.moneyline_gate import MoneylineValidationGate

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            # 25 trades: 15 wins, 10 losses, positive ROI
            trades = (
                [{"won": True, "pnl": 5.0} for _ in range(15)] +
                [{"won": False, "pnl": -3.0} for _ in range(10)]
            )
            json.dump(trades, f)
            f.flush()

            gate = MoneylineValidationGate(history_file=f.name)
            assert gate.is_validated() is True


class TestGateBlocksNegativeRoi:
    """Gate blocks when ROI is negative even with 20+ trades."""

    def test_gate_blocks_negative_roi(self):
        """20+ trades but negative ROI → is_validated() returns False."""
        from poly24h.strategy.moneyline_gate import MoneylineValidationGate

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            # 25 trades: 5 wins, 20 losses → negative ROI
            trades = (
                [{"won": True, "pnl": 3.0} for _ in range(5)] +
                [{"won": False, "pnl": -5.0} for _ in range(20)]
            )
            json.dump(trades, f)
            f.flush()

            gate = MoneylineValidationGate(history_file=f.name)
            assert gate.is_validated() is False
