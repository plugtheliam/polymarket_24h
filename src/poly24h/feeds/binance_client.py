"""Binance Public API client (F-021).

Provides unauthenticated access to Binance market data:
- OHLCV (klines) for technical analysis
- Current price
- 24h ticker stats

No API key required for public endpoints.
"""

from __future__ import annotations

import logging
from typing import List, Optional

import aiohttp

logger = logging.getLogger(__name__)


class BinanceClient:
    """Async client for Binance public API.
    
    Usage:
        async with BinanceClient() as client:
            klines = await client.get_klines("BTCUSDT", "1h", 20)
            price = await client.get_price("BTCUSDT")
    """
    
    BASE_URL = "https://api.binance.com"
    
    def __init__(self, timeout: float = 10.0):
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self) -> "BinanceClient":
        self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._session:
            await self._session.close()
            self._session = None
    
    async def _get(self, endpoint: str, params: dict) -> Optional[dict | list]:
        """Make GET request to Binance API."""
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        
        url = f"{self.BASE_URL}{endpoint}"
        try:
            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning(
                        "Binance API error: %s %s", resp.status, await resp.text()
                    )
                    return None
                return await resp.json()
        except Exception as e:
            logger.error("Binance request failed: %s", e)
            return None
    
    async def get_klines(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 20,
    ) -> List[dict]:
        """Fetch OHLCV klines data.
        
        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            interval: Candle interval (e.g., "1m", "1h", "1d")
            limit: Number of candles (max 1000)
        
        Returns:
            List of OHLCV dicts with keys:
            - timestamp: Open time (milliseconds)
            - open, high, low, close, volume: floats
        """
        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": min(limit, 1000),
        }
        
        raw = await self._get("/api/v3/klines", params)
        if not raw:
            return []
        
        result = []
        for candle in raw:
            result.append({
                "timestamp": candle[0],
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]),
            })
        return result
    
    async def get_price(self, symbol: str) -> Optional[float]:
        """Get current price for symbol.
        
        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
        
        Returns:
            Current price or None on error.
        """
        params = {"symbol": symbol.upper()}
        data = await self._get("/api/v3/ticker/price", params)
        if data and "price" in data:
            return float(data["price"])
        return None
    
    async def get_24h_change(self, symbol: str) -> Optional[dict]:
        """Get 24h ticker change.
        
        Args:
            symbol: Trading pair
        
        Returns:
            Dict with priceChange, priceChangePercent, volume, etc.
        """
        params = {"symbol": symbol.upper()}
        data = await self._get("/api/v3/ticker/24hr", params)
        if data:
            return {
                "priceChange": float(data.get("priceChange", 0)),
                "priceChangePercent": float(data.get("priceChangePercent", 0)),
                "volume": float(data.get("volume", 0)),
                "quoteVolume": float(data.get("quoteVolume", 0)),
            }
        return None
    
    @staticmethod
    def symbol_for_crypto(asset: str) -> str:
        """Convert asset name to Binance symbol.
        
        Examples:
            "BTC" → "BTCUSDT"
            "ETH" → "ETHUSDT"
        """
        asset = asset.upper().strip()
        if asset.endswith("USDT"):
            return asset
        return f"{asset}USDT"
