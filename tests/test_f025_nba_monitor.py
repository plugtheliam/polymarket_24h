"""F-025: NBA Independent Monitor Tests.

Kent Beck TDD — RED phase first, then GREEN.
Tests cover: market discovery, edge calculation, entry logic,
per-game limits, Kelly sizing, daily loss limit, parallel execution.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from poly24h.models.market import Market, MarketSource
from poly24h.strategy.odds_api import GameOdds, MarketOdds


def _make_nba_market(
    market_id: str = "m1",
    question: str = "Lakers vs. Celtics",
    yes_price: float = 0.55,
    no_price: float = 0.45,
    event_id: str = "e1",
    yes_token: str = "yt1",
    no_token: str = "nt1",
    liquidity: float = 50000.0,
) -> Market:
    return Market(
        id=market_id,
        question=question,
        source=MarketSource.NBA,
        yes_token_id=yes_token,
        no_token_id=no_token,
        yes_price=yes_price,
        no_price=no_price,
        liquidity_usd=liquidity,
        end_date=datetime.now(tz=timezone.utc) + timedelta(hours=6),
        event_id=event_id,
        event_title=question,
    )


def _make_game_odds(
    home="Los Angeles Lakers",
    away="Boston Celtics",
    h2h_prices=(-150, 130),
) -> GameOdds:
    return GameOdds(
        game_id="g1",
        home_team=home,
        away_team=away,
        commence_time="2026-02-13T03:00:00Z",
        h2h=MarketOdds(outcomes=[
            {"name": home, "price": h2h_prices[0]},
            {"name": away, "price": h2h_prices[1]},
        ]),
        spreads=None,
        totals=None,
    )


# =============================================================================
# Phase 1: Edge Calculation
# =============================================================================


class TestNBAMonitorEdge:
    """Test edge detection for YES and NO sides."""

    @pytest.mark.asyncio
    async def test_yes_edge_detected(self):
        """When fair_prob > market_price, YES edge is positive."""
        from poly24h.strategy.nba_monitor import NBAMonitor

        monitor = NBAMonitor(
            odds_client=MagicMock(),
            market_scanner=MagicMock(),
            position_manager=MagicMock(),
            orderbook_fetcher=MagicMock(),
        )
        # fair=0.65, market YES ask=0.58 → edge = 0.07
        edge_yes, edge_no = monitor.calculate_edges(
            fair_prob=0.65, yes_price=0.58, no_price=0.42,
        )
        assert abs(edge_yes - 0.07) < 0.001
        assert edge_no < 0.03  # NO side has no edge

    @pytest.mark.asyncio
    async def test_no_edge_detected(self):
        """When (1-fair_prob) > no_price, NO edge is positive."""
        from poly24h.strategy.nba_monitor import NBAMonitor

        monitor = NBAMonitor(
            odds_client=MagicMock(),
            market_scanner=MagicMock(),
            position_manager=MagicMock(),
            orderbook_fetcher=MagicMock(),
        )
        # fair=0.40, market NO ask=0.52 → NO fair = 0.60, edge = 0.08
        edge_yes, edge_no = monitor.calculate_edges(
            fair_prob=0.40, yes_price=0.48, no_price=0.52,
        )
        assert edge_yes < 0.03
        assert abs(edge_no - 0.08) < 0.001

    @pytest.mark.asyncio
    async def test_no_edge_either_side(self):
        """When prices match fair value, no edge on either side."""
        from poly24h.strategy.nba_monitor import NBAMonitor

        monitor = NBAMonitor(
            odds_client=MagicMock(),
            market_scanner=MagicMock(),
            position_manager=MagicMock(),
            orderbook_fetcher=MagicMock(),
        )
        edge_yes, edge_no = monitor.calculate_edges(
            fair_prob=0.55, yes_price=0.55, no_price=0.45,
        )
        assert edge_yes < 0.03
        assert edge_no < 0.03


# =============================================================================
# Phase 2: Entry Logic
# =============================================================================


class TestNBAMonitorEntry:
    """Test paper trade entry on sufficient edge."""

    @pytest.mark.asyncio
    async def test_enters_on_yes_edge(self):
        """Edge >= 3% on YES side → enters paper trade."""
        from poly24h.strategy.nba_monitor import NBAMonitor

        pm = MagicMock()
        pm.calculate_kelly_size.return_value = 120.0
        pm.can_enter.return_value = True
        pm.enter_position.return_value = MagicMock(size_usd=120.0, shares=200.0)
        pm.bankroll = 3000.0
        pm._initial_bankroll = 3000.0

        monitor = NBAMonitor(
            odds_client=MagicMock(),
            market_scanner=MagicMock(),
            position_manager=pm,
            orderbook_fetcher=MagicMock(),
        )

        market = _make_nba_market(yes_price=0.55)
        result = await monitor.try_enter(
            market=market, side="YES", price=0.55, edge=0.07,
        )
        assert result is not None
        pm.enter_position.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_low_edge(self):
        """Edge < 3% → does NOT enter."""
        from poly24h.strategy.nba_monitor import NBAMonitor

        pm = MagicMock()
        monitor = NBAMonitor(
            odds_client=MagicMock(),
            market_scanner=MagicMock(),
            position_manager=pm,
            orderbook_fetcher=MagicMock(),
        )

        market = _make_nba_market()
        result = await monitor.try_enter(
            market=market, side="YES", price=0.55, edge=0.02,
        )
        assert result is None
        pm.enter_position.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_existing_position(self):
        """Already have position in this market → skip."""
        from poly24h.strategy.nba_monitor import NBAMonitor

        pm = MagicMock()
        pm.can_enter.return_value = False

        monitor = NBAMonitor(
            odds_client=MagicMock(),
            market_scanner=MagicMock(),
            position_manager=pm,
            orderbook_fetcher=MagicMock(),
        )

        market = _make_nba_market()
        result = await monitor.try_enter(
            market=market, side="YES", price=0.50, edge=0.05,
        )
        assert result is None


# =============================================================================
# Phase 3: Per-Game Limit
# =============================================================================


class TestNBAMonitorGameLimit:
    """Test per-game investment cap."""

    @pytest.mark.asyncio
    async def test_per_game_limit(self):
        """Total investment per game event capped at $500."""
        from poly24h.strategy.nba_monitor import NBAMonitor

        monitor = NBAMonitor(
            odds_client=MagicMock(),
            market_scanner=MagicMock(),
            position_manager=MagicMock(),
            orderbook_fetcher=MagicMock(),
            max_per_game=500.0,
        )
        # Simulate $450 already invested in event "e1"
        monitor._game_invested["e1"] = 450.0

        # Trying to invest $120 more → capped to $50
        capped = monitor.cap_for_game("e1", 120.0)
        assert capped == 50.0

    @pytest.mark.asyncio
    async def test_per_game_exceeded_returns_zero(self):
        """Game budget exhausted → returns 0."""
        from poly24h.strategy.nba_monitor import NBAMonitor

        monitor = NBAMonitor(
            odds_client=MagicMock(),
            market_scanner=MagicMock(),
            position_manager=MagicMock(),
            orderbook_fetcher=MagicMock(),
            max_per_game=500.0,
        )
        monitor._game_invested["e1"] = 510.0
        assert monitor.cap_for_game("e1", 100.0) == 0.0


# =============================================================================
# Phase 4: Kelly Sizing with Half-Kelly
# =============================================================================


class TestNBAMonitorKelly:
    """Test Half-Kelly position sizing."""

    @pytest.mark.asyncio
    async def test_uses_half_kelly(self):
        """NBAMonitor uses fraction=0.50 (Half-Kelly)."""
        from poly24h.strategy.nba_monitor import NBAMonitor

        pm = MagicMock()
        pm.calculate_kelly_size.return_value = 100.0

        monitor = NBAMonitor(
            odds_client=MagicMock(),
            market_scanner=MagicMock(),
            position_manager=pm,
            orderbook_fetcher=MagicMock(),
        )
        size = monitor.get_kelly_size(edge=0.05, price=0.50)
        pm.calculate_kelly_size.assert_called_once_with(
            edge=0.05, market_price=0.50, fraction=0.50,
        )


# =============================================================================
# Phase 5: Daily Loss Limit
# =============================================================================


class TestNBAMonitorDailyLoss:
    """Test daily loss limit stops trading."""

    @pytest.mark.asyncio
    async def test_daily_loss_limit_blocks_entry(self):
        """If daily P&L < -$300, no new entries."""
        from poly24h.strategy.nba_monitor import NBAMonitor

        monitor = NBAMonitor(
            odds_client=MagicMock(),
            market_scanner=MagicMock(),
            position_manager=MagicMock(),
            orderbook_fetcher=MagicMock(),
            daily_loss_limit=300.0,
        )
        monitor._daily_pnl = -310.0
        assert monitor.is_daily_loss_exceeded() is True

    @pytest.mark.asyncio
    async def test_daily_loss_not_exceeded(self):
        """Normal P&L → trading continues."""
        from poly24h.strategy.nba_monitor import NBAMonitor

        monitor = NBAMonitor(
            odds_client=MagicMock(),
            market_scanner=MagicMock(),
            position_manager=MagicMock(),
            orderbook_fetcher=MagicMock(),
            daily_loss_limit=300.0,
        )
        monitor._daily_pnl = -50.0
        assert monitor.is_daily_loss_exceeded() is False


# =============================================================================
# Phase 6: Full Scan Cycle
# =============================================================================


class TestNBAMonitorScanCycle:
    """Test the full scan_and_trade cycle."""

    @pytest.mark.asyncio
    async def test_scan_discovers_and_enters(self):
        """Full cycle: discover NBA → fetch odds → match → enter."""
        from poly24h.strategy.nba_monitor import NBAMonitor

        market = _make_nba_market(
            question="Lakers vs. Celtics",
            yes_price=0.55,
            event_id="e1",
        )
        game = _make_game_odds(
            home="Los Angeles Lakers",
            away="Boston Celtics",
            h2h_prices=(-200, 170),  # Lakers heavily favored → fair ~0.667
        )

        # Mock scanner
        scanner = MagicMock()
        scanner.discover_nba_markets = AsyncMock(return_value=[market])
        scanner.client = MagicMock()
        scanner.client.open = AsyncMock()

        # Mock odds client
        odds_client = MagicMock()
        odds_client.fetch_nba_odds = AsyncMock(return_value=[game])
        odds_client.get_fair_prob_for_market.return_value = 0.667

        # Mock orderbook fetcher
        fetcher = MagicMock()
        fetcher.fetch_best_asks = AsyncMock(return_value=(0.58, 0.42))

        # Mock position manager
        pm = MagicMock()
        pm.calculate_kelly_size.return_value = 80.0
        pm.can_enter.return_value = True
        pm.enter_position.return_value = MagicMock(size_usd=80.0, shares=137.9)
        pm.bankroll = 3000.0
        pm._initial_bankroll = 3000.0

        monitor = NBAMonitor(
            odds_client=odds_client,
            market_scanner=scanner,
            position_manager=pm,
            orderbook_fetcher=fetcher,
        )

        stats = await monitor.scan_and_trade()
        assert stats["markets_found"] >= 1
        assert stats["edges_found"] >= 1
        assert stats["trades_entered"] >= 1

    @pytest.mark.asyncio
    async def test_scan_no_nba_markets(self):
        """No NBA markets found → 0 trades, no crash."""
        from poly24h.strategy.nba_monitor import NBAMonitor

        scanner = MagicMock()
        scanner.discover_nba_markets = AsyncMock(return_value=[])
        scanner.client = MagicMock()
        scanner.client.open = AsyncMock()

        odds_client = MagicMock()
        odds_client.fetch_nba_odds = AsyncMock(return_value=[])

        monitor = NBAMonitor(
            odds_client=odds_client,
            market_scanner=scanner,
            position_manager=MagicMock(),
            orderbook_fetcher=MagicMock(),
        )

        stats = await monitor.scan_and_trade()
        assert stats["markets_found"] == 0
        assert stats["trades_entered"] == 0

    @pytest.mark.asyncio
    async def test_scan_no_matching_odds(self):
        """NBA markets found but no sportsbook match → 0 trades."""
        from poly24h.strategy.nba_monitor import NBAMonitor

        market = _make_nba_market(question="Hawks vs. Hornets")

        scanner = MagicMock()
        scanner.discover_nba_markets = AsyncMock(return_value=[market])
        scanner.client = MagicMock()
        scanner.client.open = AsyncMock()

        odds_client = MagicMock()
        odds_client.fetch_nba_odds = AsyncMock(return_value=[])
        odds_client.get_fair_prob_for_market.return_value = None

        monitor = NBAMonitor(
            odds_client=odds_client,
            market_scanner=scanner,
            position_manager=MagicMock(),
            orderbook_fetcher=MagicMock(),
        )

        stats = await monitor.scan_and_trade()
        assert stats["markets_found"] == 1
        assert stats["matched"] == 0
        assert stats["trades_entered"] == 0


# =============================================================================
# Phase 7: Market Discovery with negRisk
# =============================================================================


class TestNBAMarketDiscovery:
    """Test NBA market discovery including negRisk events."""

    @pytest.mark.asyncio
    async def test_discover_includes_neg_risk(self):
        """discover_nba_markets returns negRisk NBA markets."""
        from poly24h.discovery.market_scanner import MarketScanner

        # Mock Gamma client
        gamma = MagicMock()
        neg_risk_event = {
            "slug": "nba-lal-bos-2026-02-14",
            "enableNegRisk": True,
            "negRiskAugmented": True,
            "endDate": (datetime.now(tz=timezone.utc) + timedelta(hours=12)).isoformat(),
            "markets": [
                {
                    "id": "m1",
                    "question": "Lakers vs. Celtics",
                    "outcomePrices": '["0.55","0.45"]',
                    "clobTokenIds": '["yt1","nt1"]',
                    "volume": "50000",
                    "liquidity": "30000",
                    "endDate": (datetime.now(tz=timezone.utc) + timedelta(hours=12)).isoformat(),
                    "active": True,
                    "closed": False,
                    "acceptingOrders": True,
                },
            ],
        }
        gamma.fetch_nba_game_events = AsyncMock(return_value=[neg_risk_event])

        scanner = MarketScanner(gamma)
        markets = await scanner.discover_nba_markets(include_neg_risk=True)
        assert len(markets) >= 1
        assert markets[0].source == MarketSource.NBA

    @pytest.mark.asyncio
    async def test_discover_filters_non_nba(self):
        """Non-NBA events are filtered out."""
        from poly24h.discovery.market_scanner import MarketScanner

        gamma = MagicMock()
        nhl_event = {
            "slug": "nhl-bos-tor-2026-02-14",
            "enableNegRisk": False,
            "markets": [
                {
                    "id": "m1",
                    "question": "Bruins vs. Maple Leafs",
                    "outcomePrices": '["0.50","0.50"]',
                    "clobTokenIds": '["yt1","nt1"]',
                    "volume": "10000",
                    "liquidity": "5000",
                    "endDate": (datetime.now(tz=timezone.utc) + timedelta(hours=12)).isoformat(),
                    "active": True,
                    "closed": False,
                    "acceptingOrders": True,
                },
            ],
        }
        gamma.fetch_nba_game_events = AsyncMock(return_value=[nhl_event])

        scanner = MarketScanner(gamma)
        markets = await scanner.discover_nba_markets(include_neg_risk=True)
        assert len(markets) == 0
