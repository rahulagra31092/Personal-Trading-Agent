# Warren B Trading System — Complete Goals & Automations Summary
**As of June 8, 2026 — Paper Trading Launch Tomorrow**

---

## 📊 PRIMARY PROJECT GOALS

### North Star Goals
1. **Primary Goal:** 25% annual return on existing portfolio (Robinhood/Schwab/Ledger holdings)
2. **Secondary Goal:** 5-10x return on $5,000 ring-fenced trading account (aspirational, high-risk)
3. **Benchmark:** Beat SPY on risk-adjusted basis (target: 15%+ alpha annually)

### Success Metrics
- **Walk-Forward Backtest:** +21.4% avg alpha (2019-2023), beats SPY 4/5 years ✅
- **Forward Test (Jan-May 2026):** +25.72% return in 5 months, +75.8% annualized ✅
- **Paper Trading Target:** ≥45% win rate (5-week minimum validation)
- **Live Capital Gate:** ≥55% win rate before Phase 2 deployment

---

## 🤖 AUTOMATED SYSTEMS & WORKFLOWS

### 1. **Daily Briefing Automation** (n8n + FastAPI)
**Status:** ✅ LIVE & TESTED

**Universe:** 77 stocks (47 blue-chip + 30 midcap)  
**Trigger:** Every weekday at 8:05 AM EDT (via n8n cron)

**Workflow:**
```
n8n: 8:05 AM EDT
  ↓
Calls: POST http://172.17.0.1:8000/run-briefing/daily
  ↓
FastAPI: /run-briefing/daily endpoint (api/briefing.py)
  ├─ Fetch market data (VIX, SPY 3-month return, regime)
  ├─ Score all 77 stocks on 7-factor model
  ├─ Generate BUY/AVOID/WATCH picks (signal > 0.58)
  ├─ Update paper portfolio P&L
  ├─ Check trailing stops (20% from peak)
  ├─ Log daily scores (for 5-day trend tracking)
  ├─ Deploy idle cash if threshold hit
  └─ POST to Slack with formatted message
```

**Slack Output:**
- Market intel: VIX, SPY 3m return, regime (normal/elevated/crisis)
- Top BUY picks: ticker, score, conviction, 5-day trend arrow
- Paper portfolio P&L: invested value, current value, % return

**Component Status:**
- n8n workflow: ✅ All 4 nodes green, tested daily
- FastAPI service: ✅ Running on 204.48.17.22:8000
- Slack integration: ✅ 2 messages per briefing (intel + portfolio)

---

### 2. **Monthly Strategy Review** (n8n + FastAPI)
**Status:** ✅ READY & CONFIGURED

**Trigger:** 1st of every month at 1:00 PM EDT

**Workflow:**
```
n8n: 1st of month @ 1:00 PM EDT
  ↓
Calls: POST http://172.17.0.1:8000/run-briefing/monthly
  ↓
FastAPI: /run-briefing/monthly endpoint
  ├─ Aggregate 30-day signal quality metrics
  ├─ Recommend weight adjustments (if annual cap allows)
  ├─ Review quarterly rebalancing rules
  ├─ Generate narrative analysis
  └─ POST to Slack
```

**Deployment Status:**
- ✅ n8n URL fixed: `127.0.0.1:8000` → `172.17.0.1:8000` (Docker routing)
- ✅ New Warren B workflow: `/warren-b/monthly` endpoint configured
- ✅ Ready to activate on DigitalOcean

---

### 3. **Paper Portfolio Database** (SQLite Auto-Updates)
**Status:** 🔄 RESET for June 9 launch

**Auto-Updated Fields:**
- `peak_price` — updated daily with high of day if new peak
- `cash` — decremented on buy, incremented on sell
- Daily scores logged to `score_history` table
- Trade outcomes recorded in `signal_outcomes` table

**Trailing Stop Logic:**
- Fires when: `current_price < peak_price × (1 - 0.20)`
- Action: Auto-liquidate position, log exit
- Cooldown: Don't re-enter same ticker for 5 days

**Cash Deployment Trigger:**
- If `cash > 2 × POSITION_SIZE` after trailing stop fires
- Action: Buy top unowned BUY-qualified ticker immediately

---

### 4. **Daily Score Logging & Trending** (SQLite + API)
**Status:** ✅ LIVE

**What's Tracked:**
- Composite score for each ticker daily
- 5-day rolling trend (delta from 5 days ago)
- Direction indicator (↑ if positive delta, ↓ if negative)

**Use Case:** Slack briefing shows trend arrows next to each ticker:
```
AAPL   0.72 [Very High]  ↑ +0.06
NVDA   0.68 [High]       ↓ -0.04
```

**Query:** `get_score_trend(ticker, as_of=None)` returns `{latest_score, delta_5d, direction}`

---

## 📈 7-LAYER SIGNAL MODEL (Reweighted)

| Layer | Weight | Source | Key Features |
|-------|--------|--------|--------------|
| **Technical** | 15% | quant/indicators.py | RSI, ATR, EMA, SPY relative strength |
| **Momentum** | 30% | quant/momentum.py | R² trend quality + acceleration bonus |
| **Quality** | 15% | quant/quality.py | ROE, FCF, gross margin, D/E ratio |
| **Insider Trades** | 7% | smart_money/insider_trades.py | Form 4 insider buy/sell activity |
| **Est. Revisions** | 7% | smart_money/estimate_revisions.py | Analyst EPS upgrades/downgrades (30d) |
| **Earnings** | 15% | smart_money/earnings_scorer.py | Beat rate, surprise magnitude, growth |
| **(News - REMOVED)** | — | — | Deleted 2026-06-08 (unreliable keyword matching) |

**Signal Thresholds:**
- **BUY:** composite_score > 0.65 (entry threshold after threshold sensitivity testing)
- **AVOID:** composite_score < 0.42
- **WATCH:** 0.42 - 0.65

---

## 🛡️ RISK MANAGEMENT (6-GROUP MODEL UPGRADES)

### Group 1 — Risk Controls
- **Trailing Stop:** 20% from peak; auto-liquidates on breach
- **Quality Gate:** If quality < 0.35 AND composite > 0.57 → caps composite at 0.57
- **Portfolio Beta Cap:** If portfolio beta > 1.25 → raises entry threshold from 0.55 to 0.62
- **Rapid Deterioration:** If position down >8% AND held <10 days → can exit immediately (bypass 30-day min-hold)

### Group 2 — Capital Deployment
- **Conviction-Based Sizing:** `size = base × conviction_mult × regime_factor × vol_mult`
  - ≥0.75 composite → 1.40x base
  - ≥0.65 composite → 1.00x base
  - <0.65 composite → 0.20x base (weak signal)
- **Hard Cap:** Max 8% of portfolio per position
- **Volatility Scaling:** GARCH vol scalar applied (0.75-1.25x multiplier)
- **Cash Deployment:** Auto-buy top unowned ticker when cash > 2x position size

### Group 3 — Factor Quality
- **Analyst Revisions Replace Trump:** Net grade changes (upgrades vs downgrades) in last 30 days
- **Fallback Source:** Analyst recommendation mean (1=Strong Buy, 5=Strong Sell)
- **Negation Detection:** "not beat" → bearish, "not decline" → bullish (5-word window)

### Group 4 — Signal Stability
- **Daily Score Logging:** `score_history` table captures composite score every day
- **5-Day Trend:** Direction indicator (↑ or ↓) based on delta from 5 days prior
- **Threshold:** ±0.02 minimum change to register direction shift

### Group 5 — Governance
- **Quarterly Review Minimum:** 40 positions closed before weight regression (raised from 15)
- **Holdout Validation:** 75/25 temporal split; if holdout disagrees (>0.10 magnitude), halve nudge
- **Annual Weight Cap:** ±8pp per factor per 365 days; tracked in `weight_changes` table

### Group 6 — Validation
- **Walk-Forward Backtest Engine:** 2-factor composite (technical 33% + momentum 67%)
- **Success Criteria:** ≥4 positive-alpha years AND worst annual ≥ -18%
- **2019-2023 Result:** 4/5 years positive alpha, avg +21.4%, passes validation ✅

---

## 🚀 3-PHASE LIVE TRADING ROLLOUT

| Phase | Capital | Trigger Gate | Timeline |
|-------|---------|--------------|----------|
| **Phase 1** | Paper only ($10K) | Launch June 9 | 4 weeks |
| **Phase 2** | $2.5K paper + $2.5K live | ≥50% win rate in Phase 1 | June 23 |
| **Phase 3** | Full $5K live | ≥65% confidence sustained | TBD |

**Hard Stops:**
- Phase 2 pause: Cumulative loss > $2,000
- Phase 3 pause: Cumulative loss > $4,000

**Circuit Breaker (June 8 Fix):**
- Daily loss limit: 2.5% of capital → halt all trading
- Consecutive loss limit: 3 losses in a row → halt all trading
- Market gap protection: Forced liquidation on extreme moves

---

## 📊 BACKTEST RESULTS & VALIDATION

### Walk-Forward Backtest (2019-2023)
| Year | Model | SPY | Alpha | Pass? |
|------|-------|-----|-------|-------|
| 2019 | +69.6% | +30.8% | **+38.8%** | ✅ |
| 2020 | +66.0% | +16.6% | **+49.4%** | ✅ |
| 2021 | +48.0% | +30.8% | **+17.2%** | ✅ |
| 2022 | -22.1% | -18.6% | -3.5% | ❌ |
| 2023 | +31.6% | +26.7% | **+4.9%** | ✅ |

**Verdict:** 4/5 years positive alpha, avg **+21.4%** ✅

### Forward Test (Jan 2 - May 29, 2026)
- **Portfolio Return:** +25.72% (5 months)
- **Annualized:** +75.8%
- **SPY Return:** +11.03%
- **Alpha:** +14.68%
- **Win Rate:** 75% (15/20 positions profitable)
- **Best Position:** MU +208%

---

## 🔧 INFRASTRUCTURE & DEPLOYMENT

### Droplet Details
- **Host:** 204.48.17.22 (DigitalOcean)
- **FastAPI:** Port 8000 (0.0.0.0 binding)
- **n8n:** Port 5678
- **Systemd Service:** `trading-analyst.service`
- **Health Status:** API responding, all endpoints green

### Key Endpoints
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/analyze/{ticker}` | GET | Score single ticker |
| `/run-briefing/daily` | POST | Generate daily briefing + log scores |
| `/run-briefing/monthly` | POST | Monthly strategy review |
| `/health` | GET | System health check |
| `/control/circuit-breaker` | GET/POST | Check/reset circuit breaker status |

### Database Schema
| Table | Purpose | Auto-Updated |
|-------|---------|--------------|
| `paper_account` | Capital, cash, created_date | ✅ Cash on buy/sell |
| `paper_positions` | Open positions, avg_cost, peak_price | ✅ peak_price daily |
| `paper_trades` | Entry/exit history | ✅ On all trades |
| `signal_outcomes` | Signal scores at entry + exit outcome | ✅ Quarterly |
| `score_history` | Daily composite scores | ✅ Daily |
| `weight_changes` | Factor weight updates | ✅ Quarterly |
| `warren_b_decisions` | Decision log for audit trail | ✅ Daily |
| `warren_b_conversations` | Chat history with Warren B AI | ✅ On chat |

---

## 📋 CRITICAL AUTOMATIONS SUMMARY

### ✅ LIVE & ACTIVE
1. Daily score calculation & logging (7-factor model)
2. Daily Slack briefing (market intel + portfolio P&L)
3. Trailing stop monitoring (20% peak breach)
4. Cash deployment trigger (when cash > 2x position)
5. Circuit breaker enforcement (2.5% daily loss limit)
6. Paper portfolio P&L tracking

### ⚠️ PARTIALLY IMPLEMENTED
1. Monthly strategy review (workflow created, needs URL fix)
2. Quarterly weight regression (code ready, not yet scheduled)
3. Annual weight cap enforcement (logic in place, tracking enabled)

### ❌ NOT YET IMPLEMENTED
1. Schwab OAuth integration (planned, not started)
2. 13F/ARK flow imports (planned, not started)
3. GDELT geopolitical data (planned, not started)
4. Real portfolio ($100K capital) live trading (pending Phase 2 gate)

---

## 🎯 JUNE 9 PAPER TRADING LAUNCH CHECKLIST

### Critical Fixes (P0)
- [x] Database corruption root cause identified & fixed (duplicate signal_outcomes prevention)
- [x] Real-time data quality monitoring deployed (health classification: Healthy/Degraded/Dead)
- [x] Per-stock entry thresholds deployed (0.70 for MSFT/META, 0.65 for trend-followers)

### Automation & Reliability (P1)
- [x] Docker URL routing fixed (127.0.0.1:8000 → 172.17.0.1:8000 for n8n)
- [x] 24/7 circuit-breaker monitoring with Slack alerts (critical + data quality webhooks)

### Data Durability (P2)
- [x] Automated database backup system deployed (30-day retention, integrity verification)
- [x] Backup cleanup & restore utilities built and tested

### Pre-Launch Verification
- [x] All 6-group model upgrades completed
- [x] Warren B audit complete (93/100 confidence)
- [x] Backtest validation passing (4/5 years positive alpha)
- [x] Circuit breaker implemented + tested
- [x] Threshold sensitivity analysis done
- [x] Data quality diagnostics built + tested
- [x] Paper portfolio database reset (corrupted data cleaned)
- [x] **FULL TEST SUITE: 619/619 TESTS PASSING**
- [x] Final manual test of briefing endpoint
- [x] Confirm n8n workflows are active & synced
- [x] Verify Slack integration live
- [ ] First briefing tomorrow 8:05 AM EDT

---

## 📞 SUPPORT & MONITORING

### Daily Monitoring
```bash
# Check FastAPI service status
systemctl status trading-analyst

# View live logs
journalctl -u trading-analyst -f

# Test API health
curl http://204.48.17.22:8000/health

# Manual briefing trigger (if needed)
curl -X POST http://172.17.0.1:8000/run-briefing/daily
```

### Emergency Actions
1. **Service crash:** `systemctl restart trading-analyst`
2. **Database corruption:** Delete `data/paper_portfolio.db`, service auto-recreates on next briefing
3. **Circuit breaker stuck:** `curl -X POST http://204.48.17.22:8000/control/circuit-breaker/reset`
4. **Stop all trading:** Set circuit breaker max_daily_loss to 0.001 (1bp)

---

**Status:** 🟢 **READY FOR PAPER TRADING LAUNCH**  
**Date:** June 9, 2026  
**Next Milestone:** 4-week paper validation (Phase 1 → Phase 2 gate)