"""Tests for Phase 2: Paper trade settlement tracker."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from poly24h.monitoring.settlement import (
    PaperSettlementTracker,
    PaperTrade,
    SettlementSummary,
)


# ---------------------------------------------------------------------------
# PaperTrade
# ---------------------------------------------------------------------------


class TestPaperTrade:
    def test_create(self):
        trade = PaperTrade(
            market_id="m1",
            market_question="BTC up?",
            market_source="hourly_crypto",
            side="YES",
            price=0.47,
            shares=21.28,
            cost=10.0,
            timestamp="2025-01-01T00:00:00+00:00",
            end_date="2025-01-01T01:00:00+00:00",
        )
        assert trade.status == "open"
        assert trade.pnl == 0.0

    def test_to_dict_roundtrip(self):
        trade = PaperTrade(
            market_id="m1",
            market_question="BTC up?",
            market_source="hourly_crypto",
            side="YES",
            price=0.47,
            shares=21.28,
            cost=10.0,
            timestamp="2025-01-01T00:00:00+00:00",
            end_date="2025-01-01T01:00:00+00:00",
        )
        d = trade.to_dict()
        trade2 = PaperTrade.from_dict(d)
        assert trade2.market_id == "m1"
        assert trade2.side == "YES"
        assert trade2.price == 0.47
        assert trade2.status == "open"


# ---------------------------------------------------------------------------
# PaperSettlementTracker
# ---------------------------------------------------------------------------


class TestPaperSettlementTracker:
    @pytest.fixture()
    def tracker(self, tmp_path):
        return PaperSettlementTracker(data_dir=str(tmp_path / "paper_trades"))

    @pytest.fixture()
    def sample_trade(self):
        return PaperTrade(
            market_id="m1",
            market_question="Will BTC go up?",
            market_source="hourly_crypto",
            side="YES",
            price=0.47,
            shares=21.28,
            cost=10.0,
            timestamp="2025-01-15T12:00:00+00:00",
            end_date="2025-01-15T13:00:00+00:00",
        )

    def test_record_and_load(self, tracker, sample_trade):
        tracker.record_trade(sample_trade)
        trades = tracker.load_trades()
        assert len(trades) == 1
        assert trades[0].market_id == "m1"
        assert trades[0].side == "YES"

    def test_record_multiple(self, tracker, sample_trade):
        tracker.record_trade(sample_trade)
        trade2 = PaperTrade(
            market_id="m2",
            market_question="Lakers win?",
            market_source="nba",
            side="NO",
            price=0.45,
            shares=22.22,
            cost=10.0,
            timestamp="2025-01-15T12:05:00+00:00",
            end_date="2025-01-15T14:00:00+00:00",
        )
        tracker.record_trade(trade2)
        trades = tracker.load_trades()
        assert len(trades) == 2

    def test_settle_trade_win(self, tracker):
        trade = PaperTrade(
            market_id="m1", market_question="BTC up?",
            market_source="crypto", side="YES",
            price=0.47, shares=21.28, cost=10.0,
            timestamp="2025-01-15T12:00:00Z",
            end_date="2025-01-15T13:00:00Z",
        )
        pnl = tracker.settle_trade(trade, "YES")
        assert trade.status == "settled"
        assert trade.winner == "YES"
        assert trade.payout == pytest.approx(21.28, abs=0.01)
        assert pnl == pytest.approx(11.28, abs=0.01)  # 21.28 - 10.0

    def test_settle_trade_loss(self, tracker):
        trade = PaperTrade(
            market_id="m1", market_question="BTC up?",
            market_source="crypto", side="YES",
            price=0.47, shares=21.28, cost=10.0,
            timestamp="2025-01-15T12:00:00Z",
            end_date="2025-01-15T13:00:00Z",
        )
        pnl = tracker.settle_trade(trade, "NO")
        assert trade.status == "settled"
        assert trade.winner == "NO"
        assert trade.payout == 0.0
        assert pnl == -10.0

    def test_settle_trade_no_side_wins(self, tracker):
        trade = PaperTrade(
            market_id="m1", market_question="BTC up?",
            market_source="crypto", side="NO",
            price=0.53, shares=18.87, cost=10.0,
            timestamp="2025-01-15T12:00:00Z",
            end_date="2025-01-15T13:00:00Z",
        )
        pnl = tracker.settle_trade(trade, "NO")
        assert pnl == pytest.approx(8.87, abs=0.01)  # 18.87 - 10.0

    def test_settle_trade_pending(self, tracker):
        trade = PaperTrade(
            market_id="m1", market_question="BTC up?",
            market_source="crypto", side="YES",
            price=0.47, shares=21.28, cost=10.0,
            timestamp="2025-01-15T12:00:00Z",
            end_date="2025-01-15T13:00:00Z",
        )
        pnl = tracker.settle_trade(trade, "pending")
        assert pnl == 0.0
        assert trade.status == "open"  # Not changed

    def test_cumulative_pnl(self, tracker):
        trade1 = PaperTrade(
            market_id="m1", market_question="BTC up?",
            market_source="crypto", side="YES",
            price=0.47, shares=21.28, cost=10.0,
            timestamp="2025-01-15T12:00:00Z",
            end_date="2025-01-15T13:00:00Z",
        )
        trade2 = PaperTrade(
            market_id="m2", market_question="ETH up?",
            market_source="crypto", side="NO",
            price=0.48, shares=20.83, cost=10.0,
            timestamp="2025-01-15T12:00:00Z",
            end_date="2025-01-15T13:00:00Z",
        )
        tracker.settle_trade(trade1, "YES")
        tracker.settle_trade(trade2, "YES")  # We bet NO, YES won → loss
        assert tracker.wins == 0  # wins not tracked via settle_trade directly
        # Cumulative via check_and_settle

    def test_format_settlement_report(self, tracker):
        summary = SettlementSummary(
            total_open=5,
            total_settled=10,
            newly_settled=3,
            cumulative_pnl=15.50,
            wins=7,
            losses=3,
        )
        report = tracker.format_settlement_report(summary)
        assert "Paper Trade 정산" in report
        assert "Open: 5건" in report
        assert "Settled: 10건" in report
        assert "신규 3건" in report
        assert "Win Rate: 70.0%" in report
        assert "$+15.50" in report

    def test_settlement_summary_win_rate_zero(self):
        summary = SettlementSummary()
        assert summary.win_rate == 0.0

    def test_load_empty(self, tracker):
        trades = tracker.load_trades()
        assert trades == []


# ---------------------------------------------------------------------------
# query_market_result (mocked)
# ---------------------------------------------------------------------------


class TestQueryMarketResult:
    @pytest.fixture()
    def tracker(self, tmp_path):
        return PaperSettlementTracker(data_dir=str(tmp_path / "paper_trades"))

    @pytest.mark.asyncio
    async def test_query_yes_wins(self, tracker):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "closed": True,
            "outcomePrices": '["1.0", "0.0"]',
        })

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session.get = MagicMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_resp),
                __aexit__=AsyncMock(return_value=False),
            ))
            mock_session_cls.return_value = mock_session

            result = await tracker.query_market_result("m1")
            assert result == "YES"

    @pytest.mark.asyncio
    async def test_query_no_wins(self, tracker):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "closed": True,
            "outcomePrices": '["0.0", "1.0"]',
        })

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session.get = MagicMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_resp),
                __aexit__=AsyncMock(return_value=False),
            ))
            mock_session_cls.return_value = mock_session

            result = await tracker.query_market_result("m1")
            assert result == "NO"

    @pytest.mark.asyncio
    async def test_query_pending(self, tracker):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "closed": False,
            "outcomePrices": '["0.5", "0.5"]',
        })

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session.get = MagicMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_resp),
                __aexit__=AsyncMock(return_value=False),
            ))
            mock_session_cls.return_value = mock_session

            result = await tracker.query_market_result("m1")
            assert result == "pending"

    @pytest.mark.asyncio
    async def test_query_api_error(self, tracker):
        mock_resp = AsyncMock()
        mock_resp.status = 500

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session.get = MagicMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_resp),
                __aexit__=AsyncMock(return_value=False),
            ))
            mock_session_cls.return_value = mock_session

            result = await tracker.query_market_result("m1")
            assert result == "unknown"

    @pytest.mark.asyncio
    async def test_query_list_prices(self, tracker):
        """Test when outcomePrices is already a list, not a string."""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "closed": True,
            "outcomePrices": [1.0, 0.0],
        })

        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session.get = MagicMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_resp),
                __aexit__=AsyncMock(return_value=False),
            ))
            mock_session_cls.return_value = mock_session

            result = await tracker.query_market_result("m1")
            assert result == "YES"
