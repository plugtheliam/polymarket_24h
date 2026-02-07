"""Hybrid Strategy Router.

Routes markets to appropriate strategies based on source:
- Crypto 1H → Paired Entry (threshold $0.94, fee-adjusted)
- NBA → Sniper (threshold $0.48, direction prediction)

Fee-adjusted thresholds:
- Taker fee ~3% per side at 50% prob
- Both sides taker = ~6% total
- Need 7%+ gross margin for profitability
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum, auto
from typing import Optional

from poly24h.models.market import Market, MarketSource
from poly24h.strategy.fee_calculator import (
    calculate_paired_cpp,
    is_profitable_after_fees,
)

logger = logging.getLogger(__name__)


class StrategyType(Enum):
    """Available strategy types."""
    PAIRED_ENTRY = auto()
    SNIPER = auto()
    SKIP = auto()


@dataclass
class HybridConfig:
    """Configuration for hybrid strategy routing.
    
    Attributes:
        paired_max_cpp: Maximum CPP for Paired Entry (after fees)
        sniper_threshold: Maximum price for Sniper entry
        crypto_allocation: Portfolio allocation for crypto (0-1)
        nba_allocation: Portfolio allocation for NBA (0-1)
        max_per_market: Maximum USD per market
        min_profit_margin: Minimum profit margin after fees
    """
    
    # Paired Entry (Crypto)
    paired_max_cpp: Decimal = Decimal("0.94")  # 6% gross margin needed for fees
    
    # Sniper (NBA)
    sniper_threshold: Decimal = Decimal("0.48")
    
    # Portfolio allocation
    crypto_allocation: Decimal = Decimal("0.60")  # 60%
    nba_allocation: Decimal = Decimal("0.40")      # 40%
    
    # Risk limits
    max_per_market: Decimal = Decimal("100")
    min_profit_margin: Decimal = Decimal("0.005")  # 0.5% after fees


class HybridStrategy:
    """Routes markets to appropriate strategies.
    
    Usage:
        strategy = HybridStrategy(HybridConfig())
        
        for market in markets:
            strategy_type = strategy.get_strategy_for_market(market)
            
            if strategy_type == StrategyType.PAIRED_ENTRY:
                if strategy.is_paired_eligible(market):
                    # Execute paired entry...
                    
            elif strategy_type == StrategyType.SNIPER:
                signal = strategy.get_sniper_signal(market)
                if signal:
                    # Execute sniper entry...
    """
    
    def __init__(self, config: HybridConfig):
        self.config = config
    
    def get_strategy_for_market(self, market: Market) -> StrategyType:
        """Determine which strategy to use for a market.
        
        Args:
            market: Market to evaluate
        
        Returns:
            StrategyType to use
        """
        if market.source == MarketSource.HOURLY_CRYPTO:
            return StrategyType.PAIRED_ENTRY
        elif market.source == MarketSource.NBA:
            return StrategyType.SNIPER
        else:
            # Other sources (soccer, etc.) - skip for now
            return StrategyType.SKIP
    
    def is_paired_eligible(self, market: Market) -> bool:
        """Check if market is eligible for Paired Entry.
        
        Conditions:
        1. YES + NO < max_cpp (fee-adjusted threshold)
        2. Both sides have sufficient liquidity
        
        Args:
            market: Market to check
        
        Returns:
            True if eligible for paired entry
        """
        yes_price = Decimal(str(market.yes_price))
        no_price = Decimal(str(market.no_price))
        
        raw_cpp = yes_price + no_price
        
        # Must be strictly less than threshold
        if raw_cpp >= self.config.paired_max_cpp:
            return False
        
        # Check profitability after fees
        return is_profitable_after_fees(
            yes_price=yes_price,
            no_price=no_price,
            min_margin=self.config.min_profit_margin,
            use_taker=True,
        )
    
    def get_sniper_signal(self, market: Market) -> Optional[dict]:
        """Get sniper entry signal for a market.
        
        Checks if either side is below threshold.
        
        Args:
            market: Market to check
        
        Returns:
            Signal dict with 'side' and 'price', or None
        """
        threshold = float(self.config.sniper_threshold)
        
        # Prefer YES if both qualify (arbitrary choice)
        if market.yes_price <= threshold:
            return {
                "side": "YES",
                "price": market.yes_price,
                "threshold": threshold,
            }
        
        if market.no_price <= threshold:
            return {
                "side": "NO",
                "price": market.no_price,
                "threshold": threshold,
            }
        
        return None
    
    def calculate_position_size(
        self,
        market: Market,
        total_capital: Decimal,
    ) -> Decimal:
        """Calculate position size for a market.
        
        Uses allocation ratios and respects max_per_market.
        
        Args:
            market: Target market
            total_capital: Total available capital
        
        Returns:
            Position size in USD
        """
        if market.source == MarketSource.HOURLY_CRYPTO:
            allocation = self.config.crypto_allocation
        elif market.source == MarketSource.NBA:
            allocation = self.config.nba_allocation
        else:
            allocation = Decimal("0")
        
        allocated = total_capital * allocation
        
        # Respect per-market limit
        return min(allocated, self.config.max_per_market)
    
    def calculate_paired_expected_profit(
        self,
        market: Market,
        investment: Decimal,
    ) -> Decimal:
        """Calculate expected profit from paired entry.
        
        Args:
            market: Target market
            investment: Total investment (split between YES/NO)
        
        Returns:
            Expected profit in USD (after fees)
        """
        yes_price = Decimal(str(market.yes_price))
        no_price = Decimal(str(market.no_price))
        
        # Calculate fee-adjusted CPP
        cpp = calculate_paired_cpp(
            yes_price=yes_price,
            no_price=no_price,
            yes_is_maker=False,
            no_is_maker=False,
        )
        
        # Shares we can buy with investment
        # investment = shares × cpp → shares = investment / cpp
        if cpp <= 0:
            return Decimal("0")
        
        shares = investment / cpp
        
        # Profit = shares × (1.0 - cpp)
        margin_per_share = Decimal("1.0") - cpp
        profit = shares * margin_per_share
        
        return profit.quantize(Decimal("0.01"))
    
    def get_paired_entry_params(
        self,
        market: Market,
        investment: Decimal,
    ) -> Optional[dict]:
        """Get parameters for paired entry execution.
        
        Args:
            market: Target market
            investment: Total investment
        
        Returns:
            Dict with execution parameters, or None if not eligible
        """
        if not self.is_paired_eligible(market):
            return None
        
        yes_price = Decimal(str(market.yes_price))
        no_price = Decimal(str(market.no_price))
        cpp = yes_price + no_price
        
        # Calculate shares
        shares = (investment / cpp).quantize(Decimal("0.01"))
        
        # Calculate costs
        yes_cost = (shares * yes_price).quantize(Decimal("0.01"))
        no_cost = (shares * no_price).quantize(Decimal("0.01"))
        
        expected_profit = self.calculate_paired_expected_profit(market, investment)
        
        return {
            "market_id": market.id,
            "yes_price": yes_price,
            "no_price": no_price,
            "shares": shares,
            "yes_cost": yes_cost,
            "no_cost": no_cost,
            "total_cost": yes_cost + no_cost,
            "raw_cpp": cpp,
            "expected_profit": expected_profit,
            "expected_roi_pct": (expected_profit / investment * 100).quantize(Decimal("0.1")),
        }
