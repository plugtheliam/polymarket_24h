"""Hybrid Portfolio Manager.

Tracks positions and P&L across both strategies:
- Crypto Paired Entry positions
- NBA Sniper positions

Enforces risk limits:
- Max per market
- Daily loss limit
- Allocation ratios
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class PairedPosition:
    """A paired entry position (YES + NO)."""
    market_id: str
    yes_shares: Decimal = Decimal("0")
    no_shares: Decimal = Decimal("0")
    yes_cost: Decimal = Decimal("0")
    no_cost: Decimal = Decimal("0")
    entry_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    @property
    def total_cost(self) -> Decimal:
        return self.yes_cost + self.no_cost
    
    @property
    def paired_shares(self) -> Decimal:
        """Minimum of YES and NO shares (pairs that can settle)."""
        return min(self.yes_shares, self.no_shares)
    
    @property
    def cpp(self) -> Decimal:
        """Cost Per Pair."""
        if self.paired_shares <= 0:
            return Decimal("inf")
        return self.total_cost / self.paired_shares
    
    @property
    def expected_payout(self) -> Decimal:
        """Expected payout at settlement ($1 per pair)."""
        return self.paired_shares * Decimal("1.0")
    
    @property
    def expected_profit(self) -> Decimal:
        """Expected profit = payout - cost."""
        return self.expected_payout - self.total_cost


@dataclass
class SniperPosition:
    """A single-sided sniper position."""
    market_id: str
    side: str  # "YES" or "NO"
    shares: Decimal = Decimal("0")
    cost: Decimal = Decimal("0")
    entry_price: Decimal = Decimal("0")
    entry_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    @property
    def expected_payout(self) -> Decimal:
        """Expected payout if this side wins."""
        return self.shares * Decimal("1.0")
    
    @property
    def expected_profit_if_win(self) -> Decimal:
        """Profit if this side wins."""
        return self.expected_payout - self.cost


@dataclass
class HybridPortfolio:
    """Manages positions across both strategies.
    
    Attributes:
        initial_capital: Starting capital
        crypto_allocation: Allocation for crypto (0-1)
        nba_allocation: Allocation for NBA (0-1)
        max_per_market: Max USD per market
        daily_loss_limit: Max daily loss before halting
    """
    
    initial_capital: Decimal = Decimal("1000")
    crypto_allocation: Decimal = Decimal("0.60")
    nba_allocation: Decimal = Decimal("0.40")
    max_per_market: Decimal = Decimal("100")
    daily_loss_limit: Decimal = Decimal("200")
    
    # Positions
    paired_positions: Dict[str, PairedPosition] = field(default_factory=dict)
    sniper_positions: Dict[str, SniperPosition] = field(default_factory=dict)
    
    # P&L tracking
    realized_pnl: Decimal = Decimal("0")
    daily_pnl: Decimal = Decimal("0")
    
    # Capital tracking
    _invested_crypto: Decimal = Decimal("0")
    _invested_nba: Decimal = Decimal("0")
    
    @property
    def available_crypto_capital(self) -> Decimal:
        """Available capital for crypto paired entry."""
        allocated = self.initial_capital * self.crypto_allocation
        return max(Decimal("0"), allocated - self._invested_crypto)
    
    @property
    def available_nba_capital(self) -> Decimal:
        """Available capital for NBA sniper."""
        allocated = self.initial_capital * self.nba_allocation
        return max(Decimal("0"), allocated - self._invested_nba)
    
    @property
    def total_invested(self) -> Decimal:
        """Total capital currently invested."""
        return self._invested_crypto + self._invested_nba
    
    @property
    def should_halt(self) -> bool:
        """Check if daily loss limit exceeded."""
        return self.daily_pnl <= -self.daily_loss_limit
    
    def can_open_paired(self, market_id: str, cost: Decimal) -> bool:
        """Check if we can open a paired position.
        
        Args:
            market_id: Market ID
            cost: Total cost (YES + NO)
        
        Returns:
            True if position can be opened
        """
        if self.should_halt:
            logger.warning("Portfolio halted due to daily loss limit")
            return False
        
        if market_id in self.paired_positions:
            logger.debug("Already have paired position in %s", market_id)
            return False
        
        if cost > self.max_per_market:
            logger.debug("Cost $%.2f exceeds max per market $%.2f", cost, self.max_per_market)
            return False
        
        if cost > self.available_crypto_capital:
            logger.debug("Insufficient crypto capital: need $%.2f, have $%.2f",
                        cost, self.available_crypto_capital)
            return False
        
        return True
    
    def can_open_sniper(self, market_id: str, cost: Decimal) -> bool:
        """Check if we can open a sniper position.
        
        Args:
            market_id: Market ID
            cost: Position cost
        
        Returns:
            True if position can be opened
        """
        if self.should_halt:
            logger.warning("Portfolio halted due to daily loss limit")
            return False
        
        if market_id in self.sniper_positions:
            logger.debug("Already have sniper position in %s", market_id)
            return False
        
        if cost > self.max_per_market:
            logger.debug("Cost $%.2f exceeds max per market", cost)
            return False
        
        if cost > self.available_nba_capital:
            logger.debug("Insufficient NBA capital")
            return False
        
        return True
    
    def open_paired_position(
        self,
        market_id: str,
        yes_shares: Decimal,
        no_shares: Decimal,
        yes_cost: Decimal,
        no_cost: Decimal,
    ) -> PairedPosition:
        """Open a new paired position.
        
        Args:
            market_id: Market ID
            yes_shares: YES shares bought
            no_shares: NO shares bought
            yes_cost: Cost of YES shares
            no_cost: Cost of NO shares
        
        Returns:
            The new position
        """
        position = PairedPosition(
            market_id=market_id,
            yes_shares=yes_shares,
            no_shares=no_shares,
            yes_cost=yes_cost,
            no_cost=no_cost,
        )
        
        self.paired_positions[market_id] = position
        self._invested_crypto += position.total_cost
        
        logger.info(
            "[PORTFOLIO] Opened paired position: %s | shares=%s | cost=$%.2f | CPP=$%.4f",
            market_id, position.paired_shares, position.total_cost, position.cpp
        )
        
        return position
    
    def open_sniper_position(
        self,
        market_id: str,
        side: str,
        shares: Decimal,
        cost: Decimal,
        entry_price: Decimal,
    ) -> SniperPosition:
        """Open a new sniper position.
        
        Args:
            market_id: Market ID
            side: "YES" or "NO"
            shares: Shares bought
            cost: Total cost
            entry_price: Entry price per share
        
        Returns:
            The new position
        """
        position = SniperPosition(
            market_id=market_id,
            side=side,
            shares=shares,
            cost=cost,
            entry_price=entry_price,
        )
        
        self.sniper_positions[market_id] = position
        self._invested_nba += cost
        
        logger.info(
            "[PORTFOLIO] Opened sniper position: %s | %s | shares=%s | cost=$%.2f",
            market_id, side, shares, cost
        )
        
        return position
    
    def close_paired_position(self, market_id: str, payout: Decimal) -> Decimal:
        """Close a paired position at settlement.
        
        Args:
            market_id: Market ID
            payout: Actual payout received
        
        Returns:
            Profit/loss
        """
        if market_id not in self.paired_positions:
            return Decimal("0")
        
        position = self.paired_positions.pop(market_id)
        pnl = payout - position.total_cost
        
        self.realized_pnl += pnl
        self.daily_pnl += pnl
        self._invested_crypto -= position.total_cost
        
        logger.info(
            "[PORTFOLIO] Closed paired position: %s | payout=$%.2f | P&L=$%.2f",
            market_id, payout, pnl
        )
        
        return pnl
    
    def close_sniper_position(
        self,
        market_id: str,
        won: bool,
    ) -> Decimal:
        """Close a sniper position at settlement.
        
        Args:
            market_id: Market ID
            won: Whether the bet won
        
        Returns:
            Profit/loss
        """
        if market_id not in self.sniper_positions:
            return Decimal("0")
        
        position = self.sniper_positions.pop(market_id)
        
        if won:
            payout = position.shares * Decimal("1.0")
            pnl = payout - position.cost
        else:
            pnl = -position.cost
        
        self.realized_pnl += pnl
        self.daily_pnl += pnl
        self._invested_nba -= position.cost
        
        logger.info(
            "[PORTFOLIO] Closed sniper position: %s | %s | won=%s | P&L=$%.2f",
            market_id, position.side, won, pnl
        )
        
        return pnl
    
    def reset_daily_pnl(self) -> None:
        """Reset daily P&L counter (call at day boundary)."""
        self.daily_pnl = Decimal("0")
        logger.info("[PORTFOLIO] Reset daily P&L")
    
    def get_summary(self) -> dict:
        """Get portfolio summary."""
        return {
            "initial_capital": float(self.initial_capital),
            "total_invested": float(self.total_invested),
            "crypto_invested": float(self._invested_crypto),
            "nba_invested": float(self._invested_nba),
            "crypto_available": float(self.available_crypto_capital),
            "nba_available": float(self.available_nba_capital),
            "paired_positions": len(self.paired_positions),
            "sniper_positions": len(self.sniper_positions),
            "realized_pnl": float(self.realized_pnl),
            "daily_pnl": float(self.daily_pnl),
            "should_halt": self.should_halt,
        }
