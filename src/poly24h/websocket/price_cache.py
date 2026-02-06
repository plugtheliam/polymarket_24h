"""In-memory price cache for WebSocket price feeds.

WebSocket에서 받은 최신 가격을 저장하고 조회.
"""

from __future__ import annotations

import time


class PriceCache:
    """Thread-safe in-memory price cache.

    token_id → (price, timestamp) 매핑.
    """

    def __init__(self):
        self._prices: dict[str, float] = {}
        self._timestamps: dict[str, float] = {}

    def update(self, token_id: str, price: float) -> None:
        """가격 업데이트. 타임스탬프 갱신."""
        self._prices[token_id] = price
        self._timestamps[token_id] = time.time()

    def get_price(self, token_id: str) -> float | None:
        """토큰 가격 조회. 없으면 None."""
        return self._prices.get(token_id)

    def get_market_prices(
        self, yes_token: str, no_token: str,
    ) -> tuple[float, float] | None:
        """YES/NO 토큰 가격 쌍 조회. 둘 다 있어야 반환."""
        yes_price = self._prices.get(yes_token)
        no_price = self._prices.get(no_token)
        if yes_price is None or no_price is None:
            return None
        return (yes_price, no_price)

    def is_stale(self, token_id: str, max_age_secs: float = 30.0) -> bool:
        """가격이 오래되었는지 확인. 없으면 stale."""
        ts = self._timestamps.get(token_id)
        if ts is None:
            return True
        return (time.time() - ts) > max_age_secs

    def clear(self) -> None:
        """캐시 초기화."""
        self._prices.clear()
        self._timestamps.clear()
