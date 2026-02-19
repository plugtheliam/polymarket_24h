"""F-030: Sports Live Executor TDD tests.

Kent Beck TDD — Red phase first.
SportExecutor: ClobClient를 통한 단일 사이드 오더 제출.
"""

import logging
import os
from unittest.mock import MagicMock, patch

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
        """live 모드에서 ClobClient.create_order + post_order 호출."""
        from poly24h.execution.sport_executor import SportExecutor

        mock_client = MagicMock()
        mock_client.create_order.return_value = {"id": "signed_order_123"}
        mock_client.post_order.return_value = {
            "orderID": "order_abc",
            "status": "LIVE",
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
