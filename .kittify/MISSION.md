# Mission: Hybrid Mode Implementation

## 목표
- Crypto 1H: Paired Entry (무위험, Taker 우선)
- NBA: Sniper (방향 예측, 기존 유지)
- Fallback: 한쪽 체결 시 Unwind

## 설정 (수수료 반영 업데이트)
- Taker 우선 (확실한 체결)
- FOK 주문 (전량 체결 or 취소)
- **Paired Entry 조건: YES+NO < $0.94** (6% 마진 - 6% 수수료 = 수익)
- Unwind 슬리피지 한도: 5%
- 자본 배분: Crypto 60% / NBA 40%
- 마켓당 최대: $100
- 일일 손실 한도: $200

## 수수료 분석 결과
- Taker Fee: ~3% per side (at 50% prob)
- 양쪽 Taker = ~6% total fees
- 기존 $0.98 조건 → 수익 불가
- 새 조건 $0.94 → 1% 순마진 기대

## Phase 1: 수수료 로직 (TDD)
- [x] tests/test_fee_calculator.py
- [x] src/poly24h/strategy/fee_calculator.py

## Phase 2: Atomic State Machine
- [ ] tests/test_atomic_paired.py
- [ ] src/poly24h/execution/atomic_paired.py

## Phase 3: Hybrid Scheduler
- [ ] src/poly24h/scheduler/hybrid_scheduler.py

## Phase 4: 포지션 관리
- [ ] src/poly24h/portfolio/hybrid_portfolio.py
