# Warren B — AI Financial Advisor: Design Specification

**Date:** 2026-06-04
**Status:** Approved — ready for implementation planning
**Phase:** 1 of 2 (Phase 2 = Alexandra T, tax advisor)

---

## 1. Overview

Warren B is a personal AI financial advisor that reads the trading model's daily output, maintains full memory of portfolio history and past decisions, and communicates with the investor as a seasoned, human-feeling advisor. He is not a chatbot. He is not a dashboard. He is a trusted advisor available every morning and on-demand throughout the day.

**The mission, always:** Generate 20% CAGR on $100K + $2K/month contributions from June 2026 to December 2030. Target: ~$417,000.

---

## 2. Goals & Non-Goals

### Goals
- Daily automated briefing (Slack) that reads model output and translates it into actionable human language
- On-demand conversation via web chat UI and Slack slash command
- Full portfolio context injected at every session — Warren B never asks for data he should already have
- Smart memory retrieval — relevant past decisions and history pulled automatically
- Monthly $2K deployment recommendation (1st of each month)
- Sector and market condition summaries
- Pacing against the 20% CAGR goal at every touchpoint
- Honest, no-hallucination, "I don't know" communication as a core pillar

### Non-Goals (Phase 2)
- Tax optimization (Alexandra T — deferred to Phase 2)
- Automated trade execution
- Real-time price alerts (VIX spikes will be handled in daily briefing)
- Multi-client support (personal use only)

---

## 3. Interface Design

### Dual Interface: Slack + Web Chat

**Slack (push channel):**
- Warren B posts the daily briefing automatically at ~8:05am ET (after the trading model runs at 8am)
- Urgent alerts posted when: trailing stop fires, beta cap exceeded, new very-high conviction signal appears
- `/warren [question]` slash command for quick on-demand questions
- Warren B responds in-thread to slash commands

**Web Chat UI (pull interface — deep conversations):**
- Simple browser-based chat at `http://[DROPLET_IP]:5001`
- Persistent conversation threads with full history
- Warren B's full context (portfolio, signals, goal pacing, memory) always loaded
- Mobile-friendly (investor accesses from phone)
- No login required (single-user, IP-restricted)

**Relationship between the two:**
- Warren B maintains shared memory across both interfaces
- A decision made in web chat is remembered in the next Slack briefing
- A signal flagged in Slack is visible as context in web chat

---

## 4. Memory Architecture

### Smart Retrieval (Option C)

Warren B does not load all history into every session. He loads what is relevant to the current conversation. Three memory layers:

**Layer 1 — Always Loaded (every session)**
```
- Goal: 20% CAGR to Dec 2030, $417K target
- Portfolio pacing: current value vs. on-track value
- Today's model signals (top 10 by score)
- Current positions (paper + real, from Google Sheets)
- Market regime (VIX, regime label, position factor)
- Factor health (are all 7 model factors operational?)
- Last 7 days of conversation history (full)
- Last 30 days of decision log (Warren B's recommendations + outcomes)
```

**Layer 2 — Smart Retrieval (pulled on demand)**
```
- Ticker-specific history: when user mentions NVDA, all past NVDA decisions load
- Period-specific history: "last month" → loads that month's decisions
- Topic-specific: "sector rotation" → loads past rotation decisions
- Milestone events: Phase 2 transition, major drawdowns, rebalancing events
```

**Layer 3 — Compressed Archive (never omitted, always summarized)**
```
- Weekly summaries of older conversations (auto-generated)
- Monthly performance reviews
- Key milestone log: "First rebalance: [date]", "Phase 2 started: [date]"
```

### What Gets Stored (Decision Log)
Every Warren B recommendation is logged:
```sql
CREATE TABLE warren_b_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_date TEXT NOT NULL,        -- ISO date
    ticker TEXT,                         -- NULL for portfolio-level decisions
    decision_type TEXT NOT NULL,         -- 'buy', 'sell', 'hold', 'rebalance', 'monthly_deploy', 'sector'
    recommendation TEXT NOT NULL,        -- what Warren B recommended
    rationale TEXT NOT NULL,             -- why
    model_score REAL,                    -- composite score at time of decision
    regime TEXT,                         -- market regime at time
    outcome TEXT,                        -- filled in later: 'correct', 'incorrect', 'pending'
    outcome_note TEXT,                   -- context on outcome
    session_id TEXT                      -- links to conversation
)
```

### Conversation History
```sql
CREATE TABLE warren_b_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    interface TEXT NOT NULL,             -- 'slack', 'web', 'briefing'
    role TEXT NOT NULL,                  -- 'user' or 'warren'
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    tokens_used INTEGER
)
```

---

## 5. Context Injection (What Warren B Sees Every Session)

Before every response, the system automatically builds Warren B's context:

```
=== WARREN B SESSION CONTEXT ===

DATE: [today]
INTERFACE: [slack/web/briefing]

GOAL PACING:
- Target: $417,000 by December 2030 (20% CAGR)
- Months elapsed: X | Months remaining: Y
- On-track value today: $[calculated]
- Actual portfolio value: $[real + paper]
- Status: [Ahead by $X / Behind by $X / On track]

MARKET REGIME:
- VIX: [value] | Regime: [label] | Position factor: [value]
- Factor health: [X/7 OK | degraded: list if any]

REAL PORTFOLIO (Google Sheets — live):
[ticker, shares, avg_cost, current_price, pnl, pnl_pct, short/long-term]
[sector breakdown]
[cash position]

PAPER MODEL PORTFOLIO:
[ticker, shares, score_at_entry, pnl]
[total value, cash]

TODAY'S MODEL SIGNALS (top 10 by conviction):
[ticker, label, score, conviction tier, 5-day trend, price, vol_regime]

RECENT DECISIONS (last 30 days):
[date, ticker, recommendation, rationale, outcome if known]

RECENT CONVERSATIONS (last 7 days):
[full history]

SMART RETRIEVED MEMORY:
[ticker-specific or topic-specific history if relevant]
```

---

## 6. Warren B System Prompt

Validated in demo run on 2026-06-04. Key pillars:

**Philosophy:** Synthesized from Buffett (compounding, circle of competence), Munger (inversion, mental models), Marks (cycles, second-level thinking), Dalio (systems, all-weather, radical transparency), Jones (risk management, cut losses), Lynch (2-minute test, know what you own), Templeton (contrarian, maximum pessimism), Klarman (margin of safety, patient capital).

**The "I Don't Know" Protocol (non-negotiable):**
1. Say it directly: "I don't know [X], and here's why no one reliably can."
2. State what IS known: "What I DO know is [framework/data/signal]."
3. Provide a decision framework despite uncertainty.

**Daily Briefing Format:**
1. The Headline — single most important thing today (2-3 sentences)
2. Goal Pacing — are we on track for $417K?
3. What the Model Is Seeing — top signals in plain English
4. Portfolio Today — anything needing attention?
5. What I'm Watching — 1-2 things to monitor this week
6. Recommendation — **ONLY when genuinely important and actionable.** Warren B does NOT force a recommendation every day. Sitting on hands is a valid call.

**Red Lines:**
- Never ignores a model stop-loss
- Never gives price targets with false precision
- Never pretends to know Fed/geopolitics/macro
- Never makes the investor feel stupid
- Never stops asking: "Does this serve the 20% CAGR goal?"

---

## 7. API Endpoints

All endpoints added to existing FastAPI service on port 8000.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/warren-b/briefing` | POST | Generate daily briefing (called by n8n after model run) |
| `/warren-b/chat` | POST | Conversational endpoint — message + session_id in, response out |
| `/warren-b/slack-command` | POST | Slack slash command handler (`/warren [question]`) |
| `/warren-b/monthly` | POST | Monthly $2K deployment recommendation |
| `/warren-b/sessions` | GET | List recent conversation sessions |
| `/warren-b/decisions` | GET | Decision log with outcomes |
| `/warren-b/ui` | GET | Serves the web chat HTML |

---

## 8. Web Chat UI

**Simple, functional, mobile-friendly.** Not a product — a personal tool.

```
┌─────────────────────────────────────────────────┐
│  Warren B  ●  VIX: 15.4  ●  On track: ✓        │
├─────────────────────────────────────────────────┤
│                                                  │
│  Warren B — 8:05am                              │
│  ┌─────────────────────────────────────────┐    │
│  │ THE HEADLINE: Market is calm...         │    │
│  │ ...                                     │    │
│  └─────────────────────────────────────────┘    │
│                                                  │
│  You — 9:30am                                   │
│  ┌─────────────────────────────────────────┐    │
│  │ What do you think about adding AMD?     │    │
│  └─────────────────────────────────────────┘    │
│                                                  │
│  Warren B — 9:31am                              │
│  ┌─────────────────────────────────────────┐    │
│  │ AMD is our highest conviction signal    │    │
│  │ today at 0.78, but it's in a high       │    │
│  │ vol regime. Here's how I'd think        │    │
│  │ about sizing...                         │    │
│  └─────────────────────────────────────────┘    │
│                                                  │
├─────────────────────────────────────────────────┤
│  [Ask Warren anything...              ] [Send]  │
└─────────────────────────────────────────────────┘
```

**Tech:** Single HTML file served by FastAPI. JavaScript only (no framework). Server-Sent Events for streaming Warren B's responses in real time (feels more human, no waiting for full response). Dark theme. Mobile-responsive.

---

## 9. Automation (n8n)

### Workflow 1: Daily Warren B Briefing
**Trigger:** Cron — weekdays at 8:05am ET (5 min after model run)
**Steps:**
1. Wait for model run to complete (poll `/health`)
2. Call `POST /warren-b/briefing`
3. Post Warren B's response to Slack `#warren-b` channel
4. Log to decision DB if Warren B made a recommendation

### Workflow 2: Monthly Deployment Strategy
**Trigger:** Cron — 1st of each month, 8:15am ET
**Steps:**
1. Call `POST /warren-b/monthly`
2. Post to Slack with `[MONTHLY STRATEGY]` tag
3. Log recommendation to decision DB

### Workflow 3: Slack Slash Command
**Trigger:** Slack slash command webhook `/warren`
**Steps:**
1. Receive question from Slack
2. Call `POST /warren-b/slack-command` with message + user context
3. Return Warren B's response to Slack thread
4. Log conversation to DB

---

## 10. File Structure

```
C:\Claude\Trading Analyst\
├── ai/
│   └── warren_b.py              # Persona, context builder, Claude API calls
├── api/
│   ├── warren_b_routes.py       # FastAPI endpoints
│   └── main.py                  # Include warren_b router (modify)
├── data/
│   └── warren_b_memory.py       # Decision log, conversation history, smart retrieval
├── static/
│   └── warren_b_chat.html       # Web chat UI (served at /warren-b/ui)
└── deploy/
    └── n8n_warren_b_workflows.json  # n8n workflow definitions
```

New SQLite tables added to `paper_portfolio.db`:
- `warren_b_decisions` — every recommendation + outcome
- `warren_b_conversations` — full conversation history

---

## 11. Phase 2 Stub — Alexandra T (Tax Advisor)

The architecture is designed so Alexandra T can be added without refactoring:
- Warren B's context injection is modular — Alexandra reads the same portfolio data
- Decision log is shared — Alexandra can see what Warren recommended and add tax impact
- Web chat UI supports multiple advisor personas (tab switcher: Warren | Alexandra)
- Alexandra's system prompt will be written with same research depth as Warren's

Alexandra's role: capital gains optimization, tax-loss harvesting, Roth IRA vs. taxable account strategy, RSU vesting tax impact, India-move tax implications.

**Trigger for Phase 2:** When investor moves to Phase 2 live capital OR when tax complexity (RSU vesting, account transfers) warrants it.

---

## 12. Cost Summary

| Service | Monthly | Notes |
|---------|---------|-------|
| Claude API — Warren B (Sonnet) | ~$18 | Daily briefing + ~5 chat exchanges/day |
| Existing system | ~$94 | DigitalOcean + Polygon + Quiver + Claude market intel |
| **Total with Warren B** | **~$112/month** | |

Over 54 months to Dec 2030: $6,048 total system cost vs. ~$209K projected gains = **34× ROI on the technology.**

---

## 13. Success Criteria

Warren B is working correctly when:
- [ ] Daily briefing arrives in Slack by 8:10am ET on weekdays
- [ ] Warren B never asks for portfolio data he should already have
- [ ] Warren B's "I don't know" protocol fires correctly on uncertain questions
- [ ] Recommendations are NOT forced every day — silence is valid
- [ ] Monthly $2K deployment recommendation arrives on the 1st
- [ ] Conversation history persists across sessions (web chat + Slack share memory)
- [ ] Smart retrieval pulls ticker-specific history when that ticker is mentioned
- [ ] Decision log captures every recommendation with rationale
- [ ] Web chat UI streams responses in real time
- [ ] Goal pacing ($417K target) appears in every daily briefing

---

*Designed 2026-06-04. Validated with live demo run using real market signals (AMD 0.78, GOOGL 0.74, NVDA 0.73, AAPL 0.66). Phase 2 (Alexandra T) deferred pending Phase 1 stability and live capital transition.*
