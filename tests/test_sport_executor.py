"""F-030/F-031: Sports Live Executor TDD tests.

Kent Beck TDD — Red phase first.
F-030: ClobClient를 통한 단일 사이드 오더 제출.
F-031: 폴링, 취소, 재시도, 슬리피지, 킬스위치, 타임아웃.
"""

import logging
import os
import time
from unittest.mock import MagicMock, call, patch

import pytest


class TestSportExecutorDryRun:
    """R1: dry_run 모드에서 ClobClient 미호출."""

    def test_dry_run_skips_clob(self):
        """dry_run=True 시 submit_order가 CLOB 호출 없이 성공 반환."""
        from poly24h.execution.sport_executor import SportExecutor

        executor = SportExecutor(dry_run=True)
        result = executor.submit_order(
            token_id="token123",
            side="BUY",
            price=0.45,
            size=100.0,
        )
        # dry_run returns a simulated success
        assert result is not None
        assert result["success"] is True
        assert result["dry_run"] is True


class TestSportExecutorLive:
    """R1: live 모드에서 ClobClient 호출."""

    def test_submit_order_calls_clob(self):
        """live 모드에서 ClobClient.create_order + post_order + get_order 호출."""
        from poly24h.execution.sport_executor import SportExecutor

        mock_client = MagicMock()
        mock_client.create_order.return_value = {"id": "signed_order_123"}
        mock_client.post_order.return_value = {
            "orderID": "order_abc",
            "status": "LIVE",
        }
        # F-031: Poll returns MATCHED immediately
        mock_client.get_order.return_value = {
            "status": "MATCHED",
            "size_matched": "100.0",
            "price": "0.45",
        }

        executor = SportExecutor(dry_run=False, clob_client=mock_client)
        result = executor.submit_order(
            token_id="token123",
            side="BUY",
            price=0.45,
            size=100.0,
        )

        assert result is not None
        assert result["success"] is True
        assert result["order_id"] == "order_abc"
        mock_client.create_order.assert_called_once()
        mock_client.post_order.assert_called_once()
        mock_client.get_order.assert_called()

    def test_failed_order_returns_error(self):
        """CLOB 에러 시 success=False 반환, 크래시 없음."""
        from poly24h.execution.sport_executor import SportExecutor

        mock_client = MagicMock()
        mock_client.create_order.side_effect = Exception("CLOB API timeout")

        executor = SportExecutor(dry_run=False, clob_client=mock_client)
        result = executor.submit_order(
            token_id="token123",
            side="BUY",
            price=0.45,
            size=100.0,
        )

        assert result is not None
        assert result["success"] is False
        assert "CLOB API timeout" in result["error"]


class TestSlippageLogging:
    """R3: 슬리피지 로깅."""

    def test_slippage_logged(self, caplog):
        """오더 제출 시 슬리피지 관련 로그 기록."""
        from poly24h.execution.sport_executor import SportExecutor

        mock_client = MagicMock()
        mock_client.create_order.return_value = {"id": "signed_order"}
        mock_client.post_order.return_value = {
            "orderID": "order_xyz",
            "status": "MATCHED",
        }
        # F-031: Poll returns MATCHED immediately
        mock_client.get_order.return_value = {
            "status": "MATCHED",
            "size_matched": "100.0",
            "price": "0.45",
        }

        executor = SportExecutor(dry_run=False, clob_client=mock_client)

        with caplog.at_level(logging.INFO, logger="poly24h.execution.sport_executor"):
            executor.submit_order(
                token_id="token123",
                side="BUY",
                price=0.45,
                size=100.0,
            )

        # Should log the order submission with price info
        assert any("LIVE ORDER" in r.message for r in caplog.records)


class TestSportExecutorInit:
    """R1: ClobClient env var 초기화."""

    def test_create_from_env(self):
        """env vars로 SportExecutor.from_env() 생성."""
        from poly24h.execution.sport_executor import SportExecutor

        with patch.dict(os.environ, {
            "POLYMARKET_PRIVATE_KEY": "0x" + "ab" * 32,
            "POLYMARKET_API_KEY": "test-key",
            "POLYMARKET_API_SECRET": "test-secret",
            "POLYMARKET_API_PASSPHRASE": "test-pass",
            "POLYMARKET_FUNDER": "0x" + "cd" * 20,
        }):
            with patch("poly24h.execution.sport_executor.ClobClient") as MockClob:
                mock_instance = MagicMock()
                MockClob.return_value = mock_instance

                executor = SportExecutor.from_env(dry_run=False)

                assert executor is not None
                MockClob.assert_called_once()
                mock_instance.set_api_creds.assert_called_once()


# =====================================================================
# F-031: Production-Ready Executor Hardening Tests
# =====================================================================


class TestOrderPolling:
    """F-031: Order fill confirmation via polling."""

    def test_poll_order_filled(self):
        """get_order() 폴링 → FILLED 상태 반환, size_matched 포함."""
        from poly24h.execution.sport_executor import SportExecutor

        mock_client = MagicMock()
        # First call: OPEN, second call: MATCHED (filled)
        mock_client.get_order.side_effect = [
            {"status": "LIVE", "size_matched": "0", "price": "0.45"},
            {"status": "MATCHED", "size_matched": "100.0", "price": "0.45",
             "associate_trades": [{"price": "0.46", "size": "100.0"}]},
        ]

        executor = SportExecutor(dry_run=False, clob_client=mock_client)
        result = executor._poll_order_status("order_abc", timeout_sec=5.0, poll_interval=0.01)

        assert result["status"] == "MATCHED"
        assert float(result["size_matched"]) == 100.0
        assert mock_client.get_order.call_count == 2

    def test_poll_order_timeout_cancels(self):
        """폴링 타임아웃 시 cancel 호출, status=TIMEOUT 반환."""
        from poly24h.execution.sport_executor import SportExecutor

        mock_client = MagicMock()
        # Always returns LIVE (never fills)
        mock_client.get_order.return_value = {
            "status": "LIVE", "size_matched": "0", "price": "0.45",
        }
        mock_client.cancel.return_value = {"canceled": ["order_abc"]}

        executor = SportExecutor(dry_run=False, clob_client=mock_client)
        result = executor._poll_order_status("order_abc", timeout_sec=0.05, poll_interval=0.01)

        assert result["status"] == "TIMEOUT"
        # Should have attempted cancel
        mock_client.cancel.assert_called()


class TestRetryLogic:
    """F-031: Retry with backoff on transient failures."""

    def test_retry_on_failure(self):
        """첫 시도 실패 → 재시도 성공."""
        from poly24h.execution.sport_executor import SportExecutor

        mock_client = MagicMock()
        # First create_order fails, second succeeds
        mock_client.create_order.side_effect = [
            Exception("Connection reset"),
            {"id": "signed_order_retry"},
        ]
        mock_client.post_order.return_value = {
            "orderID": "order_retry_ok",
            "status": "LIVE",
        }
        # Polling returns filled immediately
        mock_client.get_order.return_value = {
            "status": "MATCHED", "size_matched": "50.0", "price": "0.45",
        }

        executor = SportExecutor(dry_run=False, clob_client=mock_client)
        result = executor.submit_order(
            token_id="token123", side="BUY", price=0.45, size=50.0,
        )

        assert result["success"] is True
        assert result["order_id"] == "order_retry_ok"
        # create_order was called twice (1 fail + 1 success)
        assert mock_client.create_order.call_count == 2


class TestKillSwitch:
    """F-031: Kill switch integration blocks orders."""

    def test_kill_switch_blocks_order(self):
        """킬 스위치 활성 시 오더 미제출, success=False."""
        from poly24h.execution.kill_switch import KillSwitch
        from poly24h.execution.sport_executor import SportExecutor

        mock_client = MagicMock()
        kill_switch = KillSwitch(kill_file="data/TEST_KILL_SWITCH_NONEXISTENT")
        kill_switch.activate("Test kill")

        executor = SportExecutor(
            dry_run=False, clob_client=mock_client, kill_switch=kill_switch,
        )
        result = executor.submit_order(
            token_id="token123", side="BUY", price=0.45, size=100.0,
        )

        assert result["success"] is False
        assert "kill_switch" in result["error"]
        # ClobClient should NOT have been called
        mock_client.create_order.assert_not_called()
        mock_client.post_order.assert_not_called()


class TestSlippageTracking:
    """F-031: Slippage tracking in results."""

    def test_slippage_calculated(self):
        """기대가격 vs 체결가격 차이가 결과에 포함."""
        from poly24h.execution.sport_executor import SportExecutor

        mock_client = MagicMock()
        mock_client.create_order.return_value = {"id": "signed"}
        mock_client.post_order.return_value = {"orderID": "order_slip", "status": "LIVE"}
        # Polling: filled at 0.47 (expected 0.45 → 2c slippage)
        mock_client.get_order.return_value = {
            "status": "MATCHED",
            "size_matched": "100.0",
            "price": "0.45",
            "associate_trades": [{"price": "0.47", "size": "100.0"}],
        }

        executor = SportExecutor(dry_run=False, clob_client=mock_client)
        result = executor.submit_order(
            token_id="token123", side="BUY", price=0.45, size=100.0,
        )

        assert result["success"] is True
        assert "expected_price" in result
        assert "fill_price" in result
        assert "slippage_pct" in result
        assert result["expected_price"] == 0.45
        # Fill price from associate_trades
        assert abs(result["fill_price"] - 0.47) < 0.001
        # Slippage = (0.47 - 0.45) / 0.45 ≈ 4.4%
        assert result["slippage_pct"] > 0


class TestResponseValidation:
    """F-031: Handle unexpected CLOB responses gracefully."""

    def test_response_validation_non_dict(self):
        """non-dict 응답도 crash 없이 처리."""
        from poly24h.execution.sport_executor import SportExecutor

        mock_client = MagicMock()
        mock_client.create_order.return_value = {"id": "signed"}
        # post_order returns a string instead of dict (malformed)
        mock_client.post_order.return_value = "unexpected_string_response"

        executor = SportExecutor(dry_run=False, clob_client=mock_client)
        result = executor.submit_order(
            token_id="token123", side="BUY", price=0.45, size=100.0,
        )

        # Should not crash, should return error
        assert result is not None
        assert result["success"] is False
        assert "error" in result
