"""Market scanner — orchestrates discovery across all enabled sources.

핵심 발견 (2026-02-06):
- 1H 크립토 마켓: tag_slug='1H'로 검색 (tag='crypto'는 장기 마켓만 반환)
  - 슬러그 패턴: bitcoin-up-or-down-february-6-9am-et
  - 태그: ['crypto', 'crypto-prices', 'recurring', 'hide-from-new', 'bitcoin', '1H', 'up-or-down']
- 스포츠 개별 경기: slug 패턴으로 식별 (nba-cha-atl-2026-02-07)
  - 태그: ['sports', 'nba', 'games', 'basketball']
  - end_date_min/max 필터로 조회
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from poly24h.config import MARKET_SOURCES
from poly24h.discovery.gamma_client import GammaClient
from poly24h.discovery.market_filter import MarketFilter
from poly24h.models.market import Market, MarketSource

logger = logging.getLogger(__name__)

# 스포츠 개별 경기 slug 패턴: {sport_prefix}-{team1}-{team2}-{date}
GAME_SLUG_PREFIXES = {
    "nba": MarketSource.NBA,
    "nhl": MarketSource.NHL,
    "atp": MarketSource.TENNIS,
    "wta": MarketSource.TENNIS,
    "epl": MarketSource.SOCCER,
    "lal": MarketSource.SOCCER,   # La Liga
    "ser": MarketSource.SOCCER,   # Serie A
    "bun": MarketSource.SOCCER,   # Bundesliga
    "ucl": MarketSource.SOCCER,   # Champions League
    "elc": MarketSource.SOCCER,   # EFL Championship
    "spl": MarketSource.SOCCER,   # Saudi Pro League
    "mls": MarketSource.SOCCER,   # MLS
}

# slug 패턴: prefix-team1-team2-YYYY-MM-DD
GAME_SLUG_RE = re.compile(
    r"^(" + "|".join(GAME_SLUG_PREFIXES) + r")-\w+-\w+-\d{4}-\d{2}-\d{2}$"
)


class MarketScanner:
    """주기적 마켓 스캔 오케스트레이터."""

    def __init__(
        self,
        client: GammaClient,
        config: dict | None = None,
    ):
        self.client = client
        self.config = config or MARKET_SOURCES

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def discover_all(self) -> list[Market]:
        """모든 enabled 소스에서 마켓 수집 + 중복 제거."""
        markets: list[Market] = []
        seen_ids: set[str] = set()

        for source_name, source_cfg in self.config.items():
            if not source_cfg.get("enabled"):
                continue

            try:
                if source_name == "hourly_crypto":
                    found = await self.discover_hourly_crypto(source_cfg)
                else:
                    found = await self.discover_sports(source_name, source_cfg)
            except Exception:
                logger.exception("Error discovering %s", source_name)
                found = []

            for mkt in found:
                if mkt.id not in seen_ids:
                    seen_ids.add(mkt.id)
                    markets.append(mkt)

        logger.info("Discovered %d markets from %d sources", len(markets), len(self.config))
        return markets

    # ------------------------------------------------------------------
    # Hourly crypto discovery (tag_slug='1H')
    # ------------------------------------------------------------------

    async def discover_hourly_crypto(
        self, cfg: dict | None = None,
    ) -> list[Market]:
        """1시간 크립토 마켓 발견: tag_slug='1H'로 조회 + 24h 필터."""
        if cfg is None:
            cfg = self.config.get("hourly_crypto", {"min_liquidity_usd": 3000})

        min_liq = cfg.get("min_liquidity_usd", 3000)

        # tag_slug='1H'로 직접 조회 — 이게 실제 hourly 마켓을 반환
        raw_events = await self.client.fetch_events_by_tag_slug("1H", limit=100)
        markets: list[Market] = []

        for event in raw_events:
            for raw_mkt in event.get("markets", []):
                # 24시간 이내 정산
                end_date_str = raw_mkt.get("endDate") or event.get("endDate", "")
                if not MarketFilter.is_within_24h(end_date_str):
                    continue

                # 최소 유동성
                if not MarketFilter.meets_min_liquidity(raw_mkt, min_liq):
                    continue

                # active & not closed
                if not MarketFilter.is_active(raw_mkt):
                    continue

                # 15분 블랙리스트 제외 (안전장치)
                question = raw_mkt.get("question", "")
                if MarketFilter.is_blacklisted(question):
                    continue

                market = Market.from_gamma_response(raw_mkt, event, MarketSource.HOURLY_CRYPTO)
                if market:
                    markets.append(market)

        logger.info("Hourly crypto: found %d markets", len(markets))
        return markets

    # ------------------------------------------------------------------
    # Sports discovery (date range + slug pattern matching)
    # ------------------------------------------------------------------

    async def discover_sports(
        self, sport: str, cfg: dict | None = None,
    ) -> list[Market]:
        """스포츠 개별 경기 마켓: date range 조회 + slug 패턴 매칭."""
        if cfg is None:
            cfg = self.config.get(sport, {"min_liquidity_usd": 5000})

        try:
            source_enum = MarketSource(sport)
        except ValueError:
            logger.warning("Unknown sport source: %s", sport)
            return []

        min_liq = cfg.get("min_liquidity_usd", 5000)

        # 향후 48시간 이내 정산되는 이벤트 조회
        now = datetime.now(tz=timezone.utc)
        end_min = now.isoformat()
        end_max = (now + timedelta(hours=48)).isoformat()

        all_events: list[dict] = []
        for offset in range(0, 600, 50):
            batch = await self.client.fetch_events_by_date_range(
                end_date_min=end_min,
                end_date_max=end_max,
                limit=50,
                offset=offset,
            )
            all_events.extend(batch)
            if len(batch) < 50:
                break

        markets: list[Market] = []

        for event in all_events:
            slug = event.get("slug", "")

            # slug 패턴으로 개별 경기 식별
            match = GAME_SLUG_RE.match(slug)
            if not match:
                continue

            # slug prefix에서 스포츠 종류 확인
            prefix = match.group(1)
            slug_source = GAME_SLUG_PREFIXES.get(prefix)
            if slug_source != source_enum:
                continue

            # NegRisk 시즌 마켓 제외 (개별 경기는 대부분 negRisk=False)
            if event.get("enableNegRisk") or event.get("negRiskAugmented"):
                continue

            for raw_mkt in event.get("markets", []):
                end_date_str = raw_mkt.get("endDate") or event.get("endDate", "")
                if not MarketFilter.is_within_24h(end_date_str, max_hours=48):
                    continue

                if not MarketFilter.meets_min_liquidity(raw_mkt, min_liq):
                    continue

                if not MarketFilter.is_active(raw_mkt):
                    continue

                market = Market.from_gamma_response(raw_mkt, event, source_enum)
                if market:
                    markets.append(market)

        logger.info("Sports [%s]: found %d individual game markets", sport, len(markets))
        return markets
