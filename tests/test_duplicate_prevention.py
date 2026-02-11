"""
TDD: PositionManager 중복 진입 버그 수정

버그: 마켓당 1회 진입이 되어야 하지만, 2회씩 진입됨
원인: _record_paper_trade에서 PositionManager 체크 후 
      _settlement_tracker.record_trade가 별도로 호출되어
      중복 기록됨
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from pathlib import Path

from poly24h.models.market import Market, MarketSource
from poly24h.scheduler.event_scheduler import EventDrivenLoop, SniperOpportunity
from poly24h.position_manager import PositionManager


class TestDuplicateEntryPrevention:
    """중복 진입 방지 테스트"""
    
    def test_position_manager_blocks_duplicate_entry(self):
        """
        RED → GREEN: 동일 마켓에 2회 진입 시도 시 2번째는 차단되어야 함
        """
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        
        # 첫 번째 진입
        pos1 = pm.enter_position(
            market_id="mkt_1",
            market_question="Test Market",
            side="YES",
            price=0.40,
            end_date="2026-02-10T00:00:00+00:00"
        )
        
        assert pos1 is not None
        assert pm.active_position_count == 1
        
        # 두 번째 진입 시도 (동일 마켓)
        can_enter = pm.can_enter("mkt_1")
        assert can_enter is False  # Should be blocked
        
        pos2 = pm.enter_position(
            market_id="mkt_1",
            market_question="Test Market",
            side="NO",
            price=0.45,
            end_date="2026-02-10T00:00:00+00:00"
        )
        
        assert pos2 is None  # Should be rejected
        assert pm.active_position_count == 1  # Still 1 position
    
    def test_record_paper_trade_respects_position_manager(self):
        """
        RED → GREEN: _record_paper_trade는 PositionManager의 제한을 존중해야 함
        """
        # Create loop with mocked state loading
        with patch.object(PositionManager, 'load_state'):
            with patch.object(PositionManager, 'sync_from_paper_trades'):
                loop = EventDrivenLoop(
                    schedule=Mock(),
                    preparer=Mock(),
                    poller=Mock(),
                    alerter=Mock()
                )
        
        market = Market(
            id="mkt_1",
            question="Test Market",
            source=MarketSource.HOURLY_CRYPTO,
            yes_token_id="yes_1",
            no_token_id="no_1",
            yes_price=0.40,
            no_price=0.45,
            liquidity_usd=100000,
            end_date=datetime.now(tz=timezone.utc),
            event_id="e1",
            event_title="Test"
        )
        
        opp = SniperOpportunity(
            trigger_price=0.40,
            trigger_side="YES",
            spread=0.92,
            timestamp=datetime.now(tz=timezone.utc)
        )
        
        # 첫 번째 진입
        trade1 = loop._record_paper_trade(opp, market)
        assert trade1 != {}  # Should succeed
        
        # 두 번째 진입 시도 (동일 마켓)
        trade2 = loop._record_paper_trade(opp, market)
        assert trade2 == {}  # Should be empty (rejected)
    
    def test_settlement_tracker_not_called_for_duplicate(self):
        """
        RED → GREEN: 중복 진입 시도 시 settlement_tracker.record_trade가
        호출되지 않아야 함
        """
        with patch.object(PositionManager, 'load_state'):
            with patch.object(PositionManager, 'sync_from_paper_trades'):
                loop = EventDrivenLoop(
                    schedule=Mock(),
                    preparer=Mock(),
                    poller=Mock(),
                    alerter=Mock()
                )

        # Mock settlement tracker
        loop._settlement_tracker = Mock()
        loop._settlement_tracker.record_trade = Mock()

        market = Market(
            id="mkt_1",
            question="Test Market",
            source=MarketSource.HOURLY_CRYPTO,
            yes_token_id="yes_1",
            no_token_id="no_1",
            yes_price=0.40,
            no_price=0.45,
            liquidity_usd=100000,
            end_date=datetime.now(tz=timezone.utc),
            event_id="e1",
            event_title="Test"
        )

        opp = SniperOpportunity(
            trigger_price=0.40,
            trigger_side="YES",
            spread=0.92,
            timestamp=datetime.now(tz=timezone.utc)
        )

        # 첫 번째 진입
        loop._record_paper_trade(opp, market)
        assert loop._settlement_tracker.record_trade.call_count == 1

        # 두 번째 진입 시도
        loop._record_paper_trade(opp, market)
        # Should still be 1, not 2
        assert loop._settlement_tracker.record_trade.call_count == 1


class TestPaperTradesListNoDuplicates:
    """paper_trades 리스트에 중복이 없어야 함"""

    def test_paper_trades_unique_by_market(self):
        """
        RED: paper_trades에 동일 마켓이 2개 이상 있으면 안 됨
        """
        with patch.object(PositionManager, 'load_state'):
            with patch.object(PositionManager, 'sync_from_paper_trades'):
                loop = EventDrivenLoop(
                    schedule=Mock(),
                    preparer=Mock(),
                    poller=Mock(),
                    alerter=Mock()
                )
        
        market = Market(
            id="mkt_1",
            question="Test Market",
            source=MarketSource.HOURLY_CRYPTO,
            yes_token_id="yes_1",
            no_token_id="no_1",
            yes_price=0.40,
            no_price=0.45,
            liquidity_usd=100000,
            end_date=datetime.now(tz=timezone.utc),
            event_id="e1",
            event_title="Test"
        )
        
        opp = SniperOpportunity(
            trigger_price=0.40,
            trigger_side="YES",
            spread=0.92,
            timestamp=datetime.now(tz=timezone.utc)
        )
        
        # 3번 진입 시도
        for _ in range(3):
            loop._record_paper_trade(opp, market)
        
        # paper_trades에는 1거이어야 함
        market_trades = [t for t in loop._paper_trades if t.get('market_id') == 'mkt_1']
        assert len(market_trades) == 1


# 실행: python -m pytest tests/test_duplicate_prevention.py -v
