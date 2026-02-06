"""Market filtering logic — blacklist, hourly crypto, 24h window, liquidity."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from poly24h.config import BLACKLIST_PATTERNS, HOURLY_CRYPTO_PATTERNS


class MarketFilter:
    """Static filter methods for Polymarket markets."""

    @staticmethod
    def is_blacklisted(title: str) -> bool:
        """15분 크립토 마켓 블랙리스트 체크."""
        lower = title.lower()
        return any(p in lower for p in BLACKLIST_PATTERNS)

    @staticmethod
    def matches_hourly_crypto(title: str) -> bool:
        """1시간 크립토 패턴 매칭."""
        lower = title.lower()
        return any(p in lower for p in HOURLY_CRYPTO_PATTERNS)

    @staticmethod
    def is_within_24h(end_date_str: str) -> bool:
        """정산일이 현재로부터 24시간 이내인지 확인."""
        if not end_date_str:
            return False
        try:
            end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return False
        now = datetime.now(tz=timezone.utc)
        return now < end_date <= now + timedelta(hours=24)

    @staticmethod
    def is_active(raw_mkt: dict) -> bool:
        """active=True, closed=False인 마켓만."""
        return raw_mkt.get("active", True) and not raw_mkt.get("closed", False)

    @staticmethod
    def meets_min_liquidity(raw_mkt: dict, min_usd: float) -> bool:
        """최소 유동성 필터."""
        liquidity = float(raw_mkt.get("liquidity", 0) or 0)
        return liquidity >= min_usd
