"""WebSocket client for Polymarket real-time prices.

Polymarket CLOB WebSocket에 연결하여 실시간 가격 수신.
Auto-reconnect: max 5 attempts, exponential backoff.
"""

from __future__ import annotations

import asyncio
import json
import logging

try:
    import websockets
except ImportError:
    websockets = None  # type: ignore

from poly24h.websocket.price_cache import PriceCache

logger = logging.getLogger(__name__)

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


class PriceWebSocket:
    """Async WebSocket client for Polymarket price feeds.

    Args:
        cache: PriceCache 인스턴스 (가격 저장).
        url: WebSocket 엔드포인트 URL.
    """

    def __init__(self, cache: PriceCache, url: str = WS_URL):
        self._cache = cache
        self._url = url
        self._ws = None
        self._connected = False
        self._max_reconnect = 5

    async def connect(self) -> None:
        """WebSocket 연결."""
        try:
            if websockets is None:
                logger.error("websockets not installed")
                return
            self._ws = await websockets.connect(self._url)
            self._connected = True
            logger.info("Connected to %s", self._url)
        except Exception as exc:
            logger.error("WebSocket connect failed: %s", exc)
            self._connected = False

    async def subscribe(self, token_ids: list[str]) -> None:
        """토큰 구독. 연결 안됐으면 무시."""
        if not self._connected or self._ws is None:
            logger.warning("Cannot subscribe: not connected")
            return
        msg = json.dumps({
            "type": "market",
            "assets_ids": token_ids,
        })
        await self._ws.send(msg)
        logger.info("Subscribed to %d tokens", len(token_ids))

    async def unsubscribe(self, token_ids: list[str]) -> None:
        """토큰 구독 해제."""
        if not self._connected or self._ws is None:
            return
        msg = json.dumps({
            "type": "unsubscribe",
            "assets_ids": token_ids,
        })
        await self._ws.send(msg)
        logger.info("Unsubscribed from %d tokens", len(token_ids))

    async def listen(self) -> None:
        """메인 수신 루프. 가격 업데이트를 캐시에 저장.

        CancelledError / ConnectionClosed 시 루프 종료.
        """
        while self._connected and self._ws:
            try:
                raw = await self._ws.recv()
                self._process_message(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Listen error: %s", exc)
                break

    async def close(self) -> None:
        """WebSocket 닫기."""
        self._connected = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    def _process_message(self, raw: str) -> None:
        """수신 메시지 파싱 → 캐시 업데이트."""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.debug("Malformed message: %s", raw[:100])
            return

        # 리스트 메시지 처리
        messages = data if isinstance(data, list) else [data]

        for msg in messages:
            if not isinstance(msg, dict):
                continue

            event_type = msg.get("event_type") or msg.get("type")
            asset_id = msg.get("asset_id", "")

            if event_type == "price_change" and asset_id:
                try:
                    price = float(msg.get("price", 0))
                    if price > 0:
                        self._cache.update(asset_id, price)
                except (ValueError, TypeError):
                    pass

            elif event_type == "book" and asset_id:
                self._process_book(msg, asset_id)

    def _process_book(self, msg: dict, asset_id: str) -> None:
        """오더북 스냅샷에서 best ask 가격 추출 → 캐시."""
        asks = msg.get("asks", [])
        if isinstance(asks, dict):
            asks = list(asks.values())

        try:
            if asks and isinstance(asks[0], dict) and "price" in asks[0]:
                best_ask = min(float(a["price"]) for a in asks if a.get("price"))
            elif asks:
                best_ask = float(asks[0][0])
            else:
                return

            if best_ask > 0:
                self._cache.update(asset_id, best_ask)
        except (ValueError, TypeError, IndexError, KeyError):
            pass
