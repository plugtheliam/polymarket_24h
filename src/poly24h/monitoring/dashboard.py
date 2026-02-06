"""Console dashboard renderer.

박스 그리기 문자 (═║╔╗╚╝) + ANSI 색상으로 가독성 높은 대시보드.
"""

from __future__ import annotations

from datetime import datetime, timezone


class DashboardRenderer:
    """콘솔 대시보드 렌더링."""

    WIDTH = 52

    def render_cycle(
        self,
        cycle_num: int,
        markets_scanned: int,
        opps_found: int,
        active_positions: int,
        session_pnl: float,
        risk_status: str,
    ) -> str:
        """사이클 결과 대시보드.

        Args:
            cycle_num: 사이클 번호.
            markets_scanned: 스캔한 마켓 수.
            opps_found: 발견된 기회 수.
            active_positions: 활성 포지션 수.
            session_pnl: 세션 PnL.
            risk_status: 리스크 상태 (OK, COOLDOWN 등).

        Returns:
            렌더링된 대시보드 문자열.
        """
        w = self.WIDTH
        now = datetime.now(tz=timezone.utc).strftime("%H:%M:%S UTC")

        pnl_str = f"${session_pnl:+.2f}"

        lines = [
            f"╔{'═' * w}╗",
            f"║  Cycle #{cycle_num:<6} {now:>30}  ║",
            f"╠{'═' * w}╣",
            f"║  Markets scanned:  {markets_scanned:<29} ║",
            f"║  Opportunities:    {opps_found:<29} ║",
            f"║  Active positions: {active_positions:<29} ║",
            f"║  Session PnL:      {pnl_str:<29} ║",
            f"║  Risk status:      {risk_status:<29} ║",
            f"╚{'═' * w}╝",
        ]
        return "\n".join(lines)

    def render_startup(
        self,
        config: dict,
        risk_params: dict,
    ) -> str:
        """시작 배너 — 설정 + 리스크 파라미터 표시.

        Args:
            config: 봇 설정 dict (dry_run, scan_interval, ...).
            risk_params: 리스크 파라미터 dict.

        Returns:
            렌더링된 배너 문자열.
        """
        w = self.WIDTH
        dry_run = config.get("dry_run", True)
        mode = "DRY RUN" if dry_run else "⚡ LIVE TRADING"
        interval = config.get("scan_interval", 60)

        lines = [
            f"╔{'═' * w}╗",
            f"║{'poly24h — Polymarket 24H Arbitrage Bot':^{w}}║",
            f"║{'Phase 3 — Full Feature':^{w}}║",
            f"╠{'═' * w}╣",
            f"║  Mode:           {mode:<31} ║",
            f"║  Scan interval:  {interval}s{'':<{28 - len(str(interval))}} ║",
        ]

        # 리스크 파라미터
        for key, value in risk_params.items():
            label = key.replace("_", " ").title()
            val_str = str(value)
            pad = 31 - len(label) - 2 - len(val_str)
            lines.append(f"║  {label}: {val_str}{' ' * max(0, pad)} ║")

        lines.append(f"╚{'═' * w}╝")
        return "\n".join(lines)
