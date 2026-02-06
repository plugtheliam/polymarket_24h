"""Telegram Bot API alerts.

아비트라지 기회, 거래, 에러 알림 전송.
봇 토큰 미설정 시 모든 메서드가 no-op (크래시 없음).
"""

from __future__ import annotations

import logging
from typing import Union

import aiohttp

from poly24h.models.negrisk import NegRiskOpportunity
from poly24h.models.opportunity import Opportunity
from poly24h.pipeline import SessionSummary, TradeRecord

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org"


class TelegramAlerter:
    """Telegram 알림 발송기.

    Args:
        bot_token: Telegram Bot API 토큰. None이면 비활성.
        chat_id: 메시지 대상 채팅 ID. None이면 비활성.
    """

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
    ):
        self._bot_token = bot_token
        self._chat_id = chat_id

    @property
    def enabled(self) -> bool:
        """토큰과 chat_id 모두 설정됐을 때만 활성."""
        return bool(self._bot_token and self._chat_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def alert_opportunity(
        self, opp: Union[Opportunity, NegRiskOpportunity],
    ) -> None:
        """아비트라지 기회 감지 알림."""
        if not self.enabled:
            return
        try:
            if isinstance(opp, NegRiskOpportunity):
                text = self._format_negrisk_opportunity(opp)
            else:
                text = self._format_opportunity(opp)
            await self._send_message(text)
        except Exception as exc:
            logger.error("Failed to send opportunity alert: %s", exc)

    async def alert_trade(self, record: TradeRecord) -> None:
        """거래 결과 알림."""
        if not self.enabled:
            return
        try:
            text = self._format_trade(record)
            await self._send_message(text)
        except Exception as exc:
            logger.error("Failed to send trade alert: %s", exc)

    async def alert_error(self, message: str, level: str = "error") -> None:
        """에러/경고 알림."""
        if not self.enabled:
            return
        try:
            emoji = "🚨" if level == "error" else "⚠️"
            text = f"{emoji} <b>{level.upper()}</b>\n{message}"
            await self._send_message(text)
        except Exception as exc:
            logger.error("Failed to send error alert: %s", exc)

    async def send_daily_report(self, summary: SessionSummary) -> None:
        """일일 거래 요약 전송."""
        if not self.enabled:
            return
        try:
            text = self._format_daily_report(summary)
            await self._send_message(text)
        except Exception as exc:
            logger.error("Failed to send daily report: %s", exc)

    # ------------------------------------------------------------------
    # Internal: HTTP
    # ------------------------------------------------------------------

    async def _send_message(self, text: str, parse_mode: str = "HTML") -> None:
        """Telegram sendMessage API 호출."""
        url = f"{TELEGRAM_API_URL}/bot{self._bot_token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("Telegram API %d: %s", resp.status, body[:200])

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _format_opportunity(self, opp: Opportunity) -> str:
        return (
            f"🔍 <b>Arb Found</b>\n"
            f"{'━' * 24}\n"
            f"Market: {opp.market.question[:60]}\n"
            f"ROI: <b>{opp.roi_pct:.2f}%</b>\n"
            f"Margin: ${opp.margin:.4f}\n"
            f"Cost: ${opp.total_cost:.4f}\n"
            f"Source: {opp.market.source.value}"
        )

    def _format_negrisk_opportunity(self, opp: NegRiskOpportunity) -> str:
        nm = opp.negrisk_market
        return (
            f"🔍 <b>NegRisk Arb Found</b>\n"
            f"{'━' * 24}\n"
            f"Event: {nm.event_title[:60]}\n"
            f"Outcomes: {len(nm.outcomes)}\n"
            f"ROI: <b>{opp.roi_pct:.2f}%</b>\n"
            f"Margin: ${opp.margin:.4f}\n"
            f"Total Prob: {nm.total_prob:.4f}"
        )

    def _format_trade(self, record: TradeRecord) -> str:
        if record.executed:
            return (
                f"✅ <b>Trade Executed</b>\n"
                f"{'━' * 24}\n"
                f"Market: {record.market_question[:60]}\n"
                f"Shares: {record.shares:.0f}\n"
                f"Cost: ${record.total_cost:.2f}\n"
                f"Expected Profit: ${record.expected_profit:.2f}"
            )
        else:
            reasons = ", ".join(record.reject_reasons) if record.reject_reasons else "Unknown"
            return (
                f"❌ <b>Trade Rejected</b>\n"
                f"{'━' * 24}\n"
                f"Market: {record.market_question[:60]}\n"
                f"Reason: {reasons}"
            )

    def _format_daily_report(self, summary: SessionSummary) -> str:
        if summary.total_trades == 0 and summary.total_cycles == 0:
            return "📊 <b>Daily Report</b>\nNo trades today."

        return (
            f"📊 <b>Daily Report</b>\n"
            f"{'━' * 24}\n"
            f"Cycles: {summary.total_cycles}\n"
            f"Opportunities: {summary.total_opportunities}\n"
            f"Trades: {summary.total_trades}\n"
            f"Rejected: {summary.total_rejected}\n"
            f"{'━' * 24}\n"
            f"Invested: ${summary.total_invested:.2f}\n"
            f"Locked Profit: ${summary.total_locked_profit:.2f}\n"
            f"Realized PnL: ${summary.total_realized_pnl:.2f}\n"
            f"Active Positions: {summary.active_positions}"
        )
