"""Preflight check — validates environment before going live.

Checks:
1. .env file presence and required keys
2. Telegram bot connectivity
3. Gamma API reachability
4. CLOB API reachability
5. Data directory writability
6. Risk parameter sanity
7. Wallet balance (placeholder for Phase 5)

Usage:
    python -m poly24h --mode preflight
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    """Single preflight check result."""

    name: str
    passed: bool
    message: str
    critical: bool = True  # If False, just a warning


@dataclass
class PreflightReport:
    """Complete preflight report."""

    checks: list[CheckResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks if c.critical)

    @property
    def critical_failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed and c.critical]

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed and not c.critical]


class PreflightChecker:
    """Runs all preflight checks."""

    def __init__(self, base_dir: str = "."):
        self.base_dir = Path(base_dir)
        self._results: list[CheckResult] = []

    async def run_all(self) -> PreflightReport:
        """Run all preflight checks."""
        self._results = []

        # Sync checks
        self._check_python_version()
        self._check_env_file()
        self._check_env_keys()
        self._check_data_directories()
        self._check_risk_params()
        self._check_dry_run_mode()

        # Async checks
        await self._check_telegram()
        await self._check_gamma_api()
        await self._check_clob_api()

        return PreflightReport(checks=list(self._results))

    def _add(self, name: str, passed: bool, message: str, critical: bool = True) -> None:
        self._results.append(CheckResult(name, passed, message, critical))

    # ------------------------------------------------------------------
    # Sync checks
    # ------------------------------------------------------------------

    def _check_python_version(self) -> None:
        """Check Python version >= 3.10."""
        ver = sys.version_info
        if ver >= (3, 10):
            self._add("Python version", True, f"Python {ver.major}.{ver.minor}.{ver.micro}")
        else:
            self._add("Python version", False, f"Python {ver.major}.{ver.minor} — need >= 3.10")

    def _check_env_file(self) -> None:
        """Check .env file exists."""
        env_path = self.base_dir / ".env"
        if env_path.exists():
            self._add(".env file", True, "Found")
        else:
            self._add(".env file", False, "Not found — create .env with required keys")

    def _check_env_keys(self) -> None:
        """Check required environment variables."""
        required_keys = [
            ("TELEGRAM_BOT_TOKEN", True),
            ("TELEGRAM_CHAT_ID", True),
        ]
        live_keys = [
            ("POLY_API_KEY", False),
            ("POLY_API_SECRET", False),
            ("POLY_API_PASSPHRASE", False),
            ("POLY_PRIVATE_KEY", False),
        ]

        for key, critical in required_keys:
            val = os.environ.get(key)
            if val:
                masked = val[:4] + "..." + val[-4:] if len(val) > 8 else "***"
                self._add(f"ENV: {key}", True, f"Set ({masked})", critical)
            else:
                self._add(f"ENV: {key}", False, "Not set", critical)

        # Live trading keys — warn if missing but not critical for dry-run
        dry_run = os.environ.get("POLY24H_DRY_RUN", "true").lower() not in ("false", "0", "no")
        for key, _ in live_keys:
            val = os.environ.get(key)
            if val:
                self._add(f"ENV: {key}", True, "Set", critical=not dry_run)
            else:
                # Critical only if NOT in dry-run mode
                self._add(
                    f"ENV: {key}", dry_run,
                    "Not set (required for live trading)" if not val else "Set",
                    critical=not dry_run,
                )

    def _check_data_directories(self) -> None:
        """Check data directories exist and are writable."""
        dirs = ["data/paper_trades", "logs"]
        for d in dirs:
            dir_path = self.base_dir / d
            if dir_path.exists() and os.access(dir_path, os.W_OK):
                self._add(f"Directory: {d}", True, "Exists & writable")
            elif dir_path.exists():
                self._add(f"Directory: {d}", False, "Exists but NOT writable")
            else:
                # Try to create
                try:
                    dir_path.mkdir(parents=True, exist_ok=True)
                    self._add(f"Directory: {d}", True, "Created")
                except OSError as e:
                    self._add(f"Directory: {d}", False, f"Cannot create: {e}")

    def _check_risk_params(self) -> None:
        """Check risk parameters are within sane ranges."""
        from poly24h.config import BotConfig

        config = BotConfig.from_env()

        # Check max_position_usd
        if 10 <= config.max_position_usd <= 10000:
            self._add(
                "Risk: max_position_usd", True,
                f"${config.max_position_usd:.0f} (OK)",
            )
        else:
            self._add(
                "Risk: max_position_usd", False,
                f"${config.max_position_usd:.0f} (outside $10-$10,000 range)",
                critical=False,
            )

        if 10 <= config.max_daily_loss_usd <= 5000:
            self._add(
                "Risk: max_daily_loss_usd", True,
                f"${config.max_daily_loss_usd:.0f} (OK)",
            )
        else:
            self._add(
                "Risk: max_daily_loss_usd", False,
                f"${config.max_daily_loss_usd:.0f} (outside $10-$5,000 range)",
                critical=False,
            )

    def _check_dry_run_mode(self) -> None:
        """Check current dry_run setting."""
        dry_run = os.environ.get("POLY24H_DRY_RUN", "true").lower() not in ("false", "0", "no")
        if dry_run:
            self._add("Mode", True, "DRY RUN (safe)", critical=False)
        else:
            self._add(
                "Mode", True,
                "⚠️  LIVE TRADING — real money at risk!",
                critical=False,
            )

    # ------------------------------------------------------------------
    # Async checks
    # ------------------------------------------------------------------

    async def _check_telegram(self) -> None:
        """Check Telegram bot connectivity."""
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            self._add("Telegram bot", False, "No bot token", critical=False)
            return

        try:
            import aiohttp
            url = f"https://api.telegram.org/bot{token}/getMe"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        bot_name = data.get("result", {}).get("username", "unknown")
                        self._add("Telegram bot", True, f"Connected (@{bot_name})")
                    else:
                        self._add("Telegram bot", False, f"HTTP {resp.status}")
        except Exception as e:
            self._add("Telegram bot", False, f"Error: {e}", critical=False)

    async def _check_gamma_api(self) -> None:
        """Check Gamma API reachability."""
        try:
            import aiohttp
            url = "https://gamma-api.polymarket.com/events?limit=1"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        self._add("Gamma API", True, "Reachable")
                    else:
                        self._add("Gamma API", False, f"HTTP {resp.status}")
        except Exception as e:
            self._add("Gamma API", False, f"Error: {e}")

    async def _check_clob_api(self) -> None:
        """Check CLOB API reachability."""
        try:
            import aiohttp
            url = "https://clob.polymarket.com/time"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        self._add("CLOB API", True, "Reachable")
                    else:
                        self._add("CLOB API", False, f"HTTP {resp.status}")
        except Exception as e:
            self._add("CLOB API", False, f"Error: {e}")


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_preflight_report(report: PreflightReport) -> str:
    """Format preflight report for console output."""
    lines = []
    lines.append("=" * 60)
    lines.append("  🔍 poly24h Preflight Check")
    lines.append("=" * 60)

    for check in report.checks:
        icon = "✅" if check.passed else ("⚠️ " if not check.critical else "❌")
        lines.append(f"  {icon} {check.name}: {check.message}")

    lines.append("")
    lines.append("-" * 60)

    if report.all_passed:
        lines.append("  ✅ All critical checks passed!")
    else:
        failures = report.critical_failures
        lines.append(f"  ❌ {len(failures)} critical check(s) FAILED:")
        for f in failures:
            lines.append(f"     • {f.name}: {f.message}")

    warnings = report.warnings
    if warnings:
        lines.append(f"  ⚠️  {len(warnings)} warning(s):")
        for w in warnings:
            lines.append(f"     • {w.name}: {w.message}")

    lines.append("=" * 60)
    return "\n".join(lines)


async def run_preflight() -> PreflightReport:
    """Run all preflight checks and return report."""
    checker = PreflightChecker()
    return await checker.run_all()
