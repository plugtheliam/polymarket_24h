"""Tests for F-001: Configuration (BotConfig, MARKET_SOURCES, patterns)."""

from __future__ import annotations

from poly24h.config import (
    BLACKLIST_PATTERNS,
    HOURLY_CRYPTO_PATTERNS,
    MARKET_SOURCES,
    BotConfig,
)


class TestMarketSources:
    def test_hourly_crypto_enabled(self):
        assert MARKET_SOURCES["hourly_crypto"]["enabled"] is True

    def test_nba_enabled(self):
        assert MARKET_SOURCES["nba"]["enabled"] is True

    def test_nhl_disabled(self):
        assert MARKET_SOURCES["nhl"]["enabled"] is False

    def test_hourly_crypto_fee_zero(self):
        assert MARKET_SOURCES["hourly_crypto"]["fee"] == 0

    def test_min_liquidity(self):
        assert MARKET_SOURCES["hourly_crypto"]["min_liquidity_usd"] == 3000
        assert MARKET_SOURCES["nba"]["min_liquidity_usd"] == 5000

    def test_all_sources_have_required_keys(self):
        required = {"enabled", "min_liquidity_usd", "min_spread", "fee"}
        for name, cfg in MARKET_SOURCES.items():
            for key in required:
                assert key in cfg, f"{name} missing key: {key}"


class TestBlacklistPatterns:
    def test_15min_patterns(self):
        """All 15-minute patterns should be present."""
        assert "15 min" in BLACKLIST_PATTERNS
        assert "15-min" in BLACKLIST_PATTERNS
        assert "15-minute" in BLACKLIST_PATTERNS
        assert "15min" in BLACKLIST_PATTERNS

    def test_blacklist_matches(self):
        """Blacklist should catch 15-min crypto markets."""
        title = "Will BTC go up in the next 15 minutes?"
        lower = title.lower()
        assert any(p in lower for p in BLACKLIST_PATTERNS)

    def test_blacklist_no_match_hourly(self):
        """Blacklist should NOT match hourly markets."""
        title = "Will BTC be above $100,000 in 1 hour?"
        lower = title.lower()
        assert not any(p in lower for p in BLACKLIST_PATTERNS)


class TestHourlyCryptoPatterns:
    def test_patterns_present(self):
        assert "1 hour" in HOURLY_CRYPTO_PATTERNS
        assert "1-hour" in HOURLY_CRYPTO_PATTERNS
        assert "hourly" in HOURLY_CRYPTO_PATTERNS
        assert "1h" in HOURLY_CRYPTO_PATTERNS

    def test_hourly_matches(self):
        title = "Will BTC be above $100,000 in 1 hour?"
        lower = title.lower()
        assert any(p in lower for p in HOURLY_CRYPTO_PATTERNS)


class TestBotConfig:
    def test_default_config(self):
        """Config with no env vars should have sensible defaults."""
        config = BotConfig()
        assert config.dry_run is True
        assert config.scan_interval >= 10
        assert config.max_position_usd > 0

    def test_dry_run_default_true(self):
        config = BotConfig()
        assert config.dry_run is True

    def test_scan_interval_minimum(self):
        """Interval should be at least 10 seconds."""
        config = BotConfig(scan_interval=1)
        assert config.scan_interval >= 10

    def test_from_env(self, monkeypatch):
        """Config should load from environment variables."""
        monkeypatch.setenv("POLY24H_DRY_RUN", "false")
        monkeypatch.setenv("POLY24H_SCAN_INTERVAL", "30")
        monkeypatch.setenv("POLY24H_MAX_POSITION_USD", "500")
        config = BotConfig.from_env()
        assert config.dry_run is False
        assert config.scan_interval == 30
        assert config.max_position_usd == 500.0

    def test_from_env_defaults(self):
        """Config.from_env with no env vars should have safe defaults."""
        config = BotConfig.from_env()
        assert config.dry_run is True

    def test_enabled_sources(self):
        """Should return only enabled market sources."""
        config = BotConfig()
        enabled = config.enabled_sources()
        enabled_names = list(enabled.keys())
        assert "hourly_crypto" in enabled_names
        assert "nba" in enabled_names
        # nhl is disabled by default
        assert "nhl" not in enabled_names
