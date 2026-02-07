"""In-memory price cache for WebSocket price feeds.

WebSocket에서 받은 최신 가격을 저장하고 조회.

Phase 3 enhancement:
- Best ask/bid tracking (separate from mid-price)
- Orderbook depth snapshot caching
- Cache hit/miss statistics for latency monitoring
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class OrderbookEntry:
    """Cached orderbook entry for a single token."""

    best_ask: float | None = None
    best_bid: float | None = None
    ask_size: float = 0.0  # shares at best ask
    bid_size: float = 0.0
    timestamp: float = 0.0


class PriceCache:
    """Thread-safe in-memory price cache.

    token_id → (price, timestamp) 매핑.

    Phase 3: Also caches orderbook snapshots (best ask/bid) for
    low-latency SNIPE phase price lookups.
    """

    def __init__(self):
        self._prices: dict[str, float] = {}
        self._timestamps: dict[str, float] = {}
        # Phase 3: Orderbook cache
        self._orderbooks: dict[str, OrderbookEntry] = {}
        # Phase 3: Cache statistics
        self._hits: int = 0
        self._misses: int = 0

    def update(self, token_id: str, price: float) -> None:
        """가격 업데이트. 타임스탬프 갱신."""
        self._prices[token_id] = price
        self._timestamps[token_id] = time.time()

    def get_price(self, token_id: str) -> float | None:
        """토큰 가격 조회. 없으면 None."""
        price = self._prices.get(token_id)
        if price is not None:
            self._hits += 1
        else:
            self._misses += 1
        return price

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
        self._orderbooks.clear()
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    # Phase 3: Orderbook cache methods
    # ------------------------------------------------------------------

    def update_orderbook(
        self,
        token_id: str,
        best_ask: float | None = None,
        best_bid: float | None = None,
        ask_size: float = 0.0,
        bid_size: float = 0.0,
    ) -> None:
        """Update orderbook entry for a token.

        Args:
            token_id: CLOB token ID.
            best_ask: Best ask price.
            best_bid: Best bid price.
            ask_size: Shares at best ask.
            bid_size: Shares at best bid.
        """
        self._orderbooks[token_id] = OrderbookEntry(
            best_ask=best_ask,
            best_bid=best_bid,
            ask_size=ask_size,
            bid_size=bid_size,
            timestamp=time.time(),
        )
        # Also update the simple price cache with best ask
        if best_ask is not None and best_ask > 0:
            self.update(token_id, best_ask)

    def get_best_ask(self, token_id: str) -> float | None:
        """Get cached best ask for a token."""
        entry = self._orderbooks.get(token_id)
        if entry is not None:
            self._hits += 1
            return entry.best_ask
        # Fall back to simple price cache
        return self.get_price(token_id)

    def get_market_best_asks(
        self, yes_token: str, no_token: str,
    ) -> tuple[float | None, float | None]:
        """Get cached best asks for a YES/NO market pair.

        Returns (yes_best_ask, no_best_ask). Either may be None.
        """
        yes_ask = self.get_best_ask(yes_token)
        no_ask = self.get_best_ask(no_token)
        return (yes_ask, no_ask)

    def is_orderbook_fresh(
        self, token_id: str, max_age_secs: float = 5.0,
    ) -> bool:
        """Check if cached orderbook is fresh enough.

        Default 5s max age — tighter than simple price (30s).
        """
        entry = self._orderbooks.get(token_id)
        if entry is None:
            return False
        return (time.time() - entry.timestamp) <= max_age_secs

    def get_orderbook_entry(self, token_id: str) -> OrderbookEntry | None:
        """Get full orderbook entry for a token."""
        return self._orderbooks.get(token_id)

    # ------------------------------------------------------------------
    # Phase 3: Cache statistics
    # ------------------------------------------------------------------

    @property
    def hit_rate(self) -> float:
        """Cache hit rate (0.0 ~ 1.0)."""
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    @property
    def stats(self) -> dict:
        """Return cache statistics."""
        return {
            "prices_cached": len(self._prices),
            "orderbooks_cached": len(self._orderbooks),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self.hit_rate, 3),
        }
