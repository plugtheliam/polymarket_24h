"""Crypto Fair Value Calculator (F-021).

Calculates fair probability for crypto 1H markets using:
- Momentum: 1-hour price change rate for direction prediction
- Volume Weighting: Volume spike detection for trend continuation
- RSI (backup): Oversold/overbought detection
- Bollinger Bands (backup): Price relative to volatility envelope

Primary signals: Momentum + Volume (proven more effective than RSI/BB alone)
"""

from __future__ import annotations

import logging
from typing import List, Tuple

import aiohttp

logger = logging.getLogger(__name__)


class CryptoFairValueCalculator:
    """Calculates fair value for crypto 1H markets using momentum + volume.
    
    Usage:
        calc = CryptoFairValueCalculator()
        ohlcv = await calc.fetch_binance_ohlcv("BTCUSDT", "1h", 24)
        closes = [c["close"] for c in ohlcv]
        
        # PRIMARY signals (momentum + volume)
        momentum = calc.calculate_1h_momentum(ohlcv)
        volume_spike, trend_dir = calc.calculate_volume_spike(ohlcv, lookback=10)
        
        # SECONDARY signals (RSI + BB)
        rsi = calc.calculate_rsi(closes, period=14)
        bb_lower, bb_mid, bb_upper = calc.calculate_bollinger_bands(closes, period=20)
        
        # Combined fair probability
        fair_prob = calc.calculate_fair_probability(
            rsi, closes[-1], bb_lower, bb_upper,
            momentum=momentum, volume_spike=volume_spike, trend_direction=trend_dir
        )
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
    
    def calculate_1h_momentum(
        self,
        ohlcv: List[dict],
    ) -> float:
        """Calculate 1-hour price momentum (change rate).
        
        Args:
            ohlcv: List of OHLCV dicts (needs at least 2 candles for 1h interval)
        
        Returns:
            Momentum as percentage change (-100 to +100).
            Positive = price going UP, Negative = price going DOWN.
        """
        if len(ohlcv) < 2:
            return 0.0
        
        # Use last candle's open vs current close for 1h change
        current_close = ohlcv[-1]["close"]
        prev_close = ohlcv[-2]["close"]
        
        if prev_close == 0:
            return 0.0
        
        momentum = ((current_close - prev_close) / prev_close) * 100
        return momentum
    
    def calculate_volume_spike(
        self,
        ohlcv: List[dict],
        lookback: int = 10,
    ) -> Tuple[float, float]:
        """Detect volume spike and return spike ratio and trend direction.
        
        Args:
            ohlcv: List of OHLCV dicts
            lookback: Number of candles for average volume calculation
        
        Returns:
            Tuple of (spike_ratio, trend_direction)
            - spike_ratio: current volume / average volume (1.0 = normal)
            - trend_direction: +1 if price up in current candle, -1 if down
        """
        if len(ohlcv) < 2:
            return (1.0, 0.0)
        
        current = ohlcv[-1]
        current_volume = current["volume"]
        
        # Calculate average volume over lookback period (excluding current)
        lookback_candles = ohlcv[-(lookback + 1):-1] if len(ohlcv) > lookback else ohlcv[:-1]
        if not lookback_candles:
            return (1.0, 0.0)
        
        avg_volume = sum(c["volume"] for c in lookback_candles) / len(lookback_candles)
        
        if avg_volume == 0:
            return (1.0, 0.0)
        
        spike_ratio = current_volume / avg_volume
        
        # Determine trend direction in current candle
        trend_direction = 1.0 if current["close"] > current["open"] else -1.0
        
        return (spike_ratio, trend_direction)
    
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
        momentum: float = 0.0,
        volume_spike: float = 1.0,
        trend_direction: float = 0.0,
    ) -> float:
        """Calculate fair UP probability based on technical indicators.
        
        PRIMARY SIGNALS (momentum + volume):
        - Momentum: Recent 1h price change predicts continuation
        - Volume Spike: High volume = trend likely continues
        
        SECONDARY SIGNALS (RSI + BB):
        - RSI < 30 (oversold) → expect bounce → UP prob increases
        - RSI > 70 (overbought) → expect pullback → UP prob decreases
        - Price near BB lower → mean reversion up likely
        - Price near BB upper → mean reversion down likely
        
        Args:
            rsi: RSI value (0-100)
            price: Current price
            bb_lower: Bollinger Band lower value
            bb_upper: Bollinger Band upper value
            momentum: 1h price change percentage (positive = up)
            volume_spike: Current volume / average volume ratio
            trend_direction: +1 (up candle) or -1 (down candle)
        
        Returns:
            Fair UP probability (0.0 to 1.0)
        """
        # Base probability: neutral
        prob = 0.50
        
        # === PRIMARY: Momentum Component ===
        # Momentum contribution: -0.25 to +0.25
        # Scale: ±2% price change → ±0.25 probability adjustment
        momentum_factor = max(-0.25, min(0.25, momentum / 2 * 0.25))
        prob += momentum_factor
        
        # === PRIMARY: Volume Spike Component ===
        # Volume spike amplifies the trend direction signal
        # Spike > 2x average = strong continuation signal
        if volume_spike >= 2.0:
            # Strong volume spike: +/- 0.15 based on trend direction
            volume_contribution = trend_direction * 0.15
            prob += volume_contribution
        elif volume_spike >= 1.5:
            # Moderate spike: +/- 0.08
            volume_contribution = trend_direction * 0.08
            prob += volume_contribution
        # Below 1.5x: no significant volume signal
        
        # === SECONDARY: RSI Component (reduced weight) ===
        # RSI contribution: -0.10 to +0.10 (reduced from 0.25)
        if rsi <= 30:
            rsi_factor = (30 - rsi) / 30 * 0.10
            prob += rsi_factor
        elif rsi >= 70:
            rsi_factor = (rsi - 70) / 30 * 0.10
            prob -= rsi_factor
        
        # === SECONDARY: Bollinger Band Component (reduced weight) ===
        # BB contribution: -0.08 to +0.08 (reduced from 0.15)
        bb_range = bb_upper - bb_lower
        if bb_range > 0:
            if price <= bb_lower:
                prob += 0.08
            elif price >= bb_upper:
                prob -= 0.08
            else:
                bb_middle = (bb_upper + bb_lower) / 2
                position = (price - bb_middle) / (bb_range / 2)
                bb_factor = -position * 0.05
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
