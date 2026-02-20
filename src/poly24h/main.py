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
from datetime import datetime

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
        choices=["sniper", "scan", "analyze", "preflight"],
        help="Bot mode: sniper, scan, analyze (paper P&L), or preflight (env check)",
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
    parser.add_argument(
        "--date", type=str, default=None,
        help="Date for analysis (YYYY-MM-DD). Default: all dates.",
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help="Number of days to analyze (e.g., --days 7 for last week).",
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
            # Error alerts disabled for Telegram (user request 2026-02-08)
            # await alerter.alert_error(f"Cycle {cycle} error — check logs")

        # Wait for next cycle or shutdown
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=config.scan_interval)
        except asyncio.TimeoutError:
            pass  # normal — time to scan again

    print("Goodbye! 🤙")


async def sniper_loop(config: BotConfig, threshold: float = 0.48) -> None:
    """이벤트 드리븐 스나이퍼 루프 (F-018).
    
    Enhanced with robust error handling:
    - Never-crash design: catches ALL exceptions in main loop
    - Auto-recovery: recreates resources after failures
    - Backoff: exponential delay on repeated failures
    """
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

    enabled = config.enabled_sources()
    source_names = ", ".join(enabled.keys())
    print(f"Enabled sources: {source_names}")
    print(f"Signal filter: min price=${RapidOrderbookPoller.MIN_MEANINGFUL_PRICE}")
    print("-" * 60)

    # Startup alert disabled for Telegram (user request 2026-02-07)
    # try:
    #     if alerter.enabled:
    #         await alerter.alert_error(
    #             f"🎯 poly24h SNIPER v2 started — {mode}\n"
    #             f"Threshold: ${threshold:.2f}\n"
    #             f"Sources: {source_names}\n"
    #             f"Signal filter: min_price≥${RapidOrderbookPoller.MIN_MEANINGFUL_PRICE}\n"
    #             f"Paper trading: ON\n"
    #             f"Strategy: Event-driven market open sniper",
    #             level="info",
    #         )
    # except Exception as e:
    #     logger.warning("Failed to send startup alert: %s", e)

    # Create a simple config-like namespace for the loop
    class SniperConfig:
        pre_open_window_secs = 120.0
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
    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 10
    
    # Outer loop: recreates resources on catastrophic failure
    while not stop_event.is_set():
        try:
            # Initialize resources (can be recreated on failure)
            schedule = MarketOpenSchedule()
            gamma_client = GammaClient()
            scanner = MarketScanner(gamma_client)
            preparer = PreOpenPreparer(gamma_client, scanner=scanner)
            clob_fetcher = ClobOrderbookFetcher(timeout=8)
            poller = RapidOrderbookPoller(clob_fetcher)
            loop = EventDrivenLoop(schedule, preparer, poller, alerter)

            # F-026: Launch multi-sport monitors as parallel background tasks
            from poly24h.execution.kill_switch import KillSwitch
            from poly24h.execution.sport_executor import SportExecutor
            from poly24h.strategy.odds_api import OddsAPIClient
            from poly24h.strategy.odds_rate_limiter import OddsAPIRateLimiter
            from poly24h.strategy.sport_config import get_enabled_sport_configs
            from poly24h.strategy.sports_monitor import SportsMonitor

            odds_client = OddsAPIClient(cache_ttl=2400)
            rate_limiter = OddsAPIRateLimiter(
                monthly_budget=500,
                min_interval=2400,  # 40min between fetches per sport (budget: ~216/day)
            )
            # F-031: Kill switch + sport executor
            daily_loss_limit = float(os.environ.get("POLY24H_DAILY_LOSS_LIMIT_USD", "300"))
            kill_switch = KillSwitch(max_daily_loss=daily_loss_limit)
            sport_executor = SportExecutor.from_env(
                dry_run=config.dry_run, kill_switch=kill_switch,
            )
            sport_configs = get_enabled_sport_configs()
            sport_tasks: list[asyncio.Task] = []

            # F-032c: Moneyline validation gate
            from poly24h.strategy.moneyline_gate import MoneylineValidationGate
            moneyline_gate = MoneylineValidationGate()
            logger.info("F-032c: MoneylineValidationGate initialized (validated=%s)",
                        moneyline_gate.is_validated())

            for i, sport_cfg in enumerate(sport_configs):
                monitor = SportsMonitor(
                    sport_config=sport_cfg,
                    odds_client=odds_client,
                    market_scanner=scanner,
                    position_manager=loop._position_manager,
                    orderbook_fetcher=clob_fetcher,
                    rate_limiter=rate_limiter,
                    sport_executor=sport_executor,
                    moneyline_gate=moneyline_gate,
                )

                async def delayed_start(m, delay):
                    if delay > 0:
                        await asyncio.sleep(delay)
                    await m.run_forever()

                task = asyncio.create_task(
                    delayed_start(monitor, delay=i * 60),
                )
                sport_tasks.append(task)

            # F-032b: Sports Paired Scanner — CPP arbitrage alongside directional
            from poly24h.strategy.sports_paired_scanner import SportsPairedScanner
            cpp_threshold = float(os.environ.get("POLY24H_CPP_THRESHOLD", "0.96"))
            sports_paired_scanner = SportsPairedScanner(
                orderbook_fetcher=clob_fetcher,
                position_manager=loop._position_manager,
                cpp_threshold=cpp_threshold,
            )
            logger.info("F-032b: SportsPairedScanner initialized (CPP threshold=%.2f)",
                        cpp_threshold)

            sport_names = [c.display_name for c in sport_configs]
            logger.info("F-026: %d sport monitors launched: %s",
                        len(sport_tasks), ", ".join(sport_names))

            logger.info("Resources initialized successfully")
            consecutive_errors = 0  # Reset on successful init
            
            # Inner loop: main event loop
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
                    
                    consecutive_errors = 0  # Reset on success
                    
                except asyncio.CancelledError:
                    logger.info("Task cancelled, shutting down...")
                    for t in sport_tasks:
                        t.cancel()
                    stop_event.set()
                    break
                except Exception as e:
                    consecutive_errors += 1
                    logger.exception(
                        "Error in cycle %d (phase: %s) [%d/%d]: %s", 
                        cycle, phase.value, consecutive_errors, MAX_CONSECUTIVE_ERRORS, e
                    )
                    
                    # Error alerts disabled for Telegram (user request 2026-02-08)
                    # Log only to local logs, don't spam Telegram
                    # try:
                    #     if alerter.enabled:
                    #         await alerter.alert_error(...)
                    # except Exception:
                    #     pass
                    
                    # Exponential backoff on repeated failures
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        logger.error("Too many consecutive errors, reinitializing resources...")
                        for t in sport_tasks:
                            t.cancel()
                        break  # Break inner loop to reinit resources
                    
                    backoff = min(30, 2 ** consecutive_errors)
                    await asyncio.sleep(backoff)

                # Brief pause between cycles
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=1)
                except asyncio.TimeoutError:
                    pass

        except asyncio.CancelledError:
            logger.info("Task cancelled during resource init, shutting down...")
            break
        except Exception as e:
            consecutive_errors += 1
            logger.exception(
                "Fatal error during resource initialization [%d]: %s",
                consecutive_errors, e
            )
            
            # Fatal error alerts disabled for Telegram (user request 2026-02-08)
            # try:
            #     if alerter.enabled:
            #         await alerter.alert_error(...)
            # except Exception:
            #     pass
            
            # Wait before retry
            await asyncio.sleep(60)

    print("Goodbye! 🤙")


def _run_preflight() -> None:
    """Run preflight environment checks."""
    from poly24h.analysis.preflight import format_preflight_report, run_preflight

    report = asyncio.run(run_preflight())
    print(format_preflight_report(report))


def _run_analyze(args: argparse.Namespace) -> None:
    """Run paper trade analysis and print report."""
    from poly24h.analysis.paper_analyzer import PaperTradeAnalyzer, format_analysis_report

    analyzer = PaperTradeAnalyzer()

    start_date = None
    if args.date:
        from datetime import timezone as tz
        start_date = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=tz.utc)

    result = analyzer.analyze(
        start_date=start_date,
        end_date=start_date if start_date and not args.days else None,
        days=args.days,
    )

    report = format_analysis_report(result)
    print(report)


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

    # Analyze mode
    if args.mode == "analyze":
        _run_analyze(args)
        return

    # Preflight mode
    if args.mode == "preflight":
        _run_preflight()
        return

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
