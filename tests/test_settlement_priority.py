"""F-028: Settlement Priority Sorting TDD tests.

Kent Beck TDD — Red phase first.
24H 이내 정산 마켓이 장기 마켓보다 먼저 자본 배치되는지 검증.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from poly24h.models.market import Market, MarketSource
from poly24h.strategy.sport_config import NBA_CONFIG
from poly24h.strategy.sports_monitor import SportsMonitor


def _make_market(
    market_id: str,
    question: str,
    end_date: datetime,
    yes_price: float = 0.50,
    no_price: float = 0.50,
    event_id: str = "",
) -> Market:
    """Helper: 테스트용 Market 생성."""
    return Market(
        id=market_id,
        question=question,
        source=MarketSource.NBA,
        yes_token_id=f"yes_{market_id}",
        no_token_id=f"no_{market_id}",
        yes_price=yes_price,
        no_price=no_price,
        liquidity_usd=10000.0,
        end_date=end_date,
        event_id=event_id or market_id,
        event_title=question,
    )


def _make_monitor(max_daily: float = 100.0, max_per_market: float = 20.0):
    """Helper: SportsMonitor + mocked dependencies."""
    from poly24h.position_manager import PositionManager

    pm = PositionManager(
        bankroll=1000.0,
        max_per_market=max_per_market,
        max_daily_deployment_usd=max_daily,
    )

    odds_client = MagicMock()
    scanner = MagicMock()
    fetcher = AsyncMock()
    rate_limiter = MagicMock()

    monitor = SportsMonitor(
        sport_config=NBA_CONFIG,
        odds_client=odds_client,
        market_scanner=scanner,
        position_manager=pm,
        orderbook_fetcher=fetcher,
        rate_limiter=rate_limiter,
    )

    return monitor, pm, odds_client, scanner, fetcher, rate_limiter


NOW = datetime.now(timezone.utc)


class TestSettlementPriority:
    """F-028: 24H 이내 정산 마켓 우선 배치."""

    @pytest.mark.asyncio
    async def test_24h_markets_entered_before_30d(self):
        """24H 마켓이 30일 마켓보다 먼저 진입.

        마켓 발견 순서: [30일, 24H, 30일, 24H]
        기대 진입 순서: 24H 마켓 먼저.
        """
        monitor, pm, odds_client, scanner, fetcher, rate_limiter = _make_monitor(
            max_daily=40.0,  # $40 한도 → 2개만 진입 가능
        )

        # 마켓 4개: 발견 순서는 30일 먼저, 24H 나중
        markets = [
            _make_market("far1", "Far Game 1", NOW + timedelta(days=30), event_id="e1"),
            _make_market("near1", "Near Game 1", NOW + timedelta(hours=12), event_id="e2"),
            _make_market("far2", "Far Game 2", NOW + timedelta(days=25), event_id="e3"),
            _make_market("near2", "Near Game 2", NOW + timedelta(hours=6), event_id="e4"),
        ]

        # Mock: discover → 위 마켓 반환
        scanner.discover_sport_markets = AsyncMock(return_value=markets)
        scanner.client = MagicMock()
        scanner.client.open = AsyncMock()

        # Mock: rate limiter allows
        rate_limiter.can_fetch.return_value = True

        # Mock: odds API → 모든 마켓에 동일 fair_prob
        odds_client.fetch_odds = AsyncMock(return_value=[])
        odds_client.get_fair_prob_for_market.return_value = 0.60  # edge for NO side

        # Mock: fetcher → 동일 가격
        fetcher.fetch_best_asks = AsyncMock(return_value=(0.55, 0.55))

        stats = await monitor.scan_and_trade()

        # $40 한도 → 2개 진입
        assert stats["trades_entered"] == 2

        # 진입된 마켓은 24H 이내 (near2: 6H, near1: 12H)
        entered_ids = [
            mid for mid, pos in pm._positions.items()
            if pos.status == "open"
        ]
        assert "near2" in entered_ids, f"6H market should be entered, got {entered_ids}"
        assert "near1" in entered_ids, f"12H market should be entered, got {entered_ids}"
        assert "far1" not in entered_ids, "30D market should NOT be entered"
        assert "far2" not in entered_ids, "25D market should NOT be entered"

    @pytest.mark.asyncio
    async def test_preserves_edge_filter(self):
        """정렬 후에도 edge 없는 마켓은 스킵."""
        monitor, pm, odds_client, scanner, fetcher, rate_limiter = _make_monitor(
            max_daily=100.0,
        )

        markets = [
            _make_market("noedge", "No Edge Game", NOW + timedelta(hours=3), event_id="e1"),
            _make_market("hasedge", "Has Edge Game", NOW + timedelta(hours=8), event_id="e2"),
        ]

        scanner.discover_sport_markets = AsyncMock(return_value=markets)
        scanner.client = MagicMock()
        scanner.client.open = AsyncMock()
        rate_limiter.can_fetch.return_value = True
        odds_client.fetch_odds = AsyncMock(return_value=[])

        # noedge: fair_prob=None (매칭 실패), hasedge: fair_prob=0.60
        def mock_fair_prob(market, games, sport_config=None):
            if market.id == "noedge":
                return None
            return 0.60

        odds_client.get_fair_prob_for_market.side_effect = mock_fair_prob
        fetcher.fetch_best_asks = AsyncMock(return_value=(0.55, 0.55))

        stats = await monitor.scan_and_trade()

        assert stats["trades_entered"] == 1
        assert "hasedge" in pm._positions

    @pytest.mark.asyncio
    async def test_daily_cap_with_settlement_priority(self):
        """daily cap $60일 때 24H 마켓 3개($60) 우선, 30일 마켓 차단."""
        monitor, pm, odds_client, scanner, fetcher, rate_limiter = _make_monitor(
            max_daily=60.0,
            max_per_market=20.0,
        )

        markets = [
            # 발견 순서: 장기 → 단기 (역순)
            _make_market("far1", "Far 1", NOW + timedelta(days=30), event_id="e1"),
            _make_market("far2", "Far 2", NOW + timedelta(days=20), event_id="e2"),
            _make_market("near1", "Near 1", NOW + timedelta(hours=18), event_id="e3"),
            _make_market("near2", "Near 2", NOW + timedelta(hours=10), event_id="e4"),
            _make_market("near3", "Near 3", NOW + timedelta(hours=4), event_id="e5"),
        ]

        scanner.discover_sport_markets = AsyncMock(return_value=markets)
        scanner.client = MagicMock()
        scanner.client.open = AsyncMock()
        rate_limiter.can_fetch.return_value = True
        odds_client.fetch_odds = AsyncMock(return_value=[])
        odds_client.get_fair_prob_for_market.return_value = 0.60
        fetcher.fetch_best_asks = AsyncMock(return_value=(0.55, 0.55))

        stats = await monitor.scan_and_trade()

        # $60 한도 → 3개 진입 (각 $20)
        assert stats["trades_entered"] == 3

        # 진입된 것은 24H 이내 마켓
        entered_ids = set(
            mid for mid, pos in pm._positions.items()
            if pos.status == "open"
        )
        assert {"near1", "near2", "near3"} == entered_ids, (
            f"All 3 near markets should be entered, got {entered_ids}"
        )
