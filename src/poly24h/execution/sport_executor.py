"""F-030: Sports Live Executor — single-side CLOB order submission.

스포츠 마켓용 단일 사이드(YES or NO) 오더 제출.
절대 크래시하지 않는다. 모든 에러를 graceful하게 처리.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    pass

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType

logger = logging.getLogger(__name__)


class SportExecutor:
    """Execute single-side sport orders via CLOB.

    dry_run=True: 시뮬레이션 (CLOB 미호출).
    dry_run=False: ClobClient로 실제 오더 제출.
    """

    def __init__(
        self,
        dry_run: bool = True,
        clob_client: Optional[ClobClient] = None,
    ):
        self.dry_run = dry_run
        self._client = clob_client

    @classmethod
    def from_env(cls, dry_run: bool = True) -> SportExecutor:
        """env vars로 ClobClient 초기화 후 SportExecutor 생성."""
        if dry_run:
            return cls(dry_run=True)

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

        return cls(dry_run=False, clob_client=client)

    def submit_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
    ) -> dict:
        """Submit a single-side order.

        Args:
            token_id: CLOB token ID (yes_token_id or no_token_id).
            side: "BUY".
            price: Limit price per share.
            size: Number of shares.

        Returns:
            dict with keys: success, order_id, dry_run, error.
            Never raises exceptions.
        """
        if self.dry_run:
            return self._submit_dry_run(token_id, side, price, size)

        return self._submit_live(token_id, side, price, size)

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

    def _submit_live(
        self, token_id: str, side: str, price: float, size: float,
    ) -> dict:
        """Live order submission via ClobClient."""
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
            result = self._client.post_order(signed_order, OrderType.GTC)

            order_id = result.get("orderID") or result.get("order_id", "")

            logger.info(
                "[LIVE ORDER] Submitted: order_id=%s | expected_price=$%.4f",
                order_id, price,
            )

            return {
                "success": True,
                "order_id": order_id,
                "dry_run": False,
                "error": None,
            }

        except Exception as exc:
            logger.error(
                "[LIVE ORDER] Failed: %s | token=%s price=$%.4f size=%.1f",
                exc, token_id[:16], price, size,
            )
            return {
                "success": False,
                "order_id": None,
                "dry_run": False,
                "error": str(exc),
            }
