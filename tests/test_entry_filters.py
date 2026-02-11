"""TDD tests for entry filters — Kent Beck style.

P0-1: NBA underdog filter ($0.35 minimum for moneyline)
P0-2: O/U per-event duplicate limit (max 1 O/U per event)
P2-2: Bankroll exposure limits (max positions + max exposure ratio)
"""

from datetime import datetime, timezone

from poly24h.models.market import Market, MarketSource
from poly24h.position_manager import PositionManager


def _make_market(
    market_id: str = "123",
    question: str = "Mavericks vs. Spurs",
    source: MarketSource = MarketSource.NBA,
    event_id: str = "evt_1",
    liquidity: float = 10000.0,
) -> Market:
    """Helper to build a test Market."""
    return Market(
        id=market_id,
        question=question,
        source=source,
        yes_token_id=f"yes_{market_id}",
        no_token_id=f"no_{market_id}",
        yes_price=0.50,
        no_price=0.50,
        liquidity_usd=liquidity,
        end_date=datetime(2026, 2, 12, 3, 0, tzinfo=timezone.utc),
        event_id=event_id,
        event_title="Mavericks vs. Spurs",
    )


# ── P0-1: NBA underdog filter ──────────────────────────────────


class TestNBAUnderdogFilter:
    """Block extreme underdog entries ($0.15-$0.31) for NBA moneyline."""

    def test_nba_moneyline_below_035_blocked(self):
        """NBA moneyline entry at $0.15 should be blocked."""
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        market = _make_market(question="Grizzlies vs. Nuggets")
        assert pm.should_skip_entry(market, trigger_price=0.15, trigger_side="YES") is True

    def test_nba_moneyline_at_035_allowed(self):
        """NBA moneyline entry at $0.35 should be allowed."""
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        market = _make_market(question="Mavericks vs. Spurs")
        assert pm.should_skip_entry(market, trigger_price=0.35, trigger_side="YES") is False

    def test_nba_moneyline_at_045_allowed(self):
        """NBA moneyline entry at $0.45 should be allowed."""
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        market = _make_market(question="Knicks vs. 76ers")
        assert pm.should_skip_entry(market, trigger_price=0.45, trigger_side="YES") is False

    def test_nba_spread_below_035_allowed(self):
        """NBA spread market at $0.30 should NOT be blocked (spread has ~50% odds)."""
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        market = _make_market(question="Cavaliers vs. Wizards: Spread CLE -18.5")
        assert pm.should_skip_entry(market, trigger_price=0.30, trigger_side="YES") is False

    def test_nba_ou_below_035_allowed(self):
        """NBA O/U market at $0.30 should NOT be blocked (O/U has ~50% odds)."""
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        market = _make_market(question="Bulls vs. Celtics: O/U 224.5")
        assert pm.should_skip_entry(market, trigger_price=0.30, trigger_side="NO") is False

    def test_crypto_below_035_allowed(self):
        """Crypto market at $0.30 should NOT be blocked (different source)."""
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        market = _make_market(
            question="Will BTC go up in the next 1 hour?",
            source=MarketSource.HOURLY_CRYPTO,
        )
        assert pm.should_skip_entry(market, trigger_price=0.30, trigger_side="NO") is False

    def test_nhl_moneyline_below_035_blocked(self):
        """NHL moneyline entry at $0.20 should also be blocked."""
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        market = _make_market(
            question="Rangers vs. Penguins",
            source=MarketSource.NHL,
        )
        assert pm.should_skip_entry(market, trigger_price=0.20, trigger_side="YES") is True

    def test_soccer_moneyline_below_035_blocked(self):
        """Soccer moneyline at $0.25 should be blocked."""
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        market = _make_market(
            question="Liverpool vs. Arsenal",
            source=MarketSource.SOCCER,
        )
        assert pm.should_skip_entry(market, trigger_price=0.25, trigger_side="YES") is True


# ── P0-2: O/U per-event duplicate limit ────────────────────────


class TestOUPerEventLimit:
    """Same event's O/U markets: max 1 entry allowed."""

    def test_first_ou_entry_allowed(self):
        """First O/U entry for an event should be allowed."""
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        market = _make_market(
            market_id="m1",
            question="Kings vs. Jazz: O/U 231.5",
            event_id="kings_jazz_0211",
        )
        assert pm.should_skip_entry(market, trigger_price=0.45, trigger_side="YES") is False
        pm.enter_position("m1", market.question, "YES", 0.45, "2026-02-12T02:00:00Z",
                          event_id="kings_jazz_0211", market_type="ou")

    def test_second_ou_same_event_blocked(self):
        """Second O/U entry for the same event should be blocked."""
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        # Enter first O/U
        m1 = _make_market(
            market_id="m1",
            question="Kings vs. Jazz: O/U 231.5",
            event_id="kings_jazz_0211",
        )
        pm.enter_position("m1", m1.question, "YES", 0.45, "2026-02-12T02:00:00Z",
                          event_id="kings_jazz_0211", market_type="ou")

        # Try second O/U for same event
        m2 = _make_market(
            market_id="m2",
            question="Kings vs. Jazz: O/U 232.5",
            event_id="kings_jazz_0211",
        )
        assert pm.should_skip_entry(m2, trigger_price=0.46, trigger_side="YES") is True

    def test_ou_different_event_allowed(self):
        """O/U entry for a different event should be allowed."""
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        # Enter O/U for event A
        pm.enter_position("m1", "Kings vs Jazz: O/U 231.5", "YES", 0.45,
                          "2026-02-12T02:00:00Z",
                          event_id="kings_jazz_0211", market_type="ou")

        # Try O/U for event B
        m2 = _make_market(
            market_id="m2",
            question="Bulls vs. Celtics: O/U 224.5",
            event_id="bulls_celtics_0211",
        )
        assert pm.should_skip_entry(m2, trigger_price=0.47, trigger_side="NO") is False

    def test_spread_same_event_as_ou_allowed(self):
        """Spread entry for same event that already has O/U should be allowed."""
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        # Enter O/U
        pm.enter_position("m1", "Kings vs Jazz: O/U 231.5", "YES", 0.45,
                          "2026-02-12T02:00:00Z",
                          event_id="kings_jazz_0211", market_type="ou")

        # Try Spread for same event
        m2 = _make_market(
            market_id="m2",
            question="Kings vs. Jazz: Spread SAC -3.5",
            event_id="kings_jazz_0211",
        )
        assert pm.should_skip_entry(m2, trigger_price=0.46, trigger_side="YES") is False

    def test_moneyline_same_event_as_ou_allowed(self):
        """Moneyline entry for same event that already has O/U should be allowed."""
        pm = PositionManager(bankroll=1000.0, max_per_market=100.0)
        pm.enter_position("m1", "Kings vs Jazz: O/U 231.5", "YES", 0.45,
                          "2026-02-12T02:00:00Z",
                          event_id="kings_jazz_0211", market_type="ou")

        m2 = _make_market(
            market_id="m2",
            question="Kings vs. Jazz",
            event_id="kings_jazz_0211",
        )
        assert pm.should_skip_entry(m2, trigger_price=0.40, trigger_side="YES") is False


# ── P2-2: Bankroll exposure limits ──────────────────────────────


class TestBankrollExposureLimits:
    """Cap concurrent positions and total exposure."""

    def test_max_concurrent_positions_blocks_entry(self):
        """Cannot enter when at max concurrent position count."""
        pm = PositionManager(
            bankroll=100000.0, max_per_market=100.0,
            max_concurrent_positions=3,
        )
        pm.enter_position("m1", "Market 1", "YES", 0.45, "2026-02-12T02:00:00Z")
        pm.enter_position("m2", "Market 2", "NO", 0.45, "2026-02-12T02:00:00Z")
        pm.enter_position("m3", "Market 3", "YES", 0.45, "2026-02-12T02:00:00Z")

        assert pm.can_enter("m4") is False

    def test_max_concurrent_positions_allows_after_settlement(self):
        """Can enter new position after settling one when at max."""
        pm = PositionManager(
            bankroll=100000.0, max_per_market=100.0,
            max_concurrent_positions=3,
        )
        pm.enter_position("m1", "Market 1", "YES", 0.45, "2026-02-12T02:00:00Z")
        pm.enter_position("m2", "Market 2", "NO", 0.45, "2026-02-12T02:00:00Z")
        pm.enter_position("m3", "Market 3", "YES", 0.45, "2026-02-12T02:00:00Z")

        pm.settle_position("m1", "YES")
        assert pm.can_enter("m4") is True

    def test_max_exposure_ratio_blocks_entry(self):
        """Cannot enter when bankroll is exhausted (exposure limit)."""
        pm = PositionManager(
            bankroll=1000.0, max_per_market=100.0,
            max_exposure_ratio=2.0,
        )
        # Max exposure = 1000 * 2.0 = $2000 = 20 positions
        # But bankroll runs out at 10. Enter 10.
        for i in range(10):
            pm.enter_position(f"m{i}", f"Market {i}", "YES", 0.45,
                              "2026-02-12T02:00:00Z")
        # bankroll = 0, can't enter.
        assert pm.can_enter("m99") is False

    def test_default_no_position_limit(self):
        """Default PositionManager has no concurrent position limit."""
        pm = PositionManager(bankroll=100000.0, max_per_market=100.0)
        for i in range(20):
            pm.enter_position(f"m{i}", f"Market {i}", "YES", 0.45,
                              "2026-02-12T02:00:00Z")
        assert pm.can_enter("m99") is True

    def test_max_concurrent_positions_in_state(self, tmp_path):
        """max_concurrent_positions survives save/load cycle."""
        pm = PositionManager(
            bankroll=1000.0, max_per_market=100.0,
            max_concurrent_positions=5,
        )
        state_file = tmp_path / "state.json"
        pm.save_state(state_file)

        pm2 = PositionManager(bankroll=0.0, max_per_market=0.0)
        pm2.load_state(state_file)
        assert pm2._max_concurrent_positions == 5
