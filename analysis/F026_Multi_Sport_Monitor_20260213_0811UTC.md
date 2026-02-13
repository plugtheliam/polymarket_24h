# F-026: 멀티 스포츠 모니터 구현 계획

## Context

NBA All-Star Break (~2/14-20)으로 NBAMonitor가 매칭할 게임이 없음. 현재 Polymarket에 NHL, 유럽 축구 리그(분데스리가, 세리에A, 리그1, 라리가, EPL, UCL) 등 대규모 유동성 마켓이 활발 운영 중. 기존 NBAMonitor 코드가 99% 범용적이므로, `SportsMonitor`로 일반화하여 복수 스포츠 병렬 모니터링.

## 시장 현황 (2026-02-13)

| 스포츠 | series_id | 활성 이벤트 | 유동성/게임 | Odds API 키 | 비고 |
|--------|-----------|------------|-------------|-------------|------|
| **NHL** | 10346 | 24+ | $5K-$12K | `ice_hockey_nhl` | 매일 경기, 2-way |
| **분데스리가** | 10194 | 7 | $250K-$1M | `soccer_germany_bundesliga` | **오늘 경기** |
| **세리에A** | 10203 | 7-8 | $350K-$1.2M | `soccer_italy_serie_a` | **오늘 경기** |
| **리그1** | 10195 | 5-6 | $249K-$1.1M | `soccer_france_ligue_one` | **오늘 경기** |
| **라리가** | 10193 | 6 | $8K-$540K | `soccer_spain_la_liga` | **오늘 경기** |
| **EPL** | 10188 | 13 | $380K-$1M | `soccer_epl` | 2/18-22 |
| **UCL** | 10204 | 6 | $267K-$893K | `soccer_uefa_champs_league` | 2/17-18 |

## Odds API 예산 제약

- 남은 요청: **488회** (500/월), ~15일 → ~32회/일
- 전략: 경기 시작 4시간 이내만 조회, 15분 캐시 TTL
- 비상 예비: remaining < 50이면 전면 차단

---

## 구현 단계 (Kent Beck TDD)

### Step 1: SportConfig + 팀명 데이터

**새 파일**: `src/poly24h/strategy/sport_config.py`

```python
@dataclass
class SportConfig:
    name: str                          # "nhl", "bundesliga"
    display_name: str                  # "NHL", "Bundesliga"
    source: MarketSource               # MarketSource.NHL, MarketSource.SOCCER
    odds_api_sport_key: str            # "ice_hockey_nhl"
    series_id: str                     # "10346"
    tag_id: str | None                 # "100639"
    team_names: dict[str, list[str]]   # canonical -> aliases
    slug_prefixes: list[str]           # ["nhl"], ["bun"]
    is_three_way: bool = False         # 축구 = True
    scan_interval: int = 300
    min_edge: float = 0.03             # 축구는 0.05 권장
    max_per_game: float = 500.0
```

상수: `NBA_CONFIG`, `NHL_CONFIG`, `BUNDESLIGA_CONFIG`, `SERIE_A_CONFIG`, `LIGUE_1_CONFIG`, `LA_LIGA_CONFIG`, `EPL_CONFIG`, `UCL_CONFIG`

`get_enabled_sport_configs()` — 환경변수 `POLY24H_SPORTS` 기반

**새 파일**: `src/poly24h/strategy/team_data.py`

기존 `odds_api.py`의 `NBA_TEAM_NAMES`를 이동하고 추가:
- `NHL_TEAM_NAMES` (32팀)
- `BUNDESLIGA_TEAM_NAMES` (18팀)
- `EPL_TEAM_NAMES` (20팀)
- `SERIE_A_TEAM_NAMES`, `LIGUE_1_TEAM_NAMES`, `LA_LIGA_TEAM_NAMES`

**테스트** (`tests/test_f026_multi_sport.py`):
- `TestSportConfig`: 필수 필드, 축구 is_three_way=True
- `TestTeamData`: 팀 수, 별칭 존재, 중복 없음

### Step 2: GammaClient + MarketScanner 일반화

**수정**: `src/poly24h/discovery/gamma_client.py`
- `fetch_game_events_by_series(series_id, tag_id)` 추가 (범용)
- 기존 `fetch_nba_game_events()`는 wrapper 유지

**수정**: `src/poly24h/discovery/market_scanner.py`
- `discover_sport_markets(sport_config)` 추가
- 기존 `discover_nba_markets()`는 wrapper 유지

**테스트**: `TestMultiSportDiscovery` — NHL/축구 시리즈 ID 기반 발견

### Step 3: OddsAPIClient 일반화 + 3-way 축구

**수정**: `src/poly24h/strategy/odds_api.py`

1. `fetch_odds(sport_config)` — 범용 (기존 `fetch_nba_odds` wrapper 유지)
2. `devig_three_way(p_home, p_draw, p_away)` — 3-way 오버라운드 제거
3. 팀명 매칭 `sport_config.team_names` 파라미터화
4. 스포츠별 독립 캐시 (`dict[sport_key, (data, timestamp)]`)
5. `get_fair_prob_for_market(market, games, sport_config)` — 3-way 분기

축구 3-way 처리:
- Odds API가 home/draw/away 3개 outcome 반환
- Polymarket은 각 outcome을 별도 YES/NO 바이너리 마켓으로 분리
- "Will Bayern Munich win?" → devigged home_win_prob 사용
- "Draw?" → devigged draw_prob 사용

**테스트**: `TestOddsAPIMultiSport` — 3-way devig, 캐시 격리, NHL/축구 오즈

### Step 4: SportsMonitor + Rate Limiter

**새 파일**: `src/poly24h/strategy/sports_monitor.py`

NBAMonitor와 거의 동일, `SportConfig` 파라미터화:
- `scan_and_trade()` → `discover_sport_markets(config)` + `fetch_odds(config)`
- 로그에 `sport_config.display_name` 사용

**수정**: `src/poly24h/strategy/nba_monitor.py`
- `NBAMonitor(SportsMonitor)` 서브클래스로 변경 (역호환)

**새 파일**: `src/poly24h/strategy/odds_rate_limiter.py`
- `can_fetch(sport_name, min_interval)` — 호출 가능 여부
- `record_fetch(sport_name, remaining)` — 잔량 추적
- 비상 예비: remaining < 50 → 전면 차단

**테스트**: `TestSportsMonitor`, `TestOddsRateLimiter`, NBAMonitor 역호환

### Step 5: main.py 멀티 모니터 런칭

**수정**: `src/poly24h/main.py`

```python
rate_limiter = OddsAPIRateLimiter(monthly_budget=500)
odds_client = OddsAPIClient()
for i, config in enumerate(get_enabled_sport_configs()):
    monitor = SportsMonitor(config, odds_client, scanner, pm, fetcher, rate_limiter)
    task = asyncio.create_task(delayed_start(monitor, delay=i * 60))
```

기존 NBAMonitor 단독 코드 교체. 스태거 시작 (60초 간격).

---

## 핵심 파일

| 파일 | 액션 |
|------|------|
| `src/poly24h/strategy/sport_config.py` | **NEW** — SportConfig + 8개 스포츠 상수 |
| `src/poly24h/strategy/team_data.py` | **NEW** — NHL/축구 팀명 (NBA 이동) |
| `src/poly24h/strategy/sports_monitor.py` | **NEW** — SportsMonitor (NBAMonitor 일반화) |
| `src/poly24h/strategy/odds_rate_limiter.py` | **NEW** — Odds API 예산 관리 |
| `src/poly24h/strategy/odds_api.py` | **MOD** — fetch_odds(), devig_three_way(), 파라미터화 |
| `src/poly24h/strategy/nba_monitor.py` | **MOD** — SportsMonitor 서브클래스 |
| `src/poly24h/discovery/gamma_client.py` | **MOD** — fetch_game_events_by_series() |
| `src/poly24h/discovery/market_scanner.py` | **MOD** — discover_sport_markets() |
| `src/poly24h/main.py` | **MOD** — 멀티 모니터 런칭 |
| `tests/test_f026_multi_sport.py` | **NEW** — 전체 TDD 테스트 |

## 검증

1. `pytest tests/test_f026_multi_sport.py -v` — 새 테스트 전체 통과
2. `pytest tests/test_f025_nba_monitor.py -v` — 기존 NBA 테스트 역호환
3. `pytest --tb=short` — 전체 스위트 회귀 없음
4. 봇 시작 → 로그에서 각 스포츠 마켓 발견 + 매칭 확인
5. Odds API remaining 헤더 정상 감소 확인
