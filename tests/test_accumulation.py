"""Tests for F-016: Gabagool-Style Accumulation Strategy.

Kent Beck TDD — test scenarios from spec.md.
"""

from __future__ import annotations

import pytest

from poly24h.strategy.accumulation import (
    AccumulatedPosition,
    AccumulationConfig,
    AccumulationStrategy,
    MarketPhaseDetector,
)

# ============================================================
# AccumulatedPosition tests
# ============================================================


class TestAccumulatedPosition:
    """AccumulatedPosition dataclass 산술/속성 테스트."""

    def test_initial_state(self):
        pos = AccumulatedPosition(market_id="test-market")
        assert pos.yes_shares == 0.0
        assert pos.no_shares == 0.0
        assert pos.yes_cost == 0.0
        assert pos.no_cost == 0.0

    def test_add_yes(self):
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", shares=10.0, price=0.50)
        assert pos.yes_shares == 10.0
        assert pos.yes_cost == 5.0  # 10 * 0.50
        assert pos.no_shares == 0.0

    def test_add_no(self):
        pos = AccumulatedPosition(market_id="m1")
        pos.add("no", shares=10.0, price=0.48)
        assert pos.no_shares == 10.0
        assert pos.no_cost == 4.80

    def test_add_multiple(self):
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 10.0, 0.50)
        pos.add("yes", 5.0, 0.52)
        assert pos.yes_shares == 15.0
        assert pos.yes_cost == pytest.approx(7.60)  # 5.0 + 2.6

    def test_paired_shares_balanced(self):
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 10.0, 0.50)
        pos.add("no", 10.0, 0.48)
        assert pos.paired_shares == 10.0

    def test_paired_shares_imbalanced(self):
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 20.0, 0.50)
        pos.add("no", 15.0, 0.48)
        assert pos.paired_shares == 15.0

    def test_paired_shares_zero(self):
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 10.0, 0.50)
        assert pos.paired_shares == 0.0

    def test_cpp_balanced(self):
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 10.0, 0.50)
        pos.add("no", 10.0, 0.48)
        # cpp = (5.0 + 4.8) / 10 = 0.98
        assert pos.cpp == pytest.approx(0.98)

    def test_cpp_imbalanced(self):
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 20.0, 0.50)
        pos.add("no", 10.0, 0.48)
        # cpp = (10.0 + 4.8) / 10 = 1.48
        assert pos.cpp == pytest.approx(1.48)

    def test_cpp_zero_paired(self):
        """paired_shares == 0이면 cpp는 inf."""
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 10.0, 0.50)
        assert pos.cpp == float("inf")

    def test_cpp_empty_position(self):
        pos = AccumulatedPosition(market_id="m1")
        assert pos.cpp == float("inf")

    def test_merge_profit_positive(self):
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 10.0, 0.50)
        pos.add("no", 10.0, 0.48)
        # merge_profit = 10 * (1.0 - 0.98) = 0.20
        assert pos.merge_profit == pytest.approx(0.20)

    def test_merge_profit_negative(self):
        """cpp > 1.0이면 merge 손실."""
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 10.0, 0.55)
        pos.add("no", 10.0, 0.50)
        # cpp = 1.05, merge_profit = 10 * (1.0 - 1.05) = -0.50
        assert pos.merge_profit == pytest.approx(-0.50)

    def test_merge_profit_zero_paired(self):
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 10.0, 0.50)
        assert pos.merge_profit == 0.0

    def test_projected_cpp_after_buy_yes(self):
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 10.0, 0.50)
        pos.add("no", 10.0, 0.48)
        # Buy 10 YES at 0.49: new yes_cost = 5.0 + 4.9 = 9.9
        # paired = min(20, 10) = 10
        # cpp = (9.9 + 4.8) / 10 = 1.47
        projected = pos.projected_cpp_after_buy("yes", 10.0, 0.49)
        assert projected == pytest.approx(1.47)

    def test_projected_cpp_after_buy_no(self):
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 10.0, 0.50)
        pos.add("no", 10.0, 0.48)
        # Buy 10 NO at 0.47: new no_cost = 4.8 + 4.7 = 9.5
        # paired = min(10, 20) = 10
        # cpp = (5.0 + 9.5) / 10 = 1.45
        projected = pos.projected_cpp_after_buy("no", 10.0, 0.47)
        assert projected == pytest.approx(1.45)

    def test_projected_cpp_creates_first_pair(self):
        """한쪽만 있다가 반대쪽 매수로 첫 pair 생성."""
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 10.0, 0.50)
        # Buy 5 NO at 0.48: paired = min(10, 5) = 5
        # cpp = (5.0 + 2.4) / 5 = 1.48
        projected = pos.projected_cpp_after_buy("no", 5.0, 0.48)
        assert projected == pytest.approx(1.48)

    def test_projected_cpp_no_paired_after_buy(self):
        """매수 후에도 paired가 0이면 inf."""
        pos = AccumulatedPosition(market_id="m1")
        # Empty position, buy more yes → still no pairs
        projected = pos.projected_cpp_after_buy("yes", 10.0, 0.50)
        assert projected == float("inf")

    def test_add_invalid_side(self):
        pos = AccumulatedPosition(market_id="m1")
        with pytest.raises(ValueError, match="side"):
            pos.add("up", 10.0, 0.50)


# ============================================================
# AccumulationStrategy.tick() tests
# ============================================================


class TestAccumulationStrategyTick:
    """tick() 매수 측 결정 로직 테스트."""

    def test_spread_over_max_returns_none(self):
        """ask_sum > max_spread → None (대기)."""
        strategy = AccumulationStrategy(AccumulationConfig(max_spread=1.02))
        pos = AccumulatedPosition(market_id="m1")
        # yes 0.55 + no 0.55 = 1.10 > 1.02
        assert strategy.tick(pos, yes_ask=0.55, no_ask=0.55) is None

    def test_spread_exactly_max_returns_none(self):
        """ask_sum == max_spread → None (경계값: 이상이면 대기)."""
        strategy = AccumulationStrategy(AccumulationConfig(max_spread=1.02))
        pos = AccumulatedPosition(market_id="m1")
        assert strategy.tick(pos, yes_ask=0.51, no_ask=0.51) is None

    def test_spread_under_max_returns_side(self):
        """ask_sum < max_spread → 매수 추천."""
        strategy = AccumulationStrategy(AccumulationConfig(max_spread=1.02))
        pos = AccumulatedPosition(market_id="m1")
        result = strategy.tick(pos, yes_ask=0.50, no_ask=0.50)
        assert result in ("yes", "no")

    def test_empty_position_cheaper_side(self):
        """빈 포지션에서는 더 싼 쪽 매수."""
        strategy = AccumulationStrategy(AccumulationConfig(max_spread=1.05))
        pos = AccumulatedPosition(market_id="m1")
        assert strategy.tick(pos, yes_ask=0.52, no_ask=0.50) == "no"

    def test_empty_position_cheaper_yes(self):
        strategy = AccumulationStrategy(AccumulationConfig(max_spread=1.05))
        pos = AccumulatedPosition(market_id="m1")
        assert strategy.tick(pos, yes_ask=0.48, no_ask=0.52) == "yes"

    def test_empty_position_equal_price(self):
        """빈 포지션 + 동일 가격 → yes (tie-breaker)."""
        strategy = AccumulationStrategy(AccumulationConfig(max_spread=1.05))
        pos = AccumulatedPosition(market_id="m1")
        result = strategy.tick(pos, yes_ask=0.50, no_ask=0.50)
        assert result == "yes"  # tie-breaker: yes 우선

    def test_dcpp_optimization_chooses_lower_cpp(self):
        """ΔCPP 최적화: projected_cpp가 낮은 쪽 선택.

        Covered by test_dcpp_picks_side_lowering_cpp below.
        """
        # 간단한 케이스: underweight 측이 CPP를 낮추는 방향과 일치
        config = AccumulationConfig(max_spread=1.05, order_size=50.0)
        strategy = AccumulationStrategy(config)
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 10.0, 0.49)
        pos.add("no", 10.0, 0.49)
        # Balanced. yes_ask cheaper → ΔCPP lower for yes
        result = strategy.tick(pos, yes_ask=0.48, no_ask=0.52)
        assert result == "yes"

    def test_dcpp_picks_side_lowering_cpp(self):
        """ΔCPP 최적화 핵심: CPP를 더 낮추는 쪽 선택."""
        config = AccumulationConfig(max_spread=1.05, order_size=50.0)
        strategy = AccumulationStrategy(config)
        pos = AccumulatedPosition(market_id="m1")
        # Imbalanced position: more YES than NO
        pos.add("yes", 20.0, 0.50)  # yes_cost=10.0
        pos.add("no", 10.0, 0.50)   # no_cost=5.0
        # Current cpp = (10.0 + 5.0) / min(20, 10) = 15.0 / 10 = 1.50

        # shares from order_size: yes → 50/0.49 ≈ 102.04, no → 50/0.49 ≈ 102.04
        # Buy NO at 0.49 would increase paired from 10 to 112.04:
        #   cpp = (10.0 + 5.0 + 50.0) / min(20, 112.04) = 65.0 / 20 = 3.25
        # Buy YES at 0.49:
        #   cpp = (10.0 + 50.0 + 5.0) / min(122.04, 10) = 65.0 / 10 = 6.5
        # NO gives lower cpp → should pick "no"
        result = strategy.tick(pos, yes_ask=0.49, no_ask=0.49)
        assert result == "no"

    def test_underweight_side_tiebreaker(self):
        """CPP 동일 시 underweight 측 우선."""
        config = AccumulationConfig(max_spread=1.05, order_size=50.0)
        strategy = AccumulationStrategy(config)
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 5.0, 0.50)
        pos.add("no", 10.0, 0.50)
        # yes is underweight → should pick "yes"
        # (ΔCPP will also favor yes since it increases paired count)
        result = strategy.tick(pos, yes_ask=0.50, no_ask=0.50)
        assert result == "yes"

    def test_cheaper_side_tiebreaker(self):
        """CPP 동일 + 균형 → 더 싼 쪽."""
        config = AccumulationConfig(max_spread=1.05, order_size=50.0)
        strategy = AccumulationStrategy(config)
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 10.0, 0.50)
        pos.add("no", 10.0, 0.50)
        # Balanced. yes_ask=0.49 is cheaper.
        result = strategy.tick(pos, yes_ask=0.49, no_ask=0.51)
        assert result == "yes"

    def test_spec_scenario_1(self):
        """Spec AS-1: yes=0.52, no=0.50, sum=1.02 → NO 매수."""
        config = AccumulationConfig(max_spread=1.03)
        strategy = AccumulationStrategy(config)
        pos = AccumulatedPosition(market_id="m1")
        # sum = 1.02 < 1.03 → proceed
        result = strategy.tick(pos, yes_ask=0.52, no_ask=0.50)
        assert result == "no"  # 더 싼 쪽

    def test_spec_scenario_2(self):
        """Spec AS-2: yes=10, no=5 (불균형) → NO 측 매수."""
        config = AccumulationConfig(max_spread=1.05, order_size=50.0)
        strategy = AccumulationStrategy(config)
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 10.0, 0.50)
        pos.add("no", 5.0, 0.50)
        result = strategy.tick(pos, yes_ask=0.50, no_ask=0.50)
        assert result == "no"  # underweight side

    def test_spec_scenario_3(self):
        """Spec AS-3: sum=1.10 → None (대기)."""
        config = AccumulationConfig(max_spread=1.02)
        strategy = AccumulationStrategy(config)
        pos = AccumulatedPosition(market_id="m1")
        result = strategy.tick(pos, yes_ask=0.55, no_ask=0.55)
        assert result is None


# ============================================================
# AccumulationStrategy.should_merge() / merge_profit() tests
# ============================================================


class TestAccumulationMerge:
    """merge 판단 로직 테스트."""

    def test_should_merge_sufficient_pairs_and_cpp(self):
        """Spec AS-4: 10쌍 축적, CPP=0.98 → merge 가능."""
        config = AccumulationConfig(min_merge_pairs=5, target_cpp=0.98)
        strategy = AccumulationStrategy(config)
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 10.0, 0.50)
        pos.add("no", 10.0, 0.48)
        # paired=10, cpp=0.98
        assert strategy.should_merge(pos) is True

    def test_should_merge_insufficient_pairs(self):
        """쌍이 부족하면 merge 불가."""
        config = AccumulationConfig(min_merge_pairs=5)
        strategy = AccumulationStrategy(config)
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 3.0, 0.50)
        pos.add("no", 3.0, 0.48)
        assert strategy.should_merge(pos) is False

    def test_should_merge_cpp_too_high(self):
        """CPP >= 1.0이면 merge 불가 (손실)."""
        config = AccumulationConfig(min_merge_pairs=5)
        strategy = AccumulationStrategy(config)
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 10.0, 0.55)
        pos.add("no", 10.0, 0.50)
        # cpp = 1.05 >= 1.0
        assert strategy.should_merge(pos) is False

    def test_should_merge_exactly_min_pairs(self):
        """경계값: 정확히 min_merge_pairs 쌍."""
        config = AccumulationConfig(min_merge_pairs=5)
        strategy = AccumulationStrategy(config)
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 5.0, 0.49)
        pos.add("no", 5.0, 0.49)
        # paired=5, cpp=0.98
        assert strategy.should_merge(pos) is True

    def test_should_merge_zero_pairs(self):
        config = AccumulationConfig(min_merge_pairs=5)
        strategy = AccumulationStrategy(config)
        pos = AccumulatedPosition(market_id="m1")
        assert strategy.should_merge(pos) is False

    def test_merge_profit_spec_scenario(self):
        """Spec: 20쌍, CPP=0.97 → 수익 $0.60."""
        config = AccumulationConfig()
        strategy = AccumulationStrategy(config)
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 20.0, 0.485)
        pos.add("no", 20.0, 0.485)
        # cpp = (9.7 + 9.7) / 20 = 0.97
        # merge_profit = 20 * (1.0 - 0.97) = 0.60
        profit = strategy.merge_profit(pos)
        assert profit == pytest.approx(0.60)

    def test_merge_profit_15_pairs_from_imbalanced(self):
        """Spec: yes=20, no=15 → 15쌍만 merge 가능."""
        config = AccumulationConfig()
        strategy = AccumulationStrategy(config)
        pos = AccumulatedPosition(market_id="m1")
        # 가격을 낮춰서 cpp < 1.0이 되도록
        pos.add("yes", 20.0, 0.30)
        pos.add("no", 15.0, 0.30)
        # paired = 15, cpp = (6.0 + 4.5) / 15 = 0.70
        assert pos.paired_shares == 15.0
        assert pos.cpp == pytest.approx(0.70)
        profit = strategy.merge_profit(pos)
        assert profit > 0  # cpp < 1.0 → positive
        assert profit == pytest.approx(15.0 * (1.0 - 0.70))

    def test_merge_profit_negative(self):
        """CPP > 1.0이면 merge 손실."""
        config = AccumulationConfig()
        strategy = AccumulationStrategy(config)
        pos = AccumulatedPosition(market_id="m1")
        pos.add("yes", 10.0, 0.55)
        pos.add("no", 10.0, 0.55)
        profit = strategy.merge_profit(pos)
        assert profit < 0


# ============================================================
# MarketPhaseDetector tests
# ============================================================


class TestMarketPhaseDetector:
    """1시간 마켓 수명 주기 phase 테스트."""

    def test_aggressive_phase(self):
        """> 55min remaining → AGGRESSIVE."""
        assert MarketPhaseDetector.get_phase(56.0) == "AGGRESSIVE"
        assert MarketPhaseDetector.get_phase(60.0) == "AGGRESSIVE"

    def test_aggressive_boundary(self):
        """55분 초과가 AGGRESSIVE."""
        assert MarketPhaseDetector.get_phase(55.1) == "AGGRESSIVE"

    def test_normal_phase(self):
        """15-55min remaining → NORMAL."""
        assert MarketPhaseDetector.get_phase(30.0) == "NORMAL"
        assert MarketPhaseDetector.get_phase(55.0) == "NORMAL"
        assert MarketPhaseDetector.get_phase(15.0) == "NORMAL"

    def test_passive_phase(self):
        """5-15min remaining → PASSIVE."""
        assert MarketPhaseDetector.get_phase(14.9) == "PASSIVE"
        assert MarketPhaseDetector.get_phase(10.0) == "PASSIVE"
        assert MarketPhaseDetector.get_phase(5.0) == "PASSIVE"

    def test_close_only_phase(self):
        """< 5min → CLOSE_ONLY."""
        assert MarketPhaseDetector.get_phase(4.9) == "CLOSE_ONLY"
        assert MarketPhaseDetector.get_phase(1.0) == "CLOSE_ONLY"
        assert MarketPhaseDetector.get_phase(0.0) == "CLOSE_ONLY"

    def test_should_accumulate_aggressive(self):
        assert MarketPhaseDetector.should_accumulate("AGGRESSIVE") is True

    def test_should_accumulate_normal(self):
        assert MarketPhaseDetector.should_accumulate("NORMAL") is True

    def test_should_not_accumulate_passive(self):
        assert MarketPhaseDetector.should_accumulate("PASSIVE") is False

    def test_should_not_accumulate_close_only(self):
        assert MarketPhaseDetector.should_accumulate("CLOSE_ONLY") is False

    def test_should_merge_always(self):
        """merge는 모든 phase에서 가능."""
        for phase in ("AGGRESSIVE", "NORMAL", "PASSIVE", "CLOSE_ONLY"):
            assert MarketPhaseDetector.should_merge(phase) is True


# ============================================================
# Full cycle integration test
# ============================================================


class TestAccumulationFullCycle:
    """전체 축적 → merge 사이클 통합 테스트."""

    def test_accumulate_then_merge(self):
        """여러 라운드 축적 후 merge 조건 확인."""
        config = AccumulationConfig(
            max_spread=1.02,
            order_size=50.0,
            min_merge_pairs=5,
            target_cpp=0.98,
        )
        strategy = AccumulationStrategy(config)
        pos = AccumulatedPosition(market_id="m1")

        # 양쪽을 교대로 축적 시뮬레이션 (가격이 낮아야 cpp < 1.0)
        for _ in range(5):
            # 저가로 양쪽 매수
            pos.add("yes", 10.0, 0.48)
            pos.add("no", 10.0, 0.48)

        # 5라운드 후: 50 yes, 50 no, cpp = (24.0 + 24.0) / 50 = 0.96
        assert pos.paired_shares == 50.0
        assert pos.cpp == pytest.approx(0.96)
        assert strategy.should_merge(pos) is True
        assert strategy.merge_profit(pos) > 0

    def test_high_spread_blocks_accumulation(self):
        """스프레드가 높으면 축적 불가."""
        config = AccumulationConfig(max_spread=1.02)
        strategy = AccumulationStrategy(config)
        pos = AccumulatedPosition(market_id="m1")

        for _ in range(10):
            result = strategy.tick(pos, yes_ask=0.55, no_ask=0.55)
            assert result is None

        # 포지션은 비어있어야
        assert pos.yes_shares == 0.0
        assert pos.no_shares == 0.0

    def test_phase_controlled_accumulation(self):
        """phase에 따라 축적 여부 결정."""
        config = AccumulationConfig(max_spread=1.05)
        strategy = AccumulationStrategy(config)
        pos = AccumulatedPosition(market_id="m1")

        # AGGRESSIVE (58분 남음) → 축적 가능
        phase = MarketPhaseDetector.get_phase(58.0)
        assert MarketPhaseDetector.should_accumulate(phase)
        side = strategy.tick(pos, 0.50, 0.50)
        assert side is not None

        # CLOSE_ONLY (3분 남음) → 축적 중단
        phase = MarketPhaseDetector.get_phase(3.0)
        assert not MarketPhaseDetector.should_accumulate(phase)
        # merge는 가능
        assert MarketPhaseDetector.should_merge(phase)
