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

# F-022: NBA 팀 약자 매핑
TEAM_ABBREVIATIONS = {
    "atl": "Atlanta Hawks",
    "bos": "Boston Celtics",
    "bkn": "Brooklyn Nets",
    "cha": "Charlotte Hornets",
    "chi": "Chicago Bulls",
    "cle": "Cleveland Cavaliers",
    "dal": "Dallas Mavericks",
    "den": "Denver Nuggets",
    "det": "Detroit Pistons",
    "gsw": "Golden State Warriors",
    "hou": "Houston Rockets",
    "ind": "Indiana Pacers",
    "lac": "LA Clippers",
    "lal": "Los Angeles Lakers",
    "mem": "Memphis Grizzlies",
    "mia": "Miami Heat",
    "mil": "Milwaukee Bucks",
    "min": "Minnesota Timberwolves",
    "nop": "New Orleans Pelicans",
    "nyk": "New York Knicks",
    "okc": "Oklahoma City Thunder",
    "orl": "Orlando Magic",
    "phi": "Philadelphia 76ers",
    "phx": "Phoenix Suns",
    "por": "Portland Trail Blazers",
    "sac": "Sacramento Kings",
    "sas": "San Antonio Spurs",
    "tor": "Toronto Raptors",
    "uta": "Utah Jazz",
    "was": "Washington Wizards",
}


def generate_polymarket_url(slug: str) -> str:
    """Generate Polymarket URL from market slug.
    
    Args:
        slug: Market slug (e.g., "nba-det-cha-2026-02-09")
        
    Returns:
        Full Polymarket URL
    """
    return f"https://polymarket.com/event/{slug}"


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

# slug 패턴: prefix-{teams...}-YYYY-MM-DD
# Flexible: team segments can contain multiple parts (e.g., "man-utd-chelsea")
GAME_SLUG_RE = re.compile(
    r"^(" + "|".join(GAME_SLUG_PREFIXES) + r")-.+-(\d{4}-\d{2}-\d{2})$"
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
        """모든 enabled 소스에서 마켓 수집 + 중복 제거.

        스포츠 소스는 discover_all_sports()로 ONE 쿼리 통합 (F-015).
        """
        markets: list[Market] = []
        seen_ids: set[str] = set()

        # 1) Hourly crypto (별도 tag_slug 쿼리)
        crypto_cfg = self.config.get("hourly_crypto")
        if crypto_cfg and crypto_cfg.get("enabled"):
            try:
                found = await self.discover_hourly_crypto(crypto_cfg)
            except Exception:
                logger.exception("Error discovering hourly_crypto")
                found = []
            for mkt in found:
                if mkt.id not in seen_ids:
                    seen_ids.add(mkt.id)
                    markets.append(mkt)

        # 2) 스포츠: 하나의 date range 쿼리로 통합
        sports_configs = {
            name: cfg
            for name, cfg in self.config.items()
            if name != "hourly_crypto" and cfg.get("enabled")
        }
        if sports_configs:
            try:
                found = await self.discover_all_sports(sports_configs)
            except Exception:
                logger.exception("Error discovering sports (unified)")
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
    # Unified sports discovery (F-015: ONE query for ALL sports)
    # ------------------------------------------------------------------

    async def discover_all_sports(
        self, configs: dict,
    ) -> list[Market]:
        """하나의 date range 쿼리로 모든 스포츠 경기 발견 후 slug prefix로 분류.

        Args:
            configs: {source_name: {enabled, min_liquidity_usd, ...}} 스포츠별 설정

        Returns:
            분류된 Market 리스트 (slug prefix → MarketSource 매핑)
        """
        # source_name → MarketSource enum 매핑 + min_liquidity
        source_map: dict[MarketSource, float] = {}
        for source_name, cfg in configs.items():
            try:
                source_enum = MarketSource(source_name)
            except ValueError:
                logger.warning("Unknown sport source: %s", source_name)
                continue
            source_map[source_enum] = cfg.get("min_liquidity_usd", 5000)

        if not source_map:
            return []

        # 향후 48시간 이내 정산되는 이벤트 조회 — ONE query
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
            if slug_source is None or slug_source not in source_map:
                continue

            # NegRisk 시즌 마켓 제외
            if event.get("enableNegRisk") or event.get("negRiskAugmented"):
                continue

            min_liq = source_map[slug_source]

            for raw_mkt in event.get("markets", []):
                end_date_str = raw_mkt.get("endDate") or event.get("endDate", "")
                if not MarketFilter.is_within_24h(end_date_str, max_hours=48):
                    continue

                if not MarketFilter.meets_min_liquidity(raw_mkt, min_liq):
                    continue

                if not MarketFilter.is_active(raw_mkt):
                    continue

                market = Market.from_gamma_response(raw_mkt, event, slug_source)
                if market:
                    markets.append(market)

        logger.info(
            "Unified sports: found %d markets from %d events",
            len(markets), len(all_events),
        )
        return markets

    # ------------------------------------------------------------------
    # F-025: NBA-specific discovery (with negRisk support)
    # ------------------------------------------------------------------

    async def discover_nba_markets(
        self, include_neg_risk: bool = True,
    ) -> list[Market]:
        """NBA-specific market discovery with negRisk support.

        Unlike discover_all_sports() which filters OUT negRisk events,
        this method can include them (NBA main markets may be negRisk).

        Args:
            include_neg_risk: If True, include negRisk NBA events.

        Returns:
            List of NBA Market objects.
        """
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

            # Only NBA events (slug starts with "nba-")
            if not slug.startswith("nba-"):
                continue

            # NegRisk filter: skip if not including negRisk
            if not include_neg_risk:
                if event.get("enableNegRisk") or event.get("negRiskAugmented"):
                    continue

            for raw_mkt in event.get("markets", []):
                end_date_str = raw_mkt.get("endDate") or event.get("endDate", "")
                if not MarketFilter.is_within_24h(end_date_str, max_hours=48):
                    continue

                if not MarketFilter.is_active(raw_mkt):
                    continue

                market = Market.from_gamma_response(raw_mkt, event, MarketSource.NBA)
                if market:
                    markets.append(market)

        logger.info("NBA discovery: found %d markets from %d events (negRisk=%s)",
                     len(markets), len(all_events), include_neg_risk)
        return markets

    # ------------------------------------------------------------------
    # Sports discovery (backwards compat — delegates to unified)
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

    # ------------------------------------------------------------------
    # F-022: Direct market lookup with CLOB verification
    # ------------------------------------------------------------------

    async def discover_and_verify_market(
        self, 
        market_id: str,
        min_liquidity: float = 10000.0,
    ) -> Market | None:
        """Direct market lookup with CLOB verification.
        
        F-022: Improved NBA market discovery process.
        1. Lookup market by ID via Gamma API
        2. Verify market is still active (not expired)
        3. Verify CLOB orderbook has liquidity
        4. Return verified Market or None
        
        Args:
            market_id: Gamma market ID (e.g., "1326267")
            min_liquidity: Minimum CLOB liquidity threshold
            
        Returns:
            Verified Market object or None if invalid/expired/no liquidity
        """
        from poly24h.discovery.gamma_client import is_market_active
        import json
        
        # Step 1: Direct market lookup
        raw_market = await self.client.get_market_by_id(market_id)
        if not raw_market:
            logger.debug("Market %s not found in Gamma API", market_id)
            return None
        
        # Step 2: Time validation - check if market is still active
        end_date = raw_market.get("endDate") or raw_market.get("end_date")
        if not is_market_active(end_date):
            logger.debug("Market %s expired (end: %s)", market_id, end_date)
            return None
        
        # Step 3: CLOB liquidity verification
        clob_token_ids = raw_market.get("clobTokenIds", [])
        if isinstance(clob_token_ids, str):
            try:
                clob_token_ids = json.loads(clob_token_ids)
            except json.JSONDecodeError:
                clob_token_ids = []
        
        if not clob_token_ids or len(clob_token_ids) < 2:
            logger.debug("Market %s has no CLOB token IDs", market_id)
            return None
        
        # Check YES side liquidity
        yes_token = clob_token_ids[0]
        has_liquidity = await self.client.verify_clob_liquidity(
            yes_token, min_liquidity
        )
        
        if not has_liquidity:
            logger.debug("Market %s insufficient CLOB liquidity", market_id)
            return None
        
        # Step 4: Build Market object
        # Determine source from slug
        slug = raw_market.get("slug", "")
        source = MarketSource.UNKNOWN
        for prefix, src in GAME_SLUG_PREFIXES.items():
            if slug.startswith(prefix + "-"):
                source = src
                break
        
        # Create event dict for from_gamma_response
        event = {
            "id": raw_market.get("eventId", ""),
            "title": raw_market.get("question", ""),
            "slug": slug,
        }
        
        market = Market.from_gamma_response(raw_market, event, source)
        if market:
            # Mark as verified
            market.is_verified = True
            market.polymarket_url = generate_polymarket_url(slug)
            logger.info(
                "Verified market %s: %s (liq: $%.0f)",
                market_id, market.question, market.liquidity_usd
            )
        
        return market
