"""F-023: Dry run fixes — TDD tests.

Tests for:
  #0: Settlement date boundary (load yesterday + today)
  #1: Spread per-event limit
  #2: Cycle entry cap (max 10 per cycle)
  #3: Crypto sniper fallback (paired entry check → sniper)
  #4: Test market ID skip in settlement
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from poly24h.models.market import Market, MarketSource
from poly24h.monitoring.settlement import PaperSettlementTracker, PaperTrade
from poly24h.position_manager import PositionManager
from poly24h.scheduler.hybrid_strategy import HybridConfig, HybridStrategy, StrategyType
from poly24h.strategy.fee_calculator import is_profitable_after_fees


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trade(
    market_id: str,
    question: str = "Test",
    side: str = "YES",
    price: float = 0.45,
    cost: float = 100.0,
    end_date: str = "2026-02-12T00:00:00+00:00",
    source: str = "nba",
    status: str = "open",
) -> PaperTrade:
    return PaperTrade(
        market_id=market_id,
        market_question=question,
        market_source=source,
        side=side,
        price=price,
        shares=cost / price if price > 0 else 0,
        cost=cost,
        timestamp="2026-02-11T23:00:00+00:00",
        end_date=end_date,
        status=status,
    )


def _make_market(
    market_id: str,
    question: str,
    source: MarketSource = MarketSource.NBA,
    event_id: str = "",
) -> Market:
    return Market(
        id=market_id,
        question=question,
        source=source,
        yes_token_id=f"yes_{market_id}",
        no_token_id=f"no_{market_id}",
        yes_price=0.50,
        no_price=0.50,
        end_date=datetime.now(tz=timezone.utc) + timedelta(hours=1),
        liquidity_usd=10000.0,
        event_id=event_id,
        event_title="Test Event",
    )


# ===========================================================================
# #0: Settlement date boundary
# ===========================================================================

class TestSettlementDateBoundary:
    """check_and_settle() should load trades from both today and yesterday."""

    def _setup_tracker(self, tmp_path: Path) -> PaperSettlementTracker:
        return PaperSettlementTracker(data_dir=str(tmp_path))

    def _write_trades(self, tmp_path: Path, date_str: str, trades: list[PaperTrade]) -> None:
        file_path = tmp_path / f"{date_str}.jsonl"
        with open(file_path, "w") as f:
            for t in trades:
                f.write(json.dumps(t.to_dict()) + "\n")

    @pytest.mark.asyncio
    async def test_loads_yesterday_trades_after_midnight(self, tmp_path: Path) -> None:
        """Trades from yesterday's file should be found when checking after midnight."""
        tracker = self._setup_tracker(tmp_path)
        trade = _make_trade("111111", "XRP Up/Down", end_date="2026-02-11T23:30:00+00:00")
        self._write_trades(tmp_path, "2026-02-11", [trade])

        # Pass Feb 12 as the date — should also load Feb 11
        tracker.query_market_result = AsyncMock(return_value="YES")
        feb12 = datetime(2026, 2, 12, 0, 5, 0, tzinfo=timezone.utc)
        summary = await tracker.check_and_settle(date=feb12)

        assert summary.newly_settled == 1

    @pytest.mark.asyncio
    async def test_loads_both_today_and_yesterday(self, tmp_path: Path) -> None:
        """Should load trades from both today and yesterday files."""
        tracker = self._setup_tracker(tmp_path)
        trade_y = _make_trade("111111", "Yesterday", end_date="2026-02-11T23:30:00+00:00")
        self._write_trades(tmp_path, "2026-02-11", [trade_y])
        trade_t = _make_trade("222222", "Today", end_date="2026-02-12T00:30:00+00:00")
        self._write_trades(tmp_path, "2026-02-12", [trade_t])

        tracker.query_market_result = AsyncMock(return_value="YES")
        feb12 = datetime(2026, 2, 12, 1, 0, 0, tzinfo=timezone.utc)
        summary = await tracker.check_and_settle(date=feb12)

        assert summary.newly_settled == 2

    @pytest.mark.asyncio
    async def test_dedup_across_files(self, tmp_path: Path) -> None:
        """Same market_id in both files should only be processed once."""
        tracker = self._setup_tracker(tmp_path)
        trade = _make_trade("111111", "Duplicate", end_date="2026-02-11T23:30:00+00:00")
        self._write_trades(tmp_path, "2026-02-11", [trade])
        self._write_trades(tmp_path, "2026-02-12", [trade])

        tracker.query_market_result = AsyncMock(return_value="NO")
        feb12 = datetime(2026, 2, 12, 1, 0, 0, tzinfo=timezone.utc)
        summary = await tracker.check_and_settle(date=feb12)

        assert summary.newly_settled == 1

    @pytest.mark.asyncio
    async def test_no_yesterday_file_no_error(self, tmp_path: Path) -> None:
        """If yesterday's file doesn't exist, should not raise."""
        tracker = self._setup_tracker(tmp_path)
        trade = _make_trade("111111", "Today", end_date="2026-02-12T00:30:00+00:00")
        self._write_trades(tmp_path, "2026-02-12", [trade])

        tracker.query_market_result = AsyncMock(return_value="YES")
        feb12 = datetime(2026, 2, 12, 1, 0, 0, tzinfo=timezone.utc)
        summary = await tracker.check_and_settle(date=feb12)

        assert summary.newly_settled == 1


# ===========================================================================
# #1: Spread per-event limit
# ===========================================================================

class TestSpreadPerEventLimit:
    """should_skip_entry() should limit Spread markets to 1 per event."""

    def test_first_spread_allowed(self) -> None:
        pm = PositionManager(bankroll=10000.0, max_per_market=100.0)
        market = _make_market("s1", "Spread: Nets (-4.5)", event_id="ev_100")
        assert pm.should_skip_entry(market, 0.44, "NO") is False

    def test_second_spread_same_event_blocked(self) -> None:
        pm = PositionManager(bankroll=10000.0, max_per_market=100.0)
        m1 = _make_market("s1", "Spread: Nets (-4.5)", event_id="ev_100")
        m2 = _make_market("s2", "Spread: Nets (-3.5)", event_id="ev_100")
        # Enter first spread
        pm.should_skip_entry(m1, 0.44, "NO")
        pm.enter_position("s1", "Spread: Nets (-4.5)", "NO", 0.44, "", event_id="ev_100")
        # Second spread same event → skip
        assert pm.should_skip_entry(m2, 0.41, "NO") is True

    def test_spread_different_event_allowed(self) -> None:
        pm = PositionManager(bankroll=10000.0, max_per_market=100.0)
        m1 = _make_market("s1", "Spread: Nets (-4.5)", event_id="ev_100")
        m2 = _make_market("s2", "Spread: Cavs (-18.5)", event_id="ev_200")
        pm.should_skip_entry(m1, 0.44, "NO")
        pm.enter_position("s1", "Spread: Nets (-4.5)", "NO", 0.44, "", event_id="ev_100")
        assert pm.should_skip_entry(m2, 0.46, "YES") is False

    def test_ou_still_allowed_when_spread_entered(self) -> None:
        pm = PositionManager(bankroll=10000.0, max_per_market=100.0)
        m_spread = _make_market("s1", "Spread: Nets (-4.5)", event_id="ev_100")
        m_ou = _make_market("ou1", "Pacers vs. Nets: O/U 216.5", event_id="ev_100")
        pm.should_skip_entry(m_spread, 0.44, "NO")
        pm.enter_position("s1", "Spread: Nets (-4.5)", "NO", 0.44, "", event_id="ev_100")
        # O/U for same event → allowed (different type)
        assert pm.should_skip_entry(m_ou, 0.47, "YES") is False

    def test_moneyline_unaffected_by_type_limits(self) -> None:
        pm = PositionManager(bankroll=10000.0, max_per_market=100.0)
        m_spread = _make_market("s1", "Spread: Nets (-4.5)", event_id="ev_100")
        m_ou = _make_market("ou1", "Pacers vs. Nets: O/U 216.5", event_id="ev_100")
        m_ml = _make_market("ml1", "Pacers vs. Nets: 1H Moneyline", event_id="ev_100")
        # Enter spread + O/U
        pm.enter_position("s1", "Spread: Nets (-4.5)", "NO", 0.44, "", event_id="ev_100")
        pm.enter_position("ou1", "Pacers vs. Nets: O/U 216.5", "YES", 0.47, "", event_id="ev_100")
        # Moneyline same event → allowed (moneyline has no type limit)
        assert pm.should_skip_entry(m_ml, 0.39, "YES") is False

    def test_state_persistence_event_type_entries(self, tmp_path: Path) -> None:
        """event_type_entries should be persisted and restored."""
        state_file = tmp_path / "state.json"
        pm = PositionManager(bankroll=10000.0, max_per_market=100.0)
        m = _make_market("s1", "Spread: Nets (-4.5)", event_id="ev_100")
        pm.enter_position("s1", "Spread: Nets (-4.5)", "NO", 0.44, "", event_id="ev_100")
        pm.save_state(state_file)

        pm2 = PositionManager(bankroll=10000.0, max_per_market=100.0)
        pm2.load_state(state_file)
        m2 = _make_market("s2", "Spread: Nets (-3.5)", event_id="ev_100")
        assert pm2.should_skip_entry(m2, 0.41, "NO") is True


# ===========================================================================
# #2: Cycle entry cap
# ===========================================================================

class TestCycleEntryCap:
    """EventDrivenLoop should limit entries per SNIPE cycle."""

    def test_position_manager_cycle_entries_tracking(self) -> None:
        """PositionManager should track and cap entries per cycle."""
        pm = PositionManager(bankroll=10000.0, max_per_market=100.0, max_entries_per_cycle=3)
        # Enter 3 positions (within limit)
        for i in range(3):
            pos = pm.enter_position(
                f"m{i}", f"Market {i}", "YES", 0.45, "", event_id=f"ev_{i}",
            )
            assert pos is not None

        # 4th entry should be rejected
        pos = pm.enter_position("m3", "Market 3", "YES", 0.45, "", event_id="ev_3")
        assert pos is None

    def test_cycle_counter_resets(self) -> None:
        """reset_cycle_entries() should reset the per-cycle counter."""
        pm = PositionManager(bankroll=10000.0, max_per_market=100.0, max_entries_per_cycle=2)
        pm.enter_position("m0", "Market 0", "YES", 0.45, "", event_id="ev_0")
        pm.enter_position("m1", "Market 1", "YES", 0.45, "", event_id="ev_1")
        # At limit
        assert pm.enter_position("m2", "Market 2", "YES", 0.45, "", event_id="ev_2") is None

        # Reset cycle
        pm.reset_cycle_entries()

        # Now should work again
        pos = pm.enter_position("m2", "Market 2", "YES", 0.45, "", event_id="ev_2")
        assert pos is not None

    def test_zero_means_unlimited(self) -> None:
        """max_entries_per_cycle=0 means no limit."""
        pm = PositionManager(bankroll=100000.0, max_per_market=100.0, max_entries_per_cycle=0)
        for i in range(20):
            pos = pm.enter_position(
                f"m{i}", f"Market {i}", "YES", 0.45, "", event_id=f"ev_{i}",
            )
            assert pos is not None


# ===========================================================================
# #3: Crypto sniper fallback
# ===========================================================================

class TestCryptoSniperFallback:
    """Crypto markets should fall through to sniper when paired entry conditions not met.

    The routing logic in event_scheduler._handle_snipe_phase():
    1. Crypto + profitable paired → skip (handled by _check_paired_entries)
    2. Crypto + NOT profitable paired → fall through to sniper
    3. NBA → always sniper (no paired check)
    """

    def test_crypto_routes_to_paired_entry(self) -> None:
        """HybridStrategy routes crypto to PAIRED_ENTRY."""
        strategy = HybridStrategy(HybridConfig())
        market = _make_market("c1", "XRP Up/Down", source=MarketSource.HOURLY_CRYPTO)
        assert strategy.get_strategy_for_market(market) == StrategyType.PAIRED_ENTRY

    def test_nba_routes_to_sniper(self) -> None:
        """HybridStrategy routes NBA to SNIPER."""
        strategy = HybridStrategy(HybridConfig())
        market = _make_market("n1", "Spread: Nets (-4.5)", source=MarketSource.NBA)
        assert strategy.get_strategy_for_market(market) == StrategyType.SNIPER

    def test_wide_spread_crypto_profitable_paired(self) -> None:
        """CPP < $0.94 → profitable paired entry (stays with paired, no fallback)."""
        from decimal import Decimal
        # YES=0.40 + NO=0.45 = 0.85 CPP → well under 0.94
        assert is_profitable_after_fees(
            Decimal("0.40"), Decimal("0.45"), min_margin=Decimal("0.005"), use_taker=True,
        ) is True

    def test_tight_spread_crypto_not_profitable_paired(self) -> None:
        """CPP >= $0.94 → not profitable for paired → should fallback to sniper."""
        from decimal import Decimal
        # YES=0.48 + NO=0.50 = 0.98 CPP → above 0.94, not profitable for paired
        assert is_profitable_after_fees(
            Decimal("0.48"), Decimal("0.50"), min_margin=Decimal("0.005"), use_taker=True,
        ) is False

    def test_typical_market_spread_not_profitable(self) -> None:
        """Typical crypto market with 0.98+ CPP should not be profitable for paired."""
        from decimal import Decimal
        # This is the common case: YES=0.50 + NO=0.49 = 0.99
        assert is_profitable_after_fees(
            Decimal("0.50"), Decimal("0.49"), min_margin=Decimal("0.005"), use_taker=True,
        ) is False


# ===========================================================================
# #4: Test market skip in settlement
# ===========================================================================

class TestSettlementSkipTestMarkets:
    """Settlement should skip test market IDs (non-numeric)."""

    @pytest.mark.asyncio
    async def test_skip_mkt_prefix(self, tmp_path: Path) -> None:
        """market_id='mkt_1' should be skipped during settlement."""
        tracker = PaperSettlementTracker(data_dir=str(tmp_path))
        trade = _make_trade("mkt_1", "Test Market", end_date="2026-02-11T22:00:00+00:00")
        file_path = tmp_path / "2026-02-11.jsonl"
        with open(file_path, "w") as f:
            f.write(json.dumps(trade.to_dict()) + "\n")

        tracker.query_market_result = AsyncMock(return_value="unknown")
        feb11 = datetime(2026, 2, 11, 23, 0, 0, tzinfo=timezone.utc)
        summary = await tracker.check_and_settle(date=feb11)

        # mkt_1 should be skipped — API not called
        tracker.query_market_result.assert_not_called()

    @pytest.mark.asyncio
    async def test_numeric_ids_not_skipped(self, tmp_path: Path) -> None:
        """Numeric market IDs like '1364593' should NOT be skipped."""
        tracker = PaperSettlementTracker(data_dir=str(tmp_path))
        trade = _make_trade("1364593", "Spread: Hornets (-6.5)", end_date="2026-02-11T22:00:00+00:00")
        file_path = tmp_path / "2026-02-11.jsonl"
        with open(file_path, "w") as f:
            f.write(json.dumps(trade.to_dict()) + "\n")

        tracker.query_market_result = AsyncMock(return_value="YES")
        feb11 = datetime(2026, 2, 11, 23, 0, 0, tzinfo=timezone.utc)
        summary = await tracker.check_and_settle(date=feb11)

        tracker.query_market_result.assert_called_once_with("1364593")
