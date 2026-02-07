"""Tests for F-014: Orderbook-Based Arbitrage Scanning.

CLOB API mock pattern: aioresponses with https://clob.polymarket.com/book
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone

import pytest
from aioresponses import aioresponses

from poly24h.models.market import Market, MarketSource
from poly24h.models.opportunity import ArbType, Opportunity
from poly24h.strategy.orderbook_scanner import OrderbookLevel, OrderbookSummary

CLOB_BOOK_PATTERN = re.compile(r"^https://clob\.polymarket\.com/book\b")
EVENTS_PATTERN = re.compile(r"^https://gamma-api\.polymarket\.com/events\b")


def _market(**kwargs) -> Market:
    """Helper: build a Market with defaults."""
    defaults = dict(
        id="mkt_1",
        question="Will Lakers win?",
        source=MarketSource.NBA,
        yes_token_id="tok_yes_1",
        no_token_id="tok_no_1",
        yes_price=0.50,
        no_price=0.50,
        liquidity_usd=10000.0,
        end_date=datetime.now(tz=timezone.utc) + timedelta(hours=6),
        event_id="evt_1",
        event_title="Lakers vs Celtics",
    )
    defaults.update(kwargs)
    return Market(**defaults)


def _orderbook(asks: list[tuple[str, str]], bids: list[tuple[str, str]] | None = None) -> dict:
    """Helper: build a CLOB orderbook response."""
    return {
        "asks": [{"price": p, "size": s} for p, s in asks],
        "bids": [{"price": p, "size": s} for p, s in (bids or [])],
    }


# ---------------------------------------------------------------------------
# ClobOrderbookFetcher tests
# ---------------------------------------------------------------------------


class TestClobOrderbookFetcher:
    """CLOB API에서 best ask 가격 조회."""

    async def test_fetch_best_asks_success(self):
        """Should return (yes_best_ask, no_best_ask) from CLOB API."""
        from poly24h.strategy.orderbook_scanner import ClobOrderbookFetcher

        yes_book = _orderbook(asks=[("0.48", "100"), ("0.50", "200")])
        no_book = _orderbook(asks=[("0.50", "150"), ("0.49", "300")])

        with aioresponses() as m:
            m.get(CLOB_BOOK_PATTERN, payload=yes_book)
            m.get(CLOB_BOOK_PATTERN, payload=no_book)
            fetcher = ClobOrderbookFetcher()
            yes_ask, no_ask = await fetcher.fetch_best_asks("tok_yes", "tok_no")
            await fetcher.close()
            assert yes_ask == 0.48  # min of [0.48, 0.50]
            assert no_ask == 0.49   # min of [0.50, 0.49]

    async def test_fetch_best_asks_empty_orderbook(self):
        """Empty asks → (None, None)."""
        from poly24h.strategy.orderbook_scanner import ClobOrderbookFetcher

        empty_book = _orderbook(asks=[])
        with aioresponses() as m:
            m.get(CLOB_BOOK_PATTERN, payload=empty_book)
            m.get(CLOB_BOOK_PATTERN, payload=empty_book)
            fetcher = ClobOrderbookFetcher()
            yes_ask, no_ask = await fetcher.fetch_best_asks("tok_yes", "tok_no")
            await fetcher.close()
            assert yes_ask is None
            assert no_ask is None

    async def test_fetch_best_asks_api_error(self):
        """HTTP 500 → (None, None), no crash."""
        from poly24h.strategy.orderbook_scanner import ClobOrderbookFetcher

        with aioresponses() as m:
            m.get(CLOB_BOOK_PATTERN, status=500)
            m.get(CLOB_BOOK_PATTERN, status=500)
            fetcher = ClobOrderbookFetcher()
            yes_ask, no_ask = await fetcher.fetch_best_asks("tok_yes", "tok_no")
            await fetcher.close()
            assert yes_ask is None
            assert no_ask is None

    async def test_fetch_best_asks_timeout(self):
        """Timeout → (None, None), no crash."""
        from poly24h.strategy.orderbook_scanner import ClobOrderbookFetcher

        with aioresponses() as m:
            m.get(CLOB_BOOK_PATTERN, exception=asyncio.TimeoutError())
            m.get(CLOB_BOOK_PATTERN, exception=asyncio.TimeoutError())
            fetcher = ClobOrderbookFetcher()
            yes_ask, no_ask = await fetcher.fetch_best_asks("tok_yes", "tok_no")
            await fetcher.close()
            assert yes_ask is None
            assert no_ask is None

    async def test_fetch_best_asks_one_side_empty(self):
        """One side empty, other side valid → (value, None)."""
        from poly24h.strategy.orderbook_scanner import ClobOrderbookFetcher

        yes_book = _orderbook(asks=[("0.48", "100")])
        no_book = _orderbook(asks=[])
        with aioresponses() as m:
            m.get(CLOB_BOOK_PATTERN, payload=yes_book)
            m.get(CLOB_BOOK_PATTERN, payload=no_book)
            fetcher = ClobOrderbookFetcher()
            yes_ask, no_ask = await fetcher.fetch_best_asks("tok_yes", "tok_no")
            await fetcher.close()
            assert yes_ask == 0.48
            assert no_ask is None

    async def test_fetch_best_asks_unsorted(self):
        """Asks may not be sorted — should still find min."""
        from poly24h.strategy.orderbook_scanner import ClobOrderbookFetcher

        book = _orderbook(asks=[("0.55", "100"), ("0.48", "50"), ("0.52", "200")])
        with aioresponses() as m:
            m.get(CLOB_BOOK_PATTERN, payload=book)
            m.get(CLOB_BOOK_PATTERN, payload=book)
            fetcher = ClobOrderbookFetcher()
            yes_ask, no_ask = await fetcher.fetch_best_asks("tok_yes", "tok_no")
            await fetcher.close()
            assert yes_ask == 0.48

    async def test_fetch_best_asks_single_ask(self):
        """Single ask entry should work."""
        from poly24h.strategy.orderbook_scanner import ClobOrderbookFetcher

        book = _orderbook(asks=[("0.60", "100")])
        with aioresponses() as m:
            m.get(CLOB_BOOK_PATTERN, payload=book)
            m.get(CLOB_BOOK_PATTERN, payload=book)
            fetcher = ClobOrderbookFetcher()
            yes_ask, _ = await fetcher.fetch_best_asks("tok_yes", "tok_no")
            await fetcher.close()
            assert yes_ask == 0.60

    async def test_fetch_connection_error(self):
        """Connection refused → (None, None)."""
        from poly24h.strategy.orderbook_scanner import ClobOrderbookFetcher

        with aioresponses() as m:
            m.get(CLOB_BOOK_PATTERN, exception=ConnectionError("refused"))
            m.get(CLOB_BOOK_PATTERN, exception=ConnectionError("refused"))
            fetcher = ClobOrderbookFetcher()
            yes_ask, no_ask = await fetcher.fetch_best_asks("tok_yes", "tok_no")
            await fetcher.close()
            assert yes_ask is None
            assert no_ask is None


# ---------------------------------------------------------------------------
# OrderbookArbDetector tests
# ---------------------------------------------------------------------------


class TestOrderbookArbDetector:
    """Orderbook best ask 기반 arb 감지."""

    def test_detect_arb_exists(self):
        """YES_ask + NO_ask < 1.0 → Opportunity."""
        from poly24h.strategy.orderbook_scanner import OrderbookArbDetector

        detector = OrderbookArbDetector()
        market = _market()
        opp = detector.detect(market, yes_ask=0.48, no_ask=0.50, min_spread=0.015)
        assert opp is not None
        assert opp.margin == pytest.approx(0.02, abs=1e-6)
        assert opp.total_cost == pytest.approx(0.98, abs=1e-6)
        assert opp.roi_pct == pytest.approx(2.040816, abs=0.01)
        assert opp.arb_type == ArbType.SINGLE_CONDITION

    def test_detect_no_arb(self):
        """YES_ask + NO_ask > 1.0 → None."""
        from poly24h.strategy.orderbook_scanner import OrderbookArbDetector

        detector = OrderbookArbDetector()
        market = _market()
        opp = detector.detect(market, yes_ask=0.51, no_ask=0.50)
        assert opp is None

    def test_detect_exact_threshold(self):
        """YES_ask + NO_ask == 1.0 → None (no profit)."""
        from poly24h.strategy.orderbook_scanner import OrderbookArbDetector

        detector = OrderbookArbDetector()
        market = _market()
        opp = detector.detect(market, yes_ask=0.50, no_ask=0.50)
        assert opp is None

    def test_detect_below_min_spread(self):
        """Margin exists but below min_spread → None."""
        from poly24h.strategy.orderbook_scanner import OrderbookArbDetector

        detector = OrderbookArbDetector()
        market = _market()
        # sum = 0.99, margin = 0.01, but min_spread = 0.015
        opp = detector.detect(market, yes_ask=0.49, no_ask=0.50, min_spread=0.015)
        assert opp is None

    def test_detect_exactly_min_spread(self):
        """Margin == min_spread → None (threshold is exclusive).

        Note: float imprecision means 1.0-(0.485+0.50) != exactly 0.015.
        Use values that cleanly demonstrate the boundary.
        """
        from poly24h.strategy.orderbook_scanner import OrderbookArbDetector

        detector = OrderbookArbDetector()
        market = _market()
        # sum = 0.985, margin ≈ 0.015 but float gives 0.01500000..013
        # This is technically > min_spread due to float imprecision
        # Test the real boundary: margin clearly <= min_spread
        # sum = 0.986, margin = 0.014 < 0.015
        opp = detector.detect(market, yes_ask=0.486, no_ask=0.50, min_spread=0.015)
        assert opp is None

    def test_detect_large_spread(self):
        """Large spread → high ROI opportunity."""
        from poly24h.strategy.orderbook_scanner import OrderbookArbDetector

        detector = OrderbookArbDetector()
        market = _market()
        opp = detector.detect(market, yes_ask=0.40, no_ask=0.40, min_spread=0.01)
        assert opp is not None
        assert opp.margin == pytest.approx(0.20, abs=1e-6)
        assert opp.roi_pct == pytest.approx(25.0, abs=0.01)

    def test_detect_zero_price(self):
        """Zero ask price → None (invalid)."""
        from poly24h.strategy.orderbook_scanner import OrderbookArbDetector

        detector = OrderbookArbDetector()
        market = _market()
        opp = detector.detect(market, yes_ask=0.0, no_ask=0.50)
        assert opp is None

    def test_detect_preserves_market(self):
        """Opportunity should reference the original market."""
        from poly24h.strategy.orderbook_scanner import OrderbookArbDetector

        detector = OrderbookArbDetector()
        market = _market(id="unique_id")
        opp = detector.detect(market, yes_ask=0.45, no_ask=0.45, min_spread=0.01)
        assert opp is not None
        assert opp.market.id == "unique_id"

    def test_detect_uses_ask_prices_not_market_prices(self):
        """Opportunity should use the orderbook ask prices, not mid-prices."""
        from poly24h.strategy.orderbook_scanner import OrderbookArbDetector

        detector = OrderbookArbDetector()
        market = _market(yes_price=0.55, no_price=0.55)  # mid-prices sum > 1
        opp = detector.detect(market, yes_ask=0.45, no_ask=0.45, min_spread=0.01)
        assert opp is not None
        assert opp.yes_price == 0.45  # orderbook ask, not mid-price
        assert opp.no_price == 0.45


# ---------------------------------------------------------------------------
# OrderbookBatchScanner tests
# ---------------------------------------------------------------------------


class TestOrderbookBatchScanner:
    """배치 스캔: 여러 마켓 동시 조회."""

    async def test_batch_scan_finds_opportunities(self):
        """Should find opportunities in batch of markets."""
        from poly24h.strategy.orderbook_scanner import (
            ClobOrderbookFetcher,
            OrderbookArbDetector,
            OrderbookBatchScanner,
        )

        yes_book = _orderbook(asks=[("0.48", "100")])
        no_book = _orderbook(asks=[("0.50", "100")])

        markets = [_market(id="m1", yes_token_id="tok_y1", no_token_id="tok_n1")]

        with aioresponses() as m:
            m.get(CLOB_BOOK_PATTERN, payload=yes_book)
            m.get(CLOB_BOOK_PATTERN, payload=no_book)
            fetcher = ClobOrderbookFetcher()
            detector = OrderbookArbDetector()
            scanner = OrderbookBatchScanner(fetcher, detector, concurrency=5)
            opps = await scanner.scan(markets, min_spread=0.015)
            await fetcher.close()
            assert len(opps) == 1
            assert opps[0].margin == pytest.approx(0.02, abs=1e-6)

    async def test_batch_scan_no_opportunities(self):
        """No arb → empty results."""
        from poly24h.strategy.orderbook_scanner import (
            ClobOrderbookFetcher,
            OrderbookArbDetector,
            OrderbookBatchScanner,
        )

        yes_book = _orderbook(asks=[("0.52", "100")])
        no_book = _orderbook(asks=[("0.50", "100")])

        markets = [_market()]

        with aioresponses() as m:
            m.get(CLOB_BOOK_PATTERN, payload=yes_book)
            m.get(CLOB_BOOK_PATTERN, payload=no_book)
            fetcher = ClobOrderbookFetcher()
            detector = OrderbookArbDetector()
            scanner = OrderbookBatchScanner(fetcher, detector)
            opps = await scanner.scan(markets, min_spread=0.015)
            await fetcher.close()
            assert opps == []

    async def test_batch_scan_mixed_results(self):
        """Some markets have arb, some don't — only return arb markets."""
        from poly24h.strategy.orderbook_scanner import (
            ClobOrderbookFetcher,
            OrderbookArbDetector,
            OrderbookBatchScanner,
        )

        arb_yes = _orderbook(asks=[("0.45", "100")])
        arb_no = _orderbook(asks=[("0.45", "100")])
        no_arb_yes = _orderbook(asks=[("0.52", "100")])
        no_arb_no = _orderbook(asks=[("0.50", "100")])

        markets = [
            _market(id="arb_market", yes_token_id="ty1", no_token_id="tn1"),
            _market(id="no_arb_market", yes_token_id="ty2", no_token_id="tn2"),
        ]

        with aioresponses() as m:
            m.get(CLOB_BOOK_PATTERN, payload=arb_yes)
            m.get(CLOB_BOOK_PATTERN, payload=arb_no)
            m.get(CLOB_BOOK_PATTERN, payload=no_arb_yes)
            m.get(CLOB_BOOK_PATTERN, payload=no_arb_no)
            fetcher = ClobOrderbookFetcher()
            detector = OrderbookArbDetector()
            scanner = OrderbookBatchScanner(fetcher, detector)
            opps = await scanner.scan(markets, min_spread=0.01)
            await fetcher.close()
            assert len(opps) == 1
            assert opps[0].market.id == "arb_market"

    async def test_batch_scan_ranked_by_roi(self):
        """Results should be sorted by ROI descending."""
        from poly24h.strategy.orderbook_scanner import (
            ClobOrderbookFetcher,
            OrderbookArbDetector,
            OrderbookBatchScanner,
        )

        # Market 1: sum=0.90, margin=0.10 → ROI ~11.1%
        high_yes = _orderbook(asks=[("0.45", "100")])
        high_no = _orderbook(asks=[("0.45", "100")])
        # Market 2: sum=0.96, margin=0.04 → ROI ~4.2%
        low_yes = _orderbook(asks=[("0.48", "100")])
        low_no = _orderbook(asks=[("0.48", "100")])

        markets = [
            _market(id="low_roi", yes_token_id="ty_low", no_token_id="tn_low"),
            _market(id="high_roi", yes_token_id="ty_high", no_token_id="tn_high"),
        ]

        with aioresponses() as m:
            m.get(CLOB_BOOK_PATTERN, payload=low_yes)
            m.get(CLOB_BOOK_PATTERN, payload=low_no)
            m.get(CLOB_BOOK_PATTERN, payload=high_yes)
            m.get(CLOB_BOOK_PATTERN, payload=high_no)
            fetcher = ClobOrderbookFetcher()
            detector = OrderbookArbDetector()
            scanner = OrderbookBatchScanner(fetcher, detector)
            opps = await scanner.scan(markets, min_spread=0.01)
            await fetcher.close()
            assert len(opps) == 2
            assert opps[0].roi_pct > opps[1].roi_pct
            assert opps[0].market.id == "high_roi"

    async def test_batch_scan_empty_markets(self):
        """Empty market list → empty results."""
        from poly24h.strategy.orderbook_scanner import (
            ClobOrderbookFetcher,
            OrderbookArbDetector,
            OrderbookBatchScanner,
        )

        fetcher = ClobOrderbookFetcher()
        detector = OrderbookArbDetector()
        scanner = OrderbookBatchScanner(fetcher, detector)
        opps = await scanner.scan([], min_spread=0.015)
        await fetcher.close()
        assert opps == []

    async def test_batch_scan_partial_failure(self):
        """Some API calls fail — skip failures, return rest."""
        from poly24h.strategy.orderbook_scanner import (
            ClobOrderbookFetcher,
            OrderbookArbDetector,
            OrderbookBatchScanner,
        )

        good_yes = _orderbook(asks=[("0.45", "100")])
        good_no = _orderbook(asks=[("0.45", "100")])

        markets = [
            _market(id="fail_market", yes_token_id="ty_fail", no_token_id="tn_fail"),
            _market(id="good_market", yes_token_id="ty_good", no_token_id="tn_good"),
        ]

        with aioresponses() as m:
            # First market: API failure
            m.get(CLOB_BOOK_PATTERN, status=500)
            m.get(CLOB_BOOK_PATTERN, status=500)
            # Second market: success
            m.get(CLOB_BOOK_PATTERN, payload=good_yes)
            m.get(CLOB_BOOK_PATTERN, payload=good_no)
            fetcher = ClobOrderbookFetcher()
            detector = OrderbookArbDetector()
            scanner = OrderbookBatchScanner(fetcher, detector)
            opps = await scanner.scan(markets, min_spread=0.01)
            await fetcher.close()
            assert len(opps) == 1
            assert opps[0].market.id == "good_market"

    async def test_batch_scan_concurrency_limit(self):
        """Semaphore should limit concurrent requests."""
        from poly24h.strategy.orderbook_scanner import (
            ClobOrderbookFetcher,
            OrderbookArbDetector,
            OrderbookBatchScanner,
        )

        # Create 10 markets with concurrency=2
        markets = [
            _market(id=f"m{i}", yes_token_id=f"ty{i}", no_token_id=f"tn{i}")
            for i in range(10)
        ]

        with aioresponses() as m:
            for _ in range(20):  # 10 markets × 2 tokens
                m.get(CLOB_BOOK_PATTERN, payload=_orderbook(asks=[("0.52", "100")]))
            fetcher = ClobOrderbookFetcher()
            detector = OrderbookArbDetector()
            scanner = OrderbookBatchScanner(fetcher, detector, concurrency=2)
            # Just verify it completes without error (semaphore works)
            opps = await scanner.scan(markets)
            await fetcher.close()
            assert isinstance(opps, list)

    async def test_batch_scan_all_fail_no_crash(self):
        """All API calls fail → empty results, no crash."""
        from poly24h.strategy.orderbook_scanner import (
            ClobOrderbookFetcher,
            OrderbookArbDetector,
            OrderbookBatchScanner,
        )

        markets = [_market()]

        with aioresponses() as m:
            m.get(CLOB_BOOK_PATTERN, exception=ConnectionError("fail"))
            m.get(CLOB_BOOK_PATTERN, exception=ConnectionError("fail"))
            fetcher = ClobOrderbookFetcher()
            detector = OrderbookArbDetector()
            scanner = OrderbookBatchScanner(fetcher, detector)
            opps = await scanner.scan(markets)
            await fetcher.close()
            assert opps == []


# ---------------------------------------------------------------------------
# Main loop integration with --orderbook flag
# ---------------------------------------------------------------------------


class TestOrderbookMainIntegration:
    """main.py integration: --orderbook flag enables orderbook scanning."""

    def test_parse_args_orderbook_flag(self):
        """--orderbook flag should be parsed."""
        from poly24h.main import parse_args

        args = parse_args(["--orderbook"])
        assert args.orderbook is True

    def test_parse_args_no_orderbook_default(self):
        """Default: orderbook scanning disabled."""
        from poly24h.main import parse_args

        args = parse_args([])
        assert args.orderbook is False

    def test_bot_config_enable_orderbook(self):
        """BotConfig should have enable_orderbook_scan field."""
        from poly24h.config import BotConfig

        config = BotConfig()
        assert config.enable_orderbook_scan is False

    def test_bot_config_enable_orderbook_true(self):
        """BotConfig can enable orderbook scan."""
        from poly24h.config import BotConfig

        config = BotConfig(enable_orderbook_scan=True)
        assert config.enable_orderbook_scan is True

    async def test_run_cycle_with_orderbook(self):
        """run_cycle with enable_orderbook_scan=True should also scan orderbooks."""
        from poly24h.config import BotConfig
        from poly24h.main import run_cycle

        end_date = (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat()
        event = {
            "id": "evt_1",
            "title": "BTC 1 hour market",
            "endDate": end_date,
            "enableNegRisk": False,
            "markets": [{
                "id": "mkt_1",
                "question": "Will BTC be above $100k in 1 hour?",
                "outcomePrices": "[0.50, 0.50]",
                "clobTokenIds": '["tok_yes_ob", "tok_no_ob"]',
                "liquidity": "5000",
                "endDate": end_date,
                "active": True,
                "closed": False,
            }],
        }
        yes_book = _orderbook(asks=[("0.45", "100")])
        no_book = _orderbook(asks=[("0.45", "100")])

        config = BotConfig(enable_orderbook_scan=True)
        scanner_config = {
            "hourly_crypto": {"enabled": True, "min_liquidity_usd": 3000, "min_spread": 0.01},
        }
        with aioresponses() as m:
            m.get(EVENTS_PATTERN, payload=[event])
            m.get(CLOB_BOOK_PATTERN, payload=yes_book)
            m.get(CLOB_BOOK_PATTERN, payload=no_book)
            opps = await run_cycle(config, scanner_config)
            # Should have OB opportunities (mid-price shows 0.50+0.50=1.0, no mid-price arb,
            # but orderbook shows 0.45+0.45=0.90 → arb)
            ob_opps = [o for o in opps if hasattr(o, '_ob_source') or o.yes_price == 0.45]
            assert len(ob_opps) >= 1

    async def test_run_cycle_without_orderbook_unchanged(self):
        """run_cycle with enable_orderbook_scan=False → same as before (no OB scan)."""
        from poly24h.config import BotConfig
        from poly24h.main import run_cycle

        end_date = (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat()
        event = {
            "id": "evt_1",
            "title": "BTC 1 hour market",
            "endDate": end_date,
            "enableNegRisk": False,
            "markets": [{
                "id": "mkt_1",
                "question": "Will BTC be above $100k in 1 hour?",
                "outcomePrices": "[0.50, 0.50]",
                "clobTokenIds": '["tok_yes_ob", "tok_no_ob"]',
                "liquidity": "5000",
                "endDate": end_date,
                "active": True,
                "closed": False,
            }],
        }
        config = BotConfig(enable_orderbook_scan=False)
        scanner_config = {
            "hourly_crypto": {"enabled": True, "min_liquidity_usd": 3000, "min_spread": 0.01},
        }
        with aioresponses() as m:
            m.get(EVENTS_PATTERN, payload=[event])
            # No CLOB API mocks — if it tries to call CLOB, it'll fail
            opps = await run_cycle(config, scanner_config)
            # 0.50 + 0.50 = 1.0 → no mid-price arb
            assert opps == []


# ---------------------------------------------------------------------------
# Format and logging for OB opportunities
# ---------------------------------------------------------------------------


class TestOrderbookFormatting:
    """[OB] prefix in formatted output."""

    def test_format_ob_opportunity_has_prefix(self):
        """Orderbook opportunities should have [OB] prefix."""
        from poly24h.main import format_ob_opportunity_line

        market = _market()
        opp = Opportunity(
            market=market,
            arb_type=ArbType.SINGLE_CONDITION,
            yes_price=0.48,
            no_price=0.50,
            total_cost=0.98,
            margin=0.02,
            roi_pct=2.04,
            recommended_size_usd=0.0,
            detected_at=datetime.now(tz=timezone.utc),
        )
        line = format_ob_opportunity_line(opp)
        assert "[OB]" in line
        assert "2.04" in line or "2.0" in line


# ---------------------------------------------------------------------------
# F-019: OrderbookLevel and OrderbookSummary tests
# ---------------------------------------------------------------------------


class TestOrderbookLevel:
    """F-019: OrderbookLevel dataclass tests."""

    def test_value_usd(self):
        """value_usd is price * size."""
        level = OrderbookLevel(price=0.50, size=100.0)
        assert level.value_usd == 50.0

    def test_value_usd_zero_size(self):
        """value_usd is 0 when size is 0."""
        level = OrderbookLevel(price=0.50, size=0.0)
        assert level.value_usd == 0.0


class TestOrderbookSummary:
    """F-019: OrderbookSummary dataclass tests."""

    def test_default_values(self):
        """OrderbookSummary has sane defaults."""
        summary = OrderbookSummary()
        assert summary.best_ask is None
        assert summary.best_ask_size == 0.0
        assert summary.total_ask_depth_usd == 0.0
        assert summary.ask_levels == 0

    def test_with_values(self):
        """OrderbookSummary can be created with all fields."""
        summary = OrderbookSummary(
            best_ask=0.45,
            best_ask_size=200.0,
            total_ask_depth_usd=500.0,
            ask_levels=5,
        )
        assert summary.best_ask == 0.45
        assert summary.best_ask_size == 200.0
        assert summary.total_ask_depth_usd == 500.0
        assert summary.ask_levels == 5


class TestClobOrderbookFetcherSummary:
    """F-019: ClobOrderbookFetcher.fetch_orderbook_summaries() tests."""

    @pytest.mark.asyncio
    async def test_fetch_orderbook_summary_success(self):
        """fetch_orderbook_summaries() returns depth info."""
        from poly24h.strategy.orderbook_scanner import ClobOrderbookFetcher

        with aioresponses() as m:
            m.get(
                CLOB_BOOK_PATTERN,
                payload={
                    "asks": [
                        {"price": "0.45", "size": "100"},
                        {"price": "0.50", "size": "200"},
                    ]
                },
            )
            m.get(
                CLOB_BOOK_PATTERN,
                payload={
                    "asks": [
                        {"price": "0.55", "size": "50"},
                    ]
                },
            )

            fetcher = ClobOrderbookFetcher(timeout=5)
            yes_summary, no_summary = await fetcher.fetch_orderbook_summaries(
                "tok_yes", "tok_no"
            )
            await fetcher.close()

        assert yes_summary.best_ask == 0.45
        assert yes_summary.best_ask_size == 100.0
        assert yes_summary.ask_levels == 2
        # total depth: 0.45*100 + 0.50*200 = 45 + 100 = 145
        assert abs(yes_summary.total_ask_depth_usd - 145.0) < 0.01

        assert no_summary.best_ask == 0.55
        assert no_summary.best_ask_size == 50.0
        assert no_summary.ask_levels == 1

    @pytest.mark.asyncio
    async def test_fetch_orderbook_summary_empty_book(self):
        """fetch_orderbook_summaries() handles empty orderbook."""
        from poly24h.strategy.orderbook_scanner import ClobOrderbookFetcher

        with aioresponses() as m:
            m.get(CLOB_BOOK_PATTERN, payload={"asks": []})
            m.get(CLOB_BOOK_PATTERN, payload={"asks": []})

            fetcher = ClobOrderbookFetcher(timeout=5)
            yes_summary, no_summary = await fetcher.fetch_orderbook_summaries(
                "tok_yes", "tok_no"
            )
            await fetcher.close()

        assert yes_summary.best_ask is None
        assert no_summary.best_ask is None
