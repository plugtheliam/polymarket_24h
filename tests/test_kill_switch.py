"""Tests for kill switch mechanism (Phase 4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from poly24h.execution.kill_switch import KillSwitch


# ===========================================================================
# KillSwitch Tests
# ===========================================================================


class TestKillSwitchBasic:
    def test_inactive_by_default(self, tmp_path):
        ks = KillSwitch(kill_file=str(tmp_path / "KILL"))
        assert not ks.is_active
        assert ks.reason == ""

    def test_activate_manually(self, tmp_path):
        ks = KillSwitch(kill_file=str(tmp_path / "KILL"))
        ks.activate("Test activation")
        assert ks.is_active
        assert "Test activation" in ks.reason
        assert ks.activation_time is not None

    def test_deactivate(self, tmp_path):
        ks = KillSwitch(kill_file=str(tmp_path / "KILL"))
        ks.activate("Test")
        assert ks.is_active
        ks.deactivate()
        assert not ks.is_active
        assert ks.reason == ""


class TestKillSwitchFile:
    def test_file_triggers_kill(self, tmp_path):
        kill_file = tmp_path / "KILL"
        kill_file.write_text("stop!")
        ks = KillSwitch(kill_file=str(kill_file))
        assert ks.is_active
        assert "Kill file" in ks.reason

    def test_activate_creates_file(self, tmp_path):
        kill_file = tmp_path / "KILL"
        ks = KillSwitch(kill_file=str(kill_file))
        ks.activate("Emergency")
        assert kill_file.exists()
        content = kill_file.read_text()
        assert "Emergency" in content

    def test_deactivate_removes_file(self, tmp_path):
        kill_file = tmp_path / "KILL"
        ks = KillSwitch(kill_file=str(kill_file))
        ks.activate("Test")
        assert kill_file.exists()
        ks.deactivate()
        assert not kill_file.exists()

    def test_no_file_no_kill(self, tmp_path):
        ks = KillSwitch(kill_file=str(tmp_path / "nonexistent"))
        assert not ks.is_active


class TestKillSwitchLoss:
    def test_loss_under_limit(self, tmp_path):
        ks = KillSwitch(kill_file=str(tmp_path / "KILL"), max_daily_loss=500.0)
        triggered = ks.record_loss(100.0)
        assert not triggered
        assert not ks.is_active

    def test_loss_triggers_kill(self, tmp_path):
        ks = KillSwitch(kill_file=str(tmp_path / "KILL"), max_daily_loss=500.0)
        ks.record_loss(300.0)
        triggered = ks.record_loss(200.0)
        assert triggered
        assert ks.is_active
        assert "Daily loss" in ks.reason

    def test_loss_exactly_at_limit(self, tmp_path):
        ks = KillSwitch(kill_file=str(tmp_path / "KILL"), max_daily_loss=500.0)
        triggered = ks.record_loss(500.0)
        assert triggered
        assert ks.is_active

    def test_reset_daily(self, tmp_path):
        ks = KillSwitch(kill_file=str(tmp_path / "KILL"), max_daily_loss=500.0)
        ks.record_loss(400.0)
        ks.reset_daily()
        triggered = ks.record_loss(100.0)
        assert not triggered

    def test_negative_loss_ignored(self, tmp_path):
        ks = KillSwitch(kill_file=str(tmp_path / "KILL"), max_daily_loss=500.0)
        ks.record_loss(-100.0)  # Negative — should be ignored
        assert not ks.is_active


class TestKillSwitchStatus:
    def test_status_dict(self, tmp_path):
        ks = KillSwitch(kill_file=str(tmp_path / "KILL"), max_daily_loss=500.0)
        status = ks.status()
        assert "active" in status
        assert "daily_loss" in status
        assert "kill_file" in status
        assert status["active"] is False
        assert status["daily_loss"] == 0.0

    def test_status_after_activation(self, tmp_path):
        ks = KillSwitch(kill_file=str(tmp_path / "KILL"))
        ks.activate("Testing status")
        status = ks.status()
        assert status["active"] is True
        assert status["reason"] == "Testing status"
        assert status["activation_time"] is not None
