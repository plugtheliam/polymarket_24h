"""F-029: Validation Throughput TDD tests.

Kent Beck TDD — Red phase first.
max_entries_per_cycle env var 오버라이드 검증.
"""

import os
from unittest.mock import patch

from poly24h.position_manager import PositionManager


class TestEntriesPerCycleEnvVar:
    """R1: max_entries_per_cycle env var 오버라이드."""

    def test_entries_per_cycle_from_env(self):
        """POLY24H_MAX_ENTRIES_PER_CYCLE=30 → PositionManager에 반영."""
        # Simulate what event_scheduler.py does
        with patch.dict(os.environ, {"POLY24H_MAX_ENTRIES_PER_CYCLE": "30"}):
            max_entries = int(os.environ.get("POLY24H_MAX_ENTRIES_PER_CYCLE", "10"))
            pm = PositionManager(
                bankroll=5000.0,
                max_per_market=50.0,
                max_daily_deployment_usd=3000.0,
                max_entries_per_cycle=max_entries,
            )
            assert pm._max_entries_per_cycle == 30

    def test_entries_per_cycle_default(self):
        """env var 미설정 시 기본값 10."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("POLY24H_MAX_ENTRIES_PER_CYCLE", None)
            max_entries = int(os.environ.get("POLY24H_MAX_ENTRIES_PER_CYCLE", "10"))
            pm = PositionManager(
                bankroll=5000.0,
                max_per_market=50.0,
                max_entries_per_cycle=max_entries,
            )
            assert pm._max_entries_per_cycle == 10

    def test_high_cycle_limit_allows_more_entries(self):
        """cycle 제한 30일 때 10건 이상 진입 가능."""
        pm = PositionManager(
            bankroll=5000.0,
            max_per_market=50.0,
            max_daily_deployment_usd=3000.0,
            max_entries_per_cycle=30,
        )
        entered = 0
        for i in range(20):
            pos = pm.enter_position(
                market_id=f"mkt{i}",
                market_question=f"Game {i}",
                side="YES",
                price=0.50,
                end_date="2026-02-20T00:00:00Z",
            )
            if pos is not None:
                entered += 1
        assert entered == 20, f"Should enter 20 with cycle limit 30, got {entered}"

    def test_low_cycle_limit_blocks_entries(self):
        """cycle 제한 10일 때 11번째 진입 차단."""
        pm = PositionManager(
            bankroll=5000.0,
            max_per_market=50.0,
            max_daily_deployment_usd=3000.0,
            max_entries_per_cycle=10,
        )
        entered = 0
        for i in range(15):
            pos = pm.enter_position(
                market_id=f"mkt{i}",
                market_question=f"Game {i}",
                side="YES",
                price=0.50,
                end_date="2026-02-20T00:00:00Z",
            )
            if pos is not None:
                entered += 1
        assert entered == 10, f"Should only enter 10 with cycle limit 10, got {entered}"
