"""F-027: Daily deployment cap TDD tests.

Kent Beck TDD — Red phase first.
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
import json
import tempfile

from poly24h.position_manager import PositionManager


def _make_pm(
    bankroll: float = 1000.0,
    max_per_market: float = 20.0,
    max_daily_deployment_usd: float = 100.0,
) -> PositionManager:
    """Helper: PositionManager 생성 (daily cap 포함)."""
    return PositionManager(
        bankroll=bankroll,
        max_per_market=max_per_market,
        max_daily_deployment_usd=max_daily_deployment_usd,
    )


def _enter(pm: PositionManager, market_id: str, price: float = 0.50):
    """Helper: 포지션 진입."""
    return pm.enter_position(
        market_id=market_id,
        market_question=f"Will team win? ({market_id})",
        side="YES",
        price=price,
        end_date="2026-02-20T00:00:00Z",
    )


class TestDailyCapBasic:
    """R1: 기본 daily cap 동작."""

    def test_allows_within_limit(self):
        """$100 한도 내에서 진입 허용."""
        pm = _make_pm(max_daily_deployment_usd=100)
        pos = _enter(pm, "mkt1")
        assert pos is not None
        assert pos.size_usd == 20.0

    def test_blocks_over_limit(self):
        """$100 한도 초과 시 진입 차단 (5 × $20 = $100, 6번째 차단)."""
        pm = _make_pm(max_daily_deployment_usd=100)
        for i in range(5):
            pos = _enter(pm, f"mkt{i}")
            assert pos is not None, f"Entry {i} should succeed"
        # 6번째: $100 한도 초과
        pos = _enter(pm, "mkt5")
        assert pos is None, "6th entry should be blocked by daily cap"

    def test_zero_means_unlimited(self):
        """max_daily_deployment_usd=0 → 무제한 (기존 동작 호환)."""
        pm = _make_pm(max_daily_deployment_usd=0)
        for i in range(10):
            pos = _enter(pm, f"mkt{i}")
            assert pos is not None, f"Entry {i} should succeed (unlimited)"


class TestDailyCapReset:
    """R1: 자정 UTC 리셋."""

    def test_resets_at_midnight(self):
        """날짜 변경 시 daily 카운터 리셋 → 재진입 허용."""
        pm = _make_pm(max_daily_deployment_usd=40)
        # Day 1: 2 × $20 = $40 (한도 도달)
        _enter(pm, "mkt1")
        _enter(pm, "mkt2")
        pos = _enter(pm, "mkt3")
        assert pos is None, "Should be blocked on day 1"

        # Day 2로 시간 변경 (다음 날)
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime(
            "%Y-%m-%d"
        )
        pm._daily_reset_date = "1970-01-01"  # 강제 리셋 트리거

        pos = _enter(pm, "mkt3")
        assert pos is not None, "Should be allowed after midnight reset"


class TestDailyCapPartial:
    """R2: 잔여 한도 내에서 축소 진입."""

    def test_partial_entry_when_near_limit(self):
        """잔여 한도 $15일 때 $20 요청 → $15로 축소 진입."""
        pm = _make_pm(
            bankroll=1000,
            max_per_market=20,
            max_daily_deployment_usd=55,
        )
        # 2 × $20 = $40 배치, 잔여 한도 $15
        _enter(pm, "mkt1")
        _enter(pm, "mkt2")
        # 3번째: $20 요청이지만 잔여 $15로 축소
        pos = _enter(pm, "mkt3")
        assert pos is not None, "Should allow partial entry"
        assert pos.size_usd <= 15.0, f"Should be capped at $15, got ${pos.size_usd}"


class TestDailyCapPersistence:
    """R3: 상태 저장/복원."""

    def test_daily_cap_persists_in_state(self):
        """save_state/load_state에서 daily tracking 유지."""
        pm = _make_pm(max_daily_deployment_usd=100)
        _enter(pm, "mkt1")  # $20 배치
        _enter(pm, "mkt2")  # $40 배치

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)
        pm.save_state(path)

        # 새 PM에 로드
        pm2 = _make_pm(max_daily_deployment_usd=100)
        pm2.load_state(path)

        assert pm2._daily_deployed == 40.0, (
            f"Daily deployed should be $40, got ${pm2._daily_deployed}"
        )

        path.unlink(missing_ok=True)
