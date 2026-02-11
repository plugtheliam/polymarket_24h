"""Position Manager for realistic dry-run simulation.

Feature: 018-realistic-dryrun
Manages positions like a real trading system:
- One position per market
- Bankroll management
- Settlement tracking
- Thread-safe concurrent entry (F-022 fix)
- P0-1: Sports moneyline minimum price filter ($0.35)
- P0-2: Max 1 O/U entry per event
- P2-2: Max concurrent positions and exposure ratio limits
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, asdict
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
    - P0-1: Sports moneyline minimum price filter ($0.35)
    - P0-2: Max 1 O/U entry per event
    - P2-2: Max concurrent positions and exposure ratio limits
    """

    MIN_POSITION_SIZE = 1.0  # Minimum $1 to enter
    # P0-1: Minimum entry price for sports moneyline bets
    SPORTS_MONEYLINE_MIN_PRICE = 0.35
    # Market sources that use moneyline filter
    _SPORTS_SOURCES = {"nba", "nhl", "soccer"}
    # Keywords that indicate non-moneyline (spread/O/U) markets
    _NON_MONEYLINE_KEYWORDS = ("spread", "o/u", "over/under", "total")

    def __init__(
        self,
        bankroll: float,
        max_per_market: float,
        max_concurrent_positions: int = 0,
        max_exposure_ratio: float = 0.0,
    ):
        """Initialize position manager.

        Args:
            bankroll: Starting capital in USD
            max_per_market: Maximum position size per market in USD
            max_concurrent_positions: Max open positions (0 = unlimited)
            max_exposure_ratio: Max total_invested / initial_bankroll (0 = unlimited)
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
        # P2-2: Exposure limits
        self._max_concurrent_positions = max_concurrent_positions
        self._max_exposure_ratio = max_exposure_ratio
        # P0-2: Track event_id + market_type for O/U dedup
        self._event_ou_entries: dict[str, str] = {}  # event_id -> market_id

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

    @staticmethod
    def _is_moneyline_market(question: str) -> bool:
        """Check if a market question is a moneyline (win/loss) market.

        Returns False for spread or O/U markets.
        """
        q = question.lower()
        for kw in PositionManager._NON_MONEYLINE_KEYWORDS:
            if kw in q:
                return False
        return True

    @staticmethod
    def _detect_market_type(question: str) -> str:
        """Detect market type from question text.

        Returns:
            "ou" for Over/Under, "spread" for spread, "moneyline" otherwise.
        """
        q = question.lower()
        if "o/u" in q or "over/under" in q or "total" in q:
            return "ou"
        if "spread" in q:
            return "spread"
        return "moneyline"

    def should_skip_entry(
        self,
        market: "Market",
        trigger_price: float,
        trigger_side: str,
    ) -> bool:
        """Check if this entry should be skipped based on filters.

        P0-1: Block extreme underdog moneyline bets (<$0.35) for sports.
        P0-2: Block duplicate O/U entries for the same event.

        Args:
            market: Market object with source, question, event_id
            trigger_price: Entry price
            trigger_side: "YES" or "NO"

        Returns:
            True if entry should be skipped.
        """
        source_val = (
            market.source.value
            if hasattr(market.source, "value")
            else str(market.source)
        )

        # P0-1: Sports moneyline minimum price
        if source_val in self._SPORTS_SOURCES:
            if self._is_moneyline_market(market.question):
                if trigger_price < self.SPORTS_MONEYLINE_MIN_PRICE:
                    logger.info(
                        "P0-1 SKIP: %s moneyline at $%.2f < $%.2f min | %s",
                        source_val.upper(),
                        trigger_price,
                        self.SPORTS_MONEYLINE_MIN_PRICE,
                        market.question[:60],
                    )
                    return True

        # P0-2: O/U per-event limit
        market_type = self._detect_market_type(market.question)
        if market_type == "ou" and market.event_id:
            if market.event_id in self._event_ou_entries:
                existing_mid = self._event_ou_entries[market.event_id]
                logger.info(
                    "P0-2 SKIP: O/U already entered for event %s "
                    "(market %s) | %s",
                    market.event_id,
                    existing_mid,
                    market.question[:60],
                )
                return True

        return False

    def can_enter(self, market_id: str) -> bool:
        """Check if we can enter a position in this market.

        Returns False if:
        - Already have a position in this market
        - Insufficient bankroll (< $1)
        - P2-2: At max concurrent positions
        """
        if market_id in self._positions:
            return False
        if self.bankroll < self.MIN_POSITION_SIZE:
            return False
        # P2-2: Concurrent position limit
        if (
            self._max_concurrent_positions > 0
            and self.active_position_count >= self._max_concurrent_positions
        ):
            return False
        return True

    def enter_position(
        self,
        market_id: str,
        market_question: str,
        side: str,
        price: float,
        end_date: str,
        event_id: str = "",
        market_type: str = "",
    ) -> Optional[Position]:
        """Enter a new position (thread-safe).

        F-022: Added lock to prevent concurrent entry causing bankroll overrun.
        P0-2: Tracks event_id + market_type for O/U dedup.

        Args:
            market_id: Unique market identifier
            market_question: Human-readable market description
            side: "YES" or "NO"
            price: Entry price (0-1)
            end_date: Market end date (ISO format)
            event_id: Event identifier (for O/U dedup)
            market_type: "ou", "spread", or "moneyline"

        Returns:
            Position object if successful, None if cannot enter
        """
        with self._lock:  # F-022: Ensure thread safety
            # Re-check under lock to prevent race conditions
            if market_id in self._positions:
                logger.debug(
                    "Cannot enter %s: already have position", market_id
                )
                return None

            if self.bankroll < self.MIN_POSITION_SIZE:
                logger.debug(
                    "Cannot enter %s: insufficient bankroll ($%.2f)",
                    market_id, self.bankroll,
                )
                return None

            # F-022: Double-check available bankroll under lock
            available_for_trade = min(self.max_per_market, self.bankroll)
            if available_for_trade < self.MIN_POSITION_SIZE:
                logger.debug(
                    "Cannot enter %s: available $%.2f < min $%.2f",
                    market_id, available_for_trade, self.MIN_POSITION_SIZE,
                )
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

            # P0-2: Track O/U entries per event
            if not market_type:
                market_type = self._detect_market_type(market_question)
            if market_type == "ou" and event_id:
                self._event_ou_entries[event_id] = market_id

            logger.info(
                "[POSITION ENTRY] %s | Side: %s @ %.2f | "
                "Size: $%.2f (%.2f shares) | "
                "Bankroll: $%.2f | Total Invested: $%.2f",
                market_question, side, price,
                size_usd, shares,
                self.bankroll, self._total_invested,
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
            self._total_invested -= position.size_usd  # F-022

            # Remove position
            del self._positions[market_id]

            result = "WIN" if pnl > 0 else "LOSS"
            logger.info(
                "[POSITION SETTLED] %s | %s: %s vs %s | "
                "P&L: $%+.2f | Bankroll: $%.2f | "
                "Total Invested: $%.2f",
                position.market_question, result,
                position.side, winner,
                pnl, self.bankroll, self._total_invested,
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
            "max_concurrent_positions": self._max_concurrent_positions,
            "max_exposure_ratio": self._max_exposure_ratio,
            "event_ou_entries": self._event_ou_entries,
            "positions": {
                mid: pos.to_dict() for mid, pos in self._positions.items()
            },
        }
        # Atomic write: write to temp file, then rename
        tmp_path = path.with_suffix(".tmp")
        try:
            tmp_path.write_text(json.dumps(state, indent=2))
            tmp_path.replace(path)  # Atomic on POSIX
            logger.info("Saved position state to %s", path)
        except Exception as e:
            logger.error("Failed to save position state: %s", e)
            # Clean up temp file if rename failed
            if tmp_path.exists():
                tmp_path.unlink()

    def load_state(self, path: Path) -> None:
        """Load state from JSON file with integrity verification."""
        if not path.exists():
            logger.info("No state file at %s, starting fresh", path)
            return

        try:
            content = path.read_text().strip()
            if not content:
                logger.warning("State file %s is empty, starting fresh", path)
                return

            state = json.loads(content)

            # Integrity check: must have required keys
            if "bankroll" not in state or "positions" not in state:
                logger.warning(
                    "State file %s missing required keys, starting fresh",
                    path,
                )
                return

            self.bankroll = state.get("bankroll", self.bankroll)
            self._initial_bankroll = state.get(
                "initial_bankroll", self._initial_bankroll
            )
            self.max_per_market = state.get(
                "max_per_market", self.max_per_market
            )
            self._total_invested = state.get("total_invested", 0.0)
            self._cumulative_pnl = state.get("cumulative_pnl", 0.0)
            self._total_settled = state.get("total_settled", 0)
            self._wins = state.get("wins", 0)
            self._losses = state.get("losses", 0)
            self._max_concurrent_positions = state.get(
                "max_concurrent_positions", 0
            )
            self._max_exposure_ratio = state.get("max_exposure_ratio", 0.0)
            self._event_ou_entries = state.get("event_ou_entries", {})
            self._positions = {
                mid: Position.from_dict(pos_data)
                for mid, pos_data in state.get("positions", {}).items()
            }
            logger.info(
                "Loaded state: bankroll=$%.2f, "
                "total_invested=$%.2f, "
                "%d active positions",
                self.bankroll,
                self._total_invested,
                self.active_position_count,
            )
        except json.JSONDecodeError as e:
            logger.error("Corrupt state file %s: %s, starting fresh", path, e)
        except Exception as e:
            logger.error("Failed to load state: %s", e)

    def sync_from_paper_trades(self, data_dir: Path) -> None:
        """Sync positions from existing paper_trades JSONL files.

        This prevents duplicate entries when starting fresh without state file.
        Loads all 'open' trades from paper_trades/YYYY-MM-DD.jsonl.
        Excludes market_stats_*.jsonl and paired_*.jsonl files.
        """
        if not data_dir.exists():
            return

        loaded_count = 0
        total_invested = 0.0
        for jsonl_file in data_dir.glob("*.jsonl"):
            # Skip non-trade files (market stats, paired entries)
            fname = jsonl_file.name
            if fname.startswith("market_stats_") or fname.startswith(
                "paired_"
            ):
                continue
            try:
                with open(jsonl_file) as f:
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
                            market_question=trade.get(
                                "market_question", ""
                            ),
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
                logger.warning("Failed to sync from %s: %s", jsonl_file, e)

        if loaded_count > 0:
            # Deduct invested amount from bankroll
            self.bankroll -= total_invested
            logger.info(
                "Synced %d positions from paper_trades files, "
                "deducted $%.2f from bankroll, "
                "remaining bankroll: $%.2f",
                loaded_count, total_invested, self.bankroll,
            )

    def get_stats_summary(self) -> dict:
        """Get summary statistics."""
        win_rate = (
            self._wins / self._total_settled
            if self._total_settled > 0
            else 0.0
        )
        return {
            "bankroll": self.bankroll,
            "initial_bankroll": self._initial_bankroll,
            "total_invested": self._total_invested,
            "active_positions": self.active_position_count,
            "cumulative_pnl": self._cumulative_pnl,
            "total_settled": self._total_settled,
            "wins": self._wins,
            "losses": self._losses,
            "win_rate": win_rate,
        }
