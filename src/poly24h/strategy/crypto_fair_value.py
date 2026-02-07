"""Crypto Fair Value Calculator (F-021).

Calculates fair probability for crypto 1H markets using technical analysis:
- RSI (Relative Strength Index): Oversold/overbought detection
- Bollinger Bands: Price relative to volatility envelope

When RSI < 30 (oversold) and price near BB lower → high UP probability
When RSI > 70 (overbought) and price near BB upper → low UP probability
"""

from __future__ import annotations

import logging
from typing import List, Tuple

import aiohttp

logger = logging.getLogger(__name__)


class CryptoFairValueCalculator:
    """Calculates fair value for crypto 1H markets using technical analysis.
    
    Usage:
        calc = CryptoFairValueCalculator()
        ohlcv = await calc.fetch_binance_ohlcv("BTCUSDT", "1h", 20)
        closes = [c["close"] for c in ohlcv]
        
        rsi = calc.calculate_rsi(closes, period=14)
        bb_lower, bb_mid, bb_upper = calc.calculate_bollinger_bands(closes, period=20)
        
        fair_prob = calc.calculate_fair_probability(rsi, closes[-1], bb_lower, bb_upper)
        is_under = calc.is_undervalued("YES", 0.40, fair_prob)
    """
    
    BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
    
    async def fetch_binance_ohlcv(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 20,
    ) -> List[dict]:
        """Fetch OHLCV data from Binance public API.
        
        Args:
            symbol: Trading pair (e.g., "BTCUSDT", "ETHUSDT")
            interval: Candle interval (e.g., "1h", "4h", "1d")
            limit: Number of candles to fetch
        
        Returns:
            List of dicts with keys: open, high, low, close, volume, timestamp
        """
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "symbol": symbol.upper(),
                    "interval": interval,
                    "limit": limit,
                }
                async with session.get(
                    self.BINANCE_KLINES_URL,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            "Binance API error: %s %s",
                            response.status, await response.text()
                        )
                        return []
                    
                    raw = await response.json()
                    
                    # Binance klines format:
                    # [open_time, open, high, low, close, volume, close_time, ...]
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
                    
        except Exception as e:
            logger.error("Failed to fetch Binance OHLCV for %s: %s", symbol, e)
            return []
    
    def calculate_rsi(
        self,
        closes: List[float],
        period: int = 14,
    ) -> float:
        """Calculate RSI (Relative Strength Index).
        
        RSI = 100 - (100 / (1 + RS))
        RS = Average Gain / Average Loss
        
        Args:
            closes: List of closing prices (oldest first)
            period: RSI period (default 14)
        
        Returns:
            RSI value (0-100). Returns 50.0 if insufficient data.
        """
        if len(closes) < period + 1:
            return 50.0  # Neutral default
        
        # Calculate price changes
        changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        
        # Separate gains and losses
        gains = [max(0, c) for c in changes]
        losses = [abs(min(0, c)) for c in changes]
        
        # Use only the last 'period' changes
        recent_gains = gains[-period:]
        recent_losses = losses[-period:]
        
        avg_gain = sum(recent_gains) / period
        avg_loss = sum(recent_losses) / period
        
        # Handle edge case: no losses
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        
        # Handle edge case: no gains
        if avg_gain == 0:
            return 0.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def calculate_bollinger_bands(
        self,
        closes: List[float],
        period: int = 20,
        std_dev: int = 2,
    ) -> Tuple[float, float, float]:
        """Calculate Bollinger Bands.
        
        Middle Band = SMA(period)
        Upper Band = Middle + (std_dev × standard deviation)
        Lower Band = Middle - (std_dev × standard deviation)
        
        Args:
            closes: List of closing prices (oldest first)
            period: SMA period (default 20)
            std_dev: Number of standard deviations (default 2)
        
        Returns:
            Tuple of (lower, middle, upper) band values.
        """
        if len(closes) < period:
            # Use available data if insufficient
            period = len(closes)
            if period == 0:
                return (0.0, 0.0, 0.0)
        
        # Use the last 'period' closes
        window = closes[-period:]
        
        # Calculate SMA (middle band)
        middle = sum(window) / len(window)
        
        # Calculate standard deviation
        variance = sum((x - middle) ** 2 for x in window) / len(window)
        std = variance ** 0.5
        
        # Calculate bands
        upper = middle + (std_dev * std)
        lower = middle - (std_dev * std)
        
        return (lower, middle, upper)
    
    def calculate_fair_probability(
        self,
        rsi: float,
        price: float,
        bb_lower: float,
        bb_upper: float,
    ) -> float:
        """Calculate fair UP probability based on technical indicators.
        
        Logic:
        - RSI < 30 (oversold) → expect bounce → UP prob increases
        - RSI > 70 (overbought) → expect pullback → UP prob decreases
        - Price near BB lower → mean reversion up likely
        - Price near BB upper → mean reversion down likely
        
        Args:
            rsi: RSI value (0-100)
            price: Current price
            bb_lower: Bollinger Band lower value
            bb_upper: Bollinger Band upper value
        
        Returns:
            Fair UP probability (0.0 to 1.0)
        """
        # Base probability: neutral
        prob = 0.50
        
        # === RSI Component ===
        # RSI contribution: -0.25 to +0.25
        if rsi <= 30:
            # Oversold: strong UP signal
            # Linear scale from RSI 30 → 0: 0 → +0.25
            rsi_factor = (30 - rsi) / 30 * 0.25
            prob += rsi_factor
        elif rsi >= 70:
            # Overbought: strong DOWN signal
            # Linear scale from RSI 70 → 100: 0 → -0.25
            rsi_factor = (rsi - 70) / 30 * 0.25
            prob -= rsi_factor
        else:
            # Neutral RSI (30-70): minor adjustment toward 50
            # Slight weight toward extremes
            if rsi < 50:
                prob += (50 - rsi) / 100 * 0.05
            else:
                prob -= (rsi - 50) / 100 * 0.05
        
        # === Bollinger Band Component ===
        # BB contribution: -0.15 to +0.15
        bb_range = bb_upper - bb_lower
        if bb_range > 0:
            bb_middle = (bb_upper + bb_lower) / 2
            
            if price <= bb_lower:
                # At or below lower band: strong UP signal
                prob += 0.15
            elif price >= bb_upper:
                # At or above upper band: strong DOWN signal
                prob -= 0.15
            else:
                # Within bands: proportional adjustment
                # Position: -1 (at lower) to +1 (at upper)
                position = (price - bb_middle) / (bb_range / 2)
                # Invert: below middle → positive (expect up)
                bb_factor = -position * 0.10
                prob += bb_factor
        
        # Clamp to valid range
        return max(0.0, min(1.0, prob))
    
    def is_undervalued(
        self,
        side: str,
        market_price: float,
        fair_prob: float,
        margin: float = 0.05,
    ) -> bool:
        """Check if market price is undervalued for given side.
        
        Args:
            side: "YES" (UP) or "NO" (DOWN)
            market_price: Current market price for this side
            fair_prob: Calculated fair UP probability
            margin: Safety margin (default 0.05 = 5%)
        
        Returns:
            True if the side is undervalued.
        """
        if side.upper() == "YES":
            # YES (UP) side
            threshold = fair_prob - margin
            return market_price < threshold
        else:
            # NO (DOWN) side: fair prob = 1 - fair_up_prob
            down_fair_prob = 1.0 - fair_prob
            threshold = down_fair_prob - margin
            return market_price < threshold
    
    def get_value_scores(
        self,
        market_yes_price: float,
        market_no_price: float,
        fair_up_prob: float,
    ) -> Tuple[float, float]:
        """Calculate value scores for both sides.
        
        Returns:
            Tuple of (yes_score, no_score). Positive = undervalued.
        """
        fair_down_prob = 1.0 - fair_up_prob
        
        yes_score = fair_up_prob - market_yes_price
        no_score = fair_down_prob - market_no_price
        
        return (yes_score, no_score)
