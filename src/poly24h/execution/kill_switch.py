"""Kill switch — emergency stop mechanism for live trading.

Provides multiple layers of emergency shutdown:
1. Signal-based: SIGINT/SIGTERM → graceful shutdown
2. File-based: Touch a "kill" file → bot stops at next cycle
3. Loss-based: Daily loss limit exceeded → auto-stop
4. Manual: Call kill_switch.activate() programmatically

Phase 4: Integrated into execution pipeline.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class KillSwitch:
    """Emergency stop mechanism.

    Args:
        kill_file: Path to kill file. If this file exists, bot stops.
        max_daily_loss: Maximum daily loss before auto-kill (USD).
    """

    def __init__(
        self,
        kill_file: str = "data/KILL_SWITCH",
        max_daily_loss: float = 500.0,
    ):
        self.kill_file = Path(kill_file)
        self.max_daily_loss = max_daily_loss
        self._activated = False
        self._reason: str = ""
        self._daily_loss: float = 0.0
        self._activation_time: datetime | None = None

    @property
    def is_active(self) -> bool:
        """Check if kill switch is activated (any trigger)."""
        if self._activated:
            return True

        # Check file-based kill
        if self.kill_file.exists():
            self._activated = True
            self._reason = f"Kill file detected: {self.kill_file}"
            self._activation_time = datetime.now(tz=timezone.utc)
            logger.critical("🛑 KILL SWITCH: %s", self._reason)
            return True

        return False

    @property
    def reason(self) -> str:
        """Reason for activation."""
        return self._reason

    @property
    def activation_time(self) -> datetime | None:
        return self._activation_time

    def activate(self, reason: str = "Manual activation") -> None:
        """Programmatically activate kill switch.

        Args:
            reason: Human-readable reason for activation.
        """
        self._activated = True
        self._reason = reason
        self._activation_time = datetime.now(tz=timezone.utc)
        logger.critical("🛑 KILL SWITCH ACTIVATED: %s", reason)

        # Also create kill file for persistence across restarts
        try:
            self.kill_file.parent.mkdir(parents=True, exist_ok=True)
            self.kill_file.write_text(
                f"Activated: {self._activation_time.isoformat()}\n"
                f"Reason: {reason}\n"
            )
        except OSError:
            pass

    def deactivate(self) -> None:
        """Reset kill switch (manual override).

        Use with caution — only after resolving the issue.
        """
        self._activated = False
        self._reason = ""
        self._activation_time = None

        # Remove kill file if exists
        try:
            if self.kill_file.exists():
                self.kill_file.unlink()
        except OSError:
            pass

        logger.info("Kill switch deactivated")

    def record_loss(self, amount: float) -> bool:
        """Record a trading loss.

        Args:
            amount: Loss amount in USD (positive number).

        Returns:
            True if kill switch was triggered by this loss.
        """
        if amount > 0:
            self._daily_loss += amount

        if self._daily_loss >= self.max_daily_loss:
            self.activate(
                f"Daily loss limit exceeded: ${self._daily_loss:.2f} >= ${self.max_daily_loss:.2f}"
            )
            return True

        return False

    def reset_daily(self) -> None:
        """Reset daily loss counter (call at midnight UTC)."""
        self._daily_loss = 0.0

    def status(self) -> dict:
        """Get kill switch status."""
        return {
            "active": self.is_active,
            "reason": self._reason,
            "activation_time": (
                self._activation_time.isoformat() if self._activation_time else None
            ),
            "daily_loss": self._daily_loss,
            "max_daily_loss": self.max_daily_loss,
            "kill_file": str(self.kill_file),
            "kill_file_exists": self.kill_file.exists(),
        }
