"""Dry-Run main loop — scan → detect → log.

Usage:
    python -m poly24h
    python -m poly24h --interval 30 --sources crypto,nba
    python -m poly24h --live  # Phase 2
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from poly24h.config import MARKET_SOURCES, BotConfig
from poly24h.discovery.gamma_client import GammaClient
from poly24h.discovery.market_scanner import MarketScanner
from poly24h.models.market import Market
from poly24h.models.opportunity import Opportunity
from poly24h.strategy.dutch_book import detect_single_condition
from poly24h.strategy.opportunity import rank_opportunities

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

BANNER = r"""
╔══════════════════════════════════════════════╗
║   poly24h — Polymarket 24H Arbitrage Bot     ║
║   Dutch Book Scanner · Phase 1 MVP           ║
╚══════════════════════════════════════════════╝
"""

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


def log_results(opportunities: list[Opportunity], dry_run: bool = True) -> None:
    """결과를 콘솔에 출력."""
    mode = "[DRY RUN]" if dry_run else "[LIVE]"

    if not opportunities:
        print(f"\n{mode} No opportunities found this cycle.")
        return

    count = len(opportunities)
    noun = "opportunity" if count == 1 else "opportunities"
    print(f"\n{mode} Found {count} {noun}:")
    for opp in opportunities:
        print(format_opportunity_line(opp))
    print()


async def run_cycle(
    config: BotConfig,
    scanner_config: dict | None = None,
) -> list[Opportunity]:
    """단일 스캔 사이클: discover → detect → return."""
    async with GammaClient() as client:
        scanner = MarketScanner(client, config=scanner_config)
        markets = await scanner.discover_all()

    logger.info("Scanned %d markets", len(markets))
    opportunities = detect_all(markets, min_spread=0.01)
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
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def main_loop(config: BotConfig, scanner_config: dict | None = None) -> None:
    """메인 루프: 주기적 스캔 → 감지 → 로깅."""
    print(BANNER)
    print(f"Mode: {'DRY RUN' if config.dry_run else 'LIVE'}")
    print(f"Scan interval: {config.scan_interval}s")
    enabled = config.enabled_sources()
    print(f"Enabled sources: {', '.join(enabled.keys())}")
    print("-" * 60)

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
        except Exception:
            logger.exception("Error in cycle %d", cycle)

        # Wait for next cycle or shutdown
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=config.scan_interval)
        except asyncio.TimeoutError:
            pass  # normal — time to scan again

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

    # Source filtering
    scanner_config = None
    if args.sources:
        source_names = [s.strip() for s in args.sources.split(",")]
        scanner_config = {
            name: cfg
            for name, cfg in MARKET_SOURCES.items()
            if name in source_names or any(name.startswith(s) for s in source_names)
        }
        # Force enable selected sources
        for cfg in scanner_config.values():
            cfg["enabled"] = True

    asyncio.run(main_loop(config, scanner_config))


if __name__ == "__main__":
    cli_main()
