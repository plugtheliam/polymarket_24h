"""Dry-Run main loop — scan → detect → log → alert.

Usage:
    python -m poly24h
    python -m poly24h --interval 30 --sources crypto,nba
    python -m poly24h --live  # Phase 2
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal

from poly24h.config import MARKET_SOURCES, BotConfig
from poly24h.discovery.gamma_client import GammaClient
from poly24h.discovery.market_scanner import MarketScanner
from poly24h.models.market import Market
from poly24h.models.opportunity import Opportunity
from poly24h.monitoring.telegram import TelegramAlerter
from poly24h.strategy.dutch_book import detect_single_condition
from poly24h.strategy.opportunity import rank_opportunities
from poly24h.strategy.orderbook_scanner import (
    ClobOrderbookFetcher,
    OrderbookArbDetector,
    OrderbookBatchScanner,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

BANNER_SCAN = r"""
╔══════════════════════════════════════════════╗
║   poly24h — Polymarket 24H Arbitrage Bot     ║
║   Dutch Book Scanner · Polling Mode           ║
╚══════════════════════════════════════════════╝
"""

BANNER_SNIPER = r"""
╔══════════════════════════════════════════════╗
║   poly24h — Polymarket 24H Arbitrage Bot     ║
║   Event-Driven Sniper · F-018                 ║
╚══════════════════════════════════════════════╝
"""

# Keep backward compat
BANNER = BANNER_SCAN

# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def detect_all(
    markets: list[Market],
    min_spread: float = 0.01,
) -> list[Opportunity]:
    """모든 마켓에서 Dutch Book 기회 감지 + 랭킹."""
    opportunities: list[Opportunity] = []
    for market in markets:
        opp = detect_single_condition(market, min_spread=min_spread)
        if opp is not None:
            opportunities.append(opp)
    return rank_opportunities(opportunities)


def format_opportunity_line(opp: Opportunity) -> str:
    """단일 기회를 한 줄 문자열로 포맷."""
    return (
        f"  [{opp.market.source.value}] {opp.market.question[:60]:<60} "
        f"| ROI: {opp.roi_pct:6.2f}% "
        f"| margin: ${opp.margin:.4f} "
        f"| cost: ${opp.total_cost:.4f} "
        f"| liq: ${opp.market.liquidity_usd:,.0f}"
    )


def format_ob_opportunity_line(opp: Opportunity) -> str:
    """[OB] 오더북 기반 기회를 한 줄 문자열로 포맷."""
    return (
        f"  [OB] [{opp.market.source.value}] {opp.market.question[:50]:<50} "
        f"| ROI: {opp.roi_pct:6.2f}% "
        f"| yes_ask: ${opp.yes_price:.4f} "
        f"| no_ask: ${opp.no_price:.4f} "
        f"| margin: ${opp.margin:.4f} "
        f"| liq: ${opp.market.liquidity_usd:,.0f}"
    )


def log_results(
    opportunities: list[Opportunity],
    dry_run: bool = True,
    ob_opportunities: list[Opportunity] | None = None,
) -> None:
    """결과를 콘솔에 출력."""
    mode = "[DRY RUN]" if dry_run else "[LIVE]"

    if not opportunities and not ob_opportunities:
        print(f"\n{mode} No opportunities found this cycle.")
        return

    if opportunities:
        count = len(opportunities)
        noun = "opportunity" if count == 1 else "opportunities"
        print(f"\n{mode} Found {count} mid-price {noun}:")
        for opp in opportunities:
            print(format_opportunity_line(opp))

    if ob_opportunities:
        count = len(ob_opportunities)
        noun = "opportunity" if count == 1 else "opportunities"
        print(f"\n{mode} Found {count} orderbook {noun}:")
        for opp in ob_opportunities:
            print(format_ob_opportunity_line(opp))

    print()


async def run_cycle(
    config: BotConfig,
    scanner_config: dict | None = None,
) -> list[Opportunity]:
    """단일 스캔 사이클: discover → detect → return.

    enable_orderbook_scan=True일 때 CLOB 오더북 기반 arb도 추가 스캔.
    """
    async with GammaClient() as client:
        scanner = MarketScanner(client, config=scanner_config)
        markets = await scanner.discover_all()

    logger.info("Scanned %d markets", len(markets))
    opportunities = detect_all(markets, min_spread=0.01)

    # F-014: Orderbook-based arb scanning
    if config.enable_orderbook_scan and markets:
        try:
            fetcher = ClobOrderbookFetcher()
            detector = OrderbookArbDetector()
            batch_scanner = OrderbookBatchScanner(fetcher, detector, concurrency=5)
            ob_opps = await batch_scanner.scan(markets, min_spread=0.015)
            await fetcher.close()
            if ob_opps:
                logger.info("[OB] Found %d orderbook opportunities", len(ob_opps))
                opportunities.extend(ob_opps)
        except Exception:
            logger.exception("[OB] Orderbook scan error")

    return opportunities


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """커맨드라인 인자 파싱."""
    parser = argparse.ArgumentParser(
        prog="poly24h",
        description="Polymarket 24H Arbitrage Bot",
    )
    parser.add_argument(
        "--mode", type=str, default="sniper",
        choices=["sniper", "scan"],
        help="Bot mode: sniper (event-driven) or scan (polling)",
    )
    parser.add_argument(
        "--interval", type=int, default=60,
        help="Scan interval in seconds (default: 60, min: 10)",
    )
    parser.add_argument(
        "--sources", type=str, default=None,
        help="Comma-separated sources to scan (e.g., crypto,nba)",
    )
    parser.add_argument(
        "--live", action="store_true", default=False,
        help="Enable live trading (Phase 2)",
    )
    parser.add_argument(
        "--orderbook", action="store_true", default=False,
        help="Enable CLOB orderbook-based arb scanning (F-014)",
    )
    parser.add_argument(
        "--threshold", type=float, default=0.48,
        help="Sniper threshold: buy if best ask ≤ this (default: 0.48)",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _build_alerter() -> TelegramAlerter:
    """환경변수에서 TelegramAlerter 생성."""
    return TelegramAlerter(
        bot_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
        chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
    )


async def main_loop(config: BotConfig, scanner_config: dict | None = None) -> None:
    """메인 루프: 주기적 스캔 → 감지 → 로깅 → 텔레그램 알림."""
    alerter = _build_alerter()

    print(BANNER)
    print(f"Mode: {'DRY RUN' if config.dry_run else 'LIVE'}")
    print(f"Scan interval: {config.scan_interval}s")
    print(f"Telegram alerts: {'ON' if alerter.enabled else 'OFF'}")
    enabled = config.enabled_sources()
    print(f"Enabled sources: {', '.join(enabled.keys())}")
    print("-" * 60)

    # Notify startup
    if alerter.enabled:
        mode = "DRY RUN" if config.dry_run else "LIVE"
        await alerter.alert_error(
            f"🟢 poly24h started — {mode} mode\n"
            f"Sources: {', '.join(enabled.keys())}\n"
            f"Interval: {config.scan_interval}s",
            level="info",
        )

    # Graceful shutdown
    stop_event = asyncio.Event()

    def _handle_signal():
        print("\n⚡ Shutting down gracefully...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass  # Windows

    cycle = 0
    while not stop_event.is_set():
        cycle += 1
        logger.info("=== Cycle %d ===", cycle)
        try:
            opps = await run_cycle(config, scanner_config or dict(enabled))
            log_results(opps, dry_run=config.dry_run)

            # Send Telegram alerts for each opportunity
            for opp in opps:
                await alerter.alert_opportunity(opp)

        except Exception:
            logger.exception("Error in cycle %d", cycle)
            await alerter.alert_error(f"Cycle {cycle} error — check logs")

        # Wait for next cycle or shutdown
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=config.scan_interval)
        except asyncio.TimeoutError:
            pass  # normal — time to scan again

    print("Goodbye! 🤙")


async def sniper_loop(config: BotConfig, threshold: float = 0.48) -> None:
    """이벤트 드리븐 스나이퍼 루프 (F-018)."""
    from poly24h.scheduler.event_scheduler import (
        EventDrivenLoop,
        MarketOpenSchedule,
        PreOpenPreparer,
        RapidOrderbookPoller,
    )

    alerter = _build_alerter()

    print(BANNER_SNIPER)
    mode = "DRY RUN" if config.dry_run else "LIVE"
    print(f"Mode: {mode}")
    print(f"Sniper threshold: ${threshold:.2f}")
    print(f"Telegram alerts: {'ON' if alerter.enabled else 'OFF'}")
    print("-" * 60)

    if alerter.enabled:
        await alerter.alert_error(
            f"🎯 poly24h SNIPER started — {mode}\n"
            f"Threshold: ${threshold:.2f}\n"
            f"Strategy: Event-driven market open sniper",
            level="info",
        )

    schedule = MarketOpenSchedule()
    gamma_client = GammaClient()
    preparer = PreOpenPreparer(gamma_client)
    clob_fetcher = ClobOrderbookFetcher(timeout=8)
    poller = RapidOrderbookPoller(clob_fetcher)
    loop = EventDrivenLoop(schedule, preparer, poller, alerter)

    # Create a simple config-like namespace for the loop
    class SniperConfig:
        pre_open_window_secs = 30.0
        sniper_threshold = threshold

    # Graceful shutdown
    stop_event = asyncio.Event()

    def _handle_signal():
        print("\n⚡ Shutting down gracefully...")
        stop_event.set()

    ev_loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            ev_loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    sniper_cfg = SniperConfig()

    # Run the event-driven loop with shutdown check
    from datetime import datetime, timezone

    cycle = 0
    while not stop_event.is_set():
        cycle += 1
        now = datetime.now(tz=timezone.utc)
        phase = schedule.current_phase(now)
        secs = schedule.seconds_until_open(now)

        logger.info(
            "=== Cycle %d | Phase: %s | Next open in: %.0fs ===",
            cycle, phase.value, secs,
        )

        try:
            if phase.value == "idle":
                await loop._handle_idle_phase(now, sniper_cfg)
            elif phase.value == "pre_open":
                await loop._handle_pre_open_phase(sniper_cfg)
            elif phase.value == "snipe":
                await loop._handle_snipe_phase(sniper_cfg)
            elif phase.value == "cooldown":
                await loop._handle_cooldown_phase(sniper_cfg)
        except Exception:
            logger.exception("Error in cycle %d (phase: %s)", cycle, phase.value)
            if alerter.enabled:
                await alerter.alert_error(
                    f"Sniper error in {phase.value} phase — check logs"
                )

        # Brief pause
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=1)
        except asyncio.TimeoutError:
            pass

    print("Goodbye! 🤙")


def cli_main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    args = parse_args()
    config = BotConfig.from_env()
    config.scan_interval = max(args.interval, 10)
    if args.live:
        config.dry_run = False
    if args.orderbook:
        config.enable_orderbook_scan = True

    # Sniper mode (default)
    if args.mode == "sniper":
        asyncio.run(sniper_loop(config, threshold=args.threshold))
        return

    # Scan mode (legacy polling)
    scanner_config = None
    if args.sources:
        source_names = [s.strip() for s in args.sources.split(",")]
        scanner_config = {
            name: cfg
            for name, cfg in MARKET_SOURCES.items()
            if name in source_names or any(name.startswith(s) for s in source_names)
        }
        for cfg in scanner_config.values():
            cfg["enabled"] = True

    asyncio.run(main_loop(config, scanner_config))


if __name__ == "__main__":
    cli_main()
