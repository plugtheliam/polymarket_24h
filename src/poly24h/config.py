"""Bot configuration — market sources, patterns, env-based config."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 마켓 소스 정의 (PRD Section 4)
# ---------------------------------------------------------------------------

MARKET_SOURCES: dict = {
    "hourly_crypto": {
        "enabled": True,
        "description": "1시간 크립토 Up/Down 마켓",
        "coins": ["BTC", "ETH", "SOL", "XRP"],
        "resolution_window": "1 hour",
        "fee": 0,
        "daily_markets": 96,
        "expected_opportunities": "10-15/day",
        "arb_type": "single_condition",
        "min_liquidity_usd": 3000,
        "min_spread": 0.01,
    },
    "nba": {
        "enabled": True,
        "description": "NBA 개별 경기 Moneyline",
        "resolution_window": "game_end",
        "fee": 0,
        "daily_markets": "5-8",
        "expected_opportunities": "2-4/day",
        "arb_type": "single_condition",
        "min_liquidity_usd": 5000,
        "min_spread": 0.015,
    },
    "nhl": {
        "enabled": False,
        "description": "NHL 개별 경기",
        "resolution_window": "game_end",
        "fee": 0,
        "daily_markets": "4-7",
        "expected_opportunities": "2-3/day",
        "arb_type": "single_condition",
        "min_liquidity_usd": 5000,
        "min_spread": 0.015,
    },
    "tennis": {
        "enabled": False,
        "description": "ATP/WTA 개별 매치",
        "resolution_window": "match_end",
        "fee": 0,
        "daily_markets": "10-20",
        "expected_opportunities": "3-6/day",
        "arb_type": "single_condition",
        "min_liquidity_usd": 3000,
        "min_spread": 0.01,
    },
    "soccer": {
        "enabled": True,
        "description": "축구 개별 경기 (EPL, La Liga, Bundesliga, EFL, etc.)",
        "resolution_window": "game_end",
        "fee": 0,
        "daily_markets": "2-8",
        "expected_opportunities": "1-3/day",
        "arb_type": "single_condition",
        "min_liquidity_usd": 5000,
        "min_spread": 0.015,
    },
    "esports": {
        "enabled": False,
        "description": "CS2, LoL, Valorant 매치",
        "resolution_window": "match_end",
        "fee": 0,
        "daily_markets": "5-15",
        "expected_opportunities": "2-4/day",
        "arb_type": "single_condition",
        "min_liquidity_usd": 3000,
        "min_spread": 0.01,
    },
}

# ---------------------------------------------------------------------------
# 15분 크립토 블랙리스트 (수수료 ~3.15%)
# ---------------------------------------------------------------------------

BLACKLIST_PATTERNS: list[str] = [
    "15 min",
    "15-min",
    "15-minute",
    "15min",
]

# ---------------------------------------------------------------------------
# 1시간 크립토 매칭 패턴
# ---------------------------------------------------------------------------

HOURLY_CRYPTO_PATTERNS: list[str] = [
    "1 hour",
    "1-hour",
    "hourly",
    "1h",
]


# ---------------------------------------------------------------------------
# BotConfig — 환경변수 기반 설정
# ---------------------------------------------------------------------------


@dataclass
class BotConfig:
    """봇 전체 설정. 환경변수 또는 기본값."""

    dry_run: bool = True
    scan_interval: int = 60  # seconds
    max_position_usd: float = 1000.0
    max_daily_loss_usd: float = 500.0
    market_sources: dict = field(default_factory=lambda: MARKET_SOURCES)

    def __post_init__(self):
        # 최소 스캔 간격 강제 (10초)
        if self.scan_interval < 10:
            self.scan_interval = 10

    @classmethod
    def from_env(cls) -> BotConfig:
        """환경변수에서 설정 로드. 없으면 안전한 기본값."""
        dry_run_str = os.environ.get("POLY24H_DRY_RUN", "true").lower()
        dry_run = dry_run_str not in ("false", "0", "no")

        scan_interval = int(os.environ.get("POLY24H_SCAN_INTERVAL", "60"))
        max_position = float(os.environ.get("POLY24H_MAX_POSITION_USD", "1000"))

        return cls(
            dry_run=dry_run,
            scan_interval=scan_interval,
            max_position_usd=max_position,
        )

    def enabled_sources(self) -> dict:
        """활성화된 마켓 소스만 반환."""
        return {
            name: cfg
            for name, cfg in self.market_sources.items()
            if cfg.get("enabled")
        }
