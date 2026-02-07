# 🚀 poly24h Live Trading Checklist

## Overview

This checklist covers everything needed to transition from dry-run mode to live trading.
**DO NOT SKIP ANY STEP.** Each item is critical for safe live operation.

---

## 1. 환경 검증 (Environment)

### 1.1 API Keys & Credentials
- [ ] `POLY_API_KEY` — Polymarket CLOB API key set in `.env`
- [ ] `POLY_API_SECRET` — Polymarket CLOB API secret set in `.env`
- [ ] `POLY_API_PASSPHRASE` — Polymarket CLOB passphrase set in `.env`
- [ ] `POLY_PRIVATE_KEY` — Ethereum private key for order signing
- [ ] `TELEGRAM_BOT_TOKEN` — Telegram bot token for alerts
- [ ] `TELEGRAM_CHAT_ID` — Telegram chat ID for alerts
- [ ] API keys tested with a read-only request (GET /book)

### 1.2 Wallet
- [ ] Wallet has sufficient USDC balance (minimum $100 recommended)
- [ ] Wallet is approved for Polymarket CLOB trading
- [ ] Wallet allowance set for CTF Exchange contract
- [ ] Test with `python -m poly24h --mode preflight` (see below)

### 1.3 Bot Configuration
- [ ] `POLY24H_DRY_RUN=false` in `.env` (currently should be `true`)
- [ ] `POLY24H_MAX_POSITION_USD` set to desired limit
- [ ] `POLY24H_SCAN_INTERVAL` configured (recommended: 60s)
- [ ] Risk limits reviewed and adjusted:
  - `daily_loss_limit`: Max daily loss in USD
  - `max_per_market`: Max exposure per market
  - `max_total`: Max total portfolio exposure
  - `max_consecutive_losses`: Loss streak before cooldown
  - `cooldown_seconds`: Cooldown duration after streak

---

## 2. 리스크 관리 (Risk Management)

### 2.1 Position Limits
- [ ] Max position per market: $____ USD
- [ ] Max total portfolio: $____ USD
- [ ] Daily loss limit: $____ USD
- [ ] Paper trade results reviewed (run `python -m poly24h --mode analyze`)
- [ ] Kelly Criterion sizing reviewed (if enough paper trade data)

### 2.2 Kill Switch
- [ ] Kill switch mechanism verified:
  - **Screen session**: `screen -S poly24h -X quit` kills the bot
  - **Signal handling**: Bot responds to SIGINT/SIGTERM gracefully
  - **Daily loss limiter**: Auto-stops after daily limit reached
  - **Cooldown**: Auto-pauses after consecutive losses
- [ ] Emergency contact method available (Telegram alerts active)

### 2.3 Order Protections
- [ ] Orders use limit prices (no market orders)
- [ ] Order expiration set (default: 300s / 5 minutes)
- [ ] Post-only mode consideration for maker rebates
- [ ] Slippage protection: max acceptable spread defined
- [ ] Duplicate position prevention enabled

---

## 3. 인프라 (Infrastructure)

### 3.1 Server
- [ ] Bot running on reliable server (not laptop)
- [ ] Sufficient RAM (>512MB free)
- [ ] Stable internet connection
- [ ] Time synchronized (NTP)
- [ ] `screen` or `tmux` session for persistence

### 3.2 Monitoring
- [ ] Telegram alerts active and tested
- [ ] Log rotation configured (`logs/` directory)
- [ ] Cycle reports being sent correctly
- [ ] Dashboard accessible (if enabled)

### 3.3 Recovery
- [ ] Bot auto-restarts on crash (systemd/supervisor optional)
- [ ] Position state persisted to disk
- [ ] Paper trade JSONL files backed up
- [ ] Git repo up to date with latest code

---

## 4. 실전 전환 절차 (Go-Live Procedure)

### Step 1: Final Dry Run Verification
```bash
# Stop current dry-run bot
screen -S poly24h -X quit

# Run preflight check
cd /home/liam/workspace/polymarket_24h
.venv/bin/python -m poly24h --mode preflight

# Review paper trade analysis
.venv/bin/python -m poly24h --mode analyze --days 7
```

### Step 2: Update Configuration
```bash
# Edit .env
# POLY24H_DRY_RUN=false
# Set conservative limits initially:
# POLY24H_MAX_POSITION_USD=50
```

### Step 3: Start with Conservative Settings
```bash
screen -S poly24h
cd /home/liam/workspace/polymarket_24h
.venv/bin/python -m poly24h --mode sniper --threshold 0.45
# Ctrl+A, D to detach
```

### Step 4: Monitor First Hour
- [ ] Watch Telegram for first trade alerts
- [ ] Verify order submissions via CLOB API
- [ ] Check position tracking accuracy
- [ ] Confirm no duplicate entries

### Step 5: Gradual Scale-Up
- Week 1: $50 max position, threshold 0.45
- Week 2: $100 max position, threshold 0.46
- Week 3: $200 max position, threshold 0.47
- Week 4+: Full parameters based on performance

---

## 5. 비상 절차 (Emergency Procedures)

### Immediate Stop
```bash
# Kill bot immediately
screen -S poly24h -X quit

# Or send SIGTERM
kill $(pgrep -f "poly24h")
```

### Position Recovery
If bot crashes with open positions:
1. Check Polymarket UI for open orders
2. Cancel all open orders manually if needed
3. Record positions in paper_trades JSONL
4. Restart bot — it will not re-enter existing positions

### Common Issues
| Issue | Resolution |
|-------|-----------|
| API rate limit | Bot auto-retries; reduce scan frequency |
| Insufficient balance | Bot logs warning; add USDC to wallet |
| Network timeout | Bot continues next cycle; check connection |
| Telegram down | Bot still trades; check logs manually |
| Gamma API down | Discovery fails; bot retries next cycle |

---

## 6. CLOB 주문 상세 (Order Execution Details)

### Order Types
- **Limit Order (GTC)**: Good-Til-Cancelled — stays in book until filled or cancelled
- **Limit Order (GTD)**: Good-Til-Date — expires at specified timestamp
- **Currently using**: GTD with 5-minute expiration (recommended for arb)

### Order Parameters
- `side`: Always BUY (we buy both YES and NO tokens)
- `price`: Limit price in USDC (0.01 to 0.99)
- `size`: Number of shares (minimum varies by market)
- `feeRateBps`: Fee rate in basis points (typically 0 for CLOB)
- `nonce`: Unique per-order (timestamp-based)
- `expiration`: Unix timestamp for GTD orders

### Execution Sequence
1. Build YES order + NO order from opportunity
2. Sign both with EIP-712
3. Submit YES order to CLOB
4. Submit NO order to CLOB
5. Track both orders for fills
6. Update position on fill confirmation

### Known Risks
- **Leg risk**: YES fills but NO doesn't (or vice versa)
  - Mitigation: Use paired entry only when both sides have liquidity
  - Mitigation: GTD expiration prevents stale orders
- **Front-running**: Others may see and front-run our orders
  - Mitigation: Post-only consideration
  - Mitigation: Rapid execution during snipe window
- **Price movement**: Market moves between order build and fill
  - Mitigation: Short GTD expiration (5 min)
  - Mitigation: Dynamic threshold re-check

---

## Preflight Script

Run `python -m poly24h --mode preflight` to automatically verify:
- [x] Python version and dependencies
- [x] .env file exists and contains required keys
- [x] Telegram bot connectivity
- [x] Gamma API reachable
- [x] CLOB API reachable
- [x] Data directories writable
- [x] Risk parameters within safe ranges

---

*Last updated: 2026-02-07*
*Version: Phase 4*
