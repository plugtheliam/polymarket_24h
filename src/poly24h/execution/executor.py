"""Order executor — submit orders to CLOB (or simulate in dry_run).

절대 크래시하지 않는다. 모든 에러를 graceful하게 처리.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from poly24h.execution.order_builder import Order

logger = logging.getLogger(__name__)


class OrderStatus(Enum):
    """주문 실행 결과 상태."""

    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    TIMEOUT = "timeout"


@dataclass
class ExecutionResult:
    """주문 실행 결과."""

    status: OrderStatus
    yes_filled: bool
    no_filled: bool
    yes_order: Optional[Order]
    no_order: Optional[Order]
    error: Optional[str]


class OrderExecutor:
    """Execute arb order pairs.

    dry_run=True (default): 시뮬레이션 결과 반환.
    dry_run=False: 로그만 남김 (Phase 2 placeholder).
    """

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run

    def execute_arb(
        self,
        yes_order: Optional[Order],
        no_order: Optional[Order],
    ) -> ExecutionResult:
        """YES + NO 주문 실행.

        Args:
            yes_order: YES 매수 주문.
            no_order: NO 매수 주문.

        Returns:
            ExecutionResult (절대 예외를 던지지 않음).
        """
        try:
            # 주문 유효성 확인
            if yes_order is None or no_order is None:
                return ExecutionResult(
                    status=OrderStatus.FAILED,
                    yes_filled=False,
                    no_filled=False,
                    yes_order=yes_order,
                    no_order=no_order,
                    error="Missing order(s): both YES and NO orders required",
                )

            if self.dry_run:
                return self._execute_dry_run(yes_order, no_order)
            else:
                return self._execute_live(yes_order, no_order)

        except Exception as exc:
            logger.exception("Unexpected error during execution")
            return ExecutionResult(
                status=OrderStatus.FAILED,
                yes_filled=False,
                no_filled=False,
                yes_order=yes_order,
                no_order=no_order,
                error=str(exc),
            )

    def _execute_dry_run(
        self, yes_order: Order, no_order: Order,
    ) -> ExecutionResult:
        """시뮬레이션 실행."""
        logger.info(
            "[DRY RUN] Would submit: YES %s shares @ $%.4f, NO %s shares @ $%.4f",
            yes_order.size, yes_order.price,
            no_order.size, no_order.price,
        )
        return ExecutionResult(
            status=OrderStatus.SUCCESS,
            yes_filled=True,
            no_filled=True,
            yes_order=yes_order,
            no_order=no_order,
            error=None,
        )

    def _execute_live(
        self, yes_order: Order, no_order: Order,
    ) -> ExecutionResult:
        """Live 실행 placeholder — 실제 API 호출은 Phase 3."""
        logger.info(
            "LIVE: would submit to CLOB — YES %s @ $%.4f, NO %s @ $%.4f",
            yes_order.size, yes_order.price,
            no_order.size, no_order.price,
        )
        # Placeholder: 성공으로 반환
        return ExecutionResult(
            status=OrderStatus.SUCCESS,
            yes_filled=True,
            no_filled=True,
            yes_order=yes_order,
            no_order=no_order,
            error=None,
        )
