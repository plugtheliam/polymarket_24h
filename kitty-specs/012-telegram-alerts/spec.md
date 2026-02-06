# Feature Specification: Telegram Alerts

**Feature Branch**: `012-telegram-alerts`
**Created**: 2026-02-06
**Status**: Draft

## User Scenarios & Testing

### User Story 1 - Opportunity Alert (Priority: P1)

아비트라지 기회 감지 시 텔레그램으로 알림을 보낼 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** Opportunity(roi=5%, market="BTC 1H Up"), **When** alert_opportunity(), **Then** 텔레그램 메시지 전송: "🔍 Arb Found: BTC 1H Up | ROI: 5.00% | Margin: $0.05"
2. **Given** NegRisk 기회, **When** alert_opportunity(), **Then** 아웃컴 수 + 총 마진 포함 메시지
3. **Given** TELEGRAM_BOT_TOKEN 미설정, **When** alert(), **Then** 무시 (에러 없이)

---

### User Story 2 - Trade Execution Alert (Priority: P1)

거래 실행 결과를 텔레그램으로 알림할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** 거래 성공, **When** alert_trade(), **Then** "✅ Trade: BTC 1H Up | 100 shares | Cost: $85 | Exp Profit: $15"
2. **Given** 거래 실패/거부, **When** alert_trade(), **Then** "❌ Rejected: BTC 1H Up | Reason: daily loss limit"
3. **Given** 리스크 거부, **When** alert_trade(), **Then** 거부 사유 포함

---

### User Story 3 - Daily Report (Priority: P2)

일일 거래 요약을 텔레그램으로 전송할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** 하루 거래 데이터, **When** send_daily_report(), **Then** 총 거래/성공/실패, PnL, 활성 포지션 요약 전송
2. **Given** 거래 0건, **When** send_daily_report(), **Then** "📊 No trades today" 전송

---

### User Story 4 - Error Alert (Priority: P1)

심각한 에러 발생 시 즉시 알림할 수 있어야 한다.

**Acceptance Scenarios**:

1. **Given** API 연속 실패 5회, **When** alert_error(), **Then** "🚨 API Error: Gamma API unreachable (5 consecutive failures)"
2. **Given** 일일 손실 한도 도달, **When** alert_error(), **Then** "🚨 Risk: Daily loss limit reached ($500)"

### Edge Cases

- 텔레그램 API rate limit → 큐잉 + 배치 전송
- 긴 메시지 (4096자 초과) → 분할 전송
- 봇 토큰 유효하지 않음 → 에러 로깅, 크래시 없음

## Requirements

- **FR-001**: TelegramAlerter 클래스 — aiohttp로 Bot API 호출
- **FR-002**: alert_opportunity(opportunity) → 기회 감지 알림
- **FR-003**: alert_trade(trade_record) → 거래 결과 알림
- **FR-004**: alert_error(message, level) → 에러/경고 알림
- **FR-005**: send_daily_report(session_summary) → 일일 요약
- **FR-006**: 설정 없으면 모든 메서드가 no-op (graceful 비활성)
- **FR-007**: 메시지 큐잉 (초당 최대 1건)

## Success Criteria

- **SC-001**: mock HTTP로 메시지 전송 테스트
- **SC-002**: 설정 없을 때 에러 없이 동작
- **SC-003**: 모든 메시지 포맷 검증
