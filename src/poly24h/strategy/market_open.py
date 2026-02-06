"""F-017: Market Open Sniper.

1시간 크립토 마켓 오픈 직후 저가 기회를 감지하고 스나이핑.

핵심:
- MarketOpenTimer: 다음 마켓 오픈 시간 예측
- OpenSniperDetector: 오픈 직후 저가 감지
- BinancePriceSignal: Binance 가격 기반 방향 신호 (P2 placeholder)

Reference: polymarket_trader/src/sniper/opportunity_detector.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from poly24h.models.market import Market


@dataclass
class SniperOpportunity:
    """감지된 스나이핑 기회.

    Attributes:
        market: 대상 마켓
        side: 'yes' or 'no'
        price: best ask 가격
        threshold: 감지 threshold
        seconds_since_open: 오픈 후 경과 시간
        confidence: 0.0 ~ 1.0
    """

    market: Market
    side: str
    price: float
    threshold: float
    seconds_since_open: float
    confidence: float

    @property
    def expected_roi(self) -> float:
        """(1.0 - price) / price * 100 — 예상 ROI %."""
        if self.price <= 0:
            return 0.0
        return (1.0 - self.price) / self.price * 100.0


class MarketOpenTimer:
    """1시간 마켓 오픈 타이밍 계산.

    1H 마켓은 매시간 정각에 오픈.
    """

    @staticmethod
    def next_open(now: datetime | None = None) -> datetime:
        """다음 정시 반환. 현재가 정시면 현재 반환."""
        if now is None:
            now = datetime.now(tz=timezone.utc)

        # 정각이면 그대로 반환
        if now.minute == 0 and now.second == 0 and now.microsecond == 0:
            return now

        # 다음 정시로 올림
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return next_hour

    @staticmethod
    def seconds_until_open(now: datetime | None = None) -> float:
        """다음 오픈까지 남은 초."""
        if now is None:
            now = datetime.now(tz=timezone.utc)
        next_open = MarketOpenTimer.next_open(now)
        delta = (next_open - now).total_seconds()
        return max(0.0, delta)

    @staticmethod
    def is_pre_open_window(
        now: datetime | None = None, window_secs: float = 30.0
    ) -> bool:
        """오픈 window_secs 이내인지 확인."""
        secs = MarketOpenTimer.seconds_until_open(now)
        return secs <= window_secs

    @staticmethod
    def seconds_since_market_open(
        market_end_time: datetime, now: datetime | None = None
    ) -> float:
        """마켓 오픈 후 경과 시간.

        1H 마켓이므로 open_time = end_time - 1hour.
        """
        if now is None:
            now = datetime.now(tz=timezone.utc)
        open_time = market_end_time - timedelta(hours=1)
        return (now - open_time).total_seconds()


class OpenSniperDetector:
    """마켓 오픈 직후 저가 기회 감지.

    Algorithm:
    1. seconds_since_open >= max_seconds → None (too late)
    2. yes_ask <= threshold → SniperOpp(side='yes')
    3. no_ask <= threshold → SniperOpp(side='no')
    4. Both sides above threshold → None
    5. Confidence = 1.0 - (seconds_since_open / max_seconds) * 0.5
    """

    def __init__(
        self, threshold: float = 0.45, max_seconds: float = 60.0
    ) -> None:
        self.threshold = threshold
        self.max_seconds = max_seconds

    def detect(
        self,
        market: Market,
        yes_ask: float,
        no_ask: float,
        seconds_since_open: float,
    ) -> SniperOpportunity | None:
        """저가 기회 감지.

        Args:
            market: 대상 마켓
            yes_ask: YES best ask 가격
            no_ask: NO best ask 가격
            seconds_since_open: 마켓 오픈 후 경과 시간

        Returns:
            SniperOpportunity if found, None otherwise.
        """
        # Too late
        if seconds_since_open >= self.max_seconds:
            return None

        confidence = self._calculate_confidence(seconds_since_open)

        # 양쪽 모두 threshold 이하면 더 싼 쪽 선택
        yes_below = yes_ask <= self.threshold
        no_below = no_ask <= self.threshold

        if yes_below and no_below:
            # 더 싼 쪽 우선
            if yes_ask <= no_ask:
                side, price = "yes", yes_ask
            else:
                side, price = "no", no_ask
        elif yes_below:
            side, price = "yes", yes_ask
        elif no_below:
            side, price = "no", no_ask
        else:
            return None

        return SniperOpportunity(
            market=market,
            side=side,
            price=price,
            threshold=self.threshold,
            seconds_since_open=seconds_since_open,
            confidence=confidence,
        )

    def _calculate_confidence(self, seconds_since_open: float) -> float:
        """시간 기반 confidence 계산.

        1.0 (오픈 직후) → 0.5 (max_seconds 직전).
        """
        if self.max_seconds <= 0:
            return 1.0
        decay = (seconds_since_open / self.max_seconds) * 0.5
        return max(0.0, min(1.0, 1.0 - decay))


class BinancePriceSignal:
    """Binance 가격 기반 방향 신호 (P2 — placeholder with simple logic).

    실제 API 호출 없이 가격 비교만 수행.
    """

    @staticmethod
    def get_signal(
        open_price: float,
        current_price: float,
        min_change_pct: float = 0.1,
    ) -> str:
        """가격 변동률 기반 방향 신호.

        Args:
            open_price: 마켓 오픈 시점 가격
            current_price: 현재 가격
            min_change_pct: 최소 변동률 % (초과해야 signal)

        Returns:
            'up', 'down', or 'neutral'
        """
        if open_price <= 0:
            return "neutral"

        change_pct = ((current_price - open_price) / open_price) * 100.0

        if change_pct > min_change_pct:
            return "up"
        if change_pct < -min_change_pct:
            return "down"
        return "neutral"
