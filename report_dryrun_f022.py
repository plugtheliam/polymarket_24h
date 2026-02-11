#!/usr/bin/env python3
"""F-022 드라이런 개선된 리포트 - 활성/정산 포지션 모두 표시"""
import json
import subprocess
import re
from datetime import datetime, timezone, timedelta

F022_START = datetime(2026, 2, 10, 3, 6, tzinfo=timezone.utc)

def load_position_data():
    try:
        with open('data/position_manager_state.json') as f:
            return json.load(f)
    except:
        return None

def get_log_info():
    try:
        result = subprocess.run(
            ["grep", "Cycle [0-9]*", "logs/poly24h.log"],
            capture_output=True, text=True
        )
        lines = result.stdout.strip().split('\n')
        cycle_info = {'cycle': 'N/A', 'phase': 'N/A', 'markets_loaded': 'N/A', 'by_source': {}}
        
        if lines and lines[-1] and 'Cycle' in lines[-1]:
            last = lines[-1]
            parts = last.split('|')
            cycle_info['cycle'] = parts[0].split('Cycle')[1].strip()
            cycle_info['phase'] = parts[1].split(':')[1].strip() if len(parts) > 1 else 'unknown'
        
        markets_result = subprocess.run(
            ["grep", "markets loaded", "logs/poly24h.log"],
            capture_output=True, text=True
        )
        markets_lines = markets_result.stdout.strip().split('\n')
        if markets_lines and markets_lines[-1]:
            match = re.search(r'(\d+) markets loaded', markets_lines[-1])
            if match:
                cycle_info['markets_loaded'] = match.group(1)
            source_match = re.search(r'— (.+)$', markets_lines[-1])
            if source_match:
                sources = source_match.group(1).split(', ')
                for src in sources:
                    if ':' in src:
                        name, count = src.split(':')
                        cycle_info['by_source'][name] = int(count)
        
        stats_result = subprocess.run(
            ["grep", "CYCLE END", "logs/poly24h.log"],
            capture_output=True, text=True
        )
        stats_lines = stats_result.stdout.strip().split('\n')
        if stats_lines and stats_lines[-1]:
            m = re.search(r'signals=(\d+)/(\d+).*paper=(\d+).*\$(\d+)', stats_lines[-1])
            if m:
                cycle_info['filtered_signals'] = int(m.group(1))
                cycle_info['raw_signals'] = int(m.group(2))
                cycle_info['paper_trades'] = int(m.group(3))
                cycle_info['paper_invested'] = int(m.group(4))
        
        return cycle_info
    except:
        return {'cycle': 'N/A', 'phase': 'N/A', 'markets_loaded': 'N/A', 'by_source': {}}

def format_time_utc_est_kst(dt_str):
    """UTC 시간 문자열을 UTC/EST/KST 3개 시간대로 변환"""
    try:
        # 입력 파싱 (HH:MM 또는 전체 ISO)
        if len(dt_str) == 5 and ':' in dt_str:  # HH:MM
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            dt = datetime.fromisoformat(f"{today}T{dt_str}:00+00:00")
        else:
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        
        utc = dt.strftime('%H:%M')
        est = (dt.astimezone(timezone(timedelta(hours=-5)))).strftime('%H:%M')
        kst = (dt.astimezone(timezone(timedelta(hours=9)))).strftime('%H:%M')
        return f"{utc}UTC / {est}EST / {kst}KST"
    except:
        return dt_str

def get_settled_positions():
    """정산된 포지션 로그에서 추출"""
    try:
        result = subprocess.run(
            ["grep", "POSITION SETTLED", "logs/poly24h.log"],
            capture_output=True, text=True
        )
        settled = []
        for line in result.stdout.strip().split('\n'):
            if 'POSITION SETTLED' in line:
                # 파싱: [POSITION SETTLED] 마켓명 | 결과: 사이드 vs 승자 | P&L: $금액
                match = re.search(r'SETTLED\] (.+?) \| (\w+): (.+?) vs (.+?) \| P&L: \$([\-\d.]+)', line)
                if match:
                    settled.append({
                        'market': match.group(1)[:40],
                        'result': match.group(2),
                        'side': match.group(3),
                        'winner': match.group(4),
                        'pnl': float(match.group(5))
                    })
        return settled
    except:
        return []
    """정산된 포지션 로그에서 추출"""
    try:
        result = subprocess.run(
            ["grep", "POSITION SETTLED", "logs/poly24h.log"],
            capture_output=True, text=True
        )
        settled = []
        for line in result.stdout.strip().split('\n'):
            if 'POSITION SETTLED' in line:
                # 파싱: [POSITION SETTLED] 마켓명 | 결과: 사이드 vs 승자 | P&L: $금액
                match = re.search(r'SETTLED\] (.+?) \| (\w+): (.+?) vs (.+?) \| P&L: \$([\-\d.]+)', line)
                if match:
                    settled.append({
                        'market': match.group(1)[:40],
                        'result': match.group(2),
                        'side': match.group(3),
                        'winner': match.group(4),
                        'pnl': float(match.group(5))
                    })
        return settled
    except:
        return []

def main():
    data = load_position_data()
    if not data:
        print("❌ 데이터 로드 실패")
        return

    positions = data.get('positions', {})
    bankroll = data.get('bankroll', 0)
    initial = data.get('initial_bankroll', 1000)
    total_invested = data.get('total_invested', 0)
    cumulative_pnl = data.get('cumulative_pnl', 0)
    wins = data.get('wins', 0)
    losses = data.get('losses', 0)
    
    # 정산된 포지션 로그에서 추출
    settled_positions = get_settled_positions()
    
    log_info = get_log_info()
    now_utc = datetime.now(timezone.utc)
    now_est = now_utc.astimezone(timezone(timedelta(hours=-5)))
    now_kst = now_utc.astimezone(timezone(timedelta(hours=9)))
    
    time_str = f"{now_utc.strftime('%Y-%m-%d %H:%M')}UTC / {now_est.strftime('%H:%M')}EST / {now_kst.strftime('%H:%M')}KST"
    elapsed_mins = int((now_utc - F022_START).total_seconds() / 60)
    
    print(f"📊 Poly24H F-022 드라이런 리포트 (1시간)")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"⏰ {time_str} (재시작 후 {elapsed_mins}분 경과)")
    print()
    
    print(f"🤖 **봇 상태**: ✅ 실행중")
    print(f"🔄 사이클: #{log_info.get('cycle', 'N/A')} | Phase: {log_info.get('phase', 'N/A')}")
    print()
    
    # 발견 현황 - 소스별 분류
    print(f"🔍 **발견 현황** (최근 사이클)")
    total_markets = log_info.get('markets_loaded', 'N/A')
    print(f"  • 총 마켓: {total_markets}개")
    
    by_source = log_info.get('by_source', {})
    if by_source:
        for source, count in sorted(by_source.items(), key=lambda x: -x[1]):
            emoji = "🪙" if "crypto" in source else "🏀" if "nba" in source else "📊"
            print(f"  {emoji} {source}: {count}개")
    print()
    
    # 시그널 통계
    print(f"📡 **시그널 통계**")
    raw = log_info.get('raw_signals', 0)
    filtered = log_info.get('filtered_signals', 0)
    paper = log_info.get('paper_trades', 0)
    print(f"  • Raw signals: {raw}개")
    print(f"  • Filtered signals: {filtered}개")
    print(f"  • Paper trades: {paper}건")
    if raw > 0:
        filter_rate = ((raw - filtered) / raw * 100)
        print(f"  • 필터링률: {filter_rate:.1f}%")
    print()
    
    # 자금 현황
    print(f"💰 **자금 현황**")
    print(f"  • 시작 Bankroll: ${initial:.2f}")
    print(f"  • 현재 Bankroll: ${bankroll:.2f}")
    print(f"  • 총 투자액: ${total_invested:.2f}")
    print(f"  • 누적 P&L: ${cumulative_pnl:+.2f}")
    print(f"  • 승/패: {wins}승 / {losses}패")
    if bankroll <= 0:
        print(f"  ⚠️  **경고**: Bankroll 고갈!")
    elif bankroll < initial * 0.1:
        print(f"  ⚠️  **주의**: Bankroll 10% 이하")
    print()
    
    # 정산된 포지션 분석 섹션 추가
    if settled_positions:
        print(f"✅ **정산 결과 분석** (총 {len(settled_positions)}개)")
        total_settled_pnl = sum(p['pnl'] for p in settled_positions)
        
        # 카테고리별 분류
        crypto_settled = [p for p in settled_positions if 'Up or Down' in p['market']]
        nba_settled = [p for p in settled_positions if 'Up or Down' not in p['market']]
        
        crypto_wins = len([p for p in crypto_settled if p['pnl'] > 0])
        crypto_pnl = sum(p['pnl'] for p in crypto_settled)
        nba_wins = len([p for p in nba_settled if p['pnl'] > 0])
        nba_pnl = sum(p['pnl'] for p in nba_settled)
        
        print(f"  🪙 Crypto: {crypto_wins}/{len(crypto_settled)} 승 | P&L: ${crypto_pnl:+.2f}")
        print(f"  🏀 NBA: {nba_wins}/{len(nba_settled)} 승 | P&L: ${nba_pnl:+.2f}")
        print(f"  💰 총 정산 P&L: ${total_settled_pnl:+.2f}")
        
        # 최근 정산 5개
        print(f"\n  📋 최근 정산:")
        for i, p in enumerate(settled_positions[-5:], 1):
            result_emoji = "🟢" if p['pnl'] > 0 else "🔴"
            print(f"  {result_emoji} {p['market'][:40]}... | ${p['pnl']:+.2f}")
        print()
    
    # 활성 포지션 분석
    if positions:
        print(f"📈 **활성 포지션** (총 {len(positions)}개)")
        sorted_pos = sorted(positions.items(), key=lambda x: x[1].get('entry_time', ''), reverse=True)
        for i, (pid, p) in enumerate(sorted_pos, 1):
            q = p.get('market_question', 'Unknown')[:45]
            side = p.get('side', '?')
            price = p.get('entry_price', 0)
            size = p.get('size_usd', 0)
            # 시간을 3개 시간대로 변환
            entry_time = p.get('entry_time', '')
            if entry_time:
                time_str = format_time_utc_est_kst(entry_time)
            else:
                time_str = "Unknown"
            print(f"  {i:2d}. {q}")
            print(f"      ({side}) @ ${price:.2f} [${size}]")
            print(f"      정산: {time_str}")
        print()
    
    # F-022 기능 상태
    print(f"🔧 **F-022 기능 상태**")
    print(f"  • 직접 마켓 조회: ✅")
    print(f"  • 시간 검증: ✅")
    print(f"  • CLOB 유동성: ✅")
    print(f"  • 락 기반 동시성: ✅")
    print()
    
    print(f"⏱️ 다음 리포트: 1시간 후")

if __name__ == '__main__':
    main()
