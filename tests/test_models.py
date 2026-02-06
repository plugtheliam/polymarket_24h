"""Tests for F-001: Data Models (Market, Opportunity, MarketSource, ArbType)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from poly24h.models.market import Market, MarketSource
from poly24h.models.opportunity import ArbType, Opportunity

# ---------------------------------------------------------------------------
# MarketSource enum
# ---------------------------------------------------------------------------


class TestMarketSource:
    def test_hourly_crypto_value(self):
        assert MarketSource.HOURLY_CRYPTO.value == "hourly_crypto"

    def test_nba_value(self):
        assert MarketSource.NBA.value == "nba"

    def test_nhl_value(self):
        assert MarketSource.NHL.value == "nhl"

    def test_tennis_value(self):
        assert MarketSource.TENNIS.value == "tennis"

    def test_soccer_value(self):
        assert MarketSource.SOCCER.value == "soccer"

    def test_esports_value(self):
        assert MarketSource.ESPORTS.value == "esports"

    def test_from_string(self):
        assert MarketSource("nba") == MarketSource.NBA


# ---------------------------------------------------------------------------
# ArbType enum
# ---------------------------------------------------------------------------


class TestArbType:
    def test_single_condition(self):
        assert ArbType.SINGLE_CONDITION.value == "single_condition"

    def test_negrisk(self):
        assert ArbType.NEGRISK.value == "negrisk"


# ---------------------------------------------------------------------------
# Market dataclass
# ---------------------------------------------------------------------------


class TestMarket:
    def test_create_market(self, sample_market):
        assert sample_market.id == "12345"
        assert sample_market.source == MarketSource.HOURLY_CRYPTO
        assert sample_market.yes_price == 0.45
        assert sample_market.no_price == 0.40

    def test_total_cost(self, sample_market):
        """total_cost = yes_price + no_price"""
        assert sample_market.total_cost == pytest.approx(0.85)

    def test_spread(self, sample_market):
        """spread = 1.0 - total_cost"""
        assert sample_market.spread == pytest.approx(0.15)

    def test_spread_no_arb(self, no_arb_market):
        """Negative spread when total > 1.0"""
        assert no_arb_market.spread == pytest.approx(-0.01)

    def test_is_expired_false(self, sample_market):
        """Market ending in 1 hour should not be expired."""
        assert sample_market.is_expired is False

    def test_is_expired_true(self):
        """Market that ended 1 hour ago should be expired."""
        market = Market(
            id="exp",
            question="expired",
            source=MarketSource.HOURLY_CRYPTO,
            yes_token_id="y",
            no_token_id="n",
            yes_price=0.5,
            no_price=0.5,
            liquidity_usd=1000.0,
            end_date=datetime.now(tz=timezone.utc) - timedelta(hours=1),
            event_id="e",
            event_title="expired",
        )
        assert market.is_expired is True

    def test_from_gamma_response(self, sample_gamma_market_dict):
        """Market.from_gamma_response should parse Gamma API dict."""
        event = {
            "id": "evt_999",
            "title": "BTC 1 hour market",
        }
        market = Market.from_gamma_response(
            sample_gamma_market_dict, event, MarketSource.HOURLY_CRYPTO
        )
        assert market is not None
        assert market.id == "99999"
        assert market.yes_price == pytest.approx(0.45)
        assert market.no_price == pytest.approx(0.55)
        assert market.yes_token_id == "tok_yes_999"
        assert market.no_token_id == "tok_no_999"
        assert market.event_id == "evt_999"

    def test_from_gamma_response_list_prices(self):
        """outcomePrices can be a real list (not JSON string)."""
        end_date = (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat()
        raw = {
            "id": "111",
            "question": "test",
            "outcomePrices": [0.60, 0.40],
            "clobTokenIds": ["tok_a", "tok_b"],
            "liquidity": 3000,
            "endDate": end_date,
            "active": True,
            "closed": False,
        }
        market = Market.from_gamma_response(raw, {"id": "e1", "title": "t"}, MarketSource.NBA)
        assert market is not None
        assert market.yes_price == pytest.approx(0.60)

    def test_from_gamma_response_missing_prices(self):
        """Should return None if outcomePrices missing."""
        raw = {"id": "111", "question": "test", "clobTokenIds": ["a", "b"]}
        assert Market.from_gamma_response(raw, {}, MarketSource.NBA) is None

    def test_from_gamma_response_missing_token_ids(self):
        """Should return None if clobTokenIds missing."""
        raw = {"id": "111", "question": "test", "outcomePrices": [0.5, 0.5]}
        assert Market.from_gamma_response(raw, {}, MarketSource.NBA) is None

    def test_from_gamma_response_bad_json_string(self):
        """Should return None for malformed JSON string."""
        raw = {
            "id": "111",
            "question": "test",
            "outcomePrices": "not_valid_json",
            "clobTokenIds": '["a", "b"]',
        }
        assert Market.from_gamma_response(raw, {}, MarketSource.NBA) is None

    def test_from_gamma_response_fallback_event_end_date(self):
        """Should use event endDate when market endDate is missing."""
        end_date = (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat()
        raw = {
            "id": "111",
            "question": "test",
            "outcomePrices": [0.5, 0.5],
            "clobTokenIds": ["a", "b"],
            "liquidity": 1000,
            # no endDate on the market
        }
        event = {"id": "e1", "title": "t", "endDate": end_date}
        market = Market.from_gamma_response(raw, event, MarketSource.NBA)
        assert market is not None

    def test_from_gamma_response_no_end_date_at_all(self):
        """Should return None if neither market nor event has endDate."""
        raw = {
            "id": "111",
            "question": "test",
            "outcomePrices": [0.5, 0.5],
            "clobTokenIds": ["a", "b"],
            "liquidity": 1000,
        }
        assert Market.from_gamma_response(raw, {"id": "e1", "title": "t"}, MarketSource.NBA) is None


# ---------------------------------------------------------------------------
# Opportunity dataclass
# ---------------------------------------------------------------------------


class TestOpportunity:
    def test_create_opportunity(self, sample_market):
        opp = Opportunity(
            market=sample_market,
            arb_type=ArbType.SINGLE_CONDITION,
            yes_price=0.45,
            no_price=0.40,
            total_cost=0.85,
            margin=0.15,
            roi_pct=17.647,
            recommended_size_usd=0.0,
            detected_at=datetime.now(tz=timezone.utc),
        )
        assert opp.margin == pytest.approx(0.15)
        assert opp.roi_pct == pytest.approx(17.647, rel=0.01)

    def test_opportunity_sorting_by_roi(self, sample_market):
        """Opportunities should be sortable by ROI descending."""
        now = datetime.now(tz=timezone.utc)
        opps = [
            Opportunity(
                market=sample_market, arb_type=ArbType.SINGLE_CONDITION,
                yes_price=0.5, no_price=0.45, total_cost=0.95, margin=0.05,
                roi_pct=5.26, recommended_size_usd=0, detected_at=now,
            ),
            Opportunity(
                market=sample_market, arb_type=ArbType.SINGLE_CONDITION,
                yes_price=0.45, no_price=0.40, total_cost=0.85, margin=0.15,
                roi_pct=17.65, recommended_size_usd=0, detected_at=now,
            ),
            Opportunity(
                market=sample_market, arb_type=ArbType.SINGLE_CONDITION,
                yes_price=0.48, no_price=0.42, total_cost=0.90, margin=0.10,
                roi_pct=11.11, recommended_size_usd=0, detected_at=now,
            ),
        ]
        sorted_opps = sorted(opps, key=lambda o: o.roi_pct, reverse=True)
        assert sorted_opps[0].roi_pct == pytest.approx(17.65, rel=0.01)
        assert sorted_opps[1].roi_pct == pytest.approx(11.11, rel=0.01)
        assert sorted_opps[2].roi_pct == pytest.approx(5.26, rel=0.01)
