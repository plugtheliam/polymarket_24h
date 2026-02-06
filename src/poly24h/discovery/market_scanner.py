"""Market scanner — orchestrates discovery across all enabled sources."""

from __future__ import annotations

import logging

from poly24h.config import MARKET_SOURCES
from poly24h.discovery.gamma_client import GammaClient
from poly24h.discovery.market_filter import MarketFilter
from poly24h.models.market import Market, MarketSource

logger = logging.getLogger(__name__)


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

            if source_name == "hourly_crypto":
                found = await self.discover_hourly_crypto(source_cfg)
            else:
                found = await self.discover_sports(source_name, source_cfg)

            for mkt in found:
                if mkt.id not in seen_ids:
                    seen_ids.add(mkt.id)
                    markets.append(mkt)

        logger.info("Discovered %d markets from %d sources", len(markets), len(self.config))
        return markets

    # ------------------------------------------------------------------
    # Hourly crypto discovery
    # ------------------------------------------------------------------

    async def discover_hourly_crypto(
        self, cfg: dict | None = None,
    ) -> list[Market]:
        """1시간 크립토 마켓 발견: 패턴 매칭 + 블랙리스트 제외."""
        if cfg is None:
            cfg = self.config.get("hourly_crypto", {"min_liquidity_usd": 3000})

        raw_events = await self.client.fetch_events(tag="crypto")
        markets: list[Market] = []

        for event in raw_events:
            for raw_mkt in event.get("markets", []):
                question = raw_mkt.get("question", "")

                # hourly 패턴 매칭 필수
                if not MarketFilter.matches_hourly_crypto(question):
                    continue

                # 15분 블랙리스트 제외
                if MarketFilter.is_blacklisted(question):
                    continue

                # 24시간 이내 정산
                end_date_str = raw_mkt.get("endDate") or event.get("endDate", "")
                if not MarketFilter.is_within_24h(end_date_str):
                    continue

                # 최소 유동성
                if not MarketFilter.meets_min_liquidity(
                    raw_mkt, cfg.get("min_liquidity_usd", 3000)
                ):
                    continue

                # active & not closed
                if not MarketFilter.is_active(raw_mkt):
                    continue

                market = Market.from_gamma_response(raw_mkt, event, MarketSource.HOURLY_CRYPTO)
                if market:
                    markets.append(market)

        return markets

    # ------------------------------------------------------------------
    # Sports discovery
    # ------------------------------------------------------------------

    async def discover_sports(
        self, sport: str, cfg: dict | None = None,
    ) -> list[Market]:
        """스포츠 마켓 발견: 24h 이내 + NegRisk 제외."""
        if cfg is None:
            cfg = self.config.get(sport, {"min_liquidity_usd": 5000})

        try:
            source_enum = MarketSource(sport)
        except ValueError:
            logger.warning("Unknown sport source: %s", sport)
            return []

        raw_events = await self.client.fetch_events(tag=sport)
        markets: list[Market] = []

        for event in raw_events:
            # NegRisk 시즌 마켓 제외
            if event.get("enableNegRisk") or event.get("negRiskAugmented"):
                continue

            for raw_mkt in event.get("markets", []):
                end_date_str = raw_mkt.get("endDate") or event.get("endDate", "")
                if not MarketFilter.is_within_24h(end_date_str):
                    continue

                if not MarketFilter.meets_min_liquidity(
                    raw_mkt, cfg.get("min_liquidity_usd", 5000)
                ):
                    continue

                if not MarketFilter.is_active(raw_mkt):
                    continue

                market = Market.from_gamma_response(raw_mkt, event, source_enum)
                if market:
                    markets.append(market)

        return markets
