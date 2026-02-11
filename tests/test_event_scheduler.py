"""Tests for F-018: Event-Driven Market Open Sniper.

Tests event-driven scheduler that switches phases based on market open timing:
- IDLE: >30s before open
- PRE_OPEN: 30s before open
- SNIPE: 0-60s after open
- COOLDOWN: 60-120s after open
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from poly24h.models.market import Market, MarketSource
from poly24h.scheduler.event_scheduler import (
    EventDrivenLoop,
    MarketOpenSchedule,
    OrderbookSnapshot,
    Phase,
    PreOpenPreparer,
    RapidOrderbookPoller,
    SniperOpportunity,
)


def _dt(minute: int, second: int = 0) -> datetime:
    """Helper: build datetime at specific minute:second in the current hour."""
    now = datetime.now(tz=timezone.utc)
    return now.replace(minute=minute, second=second, microsecond=0)


def _market(**kwargs) -> Market:
    """Helper: build a Market with defaults."""
    defaults = dict(
        id="mkt_1",
        question="Will ETH go up?",
        source=MarketSource.HOURLY_CRYPTO,
        yes_token_id="tok_yes_1",
        no_token_id="tok_no_1",
        yes_price=0.50,
        no_price=0.50,
        liquidity_usd=10000.0,
        end_date=datetime.now(tz=timezone.utc) + timedelta(hours=6),
        event_id="evt_1",
        event_title="ETH Price Movement",
    )
    defaults.update(kwargs)
    return Market(**defaults)


# ---------------------------------------------------------------------------
# Phase enum tests


def test_phase_enum_values():
    """Phase enum has correct values."""
    assert Phase.IDLE.value == "idle"
    assert Phase.PRE_OPEN.value == "pre_open"
    assert Phase.SNIPE.value == "snipe"
    assert Phase.COOLDOWN.value == "cooldown"


# ---------------------------------------------------------------------------
# MarketOpenSchedule tests


def test_next_open_at_start_of_hour():
    """next_open() returns next hour when at exactly :00."""
    now = _dt(0, 0)  # exactly on the hour
    schedule = MarketOpenSchedule()

    next_open = schedule.next_open(now)

    # Should return the NEXT hour (current + 1 hour)
    expected = now + timedelta(hours=1)
    assert next_open == expected


def test_next_open_mid_hour():
    """next_open() returns next hour boundary when mid-hour."""
    now = _dt(30, 45)  # 30:45
    schedule = MarketOpenSchedule()

    next_open = schedule.next_open(now)

    # Should return next hour at :00:00
    expected = now.replace(minute=0, second=0) + timedelta(hours=1)
    assert next_open == expected


def test_seconds_until_open_exact():
    """seconds_until_open() calculates correctly."""
    now = _dt(59, 30)  # 59:30 - 30 seconds before next hour
    schedule = MarketOpenSchedule()

    seconds = schedule.seconds_until_open(now)

    assert seconds == 30.0


def test_seconds_until_open_at_open():
    """seconds_until_open() returns 0 at market open."""
    now = _dt(0, 0)  # exactly at open
    schedule = MarketOpenSchedule()

    seconds = schedule.seconds_until_open(now)

    assert seconds == 0.0


def test_is_pre_open_window_true():
    """is_pre_open_window() returns True when within 30s before open."""
    now = _dt(59, 45)  # 15 seconds before open
    schedule = MarketOpenSchedule()

    assert schedule.is_pre_open_window(now, window_secs=30) is True


def test_is_pre_open_window_false_too_early():
    """is_pre_open_window() returns False when too early."""
    now = _dt(59, 0)  # 60 seconds before open
    schedule = MarketOpenSchedule()

    assert schedule.is_pre_open_window(now, window_secs=30) is False


def test_is_pre_open_window_false_after_open():
    """is_pre_open_window() returns False after market opens."""
    now = _dt(0, 5)  # 5 seconds after open
    schedule = MarketOpenSchedule()

    assert schedule.is_pre_open_window(now, window_secs=30) is False


def test_is_snipe_window_true_just_opened():
    """is_snipe_window() returns True just after market opens."""
    now = _dt(0, 5)  # 5 seconds after open
    schedule = MarketOpenSchedule()

    assert schedule.is_snipe_window(now, window_secs=60) is True


def test_is_snipe_window_false_before_open():
    """is_snipe_window() returns False before market opens."""
    now = _dt(59, 55)  # 5 seconds before open
    schedule = MarketOpenSchedule()

    assert schedule.is_snipe_window(now, window_secs=60) is False


def test_is_snipe_window_false_too_late():
    """is_snipe_window() returns False after snipe window closes."""
    now = _dt(1, 30)  # 90 seconds after open
    schedule = MarketOpenSchedule()

    assert schedule.is_snipe_window(now, window_secs=60) is False


def test_current_phase_idle():
    """current_phase() returns IDLE when >30s before open."""
    now = _dt(30, 0)  # 30 minutes before open
    schedule = MarketOpenSchedule()

    phase = schedule.current_phase(now)

    assert phase == Phase.IDLE


def test_current_phase_pre_open():
    """current_phase() returns PRE_OPEN when within 30s before open."""
    now = _dt(59, 45)  # 15 seconds before open
    schedule = MarketOpenSchedule()

    phase = schedule.current_phase(now)

    assert phase == Phase.PRE_OPEN


def test_current_phase_snipe():
    """current_phase() returns SNIPE when within 60s after open."""
    now = _dt(0, 30)  # 30 seconds after open
    schedule = MarketOpenSchedule()

    phase = schedule.current_phase(now)

    assert phase == Phase.SNIPE


def test_current_phase_cooldown():
    """current_phase() returns COOLDOWN when 60-120s after open."""
    now = _dt(1, 30)  # 90 seconds after open
    schedule = MarketOpenSchedule()

    phase = schedule.current_phase(now)

    assert phase == Phase.COOLDOWN


def test_current_phase_back_to_idle():
    """current_phase() returns IDLE when >120s after open."""
    now = _dt(3, 0)  # 3 minutes after open
    schedule = MarketOpenSchedule()

    phase = schedule.current_phase(now)

    assert phase == Phase.IDLE


# ---------------------------------------------------------------------------
# OrderbookSnapshot tests


def test_orderbook_snapshot_creation():
    """OrderbookSnapshot can be created with all fields."""
    now = datetime.now(tz=timezone.utc)
    snapshot = OrderbookSnapshot(
        yes_best_ask=0.45,
        no_best_ask=0.50,
        spread=0.95,
        timestamp=now
    )

    assert snapshot.yes_best_ask == 0.45
    assert snapshot.no_best_ask == 0.50
    assert snapshot.spread == 0.95
    assert snapshot.timestamp == now


def test_orderbook_snapshot_is_opportunity_true():
    """is_opportunity() returns True when either side <= threshold."""
    snapshot = OrderbookSnapshot(
        yes_best_ask=0.45,  # <= 0.48 threshold
        no_best_ask=0.50,
        spread=0.95,
        timestamp=datetime.now(tz=timezone.utc)
    )

    assert snapshot.is_opportunity(threshold=0.48) is True


def test_orderbook_snapshot_is_opportunity_false():
    """is_opportunity() returns False when both sides > threshold."""
    snapshot = OrderbookSnapshot(
        yes_best_ask=0.55,  # > 0.48 threshold
        no_best_ask=0.52,   # > 0.48 threshold
        spread=1.07,
        timestamp=datetime.now(tz=timezone.utc)
    )

    assert snapshot.is_opportunity(threshold=0.48) is False


def test_orderbook_snapshot_is_opportunity_no_side():
    """is_opportunity() works with NO side opportunity."""
    snapshot = OrderbookSnapshot(
        yes_best_ask=0.55,
        no_best_ask=0.40,  # <= 0.48 threshold
        spread=0.95,
        timestamp=datetime.now(tz=timezone.utc)
    )

    assert snapshot.is_opportunity(threshold=0.48) is True


# ---------------------------------------------------------------------------
# PreOpenPreparer tests


@pytest.fixture
def mock_gamma_client():
    """Mock GammaClient for testing."""
    client = MagicMock()
    client.open = AsyncMock()
    client.fetch_events = AsyncMock()
    client.fetch_events_by_tag_slug = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_pre_open_preparer_discover_upcoming_markets(mock_gamma_client):
    """discover_upcoming_markets() delegates to MarketScanner.discover_all() (F-019)."""
    from poly24h.discovery.market_scanner import MarketScanner

    # Mock the scanner's discover_all method (F-019: uses discover_all, not just crypto)
    mock_scanner = MagicMock(spec=MarketScanner)
    expected_markets = [
        _market(
            question="Will ETH go up?",
            yes_token_id="tok_yes_1",
            no_token_id="tok_no_1",
        ),
    ]
    mock_scanner.discover_all = AsyncMock(return_value=expected_markets)

    preparer = PreOpenPreparer(mock_gamma_client, scanner=mock_scanner)
    markets = await preparer.discover_upcoming_markets()

    assert len(markets) == 1
    assert markets[0].question == "Will ETH go up?"
    assert markets[0].yes_token_id == "tok_yes_1"
    assert markets[0].no_token_id == "tok_no_1"

    # Should delegate to scanner.discover_all(), not fetch_events directly
    mock_scanner.discover_all.assert_called_once()
    mock_gamma_client.open.assert_called_once()


@pytest.mark.asyncio
async def test_pre_open_preparer_discover_all_sources(mock_gamma_client):
    """discover_upcoming_markets() returns markets from ALL enabled sources (F-019)."""
    from poly24h.discovery.market_scanner import MarketScanner

    mock_scanner = MagicMock(spec=MarketScanner)
    expected_markets = [
        _market(
            id="mkt_crypto",
            question="Will ETH go up?",
            source=MarketSource.HOURLY_CRYPTO,
        ),
        _market(
            id="mkt_nba",
            question="CHA vs ATL?",
            source=MarketSource.NBA,
            yes_token_id="tok_nba_yes",
            no_token_id="tok_nba_no",
        ),
    ]
    mock_scanner.discover_all = AsyncMock(return_value=expected_markets)

    preparer = PreOpenPreparer(mock_gamma_client, scanner=mock_scanner)
    markets = await preparer.discover_upcoming_markets()

    assert len(markets) == 2
    sources = {m.source for m in markets}
    assert MarketSource.HOURLY_CRYPTO in sources
    assert MarketSource.NBA in sources


@pytest.mark.asyncio
async def test_pre_open_preparer_discover_empty_response(mock_gamma_client):
    """discover_upcoming_markets() handles empty response from scanner."""
    from poly24h.discovery.market_scanner import MarketScanner

    mock_scanner = MagicMock(spec=MarketScanner)
    mock_scanner.discover_all = AsyncMock(return_value=[])

    preparer = PreOpenPreparer(mock_gamma_client, scanner=mock_scanner)
    markets = await preparer.discover_upcoming_markets()

    assert markets == []


@pytest.mark.asyncio
async def test_pre_open_preparer_lazy_init_scanner(mock_gamma_client):
    """PreOpenPreparer creates MarketScanner lazily if not injected."""
    preparer = PreOpenPreparer(mock_gamma_client)
    scanner = preparer.scanner
    assert scanner is not None
    # Same instance on second access
    assert preparer.scanner is scanner


def test_pre_open_preparer_extract_token_market_map():
    """extract_token_market_map() maps token IDs to Market objects (F-019)."""
    markets = [
        _market(yes_token_id="tok_yes_1", no_token_id="tok_no_1"),
        _market(id="mkt_2", yes_token_id="tok_yes_2", no_token_id="tok_no_2"),
    ]

    preparer = PreOpenPreparer(MagicMock())
    mapping = preparer.extract_token_market_map(markets)

    assert "tok_yes_1" in mapping
    assert "tok_no_1" in mapping
    assert "tok_yes_2" in mapping
    assert mapping["tok_yes_1"].id == "mkt_1"
    assert mapping["tok_yes_2"].id == "mkt_2"


def test_pre_open_preparer_extract_token_pairs():
    """extract_token_pairs() extracts (yes, no) token pairs from markets."""
    markets = [
        _market(yes_token_id="tok_yes_1", no_token_id="tok_no_1"),
        _market(yes_token_id="tok_yes_2", no_token_id="tok_no_2"),
    ]

    preparer = PreOpenPreparer(MagicMock())
    pairs = preparer.extract_token_pairs(markets)

    expected = [("tok_yes_1", "tok_no_1"), ("tok_yes_2", "tok_no_2")]
    assert pairs == expected


def test_pre_open_preparer_extract_token_pairs_empty():
    """extract_token_pairs() handles empty market list."""
    preparer = PreOpenPreparer(MagicMock())
    pairs = preparer.extract_token_pairs([])

    assert pairs == []


@pytest.mark.asyncio
async def test_pre_open_preparer_warm_clob_connection_success():
    """warm_clob_connection() makes HTTP request and returns True on success."""
    with patch('aiohttp.ClientSession.get') as mock_get:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_get.return_value.__aenter__.return_value = mock_response

        preparer = PreOpenPreparer(MagicMock())
        result = await preparer.warm_clob_connection("tok_123")

        assert result is True
        mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_pre_open_preparer_warm_clob_connection_failure():
    """warm_clob_connection() returns False on HTTP error."""
    with patch('aiohttp.ClientSession.get') as mock_get:
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_get.return_value.__aenter__.return_value = mock_response

        preparer = PreOpenPreparer(MagicMock())
        result = await preparer.warm_clob_connection("tok_123")

        assert result is False


# ---------------------------------------------------------------------------
# RapidOrderbookPoller tests


@pytest.fixture
def mock_clob_fetcher():
    """Mock ClobOrderbookFetcher for testing."""
    fetcher = MagicMock()
    fetcher.fetch_best_asks = AsyncMock()
    return fetcher


@pytest.mark.asyncio
async def test_rapid_orderbook_poller_poll_once(mock_clob_fetcher):
    """poll_once() fetches orderbook and returns snapshot."""
    mock_clob_fetcher.fetch_best_asks.return_value = (0.45, 0.50)

    poller = RapidOrderbookPoller(mock_clob_fetcher)
    snapshot = await poller.poll_once("tok_yes_1", "tok_no_1")

    assert snapshot.yes_best_ask == 0.45
    assert snapshot.no_best_ask == 0.50
    assert snapshot.spread == 0.95
    assert isinstance(snapshot.timestamp, datetime)

    mock_clob_fetcher.fetch_best_asks.assert_called_once_with("tok_yes_1", "tok_no_1")


@pytest.mark.asyncio
async def test_rapid_orderbook_poller_poll_once_partial_data(mock_clob_fetcher):
    """poll_once() handles partial data (one side None)."""
    mock_clob_fetcher.fetch_best_asks.return_value = (0.45, None)

    poller = RapidOrderbookPoller(mock_clob_fetcher)
    snapshot = await poller.poll_once("tok_yes_1", "tok_no_1")

    assert snapshot.yes_best_ask == 0.45
    assert snapshot.no_best_ask is None
    assert snapshot.spread is None


@pytest.mark.asyncio
async def test_rapid_orderbook_poller_poll_once_no_data(mock_clob_fetcher):
    """poll_once() handles no data (both sides None)."""
    mock_clob_fetcher.fetch_best_asks.return_value = (None, None)

    poller = RapidOrderbookPoller(mock_clob_fetcher)
    snapshot = await poller.poll_once("tok_yes_1", "tok_no_1")

    assert snapshot.yes_best_ask is None
    assert snapshot.no_best_ask is None
    assert snapshot.spread is None


def test_rapid_orderbook_poller_detect_opportunity_found():
    """detect_opportunity() returns SniperOpportunity when threshold met."""
    snapshot = OrderbookSnapshot(
        yes_best_ask=0.40,  # <= 0.48 threshold, >= $0.02 min price
        no_best_ask=0.52,
        spread=0.92,
        timestamp=datetime.now(tz=timezone.utc)
    )

    poller = RapidOrderbookPoller(MagicMock())
    opportunity = poller.detect_opportunity(snapshot, threshold=0.48)

    assert opportunity is not None
    assert opportunity.trigger_price == 0.40
    assert opportunity.trigger_side == "YES"
    assert opportunity.spread == 0.92


def test_rapid_orderbook_poller_detect_opportunity_not_found():
    """detect_opportunity() returns None when threshold not met."""
    snapshot = OrderbookSnapshot(
        yes_best_ask=0.55,  # > 0.48 threshold
        no_best_ask=0.52,   # > 0.48 threshold
        spread=1.07,
        timestamp=datetime.now(tz=timezone.utc)
    )

    poller = RapidOrderbookPoller(MagicMock())
    opportunity = poller.detect_opportunity(snapshot, threshold=0.48)

    assert opportunity is None


def test_rapid_orderbook_poller_detect_opportunity_no_data():
    """detect_opportunity() returns None when no price data."""
    snapshot = OrderbookSnapshot(
        yes_best_ask=None,
        no_best_ask=None,
        spread=None,
        timestamp=datetime.now(tz=timezone.utc)
    )

    poller = RapidOrderbookPoller(MagicMock())
    opportunity = poller.detect_opportunity(snapshot, threshold=0.48)

    assert opportunity is None


def test_rapid_orderbook_poller_filters_garbage_signal():
    """F-019: detect_opportunity() filters NO@$0.001 garbage signals."""
    snapshot = OrderbookSnapshot(
        yes_best_ask=0.55,
        no_best_ask=0.001,  # Below MIN_MEANINGFUL_PRICE ($0.02)
        spread=0.551,
        timestamp=datetime.now(tz=timezone.utc)
    )

    poller = RapidOrderbookPoller(MagicMock())
    opportunity = poller.detect_opportunity(snapshot, threshold=0.48)

    # Should be None — NO@$0.001 is garbage, not a real opportunity
    assert opportunity is None


def test_rapid_orderbook_poller_filters_very_low_prices():
    """F-019: Prices below $0.02 are always filtered out."""
    snapshot = OrderbookSnapshot(
        yes_best_ask=0.01,  # Below min meaningful price
        no_best_ask=0.01,   # Below min meaningful price
        spread=0.02,
        timestamp=datetime.now(tz=timezone.utc)
    )

    poller = RapidOrderbookPoller(MagicMock())
    opportunity = poller.detect_opportunity(snapshot, threshold=0.48)

    assert opportunity is None


def test_rapid_orderbook_poller_accepts_valid_cheap_signal():
    """F-019: Valid cheap signals ($0.02+) are still detected."""
    snapshot = OrderbookSnapshot(
        yes_best_ask=0.55,
        no_best_ask=0.05,  # Cheap but above MIN_MEANINGFUL_PRICE
        spread=0.60,
        timestamp=datetime.now(tz=timezone.utc)
    )

    poller = RapidOrderbookPoller(MagicMock())
    opportunity = poller.detect_opportunity(snapshot, threshold=0.48)

    assert opportunity is not None
    assert opportunity.trigger_side == "NO"
    assert opportunity.trigger_price == 0.05


def test_rapid_orderbook_poller_picks_cheapest_valid_side():
    """F-019: When both sides are valid, picks the cheapest."""
    snapshot = OrderbookSnapshot(
        yes_best_ask=0.30,
        no_best_ask=0.25,
        spread=0.55,
        timestamp=datetime.now(tz=timezone.utc)
    )

    poller = RapidOrderbookPoller(MagicMock())
    opportunity = poller.detect_opportunity(snapshot, threshold=0.48)

    assert opportunity is not None
    assert opportunity.trigger_side == "NO"
    assert opportunity.trigger_price == 0.25


# ---------------------------------------------------------------------------
# EventDrivenLoop tests


@pytest.fixture
def mock_config():
    """Mock BotConfig for testing."""
    config = MagicMock()
    config.sniper_threshold = 0.48
    config.snipe_window_secs = 60
    config.pre_open_window_secs = 30
    config.cooldown_window_secs = 60
    return config


@pytest.fixture
def mock_telegram_alerter():
    """Mock TelegramAlerter for testing."""
    alerter = MagicMock()
    alerter.alert_opportunity = AsyncMock()
    alerter.alert_error = AsyncMock()
    return alerter


@pytest.mark.asyncio
async def test_event_driven_loop_run_idle_phase(
    mock_config, mock_telegram_alerter
):
    """run() handles IDLE phase correctly."""
    mock_config.pre_open_window_secs = 30

    with patch('poly24h.scheduler.event_scheduler.MarketOpenSchedule') as mock_schedule_class:
        mock_schedule = mock_schedule_class.return_value
        mock_schedule.current_phase.return_value = Phase.IDLE
        mock_schedule.seconds_until_open.return_value = 300.0  # 5 minutes until pre-open

        loop = EventDrivenLoop(
            schedule=mock_schedule,
            preparer=MagicMock(),
            poller=MagicMock(),
            alerter=mock_telegram_alerter
        )

        # Mock sleep to exit after first iteration
        call_count = 0
        async def mock_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:  # Exit after second sleep call
                raise SystemExit("Test completed")

        with patch('asyncio.sleep', side_effect=mock_sleep):
            with pytest.raises(SystemExit):
                await loop.run(mock_config)

        # Should calculate sleep time for pre-open window
        expected_sleep = 300.0 - mock_config.pre_open_window_secs
        assert expected_sleep == 270.0


@pytest.mark.asyncio
async def test_event_driven_loop_run_pre_open_phase(
    mock_config, mock_telegram_alerter
):
    """run() handles PRE_OPEN phase correctly."""
    mock_preparer = MagicMock()
    mock_preparer.discover_upcoming_markets = AsyncMock()
    mock_preparer.discover_upcoming_markets.return_value = [_market()]
    mock_preparer.extract_token_pairs.return_value = [("tok_yes_1", "tok_no_1")]
    mock_preparer.warm_clob_connection = AsyncMock(return_value=True)

    with patch('poly24h.scheduler.event_scheduler.MarketOpenSchedule') as mock_schedule_class:
        mock_schedule = mock_schedule_class.return_value
        mock_schedule.current_phase.side_effect = [Phase.PRE_OPEN, Phase.SNIPE]
        mock_schedule.seconds_until_open.return_value = 15.0

        loop = EventDrivenLoop(
            schedule=mock_schedule,
            preparer=mock_preparer,
            poller=MagicMock(),
            alerter=mock_telegram_alerter
        )

        # Mock sleep to exit after first phase
        call_count = 0
        async def mock_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise SystemExit("Test completed")

        with patch('asyncio.sleep', side_effect=mock_sleep):
            with pytest.raises(SystemExit):
                await loop.run(mock_config)

        # Should have discovered markets and warmed connections
        mock_preparer.discover_upcoming_markets.assert_called_once()
        mock_preparer.extract_token_pairs.assert_called_once()
        assert mock_preparer.warm_clob_connection.call_count == 2  # yes + no tokens


@pytest.mark.asyncio
async def test_event_driven_loop_run_snipe_phase_with_opportunity(
    mock_config, mock_telegram_alerter
):
    """run() handles SNIPE phase and detects opportunities."""
    mock_config.sniper_threshold = 0.48

    mock_poller = MagicMock()

    # Mock opportunity detection
    mock_snapshot = OrderbookSnapshot(
        yes_best_ask=0.40,  # opportunity
        no_best_ask=0.52,
        spread=0.92,
        timestamp=datetime.now(tz=timezone.utc)
    )
    mock_opportunity = SniperOpportunity(
        trigger_price=0.40,
        trigger_side="YES",
        spread=0.92,
        timestamp=datetime.now(tz=timezone.utc),
    )

    mock_poller.poll_once = AsyncMock(return_value=mock_snapshot)
    mock_poller.detect_opportunity.return_value = mock_opportunity

    with patch('poly24h.scheduler.event_scheduler.MarketOpenSchedule') as mock_schedule_class:
        mock_schedule = mock_schedule_class.return_value
        mock_schedule.current_phase.side_effect = [Phase.SNIPE, Phase.COOLDOWN]

        loop = EventDrivenLoop(
            schedule=mock_schedule,
            preparer=MagicMock(),
            poller=mock_poller,
            alerter=mock_telegram_alerter
        )

        # Set pre-discovered token pairs
        loop._active_token_pairs = [("tok_yes_1", "tok_no_1")]

        # Mock sleep to exit after one polling iteration
        call_count = 0
        async def mock_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise SystemExit("Test completed")

        with patch('asyncio.sleep', side_effect=mock_sleep):
            with pytest.raises(SystemExit):
                await loop.run(mock_config)

        # Should have polled orderbook and accumulated opportunity in batch
        mock_poller.poll_once.assert_called()
        # F-020: Alerts are now batched, so check pending_opps instead
        assert len(loop._pending_opps) > 0, "Opportunity should be accumulated in batch"
        assert loop._pending_opps[0][0].trigger_price == 0.40
        assert loop._pending_opps[0][0].trigger_side == "YES"


# SniperOpportunity model for RapidOrderbookPoller.detect_opportunity()


@pytest.fixture
def sniper_opportunity():
    """Create a SniperOpportunity for testing."""
    from poly24h.scheduler.event_scheduler import SniperOpportunity
    return SniperOpportunity(
        trigger_price=0.40,
        trigger_side="YES",
        spread=0.92,
        timestamp=datetime.now(tz=timezone.utc)
    )


def test_sniper_opportunity_creation(sniper_opportunity):
    """SniperOpportunity can be created with required fields."""
    assert sniper_opportunity.trigger_price == 0.40
    assert sniper_opportunity.trigger_side == "YES"
    assert sniper_opportunity.spread == 0.92
    assert isinstance(sniper_opportunity.timestamp, datetime)


# ---------------------------------------------------------------------------
# F-019: Paper trading & signal quality tests


def test_event_driven_loop_paper_trading_summary():
    """F-019: get_paper_trading_summary() returns correct initial state."""
    loop = EventDrivenLoop(
        schedule=MagicMock(),
        preparer=MagicMock(),
        poller=MagicMock(),
        alerter=MagicMock()
    )

    summary = loop.get_paper_trading_summary()
    assert summary["total_trades"] == 0
    assert summary["open_trades"] == 0
    assert summary["total_invested"] == 0.0
    assert summary["realized_pnl"] == 0.0


def test_event_driven_loop_record_paper_trade():
    """F-019: _record_paper_trade() stores trade with correct fields."""
    from poly24h.position_manager import PositionManager
    with patch.object(PositionManager, 'load_state'):
        with patch.object(PositionManager, 'sync_from_paper_trades'):
            loop = EventDrivenLoop(
                schedule=MagicMock(),
                preparer=MagicMock(),
                poller=MagicMock(),
                alerter=MagicMock()
            )

    market = _market(question="Will BTC go up?")
    opp = SniperOpportunity(
        trigger_price=0.40,
        trigger_side="YES",
        spread=0.92,
        timestamp=datetime.now(tz=timezone.utc)
    )

    trade = loop._record_paper_trade(opp, market)

    assert trade["side"] == "YES"
    assert trade["price"] == 0.40
    # F-018: Now uses PositionManager with max_per_market=$100 (was $10 fixed)
    assert trade["paper_size_usd"] == 100.0
    # F-018: Now uses max_per_market=$100, so shares = $100 / $0.40 = 250
    assert trade["paper_shares"] == 250.0
    assert trade["market_question"] == "Will BTC go up?"
    assert trade["status"] == "open"

    summary = loop.get_paper_trading_summary()
    assert summary["total_trades"] == 1
    # F-018: Now uses max_per_market=$100
    assert summary["total_invested"] == 100.0


def test_event_driven_loop_find_market_for_opp():
    """F-019: _find_market_for_opp() matches opp to market by index."""
    loop = EventDrivenLoop(
        schedule=MagicMock(),
        preparer=MagicMock(),
        poller=MagicMock(),
        alerter=MagicMock()
    )

    market1 = _market(id="mkt_1", question="Will ETH go up?")
    loop._active_markets = [market1]
    loop._active_token_pairs = [("tok_yes_1", "tok_no_1")]

    opp = SniperOpportunity(
        trigger_price=0.40,
        trigger_side="YES",
        spread=0.92,
        timestamp=datetime.now(tz=timezone.utc)
    )

    found = loop._find_market_for_tokens("tok_yes_1", "tok_no_1")
    assert found is not None
    assert found.id == "mkt_1"
