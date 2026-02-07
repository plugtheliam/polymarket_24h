"""Tests for preflight check (Phase 4)."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from poly24h.analysis.preflight import (
    CheckResult,
    PreflightChecker,
    PreflightReport,
    format_preflight_report,
)


# ===========================================================================
# CheckResult / PreflightReport Tests
# ===========================================================================


class TestCheckResult:
    def test_fields(self):
        cr = CheckResult(name="test", passed=True, message="OK")
        assert cr.name == "test"
        assert cr.passed is True
        assert cr.critical is True  # default


class TestPreflightReport:
    def test_all_passed(self):
        report = PreflightReport(checks=[
            CheckResult("a", True, "ok"),
            CheckResult("b", True, "ok"),
        ])
        assert report.all_passed

    def test_critical_failure(self):
        report = PreflightReport(checks=[
            CheckResult("a", True, "ok"),
            CheckResult("b", False, "fail", critical=True),
        ])
        assert not report.all_passed
        assert len(report.critical_failures) == 1

    def test_warning_not_critical(self):
        report = PreflightReport(checks=[
            CheckResult("a", True, "ok"),
            CheckResult("b", False, "warn", critical=False),
        ])
        assert report.all_passed
        assert len(report.warnings) == 1

    def test_empty_report(self):
        report = PreflightReport()
        assert report.all_passed
        assert len(report.critical_failures) == 0


# ===========================================================================
# PreflightChecker Tests (sync checks only)
# ===========================================================================


class TestPreflightCheckerSync:
    def test_python_version_passes(self):
        checker = PreflightChecker()
        checker._check_python_version()
        assert len(checker._results) == 1
        assert checker._results[0].passed  # We're running >= 3.10

    def test_data_directory_creation(self, tmp_path):
        checker = PreflightChecker(base_dir=str(tmp_path))
        # data dirs don't exist yet
        checker._check_data_directories()
        # Should have created them
        results = [r for r in checker._results if "Directory" in r.name]
        assert all(r.passed for r in results)

    def test_env_file_missing(self, tmp_path):
        checker = PreflightChecker(base_dir=str(tmp_path))
        checker._check_env_file()
        env_check = [r for r in checker._results if ".env" in r.name]
        assert len(env_check) == 1
        # .env doesn't exist in tmp_path
        assert not env_check[0].passed

    def test_env_file_exists(self, tmp_path):
        (tmp_path / ".env").write_text("TEST=1\n")
        checker = PreflightChecker(base_dir=str(tmp_path))
        checker._check_env_file()
        env_check = [r for r in checker._results if ".env" in r.name]
        assert env_check[0].passed


class TestPreflightCheckerEnvKeys:
    def test_telegram_keys_present(self):
        checker = PreflightChecker()
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test_token_12345",
            "TELEGRAM_CHAT_ID": "-123456789",
            "POLY24H_DRY_RUN": "true",
        }):
            checker._check_env_keys()
        telegram_checks = [r for r in checker._results if "TELEGRAM" in r.name]
        assert all(r.passed for r in telegram_checks)

    def test_telegram_keys_missing(self):
        checker = PreflightChecker()
        with patch.dict(os.environ, {}, clear=True):
            checker._check_env_keys()
        telegram_checks = [r for r in checker._results if "TELEGRAM" in r.name]
        assert not all(r.passed for r in telegram_checks)


class TestPreflightCheckerDryRun:
    def test_dry_run_mode(self):
        checker = PreflightChecker()
        with patch.dict(os.environ, {"POLY24H_DRY_RUN": "true"}):
            checker._check_dry_run_mode()
        mode_check = [r for r in checker._results if "Mode" in r.name]
        assert len(mode_check) == 1
        assert "DRY RUN" in mode_check[0].message

    def test_live_mode(self):
        checker = PreflightChecker()
        with patch.dict(os.environ, {"POLY24H_DRY_RUN": "false"}):
            checker._check_dry_run_mode()
        mode_check = [r for r in checker._results if "Mode" in r.name]
        assert "LIVE" in mode_check[0].message


# ===========================================================================
# Full Async Run Test
# ===========================================================================


class TestPreflightFullRun:
    @pytest.mark.asyncio
    async def test_run_all_no_crash(self, tmp_path):
        """Full preflight run should not crash regardless of environment."""
        checker = PreflightChecker(base_dir=str(tmp_path))
        report = await checker.run_all()
        assert isinstance(report, PreflightReport)
        assert len(report.checks) > 0


# ===========================================================================
# Report Formatting
# ===========================================================================


class TestFormatPreflightReport:
    def test_format_all_passed(self):
        report = PreflightReport(checks=[
            CheckResult("Test 1", True, "OK"),
            CheckResult("Test 2", True, "Good"),
        ])
        text = format_preflight_report(report)
        assert "Preflight Check" in text
        assert "All critical checks passed" in text

    def test_format_with_failures(self):
        report = PreflightReport(checks=[
            CheckResult("Test 1", True, "OK"),
            CheckResult("Test 2", False, "FAIL", critical=True),
        ])
        text = format_preflight_report(report)
        assert "FAILED" in text

    def test_format_with_warnings(self):
        report = PreflightReport(checks=[
            CheckResult("Test 1", True, "OK"),
            CheckResult("Test 2", False, "Warn", critical=False),
        ])
        text = format_preflight_report(report)
        assert "warning" in text
