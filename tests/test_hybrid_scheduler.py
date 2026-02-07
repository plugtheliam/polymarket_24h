"""TDD tests for Hybrid Scheduler (Kent Beck style).

Routes markets to appropriate strategies:
- Crypto 1H → Paired Entry (threshold $0.94)
- NBA → Sniper (threshold $0.48)
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from poly24h.models.market import Market, MarketSource
from poly24h.scheduler.hybrid_strategy import (
    HybridConfig,
    HybridStrategy,
    StrategyType,
)


@pytest.fixture
def crypto_market():
    """Sample crypto 1H market."""
    return Market(
        id="crypto-btc-123",
        question="Bitcoin Up or Down - February 7, 5PM ET",
        source=MarketSource.HOURLY_CRYPTO,
        yes_token_id="yes-token-123",
        no_token_id="no-token-123",
        yes_price=0.45,
        no_price=0.48,
        liquidity_usd=10000,
        end_date=datetime(2026, 2, 8, 0, 0, tzinfo=timezone.utc),
        event_id="event-123",
        event_title="Bitcoin 1H",
    )


@pytest.fixture
def nba_market():
    """Sample NBA market."""
    return Market(
        id="nba-lakers-123",
        question="Lakers vs. Celtics",
        source=MarketSource.NBA,
        yes_token_id="yes-token-456",
        no_token_id="no-token-456",
        yes_price=0.42,
        no_price=0.55,
        liquidity_usd=5000,
        end_date=datetime(2026, 2, 8, 0, 0, tzinfo=timezone.utc),
        event_id="event-456",
        event_title="NBA Game",
    )


class TestHybridConfig:
    """Test hybrid configuration."""

    def test_default_config(self):
        """Default config values."""
        config = HybridConfig()
        
        assert config.paired_max_cpp == Decimal("0.94")
        assert config.sniper_threshold == Decimal("0.48")
        assert config.crypto_allocation == Decimal("0.60")
        assert config.nba_allocation == Decimal("0.40")

    def test_custom_config(self):
        """Custom config values."""
        config = HybridConfig(
            paired_max_cpp=Decimal("0.92"),
            sniper_threshold=Decimal("0.45"),
        )
        
        assert config.paired_max_cpp == Decimal("0.92")
        assert config.sniper_threshold == Decimal("0.45")


class TestStrategyRouting:
    """Test strategy routing based on market source."""

    def test_crypto_routes_to_paired(self, crypto_market):
        """Crypto markets use Paired Entry."""
        strategy = HybridStrategy(HybridConfig())
        
        result = strategy.get_strategy_for_market(crypto_market)
        
        assert result == StrategyType.PAIRED_ENTRY

    def test_nba_routes_to_sniper(self, nba_market):
        """NBA markets use Sniper."""
        strategy = HybridStrategy(HybridConfig())
        
        result = strategy.get_strategy_for_market(nba_market)
        
        assert result == StrategyType.SNIPER


class TestPairedEntryConditions:
    """Test Paired Entry eligibility conditions."""

    def test_eligible_when_spread_wide(self, crypto_market):
        """Eligible when YES+NO < max_cpp."""
        crypto_market.yes_price = 0.40
        crypto_market.no_price = 0.48  # Total 0.88 < 0.94
        
        strategy = HybridStrategy(HybridConfig())
        
        assert strategy.is_paired_eligible(crypto_market) is True

    def test_not_eligible_when_spread_tight(self, crypto_market):
        """Not eligible when YES+NO >= max_cpp."""
        crypto_market.yes_price = 0.48
        crypto_market.no_price = 0.50  # Total 0.98 > 0.94
        
        strategy = HybridStrategy(HybridConfig())
        
        assert strategy.is_paired_eligible(crypto_market) is False

    def test_marginal_case_at_threshold(self, crypto_market):
        """Marginal case at exactly threshold."""
        crypto_market.yes_price = 0.44
        crypto_market.no_price = 0.50  # Total 0.94 = threshold
        
        strategy = HybridStrategy(HybridConfig())
        
        # At threshold, should NOT be eligible (need strictly less)
        assert strategy.is_paired_eligible(crypto_market) is False


class TestSniperConditions:
    """Test Sniper eligibility conditions."""

    def test_sniper_eligible_yes_side(self, nba_market):
        """Sniper eligible when YES <= threshold."""
        nba_market.yes_price = 0.45
        
        strategy = HybridStrategy(HybridConfig())
        result = strategy.get_sniper_signal(nba_market)
        
        assert result is not None
        assert result["side"] == "YES"
        assert result["price"] == 0.45

    def test_sniper_eligible_no_side(self, nba_market):
        """Sniper eligible when NO <= threshold."""
        nba_market.yes_price = 0.55
        nba_market.no_price = 0.42
        
        strategy = HybridStrategy(HybridConfig())
        result = strategy.get_sniper_signal(nba_market)
        
        assert result is not None
        assert result["side"] == "NO"
        assert result["price"] == 0.42

    def test_sniper_not_eligible_both_high(self, nba_market):
        """No signal when both sides > threshold."""
        nba_market.yes_price = 0.55
        nba_market.no_price = 0.52
        
        strategy = HybridStrategy(HybridConfig())
        result = strategy.get_sniper_signal(nba_market)
        
        assert result is None


class TestPositionSizing:
    """Test position sizing calculations."""

    def test_crypto_position_size(self, crypto_market):
        """Crypto uses allocation ratio."""
        config = HybridConfig(
            max_per_market=Decimal("100"),
            crypto_allocation=Decimal("0.60"),
        )
        strategy = HybridStrategy(config)
        
        size = strategy.calculate_position_size(crypto_market, Decimal("1000"))
        
        # 60% of $1000 = $600, but max $100 per market
        assert size == Decimal("100")

    def test_nba_position_size(self, nba_market):
        """NBA uses allocation ratio."""
        config = HybridConfig(
            max_per_market=Decimal("100"),
            nba_allocation=Decimal("0.40"),
        )
        strategy = HybridStrategy(config)
        
        size = strategy.calculate_position_size(nba_market, Decimal("1000"))
        
        # 40% of $1000 = $400, but max $100 per market
        assert size == Decimal("100")

    def test_position_size_respects_max(self):
        """Position size respects max_per_market."""
        config = HybridConfig(
            max_per_market=Decimal("50"),
            crypto_allocation=Decimal("0.60"),
        )
        strategy = HybridStrategy(config)
        
        market = Market(
            id="test",
            question="test",
            source=MarketSource.HOURLY_CRYPTO,
            yes_token_id="y",
            no_token_id="n",
            yes_price=0.45,
            no_price=0.50,
            liquidity_usd=10000,
            end_date=datetime(2026, 2, 8, 0, 0, tzinfo=timezone.utc),
            event_id="event-test",
            event_title="Test Event",
        )
        
        size = strategy.calculate_position_size(market, Decimal("1000"))
        
        assert size == Decimal("50")


class TestExpectedProfit:
    """Test expected profit calculations."""

    def test_paired_expected_profit(self, crypto_market):
        """Calculate paired entry expected profit."""
        crypto_market.yes_price = 0.40
        crypto_market.no_price = 0.48  # CPP = 0.88
        
        strategy = HybridStrategy(HybridConfig())
        
        # $100 investment, CPP 0.88 → ~113 shares
        # Gross margin: 12% × $100 = $12
        # After ~6% fees: ~$6 profit
        profit = strategy.calculate_paired_expected_profit(
            crypto_market, 
            investment=Decimal("100"),
        )
        
        assert profit > Decimal("0")
        assert profit < Decimal("15")  # Reasonable range
