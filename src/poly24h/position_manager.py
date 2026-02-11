"""Position Manager for realistic dry-run simulation.

Feature: 018-realistic-dryrun
Manages positions like a real trading system:
- One position per market
- Bankroll management
- Settlement tracking
- Thread-safe concurrent entry (F-022 fix)
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """A single trading position."""
    
    market_id: str
    market_question: str
    side: str  # "YES" or "NO"
    entry_price: float
    size_usd: float
    shares: float
    entry_time: str
    end_date: str
    status: str = "open"  # "open", "settled"
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> Position:
        return cls(**data)


class PositionManager:
    """Manages trading positions with bankroll tracking.
    
    Key behaviors:
    - Only one position per market allowed
    - Bankroll is deducted on entry, updated on settlement
    - Positions are tracked until settlement
    - Thread-safe concurrent entry (F-022)
    """
    
    MIN_POSITION_SIZE = 1.0  # Minimum $1 to enter
    
    def __init__(self, bankroll: float, max_per_market: float):
        """Initialize position manager.
        
        Args:
            bankroll: Starting capital in USD
            max_per_market: Maximum position size per market in USD
        """
        self._initial_bankroll = bankroll  # F-022: track initial
        self.bankroll = bankroll
        self.max_per_market = max_per_market
        self._positions: dict[str, Position] = {}  # market_id -> Position
        self._cumulative_pnl: float = 0.0
        self._total_settled: int = 0
        self._wins: int = 0
        self._losses: int = 0
        self._lock = threading.Lock()  # F-022: thread safety
        self._total_invested: float = 0.0  # F-022: track total invested
    
    @property
    def active_position_count(self) -> int:
        """Number of currently open positions."""
        return len(self._positions)
    
    @property
    def total_invested(self) -> float:
        """F-022: Total amount invested in all positions."""
        return self._total_invested
    
    @property
    def initial_bankroll(self) -> float:
        """F-022: Starting bankroll."""
        return self._initial_bankroll
    
    @property
    def cumulative_pnl(self) -> float:
        """Total P&L from all settled positions."""
        return self._cumulative_pnl
    
    @property
    def total_settled(self) -> int:
        """Total number of settled positions."""
        return self._total_settled
    
    @property
    def wins(self) -> int:
        """Number of winning trades."""
        return self._wins
    
    @property
    def losses(self) -> int:
        """Number of losing trades."""
        return self._losses
    
    def can_enter(self, market_id: str) -> bool:
        """Check if we can enter a position in this market.
        
        Returns False if:
        - Already have a position in this market
        - Insufficient bankroll (< $1)
        """
        if market_id in self._positions:
            return False
        if self.bankroll < self.MIN_POSITION_SIZE:
            return False
        return True
    
    def enter_position(
        self,
        market_id: str,
        market_question: str,
        side: str,
        price: float,
        end_date: str,
    ) -> Optional[Position]:
        """Enter a new position (thread-safe).
        
        F-022: Added lock to prevent concurrent entry causing bankroll overrun.
        
        Args:
            market_id: Unique market identifier
            market_question: Human-readable market description
            side: "YES" or "NO"
            price: Entry price (0-1)
            end_date: Market end date (ISO format)
        
        Returns:
            Position object if successful, None if cannot enter
        """
        with self._lock:  # F-022: Ensure thread safety
            # Re-check under lock to prevent race conditions
            if market_id in self._positions:
                logger.debug(f"Cannot enter {market_id}: already have position")
                return None
            
            if self.bankroll < self.MIN_POSITION_SIZE:
                logger.debug(f"Cannot enter {market_id}: insufficient bankroll (${self.bankroll:.2f})")
                return None
            
            # F-022: Double-check available bankroll under lock
            available_for_trade = min(self.max_per_market, self.bankroll)
            if available_for_trade < self.MIN_POSITION_SIZE:
                logger.debug(f"Cannot enter {market_id}: available ${available_for_trade:.2f} < min ${self.MIN_POSITION_SIZE}")
                return None
            
            # Calculate position size (limited by bankroll and max_per_market)
            size_usd = available_for_trade
            shares = size_usd / price if price > 0 else 0
            
            position = Position(
                market_id=market_id,
                market_question=market_question,
                side=side,
                entry_price=price,
                size_usd=size_usd,
                shares=shares,
                entry_time=datetime.now(timezone.utc).isoformat(),
                end_date=end_date,
                status="open",
            )
            
            self._positions[market_id] = position
            self.bankroll -= size_usd
            self._total_invested += size_usd  # F-022: track total
            
            logger.info(
                f"[POSITION ENTRY] {market_question} | "
                f"Side: {side} @ {price:.2f} | "
                f"Size: ${size_usd:.2f} ({shares:.2f} shares) | "
                f"Bankroll: ${self.bankroll:.2f} | "
                f"Total Invested: ${self._total_invested:.2f}"
            )
            
            return position
    
    def settle_position(self, market_id: str, winner: str) -> float:
        """Settle a position and calculate P&L.
        
        Args:
            market_id: Market to settle
            winner: Winning side ("YES" or "NO")
        
        Returns:
            P&L in USD (positive for win, negative for loss)
        """
        with self._lock:  # F-022: Ensure thread safety
            position = self._positions.get(market_id)
            if position is None:
                return 0.0
            
            # Calculate P&L
            if position.side == winner:
                # Win: payout = shares * $1
                payout = position.shares * 1.0
                pnl = payout - position.size_usd
                self._wins += 1
            else:
                # Loss: lose entire position
                pnl = -position.size_usd
                self._losses += 1
            
            # Update bankroll (add back position + P&L)
            # If won: bankroll += size + profit
            # If lost: bankroll stays same (already deducted on entry)
            if pnl > 0:
                self.bankroll += position.size_usd + pnl
            # If lost, bankroll was already reduced on entry, nothing to add back
            
            # Track stats
            self._cumulative_pnl += pnl
            self._total_settled += 1
            self._total_invested -= position.size_usd  # F-022: reduce invested on settlement
            
            # Remove position
            del self._positions[market_id]
            
            result = "WIN" if pnl > 0 else "LOSS"
            logger.info(
                f"[POSITION SETTLED] {position.market_question} | "
                f"{result}: {position.side} vs {winner} | "
                f"P&L: ${pnl:+.2f} | "
                f"Bankroll: ${self.bankroll:.2f} | "
                f"Total Invested: ${self._total_invested:.2f}"
            )
            
            return pnl
    
    def get_active_positions(self) -> list[Position]:
        """Get list of all active positions."""
        return list(self._positions.values())
    
    def get_position(self, market_id: str) -> Optional[Position]:
        """Get a specific position by market ID."""
        return self._positions.get(market_id)
    
    def save_state(self, path: Path) -> None:
        """Save current state to JSON file (atomic write via temp+rename)."""
        state = {
            "bankroll": self.bankroll,
            "initial_bankroll": self._initial_bankroll,  # F-022
            "max_per_market": self.max_per_market,
            "total_invested": self._total_invested,  # F-022
            "cumulative_pnl": self._cumulative_pnl,
            "total_settled": self._total_settled,
            "wins": self._wins,
            "losses": self._losses,
            "positions": {
                mid: pos.to_dict() for mid, pos in self._positions.items()
            },
        }
        # Atomic write: write to temp file, then rename
        tmp_path = path.with_suffix(".tmp")
        try:
            tmp_path.write_text(json.dumps(state, indent=2))
            tmp_path.replace(path)  # Atomic on POSIX
            logger.info(f"Saved position state to {path}")
        except Exception as e:
            logger.error(f"Failed to save position state: {e}")
            # Clean up temp file if rename failed
            if tmp_path.exists():
                tmp_path.unlink()
    
    def load_state(self, path: Path) -> None:
        """Load state from JSON file with integrity verification."""
        if not path.exists():
            logger.info(f"No state file at {path}, starting fresh")
            return

        try:
            content = path.read_text().strip()
            if not content:
                logger.warning(f"State file {path} is empty, starting fresh")
                return

            state = json.loads(content)

            # Integrity check: must have required keys
            if "bankroll" not in state or "positions" not in state:
                logger.warning(f"State file {path} missing required keys, starting fresh")
                return

            self.bankroll = state.get("bankroll", self.bankroll)
            self._initial_bankroll = state.get("initial_bankroll", self._initial_bankroll)  # F-022
            self.max_per_market = state.get("max_per_market", self.max_per_market)
            self._total_invested = state.get("total_invested", 0.0)  # F-022
            self._cumulative_pnl = state.get("cumulative_pnl", 0.0)
            self._total_settled = state.get("total_settled", 0)
            self._wins = state.get("wins", 0)
            self._losses = state.get("losses", 0)
            self._positions = {
                mid: Position.from_dict(pos_data)
                for mid, pos_data in state.get("positions", {}).items()
            }
            logger.info(
                f"Loaded state: bankroll=${self.bankroll:.2f}, "
                f"total_invested=${self._total_invested:.2f}, "  # F-022
                f"{self.active_position_count} active positions"
            )
        except json.JSONDecodeError as e:
            logger.error(f"Corrupt state file {path}: {e}, starting fresh")
        except Exception as e:
            logger.error(f"Failed to load state: {e}")

    def sync_from_paper_trades(self, data_dir: Path) -> None:
        """Sync positions from existing paper_trades JSONL files.

        This prevents duplicate entries when starting fresh without state file.
        Loads all 'open' trades from paper_trades/YYYY-MM-DD.jsonl and marks them as positions.
        Excludes market_stats_*.jsonl and paired_*.jsonl files.
        """
        if not data_dir.exists():
            return

        loaded_count = 0
        total_invested = 0.0
        for jsonl_file in data_dir.glob("*.jsonl"):
            # Skip non-trade files (market stats, paired entries)
            fname = jsonl_file.name
            if fname.startswith("market_stats_") or fname.startswith("paired_"):
                continue
            try:
                with open(jsonl_file, "r") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        trade = json.loads(line)
                        # Only sync open trades that aren't settled
                        if trade.get("status") != "open":
                            continue
                        market_id = trade.get("market_id", "")
                        if not market_id or market_id in self._positions:
                            continue

                        # Create position from trade
                        position = Position(
                            market_id=market_id,
                            market_question=trade.get("market_question", ""),
                            side=trade.get("side", "YES"),
                            entry_price=trade.get("price", 0.0),
                            size_usd=trade.get("paper_size_usd", 10.0),
                            shares=trade.get("paper_shares", 0.0),
                            entry_time=trade.get("timestamp", ""),
                            end_date=trade.get("end_date", ""),
                            status="open",
                        )
                        self._positions[market_id] = position
                        total_invested += position.size_usd
                        loaded_count += 1
            except Exception as e:
                logger.warning(f"Failed to sync from {jsonl_file}: {e}")

        if loaded_count > 0:
            # Deduct invested amount from bankroll
            self.bankroll -= total_invested
            logger.info(
                f"Synced {loaded_count} positions from paper_trades files, "
                f"deducted ${total_invested:.2f} from bankroll, "
                f"remaining bankroll: ${self.bankroll:.2f}"
            )
    
    def get_stats_summary(self) -> dict:
        """Get summary statistics."""
        win_rate = self._wins / self._total_settled if self._total_settled > 0 else 0.0
        return {
            "bankroll": self.bankroll,
            "initial_bankroll": self._initial_bankroll,  # F-022
            "total_invested": self._total_invested,  # F-022
            "active_positions": self.active_position_count,
            "cumulative_pnl": self._cumulative_pnl,
            "total_settled": self._total_settled,
            "wins": self._wins,
            "losses": self._losses,
            "win_rate": win_rate,
        }
