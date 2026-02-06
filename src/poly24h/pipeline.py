"""Trading pipeline — scan → risk → build → execute → track.

전체 거래 파이프라인 오케스트레이션.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from poly24h.execution.executor import OrderExecutor, OrderStatus
from poly24h.execution.order_builder import ArbOrderBuilder
from poly24h.models.opportunity import Opportunity
from poly24h.position.portfolio import PortfolioManager
from poly24h.risk.controller import RiskController

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TradeRecord:
    """단일 거래 시도 기록."""

    market_id: str
    market_question: str = ""
    executed: bool = False
    reject_reasons: list[str] = field(default_factory=list)
    yes_price: float = 0.0
    no_price: float = 0.0
    shares: float = 0.0
    total_cost: float = 0.0
    expected_profit: float = 0.0


@dataclass
class CycleSummary:
    """한 사이클 결과 요약."""

    cycle_number: int = 0
    opportunities_found: int = 0
    trades_attempted: int = 0
    trades_executed: int = 0
    trades_rejected: int = 0


@dataclass
class SessionSummary:
    """세션 전체 요약."""

    total_cycles: int = 0
    total_opportunities: int = 0
    total_trades: int = 0
    total_rejected: int = 0
    total_invested: float = 0.0
    total_locked_profit: float = 0.0
    total_realized_pnl: float = 0.0
    active_positions: int = 0

    def __str__(self) -> str:
        lines = [
            "═" * 50,
            "  Session Summary",
            "═" * 50,
            f"  Cycles: {self.total_cycles}",
            f"  Total trades: {self.total_trades}",
            f"  Rejected: {self.total_rejected}",
            f"  Active positions: {self.active_positions}",
            f"  Total invested: ${self.total_invested:.2f}",
            f"  Locked profit: ${self.total_locked_profit:.2f}",
            f"  Realized PnL: ${self.total_realized_pnl:.2f}",
            "═" * 50,
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class TradingPipeline:
    """Orchestrate: risk_check → build_orders → execute → track_position.

    Args:
        dry_run: True면 실행 시뮬레이션만.
        daily_loss_limit: 일일 손실 한도.
        max_per_market: 마켓당 최대 포지션.
        max_total: 전체 최대 포지션.
        max_consecutive_losses: 연속 손실 한도.
        cooldown_seconds: 쿨다운 시간.
    """

    def __init__(
        self,
        dry_run: bool = True,
        daily_loss_limit: float = 500.0,
        max_per_market: float = 1000.0,
        max_total: float = 5000.0,
        max_consecutive_losses: int = 3,
        cooldown_seconds: int = 300,
    ):
        self.dry_run = dry_run
        self.portfolio = PortfolioManager()
        self.risk_controller = RiskController(
            daily_loss_limit=daily_loss_limit,
            max_per_market=max_per_market,
            max_total=max_total,
            max_consecutive_losses=max_consecutive_losses,
            cooldown_seconds=cooldown_seconds,
            dry_run=dry_run,
        )
        self.order_builder = ArbOrderBuilder()
        self.executor = OrderExecutor(dry_run=dry_run)

        self._trade_log: list[TradeRecord] = []
        self._cycle_count: int = 0
        self._total_trades: int = 0
        self._total_rejected: int = 0

    def process_opportunity(self, opp: Opportunity) -> TradeRecord:
        """단일 기회 처리: risk → build → execute → track.

        Returns:
            TradeRecord (절대 예외를 던지지 않음).
        """
        market_id = opp.market.id

        try:
            # 1) 중복 진입 방지
            existing = self.portfolio.get_position(market_id)
            if existing and (existing.yes_shares > 0 or existing.no_shares > 0):
                record = TradeRecord(
                    market_id=market_id,
                    market_question=opp.market.question,
                    executed=False,
                    reject_reasons=["Duplicate: already have position in this market"],
                )
                self._trade_log.append(record)
                self._total_rejected += 1
                logger.info("Skipped %s: duplicate position", market_id)
                return record

            # 2) 리스크 체크
            risk_result = self.risk_controller.check_risk(opp, self.portfolio)
            if not risk_result.approved:
                record = TradeRecord(
                    market_id=market_id,
                    market_question=opp.market.question,
                    executed=False,
                    reject_reasons=risk_result.reasons,
                )
                self._trade_log.append(record)
                self._total_rejected += 1
                return record

            # 3) 주문 빌드
            budget = risk_result.allowed_size
            yes_order, no_order = self.order_builder.build_arb_orders(
                opp, max_position_usd=budget,
            )

            # 4) 실행
            exec_result = self.executor.execute_arb(yes_order, no_order)

            if exec_result.status == OrderStatus.SUCCESS:
                # 5) 포지션 추적
                self.portfolio.add_trade(
                    market_id, "YES", yes_order.size, yes_order.price,
                )
                self.portfolio.add_trade(
                    market_id, "NO", no_order.size, no_order.price,
                )

                expected_profit = yes_order.size * opp.margin
                record = TradeRecord(
                    market_id=market_id,
                    market_question=opp.market.question,
                    executed=True,
                    yes_price=opp.yes_price,
                    no_price=opp.no_price,
                    shares=yes_order.size,
                    total_cost=yes_order.total_cost + no_order.total_cost,
                    expected_profit=expected_profit,
                )
                self._trade_log.append(record)
                self._total_trades += 1

                logger.info(
                    "Executed arb: %s | %.0f shares | cost=$%.2f | exp_profit=$%.2f",
                    market_id, yes_order.size,
                    yes_order.total_cost + no_order.total_cost,
                    expected_profit,
                )
                return record

            else:
                record = TradeRecord(
                    market_id=market_id,
                    market_question=opp.market.question,
                    executed=False,
                    reject_reasons=[f"Execution failed: {exec_result.error}"],
                )
                self._trade_log.append(record)
                self._total_rejected += 1
                return record

        except Exception as exc:
            logger.exception("Error processing opportunity %s", market_id)
            record = TradeRecord(
                market_id=market_id,
                market_question=opp.market.question,
                executed=False,
                reject_reasons=[f"Error: {exc}"],
            )
            self._trade_log.append(record)
            self._total_rejected += 1
            return record

    def process_cycle(self, opportunities: list[Opportunity]) -> CycleSummary:
        """한 사이클의 기회 목록 처리.

        Returns:
            CycleSummary.
        """
        self._cycle_count += 1
        executed = 0
        rejected = 0

        for opp in opportunities:
            record = self.process_opportunity(opp)
            if record.executed:
                executed += 1
            else:
                rejected += 1

        summary = CycleSummary(
            cycle_number=self._cycle_count,
            opportunities_found=len(opportunities),
            trades_attempted=len(opportunities),
            trades_executed=executed,
            trades_rejected=rejected,
        )

        logger.info(
            "Cycle %d: %d found, %d executed, %d rejected",
            summary.cycle_number,
            summary.opportunities_found,
            summary.trades_executed,
            summary.trades_rejected,
        )
        return summary

    def session_summary(self) -> SessionSummary:
        """세션 전체 요약."""
        active = self.portfolio.active_positions()
        return SessionSummary(
            total_cycles=self._cycle_count,
            total_opportunities=len(self._trade_log),
            total_trades=self._total_trades,
            total_rejected=self._total_rejected,
            total_invested=self.portfolio.total_invested,
            total_locked_profit=self.portfolio.total_locked_profit,
            total_realized_pnl=self.portfolio.total_realized_pnl,
            active_positions=len(active),
        )
