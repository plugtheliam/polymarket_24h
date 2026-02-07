"""Atomic Paired Transaction State Machine.

Ensures paired entry executes atomically:
- Both legs confirmed → COMMIT
- Partial fill → UNWIND the filled leg
- Neither confirmed → ABORT (no action needed)

State Machine:
    INIT → SUBMITTED → BOTH_CONFIRMED → COMMITTED
                    → PARTIAL_YES → UNWIND → UNWOUND
                    → PARTIAL_NO → UNWIND → UNWOUND
                    → NONE_CONFIRMED (terminal)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, auto
from typing import Optional

logger = logging.getLogger(__name__)


class PairState(Enum):
    """Atomic paired transaction states."""
    INIT = auto()
    SUBMITTED = auto()
    BOTH_CONFIRMED = auto()
    PARTIAL_YES = auto()      # YES confirmed, NO not
    PARTIAL_NO = auto()       # NO confirmed, YES not
    NONE_CONFIRMED = auto()   # Neither confirmed (terminal)
    UNWOUND = auto()          # Successfully unwound (terminal)
    COMMITTED = auto()        # Successfully committed (terminal)


@dataclass
class LegStatus:
    """Status of a single leg (YES or NO)."""
    price: Decimal = Decimal("0")
    target: Decimal = Decimal("0")
    filled: Decimal = Decimal("0")
    confirmed: bool = False
    timed_out: bool = False
    order_id: Optional[str] = None

    def is_filled(self) -> bool:
        """Check if leg is filled (filled >= target)."""
        return self.filled >= self.target and self.target > 0


@dataclass
class AtomicPairedTransaction:
    """Manages a paired YES/NO transaction atomically.
    
    Ensures both legs are confirmed or neither is kept.
    
    Usage:
        txn = AtomicPairedTransaction(market_id="abc-123")
        txn.submit(yes_price=0.40, no_price=0.45, shares=100)
        
        # After order placement...
        txn.confirm_leg("YES", filled=100)
        txn.confirm_leg("NO", filled=100)
        
        if txn.state == PairState.BOTH_CONFIRMED:
            txn.commit()
        elif txn.needs_unwind():
            # Handle unwind...
    """
    
    market_id: str
    txn_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    state: PairState = PairState.INIT
    
    yes_leg: LegStatus = field(default_factory=LegStatus)
    no_leg: LegStatus = field(default_factory=LegStatus)
    
    # Unwind tracking
    unwind_attempts: int = 0
    unwind_slippage_total: Decimal = Decimal("0")
    
    def submit(
        self,
        yes_price: Decimal,
        no_price: Decimal,
        shares: Decimal,
    ) -> None:
        """Submit paired orders.
        
        Args:
            yes_price: YES side price
            no_price: NO side price
            shares: Number of shares for each side
        """
        if self.state != PairState.INIT:
            raise ValueError(f"Cannot submit from state {self.state}")
        
        self.yes_leg = LegStatus(price=yes_price, target=shares)
        self.no_leg = LegStatus(price=no_price, target=shares)
        self.state = PairState.SUBMITTED
        
        logger.info(
            "[PAIR-TXN] id=%s market=%s submit YES@$%.3f NO@$%.3f shares=%s",
            self.txn_id, self.market_id, yes_price, no_price, shares
        )
    
    def confirm_leg(self, side: str, filled: Decimal) -> None:
        """Confirm a leg fill.
        
        Args:
            side: "YES" or "NO"
            filled: Number of shares filled
        """
        if side.upper() == "YES":
            self.yes_leg.filled = filled
            self.yes_leg.confirmed = True
        else:
            self.no_leg.filled = filled
            self.no_leg.confirmed = True
        
        self._update_state()
        
        logger.info(
            "[PAIR-STATE] id=%s %s confirmed filled=%s state=%s",
            self.txn_id, side, filled, self.state.name
        )
    
    def timeout_leg(self, side: str) -> None:
        """Mark a leg as timed out (not confirmed).
        
        Args:
            side: "YES" or "NO"
        """
        if side.upper() == "YES":
            self.yes_leg.timed_out = True
        else:
            self.no_leg.timed_out = True
        
        self._update_state()
        
        logger.info(
            "[PAIR-STATE] id=%s %s timed_out state=%s",
            self.txn_id, side, self.state.name
        )
    
    def _update_state(self) -> None:
        """Update state based on leg statuses."""
        yes_done = self.yes_leg.confirmed or self.yes_leg.timed_out
        no_done = self.no_leg.confirmed or self.no_leg.timed_out
        
        if not yes_done or not no_done:
            return  # Still waiting
        
        yes_ok = self.yes_leg.confirmed and self.yes_leg.is_filled()
        no_ok = self.no_leg.confirmed and self.no_leg.is_filled()
        
        if yes_ok and no_ok:
            self.state = PairState.BOTH_CONFIRMED
        elif yes_ok and not no_ok:
            self.state = PairState.PARTIAL_YES
        elif no_ok and not yes_ok:
            self.state = PairState.PARTIAL_NO
        else:
            self.state = PairState.NONE_CONFIRMED
    
    def needs_unwind(self) -> Optional[str]:
        """Check if we need to unwind a leg.
        
        Returns:
            The leg name to unwind ("YES" or "NO") or None.
        """
        if self.state == PairState.PARTIAL_YES:
            return "YES"
        elif self.state == PairState.PARTIAL_NO:
            return "NO"
        return None
    
    def record_unwind(
        self,
        leg: str,
        success: bool,
        sold_shares: Decimal,
        slippage_pct: Decimal,
    ) -> None:
        """Record an unwind attempt.
        
        Args:
            leg: "YES" or "NO"
            success: Whether unwind succeeded
            sold_shares: Shares sold in unwind
            slippage_pct: Slippage percentage
        """
        self.unwind_attempts += 1
        self.unwind_slippage_total += slippage_pct
        
        logger.info(
            "[UNWIND] id=%s leg=%s success=%s sold=%s slippage=%.2f%%",
            self.txn_id, leg, success, sold_shares, slippage_pct
        )
        
        if success:
            self.state = PairState.UNWOUND
    
    def commit(self) -> None:
        """Commit the successful transaction."""
        if self.state != PairState.BOTH_CONFIRMED:
            raise ValueError(f"Cannot commit from state {self.state}")
        
        self.state = PairState.COMMITTED
        profit = self.calculate_gross_profit()
        
        logger.info(
            "[PAIR-COMMIT] id=%s market=%s profit=$%.2f",
            self.txn_id, self.market_id, profit
        )
    
    def calculate_gross_profit(self) -> Decimal:
        """Calculate gross profit (before fees).
        
        Profit = shares × (1.0 - CPP)
        where CPP = yes_price + no_price
        """
        if not self.yes_leg.is_filled() or not self.no_leg.is_filled():
            return Decimal("0")
        
        cpp = self.yes_leg.price + self.no_leg.price
        margin_per_pair = Decimal("1.0") - cpp
        shares = min(self.yes_leg.filled, self.no_leg.filled)
        
        return (margin_per_pair * shares).quantize(Decimal("0.01"))
    
    def is_terminal(self) -> bool:
        """Check if transaction is in a terminal state."""
        return self.state in (
            PairState.COMMITTED,
            PairState.UNWOUND,
            PairState.NONE_CONFIRMED,
        )
    
    def should_halt(
        self,
        max_attempts: int = 3,
        slippage_cap: float = 5.0,
    ) -> bool:
        """Check if we should halt due to failures.
        
        Args:
            max_attempts: Maximum unwind attempts
            slippage_cap: Maximum cumulative slippage %
        
        Returns:
            True if should halt operations
        """
        if self.unwind_attempts >= max_attempts:
            logger.error(
                "[PAIR-HALT] id=%s reason=max_attempts attempts=%d",
                self.txn_id, self.unwind_attempts
            )
            return True
        
        if float(self.unwind_slippage_total) > slippage_cap:
            logger.error(
                "[PAIR-HALT] id=%s reason=slippage slippage=%.2f%% cap=%.2f%%",
                self.txn_id, self.unwind_slippage_total, slippage_cap
            )
            return True
        
        return False
