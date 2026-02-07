# Mission: NBA Team Name Parser Improvement

## Problem
현재 NBA 마켓 팀명 파싱이 실패하여 모든 NBA 마켓에서 "Unknown NBA team: opponent" 경고 발생.
결과적으로 NBA 마켓 트레이드가 0건.

## Root Cause
Polymarket NBA 마켓 질문 형식:
- "Mavericks vs. Spurs"
- "Warriors vs. Lakers"
- "Knicks vs. Celtics"
- "76ers vs. Suns"

현재 파서는 질문에서 팀 키워드를 검색하지만, 두 번째 팀을 "opponent"로 잘못 설정.

## Solution
1. "Team1 vs. Team2" 패턴을 파싱하는 정규식 추가
2. 팀명 매핑 확장 (Mavericks → mavericks, 76ers → sixers 등)
3. Kent Beck TDD 방식으로 테스트 먼저 작성

## Acceptance Criteria
- [ ] "Mavericks vs. Spurs" → team_a="mavericks", team_b="spurs"
- [ ] "Warriors vs. Lakers" → team_a="warriors", team_b="lakers"
- [ ] "76ers vs. Suns" → team_a="sixers", team_b="suns"
- [ ] "Knicks vs. Celtics" → team_a="knicks", team_b="celtics"
- [ ] 모든 테스트 통과
- [ ] 드라이런에서 NBA 마켓 트레이드 발생

## Files to Modify
- `src/poly24h/strategy/nba_fair_value.py` - 팀명 파싱 로직 추가
- `tests/test_nba_parser.py` - TDD 테스트 (신규)
