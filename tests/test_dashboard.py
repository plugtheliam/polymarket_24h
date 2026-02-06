"""Tests for DashboardRenderer (F-013).

콘솔 대시보드 렌더링 테스트.
"""

from __future__ import annotations

import pytest

from poly24h.monitoring.dashboard import DashboardRenderer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def renderer():
    return DashboardRenderer()


# ---------------------------------------------------------------------------
# render_cycle tests
# ---------------------------------------------------------------------------


class TestRenderCycle:
    def test_contains_cycle_number(self, renderer):
        output = renderer.render_cycle(
            cycle_num=42,
            markets_scanned=100,
            opps_found=3,
            active_positions=2,
            session_pnl=15.50,
            risk_status="OK",
        )
        assert "42" in output

    def test_contains_markets_scanned(self, renderer):
        output = renderer.render_cycle(
            cycle_num=1,
            markets_scanned=250,
            opps_found=0,
            active_positions=0,
            session_pnl=0.0,
            risk_status="OK",
        )
        assert "250" in output

    def test_contains_opportunities(self, renderer):
        output = renderer.render_cycle(
            cycle_num=1,
            markets_scanned=50,
            opps_found=5,
            active_positions=3,
            session_pnl=25.0,
            risk_status="OK",
        )
        assert "5" in output

    def test_contains_pnl(self, renderer):
        output = renderer.render_cycle(
            cycle_num=1,
            markets_scanned=50,
            opps_found=0,
            active_positions=0,
            session_pnl=-10.50,
            risk_status="OK",
        )
        assert "-10.50" in output or "-10.5" in output

    def test_contains_risk_status(self, renderer):
        output = renderer.render_cycle(
            cycle_num=1,
            markets_scanned=50,
            opps_found=0,
            active_positions=0,
            session_pnl=0.0,
            risk_status="COOLDOWN",
        )
        assert "COOLDOWN" in output

    def test_contains_box_chars(self, renderer):
        """박스 그리기 문자 포함."""
        output = renderer.render_cycle(
            cycle_num=1,
            markets_scanned=10,
            opps_found=0,
            active_positions=0,
            session_pnl=0.0,
            risk_status="OK",
        )
        assert any(c in output for c in "═║╔╗╚╝")

    def test_no_opportunities_message(self, renderer):
        output = renderer.render_cycle(
            cycle_num=1,
            markets_scanned=50,
            opps_found=0,
            active_positions=0,
            session_pnl=0.0,
            risk_status="OK",
        )
        assert "0" in output


# ---------------------------------------------------------------------------
# render_startup tests
# ---------------------------------------------------------------------------


class TestRenderStartup:
    def test_contains_mode(self, renderer):
        output = renderer.render_startup(
            config={"dry_run": True, "scan_interval": 60},
            risk_params={"max_position": 1000, "daily_loss_limit": 500},
        )
        assert "DRY" in output.upper() or "dry" in output.lower()

    def test_live_mode_warning(self, renderer):
        output = renderer.render_startup(
            config={"dry_run": False, "scan_interval": 60},
            risk_params={"max_position": 1000},
        )
        assert "LIVE" in output.upper()

    def test_contains_scan_interval(self, renderer):
        output = renderer.render_startup(
            config={"dry_run": True, "scan_interval": 30},
            risk_params={},
        )
        assert "30" in output

    def test_contains_risk_params(self, renderer):
        output = renderer.render_startup(
            config={"dry_run": True, "scan_interval": 60},
            risk_params={"max_position": 1000, "daily_loss_limit": 500},
        )
        assert "1000" in output
        assert "500" in output

    def test_contains_box_chars(self, renderer):
        output = renderer.render_startup(
            config={"dry_run": True, "scan_interval": 60},
            risk_params={},
        )
        assert any(c in output for c in "═║╔╗╚╝")

    def test_returns_string(self, renderer):
        output = renderer.render_startup(
            config={"dry_run": True, "scan_interval": 60},
            risk_params={},
        )
        assert isinstance(output, str)
        assert len(output) > 0
