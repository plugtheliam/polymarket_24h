"""Risk controller — 모든 리스크 모듈 통합."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from poly24h.models.opportunity import Opportunity
from poly24h.position.portfolio import PortfolioManager
from poly24h.risk.cooldown import CooldownManager
from poly24h.risk.loss_limiter import DailyLossLimiter
from poly24h.risk.position_limiter import PositionSizeLimiter

logger = logging.getLogger(__name__)


@dataclass
class RiskResult:
    """리스크 체크 결과."""

    approved: bool
    reasons: list[str] = field(default_factory=list)
    allowed_size: float = 0.0


class RiskController:
    """Combine all risk checks into a single gate.

    Args:
        daily_loss_limit: 일일 손실 한도 (USD).
        max_per_market: 마켓당 최대 포지션 (USD).
        max_total: 전체 최대 포지션 (USD).
        max_consecutive_losses: 연속 손실 한도.
        cooldown_seconds: 쿨다운 시간 (초).
        dry_run: True면 체크 실행하되 항상 승인.
    """

    def __init__(
        self,
        daily_loss_limit: float = 500.0,
        max_per_market: float = 1000.0,
        max_total: float = 5000.0,
        max_consecutive_losses: int = 3,
        cooldown_seconds: int = 300,
        dry_run: bool = False,
    ):
        self.dry_run = dry_run
        self.loss_limiter = DailyLossLimiter(limit_usd=daily_loss_limit)
        self.position_limiter = PositionSizeLimiter(
            max_per_market=max_per_market,
            max_total=max_total,
        )
        self.cooldown = CooldownManager(
            max_consecutive_losses=max_consecutive_losses,
            cooldown_seconds=cooldown_seconds,
        )

    def check_risk(
        self,
        opportunity: Opportunity,
        portfolio: PortfolioManager,
    ) -> RiskResult:
        """전체 리스크 체크.

        Args:
            opportunity: 감지된 아비트라지 기회.
            portfolio: 현재 포트폴리오.

        Returns:
            RiskResult(approved, reasons, allowed_size).
        """
        reasons: list[str] = []
        allowed_size = opportunity.recommended_size_usd

        # 1) Daily loss check
        loss_ok, loss_reason = self.loss_limiter.check()
        if not loss_ok:
            reasons.append(loss_reason or "Daily loss limit reached")

        # 2) Cooldown check
        cool_ok, remaining = self.cooldown.check()
        if not cool_ok:
            reasons.append(f"Cooldown active: {remaining}s remaining")

        # 3) Position size check
        market_id = opportunity.market.id
        pos = portfolio.get_position(market_id)
        current_market_exposure = pos.total_invested if pos else 0.0
        current_total_exposure = portfolio.total_invested

        pos_ok, pos_allowed = self.position_limiter.check(
            current_market_exposure=current_market_exposure,
            current_total_exposure=current_total_exposure,
            new_trade_size=allowed_size,
        )
        if not pos_ok:
            reasons.append(
                f"Position limit: market=${current_market_exposure:.2f}, "
                f"total=${current_total_exposure:.2f}"
            )
        else:
            allowed_size = pos_allowed

        # 결과 결정
        if reasons:
            for r in reasons:
                logger.warning("Risk rejection: %s", r)

            if self.dry_run:
                # dry_run: 사유는 기록하되 승인
                logger.info("[DRY RUN] Would reject, but approving for simulation")
                return RiskResult(
                    approved=True,
                    reasons=reasons,
                    allowed_size=allowed_size,
                )

            return RiskResult(
                approved=False,
                reasons=reasons,
                allowed_size=0.0,
            )

        return RiskResult(
            approved=True,
            reasons=[],
            allowed_size=allowed_size,
        )
