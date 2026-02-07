"""TDD tests for Hybrid Portfolio Manager (Kent Beck style)."""

import pytest
from decimal import Decimal

from poly24h.portfolio.hybrid_portfolio import (
    HybridPortfolio,
    PairedPosition,
    SniperPosition,
)


class TestPairedPosition:
    """Test paired position calculations."""

    def test_cpp_calculation(self):
        """CPP = total_cost / paired_shares."""
        pos = PairedPosition(
            market_id="test",
            yes_shares=Decimal("100"),
            no_shares=Decimal("100"),
            yes_cost=Decimal("40"),
            no_cost=Decimal("48"),
        )
        
        assert pos.total_cost == Decimal("88")
        assert pos.paired_shares == Decimal("100")
        assert pos.cpp == Decimal("0.88")

    def test_expected_profit(self):
        """Expected profit = payout - cost."""
        pos = PairedPosition(
            market_id="test",
            yes_shares=Decimal("100"),
            no_shares=Decimal("100"),
            yes_cost=Decimal("40"),
            no_cost=Decimal("48"),
        )
        
        # Payout: 100 shares × $1 = $100
        # Cost: $88
        # Profit: $12
        assert pos.expected_payout == Decimal("100")
        assert pos.expected_profit == Decimal("12")

    def test_unbalanced_shares(self):
        """Paired shares = min of YES/NO."""
        pos = PairedPosition(
            market_id="test",
            yes_shares=Decimal("100"),
            no_shares=Decimal("80"),  # Less NO shares
            yes_cost=Decimal("40"),
            no_cost=Decimal("38"),
        )
        
        assert pos.paired_shares == Decimal("80")


class TestSniperPosition:
    """Test sniper position calculations."""

    def test_expected_profit_if_win(self):
        """Profit if win = payout - cost."""
        pos = SniperPosition(
            market_id="test",
            side="YES",
            shares=Decimal("100"),
            cost=Decimal("45"),
            entry_price=Decimal("0.45"),
        )
        
        # Win: 100 × $1 = $100 payout
        # Profit: $100 - $45 = $55
        assert pos.expected_payout == Decimal("100")
        assert pos.expected_profit_if_win == Decimal("55")


class TestPortfolioCapital:
    """Test capital allocation and availability."""

    def test_initial_allocation(self):
        """Check initial capital allocation."""
        portfolio = HybridPortfolio(
            initial_capital=Decimal("1000"),
            crypto_allocation=Decimal("0.60"),
            nba_allocation=Decimal("0.40"),
        )
        
        assert portfolio.available_crypto_capital == Decimal("600")
        assert portfolio.available_nba_capital == Decimal("400")

    def test_capital_decreases_after_investment(self):
        """Available capital decreases after opening position."""
        portfolio = HybridPortfolio(initial_capital=Decimal("1000"))
        
        portfolio.open_paired_position(
            market_id="test",
            yes_shares=Decimal("50"),
            no_shares=Decimal("50"),
            yes_cost=Decimal("22.5"),
            no_cost=Decimal("25"),
        )
        
        # Invested $47.5 in crypto
        assert portfolio._invested_crypto == Decimal("47.5")
        assert portfolio.available_crypto_capital == Decimal("552.5")


class TestPositionOpening:
    """Test position opening logic."""

    def test_can_open_paired_with_capital(self):
        """Can open if sufficient capital."""
        portfolio = HybridPortfolio(initial_capital=Decimal("1000"))
        
        assert portfolio.can_open_paired("test", Decimal("100")) is True

    def test_cannot_open_paired_insufficient_capital(self):
        """Cannot open if insufficient capital."""
        portfolio = HybridPortfolio(
            initial_capital=Decimal("100"),
            crypto_allocation=Decimal("0.50"),  # $50 available
        )
        
        assert portfolio.can_open_paired("test", Decimal("60")) is False

    def test_cannot_open_duplicate_position(self):
        """Cannot open duplicate position."""
        portfolio = HybridPortfolio(initial_capital=Decimal("1000"))
        
        portfolio.open_paired_position(
            "test",
            Decimal("50"), Decimal("50"),
            Decimal("25"), Decimal("25"),
        )
        
        assert portfolio.can_open_paired("test", Decimal("50")) is False

    def test_cannot_exceed_max_per_market(self):
        """Cannot exceed max per market limit."""
        portfolio = HybridPortfolio(
            initial_capital=Decimal("10000"),
            max_per_market=Decimal("100"),
        )
        
        assert portfolio.can_open_paired("test", Decimal("150")) is False


class TestPositionClosing:
    """Test position closing and P&L."""

    def test_close_paired_with_profit(self):
        """Close paired position with profit."""
        portfolio = HybridPortfolio(initial_capital=Decimal("1000"))
        
        portfolio.open_paired_position(
            "test",
            Decimal("100"), Decimal("100"),
            Decimal("40"), Decimal("48"),
        )
        
        # Close with $100 payout (100 pairs × $1)
        pnl = portfolio.close_paired_position("test", Decimal("100"))
        
        assert pnl == Decimal("12")  # $100 - $88 = $12
        assert portfolio.realized_pnl == Decimal("12")
        assert "test" not in portfolio.paired_positions

    def test_close_sniper_win(self):
        """Close sniper position with win."""
        portfolio = HybridPortfolio(initial_capital=Decimal("1000"))
        
        portfolio.open_sniper_position(
            "test", "YES",
            Decimal("100"), Decimal("45"), Decimal("0.45"),
        )
        
        pnl = portfolio.close_sniper_position("test", won=True)
        
        assert pnl == Decimal("55")  # $100 - $45
        assert portfolio.realized_pnl == Decimal("55")

    def test_close_sniper_loss(self):
        """Close sniper position with loss."""
        portfolio = HybridPortfolio(initial_capital=Decimal("1000"))
        
        portfolio.open_sniper_position(
            "test", "YES",
            Decimal("100"), Decimal("45"), Decimal("0.45"),
        )
        
        pnl = portfolio.close_sniper_position("test", won=False)
        
        assert pnl == Decimal("-45")
        assert portfolio.realized_pnl == Decimal("-45")


class TestDailyLossLimit:
    """Test daily loss limit enforcement."""

    def test_should_halt_when_limit_exceeded(self):
        """Should halt when daily loss exceeds limit."""
        portfolio = HybridPortfolio(
            initial_capital=Decimal("1000"),
            daily_loss_limit=Decimal("100"),
        )
        
        # Simulate $150 loss
        portfolio.daily_pnl = Decimal("-150")
        
        assert portfolio.should_halt is True

    def test_can_open_blocked_when_halted(self):
        """Cannot open positions when halted."""
        portfolio = HybridPortfolio(
            initial_capital=Decimal("1000"),
            daily_loss_limit=Decimal("100"),
        )
        
        portfolio.daily_pnl = Decimal("-150")
        
        assert portfolio.can_open_paired("test", Decimal("50")) is False
        assert portfolio.can_open_sniper("test", Decimal("50")) is False

    def test_reset_daily_pnl(self):
        """Daily P&L reset works."""
        portfolio = HybridPortfolio()
        portfolio.daily_pnl = Decimal("-50")
        
        portfolio.reset_daily_pnl()
        
        assert portfolio.daily_pnl == Decimal("0")


class TestPortfolioSummary:
    """Test portfolio summary output."""

    def test_summary_structure(self):
        """Summary contains expected fields."""
        portfolio = HybridPortfolio(initial_capital=Decimal("1000"))
        
        summary = portfolio.get_summary()
        
        assert "initial_capital" in summary
        assert "total_invested" in summary
        assert "crypto_invested" in summary
        assert "nba_invested" in summary
        assert "realized_pnl" in summary
        assert "should_halt" in summary
