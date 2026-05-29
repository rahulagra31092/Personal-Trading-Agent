# Personal Trading Analyst — Design Spec
**Date:** 2026-05-18  
**Status:** Approved  
**Owner:** Rahul  
**Monthly cost:** ~$34/month (Polygon.io $29 + Claude API ~$5)

---

## Overview

A personal AI-powered trading analyst that analyzes Rahul's existing portfolio, generates daily trade recommendations for a $5,000 ring-fenced account, and delivers morning + evening market briefings to Slack. All trades are executed manually by Rahul — the system is a recommendation and tracking engine, not an autonomous trader.

---

## Architecture: Python Core + n8n Orchestration

Python handles all computation (quant model, data fetching, signal generation, portfolio analysis). FastAPI exposes endpoints that n8n calls on schedule. Claude API narrates raw signals into readable Slack briefings. All runs on the existing DigitalOcean server (204.48.17.22) with the existing n8n instance.

```
Data Sources → Python Core → FastAPI → n8n → Slack
```

---

## North Star Goals

| Goal | Target | Account |
|------|--------|---------|
| **Primary** | 25% annual return | Existing portfolio (all holdings) |
| **Secondary** | 5–10x return over model lifetime | $5,000 ring-fenced trading account |

The 25% annual return on the existing portfolio is the north star — every signal weight tuning decision, every model improvement, and every monthly review is evaluated against this benchmark. SPY (S&P 500) is the floor; 25% is the goal.

The $5K account is the high-risk proving ground. 5–10x means 50–100%+ annual return — this requires aggressive signal confidence thresholds and is explicitly understood to carry meaningful loss risk. It is separate from the main portfolio north star.

**Risk acknowledgement:** 5–10x on the $5K is an aspirational target, not a projection. Any strategy capable of 5–10x returns carries commensurate risk of significant loss. The hard stop rules (Phase 2: $2K floor, Phase 3: $4K floor) are the guardrails.

---

## Hard Rules (Non-Negotiable)

- **FUBO excluded everywhere** — hardcoded in portfolio analyzer and signal generator. Never surfaces as a recommendation regardless of signals.
- **No automated trade execution** — system generates recommendations only. Rahul executes manually.
- **Phase gates** — system does not advance phases automatically. Rahul reviews and approves.
- **Hard stops** — Phase 2: pause if live drops to $2,000. Phase 3: pause if live drops to $4,000. System alerts Rahul and waits for instruction.

---

## Data Sources

| Source | Data | Cost |
|--------|------|------|
| Polygon.io | Real-time + EOD stock prices | $29/mo |
| yfinance | Historical prices, crypto, earnings calendar | Free |
| NewsAPI | Market news headlines | Free |
| SEC EDGAR | 13F filings, STOCK Act disclosures | Free |
| ARK ETF | Daily holdings CSV (auto-downloaded) | Free |
| Whale Alert | On-chain crypto whale transactions | Free tier |
| Quiver Quantitative | Congressional trade data | Free tier |
| Claude API (Sonnet 4.6) | Analysis narration, news classification | ~$5/mo |

All data is cached in a local SQLite database to avoid redundant API calls between morning and evening runs.

---

## Quant Model — 8 Layers

### Layer 1: Technical Indicators
RSI · MACD · Bollinger Bands · EMA 20/50/200 · ATR-based stops · Volume confirmation (signal requires volume > 20-day average).

### Layer 2: Forecasting (ARIMA + GARCH)
- **ARIMA**: Price direction forecast 1–5 days. Outputs probability and target range.
- **GARCH**: Volatility forecast. High GARCH = wider confidence band = lower position sizing.

### Layer 3: Smart Money Overlay
- **13F filings** — Buffett, Ackman, Burry and other major institutional holders (quarterly, SEC EDGAR)
- **ARK ETF flows** — Cathie Wood daily buys/sells (daily CSV)
- **Crypto whale wallets** — Large BTC/ETH/SOL wallet accumulation (Whale Alert)
- **Congressional trades** — STOCK Act disclosures filtered to party in power (Quiver Quantitative)

### Layer 4: Signal Combiner + Scorer
Weighted composite score per ticker → BUY (>0.65) / WATCH (0.40–0.65) / AVOID (<0.40)

| Signal Layer | Weight |
|-------------|--------|
| Technical indicators | 30% |
| ARIMA forecast | 20% |
| Smart money overlay | 20% |
| News reaction | 15% |
| Earnings layer | 15% |

Weights are tunable. Updated via monthly weight review report (system recommends, Rahul approves).

### Layer 5: Monte Carlo Confidence Bands
1,000 simulations per ticker signal. Outputs: base price target, 80% confidence interval, downside %, upside %, and expected daily volatility. Every recommendation includes these bands — never a single number.

### Layer 6: Backtester
2-year historical validation run on signal model before any live deployment. Two mandatory guards:
- **Lookahead bias prevention** — signals only use data available at the time of the bar being evaluated
- **Survivorship bias protection** — uses adjusted prices accounting for splits, delistings, and mergers

### Layer 7: Earnings Layer
- **Pre-earnings setup** — is the stock running up into earnings (sell-the-news risk) or beaten down (surprise pop potential)?
- **Historical beat/miss rate** — per-company EPS beat rate from yfinance earnings history
- **Analyst consensus vs implied whisper** — analyst EPS estimate vs what options market is pricing
- **Implied move** — derived from options implied volatility (read-only, no options trading)
- **Post-earnings drift** — signal activates day+1 to capture 3–5 day continuation move

### Layer 8: News Reaction Layer (Claude-powered)
- **News classification** — Claude categorises each headline: regulatory, product launch, macro, earnings, insider, partnership, etc.
- **Historical reaction matching** — cross-references news type with historical price reaction for that ticker
- **News-price divergence signal** — the primary signal: stock drops on good news (bearish reversal), stock holds on bad news (bullish strength). These divergences outperform pure sentiment.

---

## Portfolio Analyzer

**Holdings input:** Initial `holdings.csv` set up manually by Rahul. All subsequent updates via Slack trade logger (see below).

**Holdings tracked:**

| Account | Method |
|---------|--------|
| Robinhood | Initial CSV + Slack trade logger |
| Schwab | Schwab official OAuth API (auto-sync) |
| Fidelity | Skip — FUBO only, excluded |
| Ledger | Static quantities in config.py |

**Portfolio analysis outputs:**
- Current positions with unrealised P&L
- Portfolio beta, Sharpe ratio, VaR (95%)
- Sector and crypto exposure %
- Rebalancing suggestions with specific ticker actions
- Portfolio impact estimate for today's signals

**Triggered:** Automatically in every evening digest. On-demand via `/portfolio` Slack slash command.

---

## Slack Trade Logger

Rahul sends natural language trade messages to `#trading` Slack channel. n8n listens, passes to `/update-holding` endpoint, Claude parses to structured data, holdings.csv updates, Slack confirms.

**Accepted formats:**
```
bought 5 AMZN at 185.40
sold 2 ETH at 3200
added 10 SHOP in Schwab at 92.50
sold half my GOOG
```

**Confirmation response:**
```
✅ AMZN +5 shares at $185.40
   New position: 35.37 shares · Avg cost: $169.82
   Portfolio beta now 1.48 · Crypto at 37%
```

**Edge cases handled:**
- Ambiguous quantity/price → Slack asks clarifying question
- FUBO mentioned → "FUBO is excluded from analysis. Holdings noted but no signals generated."
- Unrecognised ticker → confirmation prompt before updating

---

## 3-Phase Rollout ($5,000 Account)

### Phase 1 — Month 1: Paper Trading Only
- Full model runs live, all signals fire, all recommendations sent to Slack
- No real money. P&L tracked in simulation.
- **Gate to Phase 2:** ≥55% win rate over the month
- Monthly weight review at end of month

### Phase 2 — Month 2: $2,500 Paper + $2,500 Live
- Paper portfolio: all signals (any confidence)
- Live portfolio: HIGH confidence signals only (≥70%)
- Side-by-side P&L comparison included in every evening digest
- **Hard stop:** if live drops to $2,000 → system pauses live signals, sends alert
- **Gate to Phase 3:** paper and live portfolios tracking closely (within 15% of each other)

### Phase 3 — Month 3+: Full $5,000 Live
- Full $5,000 deployed. Signals at ≥65% confidence.
- Paper portfolio continues as shadow (for ongoing signal validation)
- Weights tuned from 2 months of attribution data
- **Hard stop:** if live drops to $4,000 → system pauses, sends detailed alert, waits for Rahul instruction
- **Benchmark:** beat SPY on risk-adjusted basis over 12 months

---

## Daily Slack Briefings

**Weekdays only. No weekend noise.**

### Morning Brief — 7:00 AM ET
- Macro context: Fed events, VIX, dollar, overnight futures
- Today's signals: BUY/WATCH/AVOID per ticker with confidence %, price target range, ATR stop level
- Which smart money layers are confirming each signal
- Earnings alerts for next 48 hours
- Portfolio estimated impact if signals play out
- Paper trading running P&L vs SPY

### Evening Digest — 5:30 PM ET
- Market close summary
- Signal outcomes: which signals from this morning were correct (feeds attribution tracker)
- New signals firing for tomorrow
- Smart money alerts: any new congressional trades, ARK moves, whale transactions
- Paper P&L update + win rate
- Portfolio analysis one-liner (beta, crypto exposure)

### Instant Alerts (as they happen)
- Congressional trade disclosure filed for a ticker in portfolio or watchlist
- Crypto whale move above threshold
- Any signal crosses from WATCH to BUY or BUY to AVOID

---

## Signal Attribution Tracker + Monthly Weight Review

Every signal that fires is logged to `trades_log.csv` with: ticker, signal type, confidence, layers that fired, price at signal, price 5 days later, outcome (correct/incorrect).

**Monthly weight review report** (Sunday evening, end of each month):
- Per-layer accuracy over the month
- Suggested weight adjustments based on performance
- Paper trading P&L vs SPY
- Rahul approves or modifies weights → config.py updated

---

## Weekly Report

Sunday evening: PDF summary of the week — portfolio performance, top signals, win rate, paper trading P&L, and one paragraph on market outlook for the coming week. Delivered to `#trading` Slack.

---

## FastAPI Endpoints

| Endpoint | Called by | When |
|----------|-----------|------|
| `POST /morning-brief` | n8n | 7:00 AM ET weekdays |
| `POST /evening-digest` | n8n | 5:30 PM ET weekdays |
| `GET /signals` | n8n (poll) | Every 30 min |
| `POST /update-holding` | n8n (Slack trigger) | When Rahul logs a trade |
| `POST /portfolio` | n8n (Slack `/portfolio`) | On demand |
| `GET /paper-trades` | n8n (Slack `/paper`) | On demand |
| `GET /health` | n8n | Every 5 min |

---

## n8n Workflows (4 total, import to existing instance)

| File | Purpose |
|------|---------|
| `morning_brief.json` | Cron 7:00 AM → POST /morning-brief → format → Slack |
| `evening_digest.json` | Cron 5:30 PM → POST /evening-digest → format → Slack |
| `signal_alert.json` | Every 30 min → GET /signals → if significant → Slack |
| `trade_logger.json` | Listen #trading channel → POST /update-holding → confirm to Slack |

---

## Project File Structure

```
C:\Claude\Trading Analyst\
├── api/
│   └── main.py                  # FastAPI server — 7 endpoints
├── data/
│   ├── market.py                # Polygon.io + yfinance collector
│   ├── news.py                  # NewsAPI fetcher
│   ├── earnings.py              # Calendar, beat/miss history, implied move
│   └── cache.db                 # SQLite cache
├── smart_money/
│   ├── sec_13f.py               # SEC EDGAR 13F parser
│   ├── ark_flows.py             # ARK daily CSV downloader
│   ├── whale_tracker.py         # Whale Alert
│   └── congress.py              # STOCK Act scraper + party filter
├── quant/
│   ├── indicators.py            # RSI, MACD, Bollinger, EMA, ATR, Volume
│   ├── forecast.py              # ARIMA + GARCH
│   ├── signals.py               # Combiner + scorer (reads weights from config)
│   ├── confidence.py            # Monte Carlo simulations
│   ├── news_reaction.py         # Claude news classification + divergence
│   └── backtest.py              # Historical validation
├── portfolio/
│   ├── analyzer.py              # Sharpe, beta, VaR, rebalancing
│   ├── schwab_sync.py           # Schwab official OAuth sync
│   └── holdings.csv             # Source of truth — updated via Slack logger
├── narrator/
│   └── briefing.py              # Claude API — signals → Slack messages
├── paper_trading/
│   ├── tracker.py               # Phase 1→2→3 P&L + attribution ledger
│   └── trades_log.csv           # Every signal + outcome
├── n8n/
│   ├── morning_brief.json
│   ├── evening_digest.json
│   ├── signal_alert.json
│   └── trade_logger.json
├── config.py                    # API keys, signal weights, phase config, watchlist
├── requirements.txt
└── .env                         # Polygon, Claude, NewsAPI, Slack, Schwab keys
```

---

## Tech Stack

**Python libraries:** fastapi · uvicorn · pandas · numpy · pandas-ta · statsmodels · scipy · yfinance · polygon-api-client · anthropic · requests · httpx · schwab-py

**Infrastructure:** DigitalOcean (existing) · n8n (existing) · SQLite · Linux cron (backup)

**External services:** Polygon.io · Claude API (Sonnet 4.6 with prompt caching) · NewsAPI · SEC EDGAR · ARK ETF CSV · Whale Alert · Quiver Quantitative · Slack webhook · Schwab OAuth API

---

## Cost Summary

| Item | Monthly |
|------|---------|
| Polygon.io | $29.00 |
| Claude API (with prompt caching) | ~$5.00 |
| Everything else | $0.00 |
| **Total** | **~$34/month** |

---

## What This System Cannot Guarantee

- Positive returns on the $5,000 account — any model can lose money
- Perfect signal accuracy — all recommendations come with confidence bands, not certainties
- SEC/FINRA compliance advice — consult a CPA/attorney for regulatory questions
- Schwab API availability — unofficial downtime or OAuth token expiry may require a manual re-auth
