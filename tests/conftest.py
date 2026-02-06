"""Shared test fixtures for poly24h."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from poly24h.models.market import Market, MarketSource


@pytest.fixture
def sample_market() -> Market:
    """A sample 1-hour crypto market with arb opportunity (YES+NO < 1.0)."""
    return Market(
        id="12345",
        question="Will BTC be above $100,000 at 2pm UTC?",
        source=MarketSource.HOURLY_CRYPTO,
        yes_token_id="tok_yes_123",
        no_token_id="tok_no_123",
        yes_price=0.45,
        no_price=0.40,
        liquidity_usd=5000.0,
        end_date=datetime.now(tz=timezone.utc) + timedelta(hours=1),
        event_id="evt_123",
        event_title="BTC Hourly",
    )


@pytest.fixture
def no_arb_market() -> Market:
    """A market with no arb opportunity (YES+NO >= 1.0)."""
    return Market(
        id="12346",
        question="Will ETH be above $5,000 at 3pm UTC?",
        source=MarketSource.HOURLY_CRYPTO,
        yes_token_id="tok_yes_456",
        no_token_id="tok_no_456",
        yes_price=0.50,
        no_price=0.51,
        liquidity_usd=8000.0,
        end_date=datetime.now(tz=timezone.utc) + timedelta(hours=1),
        event_id="evt_456",
        event_title="ETH Hourly",
    )


@pytest.fixture
def sample_gamma_market_dict() -> dict:
    """Raw market dict as returned by Gamma API."""
    end_date = (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat()
    return {
        "id": "99999",
        "question": "Will BTC be above $100,000 at 2pm UTC?",
        "outcomePrices": '[0.45, 0.55]',  # JSON string (Gamma API 특성)
        "clobTokenIds": '["tok_yes_999", "tok_no_999"]',
        "liquidity": "5000",
        "endDate": end_date,
        "active": True,
        "closed": False,
    }


@pytest.fixture
def sample_gamma_event(sample_gamma_market_dict) -> dict:
    """Raw event dict as returned by Gamma API."""
    end_date = (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat()
    return {
        "id": "evt_999",
        "title": "BTC 1 hour market",
        "endDate": end_date,
        "markets": [sample_gamma_market_dict],
        "enableNegRisk": False,
    }
