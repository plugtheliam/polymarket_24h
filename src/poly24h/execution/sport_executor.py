"""F-030/F-031: Sports Live Executor — production-ready CLOB order submission.

F-030: 기본 단일 사이드 오더 제출.
F-031: 폴링 확인, 취소, 재시도, 슬리피지, 킬스위치, 타임아웃.

절대 크래시하지 않는다. 모든 에러를 graceful하게 처리.
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from poly24h.execution.kill_switch import KillSwitch

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType

logger = logging.getLogger(__name__)

# Statuses that indicate the order is done (filled)
_FILLED_STATUSES = {"MATCHED", "FILLED"}
# Statuses that indicate the order was cancelled
_CANCELLED_STATUSES = {"CANCELLED", "CANCELED"}


class SportExecutor:
    """Execute single-side sport orders via CLOB.

    dry_run=True: 시뮬레이션 (CLOB 미호출).
    dry_run=False: ClobClient로 실제 오더 제출 + 폴링 확인.
    """

    POLL_TIMEOUT_SEC = 30.0
    POLL_INTERVAL_SEC = 0.5
    MAX_RETRIES = 2  # Total attempts = 1 + MAX_RETRIES
    RETRY_BACKOFF_SEC = 0.5

    def __init__(
        self,
        dry_run: bool = True,
        clob_client: Optional[ClobClient] = None,
        kill_switch: Optional[KillSwitch] = None,
    ):
        self.dry_run = dry_run
        self._client = clob_client
        self._kill_switch = kill_switch

    @classmethod
    def from_env(
        cls,
        dry_run: bool = True,
        kill_switch: Optional[KillSwitch] = None,
    ) -> SportExecutor:
        """env vars로 ClobClient 초기화 후 SportExecutor 생성."""
        if dry_run:
            return cls(dry_run=True, kill_switch=kill_switch)

        private_key = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
        funder = os.environ.get("POLYMARKET_FUNDER", "")
        api_key = os.environ.get("POLYMARKET_API_KEY", "")
        api_secret = os.environ.get("POLYMARKET_API_SECRET", "")
        api_passphrase = os.environ.get("POLYMARKET_API_PASSPHRASE", "")

        client = ClobClient(
            host="https://clob.polymarket.com",
            chain_id=137,
            key=private_key,
            signature_type=2,  # POLY_PROXY
            funder=funder,
        )
        client.set_api_creds(ApiCreds(
            api_key=api_key,
            api_secret=api_secret,
            api_passphrase=api_passphrase,
        ))

        return cls(dry_run=False, clob_client=client, kill_switch=kill_switch)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
    ) -> dict:
        """Submit a single-side order with retry, polling, and slippage tracking.

        Returns:
            dict with keys: success, order_id, dry_run, error,
            expected_price, fill_price, slippage_pct, size_matched.
            Never raises exceptions.
        """
        if self.dry_run:
            return self._submit_dry_run(token_id, side, price, size)

        # Kill switch check
        if self._kill_switch and self._kill_switch.is_active:
            logger.warning("[LIVE ORDER] Blocked by kill_switch: %s",
                           self._kill_switch.reason)
            return self._error_result("kill_switch_active", price)

        return self._submit_live_with_retry(token_id, side, price, size)

    # ------------------------------------------------------------------
    # Dry run
    # ------------------------------------------------------------------

    def _submit_dry_run(
        self, token_id: str, side: str, price: float, size: float,
    ) -> dict:
        """Dry-run simulation — no CLOB calls."""
        logger.info(
            "[DRY RUN] Would submit: %s %s %.1f shares @ $%.4f",
            side, token_id[:12], size, price,
        )
        return {
            "success": True,
            "order_id": None,
            "dry_run": True,
            "error": None,
        }

    # ------------------------------------------------------------------
    # Live submission with retry
    # ------------------------------------------------------------------

    def _submit_live_with_retry(
        self, token_id: str, side: str, price: float, size: float,
    ) -> dict:
        """Submit with retry logic: MAX_RETRIES attempts with backoff."""
        last_error = ""

        for attempt in range(1 + self.MAX_RETRIES):
            if attempt > 0:
                time.sleep(self.RETRY_BACKOFF_SEC * attempt)
                logger.info("[LIVE ORDER] Retry %d/%d", attempt, self.MAX_RETRIES)

            result = self._submit_live(token_id, side, price, size)

            if result["success"]:
                return result

            last_error = result.get("error", "unknown")
            logger.warning("[LIVE ORDER] Attempt %d failed: %s", attempt + 1, last_error)

        return self._error_result(f"all_retries_exhausted: {last_error}", price)

    def _submit_live(
        self, token_id: str, side: str, price: float, size: float,
    ) -> dict:
        """Single live order attempt: submit → poll → report slippage."""
        try:
            logger.info(
                "[LIVE ORDER] Submitting: %s %.1f shares @ $%.4f | token=%s",
                side, size, price, token_id[:16],
            )

            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=side,
            )

            signed_order = self._client.create_order(order_args)
            response = self._client.post_order(signed_order, OrderType.GTC)

            # Response validation
            if not isinstance(response, dict):
                return self._error_result(
                    f"invalid_response_type: {type(response).__name__}", price,
                )

            order_id = response.get("orderID") or response.get("order_id", "")
            if not order_id:
                return self._error_result("no_order_id_in_response", price)

            logger.info(
                "[LIVE ORDER] Submitted: order_id=%s | expected=$%.4f",
                order_id, price,
            )

            # Poll for fill confirmation
            poll_result = self._poll_order_status(order_id)

            if poll_result["status"] in _FILLED_STATUSES:
                fill_price = self._extract_fill_price(poll_result, price)
                size_matched = float(poll_result.get("size_matched", 0))
                slippage_pct = abs(fill_price - price) / price * 100 if price > 0 else 0.0

                if slippage_pct > 2.0:
                    logger.warning(
                        "[LIVE ORDER] HIGH SLIPPAGE: expected=$%.4f fill=$%.4f slip=%.1f%%",
                        price, fill_price, slippage_pct,
                    )

                return {
                    "success": True,
                    "order_id": order_id,
                    "dry_run": False,
                    "error": None,
                    "expected_price": price,
                    "fill_price": fill_price,
                    "slippage_pct": slippage_pct,
                    "size_matched": size_matched,
                }

            # Order timed out or was cancelled
            return {
                "success": False,
                "order_id": order_id,
                "dry_run": False,
                "error": f"order_{poll_result['status'].lower()}",
                "expected_price": price,
                "fill_price": None,
                "slippage_pct": None,
                "size_matched": float(poll_result.get("size_matched", 0)),
            }

        except Exception as exc:
            logger.error(
                "[LIVE ORDER] Failed: %s | token=%s price=$%.4f size=%.1f",
                exc, token_id[:16], price, size,
            )
            return self._error_result(str(exc), price)

    # ------------------------------------------------------------------
    # Order polling
    # ------------------------------------------------------------------

    def _poll_order_status(
        self,
        order_id: str,
        timeout_sec: float | None = None,
        poll_interval: float | None = None,
    ) -> dict:
        """Poll get_order() until filled, cancelled, or timeout.

        Returns dict with at least: status, size_matched.
        On timeout, attempts to cancel and returns status=TIMEOUT.
        """
        timeout = timeout_sec if timeout_sec is not None else self.POLL_TIMEOUT_SEC
        interval = poll_interval if poll_interval is not None else self.POLL_INTERVAL_SEC
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            try:
                order_data = self._client.get_order(order_id)
                status = order_data.get("status", "UNKNOWN")

                if status in _FILLED_STATUSES:
                    return order_data

                if status in _CANCELLED_STATUSES:
                    return order_data

            except Exception as exc:
                logger.warning("[POLL] get_order error: %s", exc)

            time.sleep(interval)

        # Timeout — attempt cancel
        logger.warning("[POLL] Order %s timed out after %.1fs, cancelling", order_id, timeout)
        self._cancel_order(order_id)

        return {"status": "TIMEOUT", "size_matched": "0", "order_id": order_id}

    # ------------------------------------------------------------------
    # Order cancellation
    # ------------------------------------------------------------------

    def _cancel_order(self, order_id: str) -> bool:
        """Cancel a pending GTC order. Retries up to 2 times."""
        for attempt in range(2):
            try:
                self._client.cancel(order_ids=[order_id])
                logger.info("[CANCEL] Order %s cancelled", order_id)
                return True
            except Exception as exc:
                logger.warning("[CANCEL] Attempt %d failed: %s", attempt + 1, exc)
                if attempt < 1:
                    time.sleep(0.5)

        logger.error("[CANCEL] Failed to cancel order %s after 2 attempts", order_id)
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_fill_price(poll_result: dict, expected_price: float) -> float:
        """Extract average fill price from poll result.

        Tries associate_trades first, falls back to order price, then expected.
        """
        trades = poll_result.get("associate_trades") or []
        if trades:
            total_cost = sum(float(t.get("price", 0)) * float(t.get("size", 0)) for t in trades)
            total_size = sum(float(t.get("size", 0)) for t in trades)
            if total_size > 0:
                return total_cost / total_size

        # Fallback to order-level price
        order_price = poll_result.get("price")
        if order_price:
            return float(order_price)

        return expected_price

    @staticmethod
    def _error_result(error: str, expected_price: float) -> dict:
        """Build a standardized error result dict."""
        return {
            "success": False,
            "order_id": None,
            "dry_run": False,
            "error": error,
            "expected_price": expected_price,
            "fill_price": None,
            "slippage_pct": None,
            "size_matched": 0,
        }
