# Data Resilience Audit Report
## Trading Analyst 7-Layer Signal Pipeline
**Date:** 2026-06-05  
**Scope:** Complete data dependency analysis & production-grade mitigation strategy  
**Status:** Ready for Phase 2 deployment with critical fixes

---

## Executive Summary

I've mapped the complete data dependency graph across the 7-layer signal pipeline (Technical, Momentum, Quality, Congress, Estimate Revisions, News, Earnings). **The system has significant staleness and failure mode vulnerabilities that would cause catastrophic signal degradation in production.**

### Critical Findings

| Risk Level | Issue | Impact | Effort to Fix |
|-----------|-------|--------|---------------|
| **CRITICAL** | Polygon API (market data) → single point of failure | Signal generation halts entirely | 2 hours |
| **CRITICAL** | Congress trades (Quiver API) → 6-hour cache with no verification | Stale signal for 6 hours if API fails | 4 hours |
| **HIGH** | News APIs (Newsdata + NewsAPI) → sequential fallback, but both fail silently | News score defaults to 0.5 (neutral) | 3 hours |
| **HIGH** | yfinance (fundamental data) → used in 4 scorers, no timeout enforcement | Can hang indefinitely on network issues | 6 hours |
| **HIGH** | Earnings calendar (yfinance) → 24h cache with stale earnings date risk | Pre-earnings uncertainty modifier applied to outdated data | 4 hours |
| **MEDIUM** | VIX/regime detection → missing graceful degradation on market_intel failure | Uses stale or zero regime weights | 2 hours |
| **MEDIUM** | Cache layer without staleness monitoring | No alerts when >4h old data is served | 1 hour |

### Recommended Immediate Actions (This Week)

1. **Circuit breaker for Polygon API** (2 hrs) — If offline >2 min, switch to yfinance fallback
2. **Dual-source Congress trades** (4 hrs) — Add SEC EDGAR fallback for insider trading
3. **Timeout enforcement on all APIs** (3 hrs) — Hard 15-second timeout with exponential backoff
4. **Staleness monitoring layer** (1 hr) — Track data age, alert >4 hours old
5. **Cache TTL verification** (1 hr) — Ensure real-time update frequency matches tolerance

### Production Readiness Gap

**Current:** Paper trading only; data quality acceptable for backtesting  
**Required for $100K+ live trading:** Dual-source redundancy, <1-hour staleness guarantee, circuit breaker on all APIs  
**Timeline:** Phase 2 can begin once CRITICAL items fixed (this week)

---

## Data Source Inventory & Staleness Analysis

### Layer 1: Technical Score (Indicators)

**Primary Data Source: Polygon API**
```
Source:        polygon.io RESTClient (quant/indicators.py ← data/market.py)
Dependencies:  POLYGON_API_KEY (required), ticker validation
Data Fetched:  Daily OHLCV bars (open, high, low, close, volume)
Lookback:      30 days (default), 250 days for SPY comparison
Cache:         1 hour (3600s) — set_cache(f"bars:{ticker}:30", TTL=3600)
Freshness:     As of market close (T+0 for US equities)
```

**Staleness Analysis**
- **Acceptable lag:** 0-4 hours (daily candles update at 4:30 PM ET)
- **Current risk:** If Polygon down, no fallback → signal generation fails
- **Failure mode:** Raises `ValueError("No bars returned for {ticker}")` → HTTP 400
- **User impact:** Cannot analyze any ticker until API restored

**Mitigation Status:** ❌ NONE
- No secondary source configured
- No timeout enforcement (uses requests.get with default timeout)
- Cache miss → immediate API call (no graceful degrada

tion)

---

### Layer 2: Momentum Score

**Primary Data Source: yfinance**
```
Source:        yfinance.download() (quant/momentum.py)
Data Fetched:  Daily adjusted close prices, 1+ years history
Cache:         None (computed fresh each request)
Freshness:     T+0 to T+1 (depends on yfinance sync with Yahoo Finance)
Lookback:      12 months, 6 months, 3 months (skip-adjusted for reversal avoidance)
```

**Staleness Analysis**
- **Acceptable lag:** 0-4 hours (daily bars)
- **Current risk:** yfinance is notoriously fragile; hangs/timeouts common
- **Failure mode:** Requests can hang indefinitely (default timeout = 30s, not enforced in code)
- **Silent failure:** Returns 0.5 (neutral) if exception occurs
- **User impact:** Momentum signal always neutral when yfinance fails → losing 30% of signal weight

**Mitigation Status:** ❌ MINIMAL
- Exception handling returns 0.5 (neutral) — better than crashing
- No timeout enforcement
- No secondary source (Polygon has 12+ months history available)

---

### Layer 3: Quality Score (Fundamentals)

**Primary Data Source: yfinance.Ticker(ticker).info**
```
Source:        yfinance.Ticker.info property
Data Fetched:  ROE, free cash flow, gross margin, debt-to-equity
Cache:         7 days (604800s) — fundamentals change quarterly
Freshness:     T+0 to T+3 (depends on company earnings release & Yahoo sync)
Update freq:   Quarterly (changed only after earnings)
```

**Staleness Analysis**
- **Acceptable lag:** 0-7 days (quarterly fundamentals)
- **Current risk:** Missing factors renormalized automatically (good), but weights can game to 0.5
- **Failure mode:** Exception returns 0.5 (neutral)
- **Data decay:** After 7 days, cached data may be stale if earnings announced
- **User impact:** Quality score becomes unreliable if earnings surprise occurs during cache window

**Mitigation Status:** ⚠️ PARTIAL
- Good: Automatic weight renormalization for missing factors
- Bad: No verification that cached data is still valid (no "data published date" check)
- Bad: yfinance can stall indefinitely fetching info

---

### Layer 4: Congress Trading Score

**Primary Data Source: Quiver Quantum API**
```
Source:        api.quiverquant.com/beta/historical/congresstrading/{ticker}
Auth:          QUIVER_API_KEY (required)
Data Fetched:  Congressional insider trades (member, transaction type, amount, date)
Cache:         6 hours (21600s) — quiver_trades_cache
Freshness:     T+2 to T+14 (trades reported with 5-day filing delay, Quiver updates daily)
Update freq:   Daily
Lookback:      180 days (last 6 months of trades analyzed)
```

**Staleness Analysis**
- **Acceptable lag:** 0-6 hours recommended (insider intelligence is perishable)
- **Current risk:** 6-hour cache means stale trades for half a day if API fails
- **Failure mode:** Returns empty list [] → score defaults to 0.5 (neutral)
- **Silent failure:** Exception logged but not propagated; signal generation continues
- **User impact:** Congress signal becomes neutral when Quiver fails; losing 8% of signal weight

**Mitigation Status:** ⚠️ PARTIAL
- Graceful degradation (returns 0.5, doesn't crash)
- No fallback source (SEC EDGAR data available as alternative)
- 6-hour cache is aggressive — could serve stale trades for entire trading day

**Critical Issue:** If Quiver API fails at 9:00 AM, cached data from yesterday will be served until 3:00 PM. If new trades landed that morning, signal misses them entirely.

---

### Layer 5: Estimate Revisions Score

**Primary Data Source: yfinance (upgrades_downgrades DataFrame)**
```
Source:        yfinance.Ticker.upgrades_downgrades
Data Fetched:  Recent analyst grade changes (to_grade, from_grade, timestamp)
Cache:         24 hours (86400s)
Freshness:     T+0 to T+1 (analyst actions within 1-2 hours of announcement)
Update freq:   Real-time (as analyst firms publish)
Fallback:      recommendationMean from yfinance.Ticker.info (pre-computed consensus)
Lookback:      Last 30 days of grade changes
```

**Staleness Analysis**
- **Acceptable lag:** 0-2 hours (analyst sentiment is real-time signal)
- **Current risk:** 24-hour cache can serve outdated grades
- **Failure mode:** Falls back to consensus recommendation mean (slower, laggier signal)
- **User impact:** Real-time analyst upgrades/downgrades missed for 24 hours; loses 7% of signal

**Mitigation Status:** ⚠️ PARTIAL
- Good: Fallback to recommendation mean prevents hard failure
- Bad: Primary source (upgrades_downgrades) is often empty/unreliable in yfinance
- Bad: No verification of data timestamp in fallback

---

### Layer 6: News Sentiment Score

**Primary Data Sources: Newsdata.io + NewsAPI (redundant)**
```
Source:        newsdata.io/api/1/news (primary) + newsapi.org/v2/everything (fallback)
Auth:          NEWSDATA_API_KEY, NEWS_API_KEY (both optional)
Data Fetched:  Articles (title, description, published_at) matching ticker query
Cache:         1 hour (3600s)
Freshness:     T+0 to T+2 hours (articles published within 2h of event)
Update freq:   Real-time (news articles as published)
Lookback:      Last 3 days of articles
```

**Staleness Analysis**
- **Acceptable lag:** 0-2 hours (market-moving news)
- **Current risk:** Sequential fallback (try Newsdata, then NewsAPI) but both can fail silently
- **Failure mode:** Empty list [] → news_score defaults to 0.5 (neutral)
- **User impact:** No news sentiment available for 1-hour cache period; losing 10% of signal

**Resilience Architecture:** ✅ GOOD
- Dual source (Newsdata + NewsAPI)
- Proper fallback chain in `_fetch_news()`
- Cache at 1 hour appropriately aggressive

**Mitigation Gap:** No circuit breaker if both APIs fail (e.g., rate limit exceeded). No logging of which source succeeded.

---

### Layer 7: Earnings Score

**Primary Data Source: yfinance (calendar + earnings_history)**
```
Source:        yfinance.Ticker.calendar + yfinance.Ticker.earnings_history
Data Fetched:  Next earnings date, EPS beat history, EPS surprises, earnings growth
Cache:         24 hours (86400s)
Freshness:     T+0 to T+1 (calendar updates at market close; earnings released after-hours)
Update freq:   Real-time (new earnings announcements as released)
Lookback:      Last 8 quarters of earnings history
```

**Staleness Analysis**
- **Acceptable lag:** 0-6 hours for earnings date (pre-earnings trades must use fresh data)
- **Current risk:** 24-hour cache can serve stale earnings dates
  - Example: If earnings announced after 4:00 PM, cached date not updated for 24 hours
  - Pre-earnings uncertainty modifier (±5-7%) applied to outdated earnings date
- **Failure mode:** Returns 0.5 (neutral) if calendar or history unavailable
- **User impact:** Earnings signal degraded for 24 hours if new data not cached

**Critical Issue:** `days_to_earnings()` called during scoring — if next_earnings_date is 24+ hours stale:
- Pre-earnings trades (days 1-7) receive -5% to -7% discount
- But discount applied to YESTERDAY'S earnings date
- Can cause false negatives on imminent earnings or false positives on already-passed earnings

**Mitigation Status:** ⚠️ PARTIAL
- Good: Earnings history is backward-looking (doesn't change)
- Bad: Earnings calendar is forward-looking (changes frequently)
- Bad: 24-hour cache too aggressive for earnings date

---

### Cross-Layer Dependency: Market Regime (VIX)

**Primary Data Source: yfinance (^VIX)**
```
Source:        yfinance.download("^VIX")
Data Fetched:  VIX closing price (5-day history for trend)
Cache:         1 hour (3600s)
Freshness:     T+0 to T+2 hours (VIX updates during market hours, final close at 4:15 PM ET)
Impact:        Drives regime-adaptive signal weights (REGIME_WEIGHTS in config.py)
```

**Staleness Analysis**
- **Acceptable lag:** 0-1 hour (VIX is real-time, used for intraday regime)
- **Current risk:** If yfinance fails, returns _FALLBACK = {"regime": "normal", "vix": 20.0}
- **Failure mode:** Falls back to neutral regime with default weights
- **User impact:** Signal weights not adapted to current volatility; can cause regime-inappropriate trades

**Example Failure Scenario:**
- VIX spiked to 35 (crisis regime) at 2:00 PM
- yfinance times out
- System uses cached VIX=20 (normal regime) for 1 hour
- Momentum weight stays at 30% instead of dropping to 10%
- Buy signals generated in crisis when capital preservation should dominate

---

## Staleness Thresholds & Recommendations

### Recommended Maximum Data Age by Signal

| Signal Layer | Data Source | Current TTL | Current Risk | Recommended Max Age | Alert Threshold | Action if Exceeded |
|-------------|-------------|-----------|-------------|-------------------|-----------------|-------------------|
| Technical | Polygon (bars) | 1 hour | Moderate | 4 hours | 3 hours | Circuit breaker to yfinance |
| Momentum | yfinance | None | High | 2 hours | 1 hour | Fallback to Polygon 12M history |
| Quality | yfinance (info) | 7 days | Medium | 3 days (post-earnings) | 2 days | Re-check on earnings date + 2h |
| Congress | Quiver API | 6 hours | High | 2 hours | 1 hour | Fallback to SEC EDGAR + cache |
| Estimate Revisions | yfinance | 24 hours | High | 4 hours | 2 hours | Use recommendation mean, check hourly |
| News Sentiment | Newsdata + NewsAPI | 1 hour | Low | 2 hours | 1 hour | Continue using cached value |
| Earnings | yfinance | 24 hours | High | 6 hours | 3 hours | Flag "earnings data stale" warning |
| Market Regime (VIX) | yfinance | 1 hour | Medium | 30 minutes | 15 minutes | Alert, use previous regime |

---

## Circuit Breaker Rules: When to Stop Trading

### Level 1: Individual Data Source Failure
**If any single API timeout/fails >2x in 5 minutes:**
- Trigger fallback source
- Log alert to monitoring system
- Continue trading with degraded signal

**Example:**
```
Time 09:00:00 — Polygon API timeout (1st failure)
Time 09:01:00 — Polygon API timeout (2nd failure)
Action: Switch to yfinance fallback for bars
Alert: WARN "Polygon API failing, using yfinance fallback"
Continue: Yes
```

### Level 2: Fallback Source Also Fails
**If both primary + fallback fail or data >2x max age threshold:**
- Degrade signal component to 0.5 (neutral)
- Do NOT trade on this signal
- Alert operator; require manual override to continue

**Example:**
```
Time 09:05:00 — yfinance fallback also times out
Time 09:06:00 — News score can't be computed (all APIs failing)
Action: Set news_score = 0.5, don't weight it
Signal: Composite score computed without news (renormalize weights)
Alert: CRIT "News sentiment unavailable; composite signal has reduced signal/noise"
Continue: Yes, but with warning
```

### Level 3: Multiple Data Sources Fail Simultaneously
**If ≥3 distinct data sources fail within 5 minutes:**
- **STOP trading entirely**
- Hard pause on all new trades
- Alert requires manual operator review to resume

**Example (Market Disruption Scenario):**
```
Time 14:00:00 (2:00 PM ET) — NYSE connectivity issue
- Polygon bars: TIMEOUT
- yfinance bars: TIMEOUT
- News APIs: TIMEOUT
- VIX: TIMEOUT
- Congress: TIMEOUT
(5 failures in 2 minutes)
Action: STOP trading
Alert: CRIT "Multiple data sources failing; halt signal generation (5+ timeouts)"
Resume: Manual operator approval required
```

### Level 4: Data Quality Check
**Before executing ANY trade, verify:**

```python
# Pseudocode for pre-trade validation
def validate_trade_signal(signal_result, data_sources_status):
    # Rule 1: No component older than max_age[component]
    for component in ['technical', 'momentum', 'quality', 'news', 'earnings', 'congress']:
        age = now() - data_sources_status[component].last_updated
        if age > MAX_AGE[component]:
            raise TradeBlockedError(f"{component} data {age} > {MAX_AGE[component]}")
    
    # Rule 2: At least 5 of 7 components have fresh data
    fresh_count = sum(1 for c in components if data_age[c] < MAX_AGE[c] * 0.5)
    if fresh_count < 5:
        raise TradeBlockedError(f"Only {fresh_count}/7 components fresh")
    
    # Rule 3: Composite score must come from ≥4 non-neutral sources
    non_neutral = sum(1 for c in components if component_score[c] != 0.5)
    if non_neutral < 4:
        raise TradeBlockedError(f"Only {non_neutral}/7 components have signal")
    
    # Rule 4: No single data source failure causing >2 retries
    if max(retry_counts) > 2:
        raise TradeBlockedError(f"Data source {argmax(retry_counts)} failing; retry count = {max(retry_counts)}")
    
    return True  # Safe to trade
```

---

## Production Resilience Stack: Architecture

### Design Philosophy
**Primary:** Optimism with timeouts  
**Secondary:** Dual sources with graceful fallback  
**Tertiary:** Graceful degradation to neutral (0.5) signals  
**Quaternary:** Hard stop on data quality below threshold

### Proposed Data Layer Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Trade Signal (7-Layer)                       │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
        ┌──────────────────────────┐    ┌──────────────────────────┐
        │   Data Resilience Layer  │    │  Circuit Breaker & Monitoring
        │   (Timeout + Fallback)   │    │  (Staleness + Retry Tracking)
        └──────────────────────────┘    └──────────────────────────┘
                    │                               │
        ┌───────────┼───────────────────────┬──────┴──────────┐
        │           │                       │                 │
        ▼           ▼                       ▼                 ▼
    ┌───────┐  ┌─────────┐  ┌──────────┐  ┌────────┐  ┌──────────┐
    │Polygon│  │yfinance │  │NewsAPI   │  │Quiver  │  │yfinance  │
    │  API  │  │         │  │+Newsdata │  │Quantum │  │  Info    │
    │(bars) │  │ (prices)│  │          │  │(trades)│  │ (funds)  │
    └───┬───┘  └────┬────┘  └──────────┘  └───┬────┘  └──────────┘
        │           │                          │
        │ (Fallback if timeout >15s)           │
        │           │                          │
        └───────────┼──────────────────────────┘
                    │
            ┌───────▼────────┐
            │ Cache Layer    │
            │ (SQLite, TTLs) │
            └────────────────┘
```

### Key Components

#### 1. Timeout Enforcement Layer
**Purpose:** Prevent hanging on network calls  
**Implementation:**
- All external API calls must have explicit 15-second timeout
- Timeout → trigger fallback or neutral default
- Log timeout events for monitoring

**Current Status:** ❌ MISSING
- `get_daily_bars()` uses `requests.get(..., timeout=10)` ✅
- `_newsdata_fetch()` uses `timeout=15` ✅
- `get_congress_trades()` uses `timeout=10` ✅
- **Missing:** yfinance calls have NO timeout enforcement
  - `yf.download()` → default to system timeout (can be minutes)
  - `yf.Ticker(ticker).info` → no timeout
  - `yf.Ticker(ticker).earnings_history` → no timeout
  - `yf.Ticker(ticker).calendar` → no timeout

#### 2. Fallback Source Layer
**Purpose:** Maintain signal when primary fails  
**Current Fallbacks:**

| Component | Primary | Fallback | Status |
|-----------|---------|----------|--------|
| Market bars | Polygon | yfinance | ❌ Not wired |
| Earnings calendar | yfinance | Manual override / skip | ⚠️ Partial |
| News sentiment | Newsdata.io | NewsAPI | ✅ Wired |
| Estimate revisions | upgrades_downgrades | recommendationMean | ✅ Wired |
| Quality fundamentals | yfinance info | Fallback to neutral | ⚠️ Minimal |
| Congress trades | Quiver | None → neutral | ❌ Not wired |
| VIX/Regime | yfinance | Hardcoded fallback | ⚠️ Poor |

#### 3. Data Staleness Monitoring
**Purpose:** Alert when cached data is too old  
**Current Status:** ❌ MISSING
- Cache layer has TTL enforcement (good)
- No tracking of "data publish time" vs "cache time"
- No alerting on stale data

**Required:**
```python
# New fields in cache layer
class CacheEntry:
    key: str
    value: dict
    cached_at: timestamp
    expires_at: timestamp
    data_published_at: timestamp  # NEW: when the data itself was published
    is_stale: bool  # True if data > max_age threshold

# Before serving cached value:
def get_cache_with_staleness_check(key: str, max_age_seconds: int):
    entry = get_cache(key)
    if entry and entry.data_published_at:
        age = now() - entry.data_published_at
        if age > max_age_seconds:
            logger.warning(f"Cache {key} is {age}s old (max {max_age_seconds}s)")
            return None  # Force refresh
    return entry
```

#### 4. Retry Logic with Exponential Backoff
**Purpose:** Recover from transient failures  
**Current Status:** ❌ MISSING
- No retry logic in any data source
- Failed API call → exception logged, returns neutral (0.5)
- No backoff between retries

**Required:**
```python
def fetch_with_retry(api_fn, max_retries=3, initial_backoff=1):
    """Retry with exponential backoff: 1s, 2s, 4s"""
    for attempt in range(max_retries):
        try:
            return api_fn()
        except TimeoutError as e:
            if attempt < max_retries - 1:
                sleep_time = initial_backoff * (2 ** attempt)
                logger.info(f"Retry {attempt+1}/{max_retries} after {sleep_time}s")
                time.sleep(sleep_time)
            else:
                logger.error(f"Failed after {max_retries} attempts: {e}")
                raise
```

#### 5. Data Quality Scoring
**Purpose:** Track signal reliability based on data freshness  
**Current Status:** ❌ MISSING
- No scoring of "data quality" or "signal confidence"
- User gets 0.60 technical score without knowing if it's from stale data

**Required:**
```python
# Return with confidence metadata
return {
    "signal": {
        "composite_score": 0.62,
        "label": "BUY",
    },
    "data_quality": {
        "freshness_score": 0.95,  # 1.0 = all components fresh, 0.5 = mixed, 0.0 = all stale
        "components_fresh": 6,     # out of 7
        "components_stale": 1,
        "stale_components": ["earnings"],
        "warning": "Earnings data 18 hours old; fundamental weakness signal may be delayed"
    }
}
```

---

## Implementation Roadmap

### Phase 1: Critical Fixes (This Week — 16 hours)

**Priority 1: yfinance Timeout Enforcement** (3 hours)
- Wrap yfinance calls with timeout wrapper
- Max 15 seconds per call; timeout → fallback to neutral or secondary source
- Affected modules:
  - `quant/momentum.py` — add timeout to yfinance.download()
  - `quant/quality.py` — add timeout to yfinance.Ticker(ticker).info
  - `data/earnings.py` — add timeout to yfinance.Ticker(ticker).calendar
  - `smart_money/estimate_revisions.py` — add timeout to yfinance.Ticker(ticker).upgrades_downgrades

**Priority 2: Polygon → yfinance Fallback** (2 hours)
- If Polygon times out (>2 retries), fall back to yfinance bars
- Update `data/market.py.get_daily_bars()` with dual-source logic
- Test fallback path

**Priority 3: Circuit Breaker for Congress Trades** (3 hours)
- Add SEC EDGAR API fallback (free, reliable)
- If Quiver fails, fetch from EDGAR instead
- Update `smart_money/congress.py.get_congress_trades()`

**Priority 4: Earnings Cache Refresh** (2 hours)
- Reduce earnings calendar TTL from 24h to 6h
- Add check: if next_earnings_date is stale, don't use earnings modifier
- Update `data/earnings.py`

**Priority 5: Staleness Monitoring Foundation** (4 hours)
- Add `data_published_at` field to cache layer
- Create `CacheStalenessChecker` class
- Add logging: "Cache {key} is {age}s old"
- Integrate into `data/cache.py`
- Test in one scorer (news_scorer.py as pilot)

**Priority 6: Data Quality Metadata** (2 hours)
- Add `data_quality` dict to analyze response
- Score freshness 0-1 based on # components fresh
- Return with every signal

### Phase 2: Resilience Infrastructure (Next Week — 20 hours)

**Priority 7: Exponential Backoff Wrapper** (3 hours)
- Create `util/retry.py` with `fetch_with_retry()` and `fetch_with_timeout()`
- Implement exponential backoff: 1s, 2s, 4s, then fail
- Use for all external API calls

**Priority 8: Dual-Source Architecture for News** (2 hours)
- Add source tracking: log which API (Newsdata vs NewsAPI) succeeded
- Monitor success rate per source
- Auto-switch primary if >50% failure rate

**Priority 9: VIX Regime Improvements** (2 hours)
- If yfinance fails, use 5-minute-old cached regime (not 1h old)
- Track regime changes separately from price data
- Alert on regime shift failures

**Priority 10: Health Check Endpoint** (3 hours)
- Add `/health/data` endpoint that checks all data sources
- Returns: which sources are responsive, data age, circuit breaker status
- Example response:
```json
{
  "polygon_api": {"status": "healthy", "data_age_seconds": 120},
  "yfinance": {"status": "healthy", "data_age_seconds": 180},
  "newsapi": {"status": "healthy", "data_age_seconds": 60},
  "newsdata": {"status": "timeout", "last_success": 600, "consecutive_failures": 2},
  "quiver": {"status": "healthy", "data_age_seconds": 300},
  "circuit_breaker": {"status": "nominal", "triggered_sources": []},
  "overall": "NOMINAL"
}
```

**Priority 11: Automated Staleness Alerts** (4 hours)
- Create monitoring rules:
  - Alert if any component >1.5x max_age
  - Alert if 3+ sources fail simultaneously
  - Alert if circuit breaker triggered
- Send to Slack webhook (already configured)
- Example: `🚨 ALERT: Congress trades {age}s old (>7200s); Quiver API failing`

**Priority 12: Multi-Source Congress Trades** (2 hours)
- Implement Quiver + SEC EDGAR dual fetch
- Weighted scoring: Quiver data (more granular) 70%, EDGAR data (slower) 30%
- Quiver fallback if EDGAR fails

### Phase 3: Production Hardening (Post-Deployment)

**Priority 13: Circuit Breaker State Machine** (4 hours)
- Implement formal circuit breaker pattern: CLOSED → OPEN → HALF_OPEN → CLOSED
- Per-API configuration of failure thresholds
- Automatic recovery with exponential backoff

**Priority 14: Cache Invalidation on News Events** (3 hours)
- If major news lands, invalidate related caches
- Monitor for keywords: earnings, guidance, acquisition, bankruptcy
- Force refresh of related tickers

**Priority 15: Forecast Data Age Tracking** (2 hours)
- For each component score, return `computed_at_timestamp`
- In briefing/reports, show: "Technical score (2 min old) | News (5 min old) | Earnings (18 hours old ⚠️)"
- User aware of data freshness trade-offs

**Priority 16: Production Staging Validation** (ongoing)
- Run 2-week staging deployment with synthetic latency injection
- Simulate API timeouts, failures, rate limits
- Verify circuit breaker triggers appropriately
- Measure signal stability under degradation

---

## Code Patterns for Robust Data Fetching

### Pattern 1: Timeout + Fallback Wrapper
```python
import time
import functools
import logging
from typing import Callable, TypeVar, Any

logger = logging.getLogger(__name__)

T = TypeVar('T')

def fetch_with_timeout_and_fallback(
    primary_fn: Callable[..., T],
    fallback_fn: Callable[..., T] | None = None,
    timeout_seconds: int = 15,
    fallback_value: Any = None,
    component_name: str = "data_source",
) -> T:
    """
    Fetch data with timeout; fall back if timeout or exception.
    
    Args:
        primary_fn: Main data fetch function
        fallback_fn: Secondary data source (optional)
        timeout_seconds: Hard limit on primary fetch
        fallback_value: Default return value if all fail
        component_name: Name for logging
    
    Returns:
        Fetched data, or fallback, or default value
    
    Example:
        bars = fetch_with_timeout_and_fallback(
            primary_fn=lambda: polygon_client.get_bars(ticker),
            fallback_fn=lambda: yfinance.download(ticker),
            timeout_seconds=15,
            fallback_value=[],
            component_name="market_bars"
        )
    """
    import signal
    
    def timeout_handler(signum, frame):
        raise TimeoutError(f"{component_name} exceeded {timeout_seconds}s timeout")
    
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout_seconds)
    
    try:
        result = primary_fn()
        signal.alarm(0)  # Cancel timeout
        logger.info(f"{component_name}: primary source successful")
        return result
    
    except (TimeoutError, Exception) as e:
        signal.alarm(0)  # Cancel timeout
        logger.warning(f"{component_name}: primary failed ({type(e).__name__}: {e})")
        
        if fallback_fn is not None:
            try:
                signal.alarm(timeout_seconds)
                result = fallback_fn()
                signal.alarm(0)
                logger.info(f"{component_name}: fallback source successful")
                return result
            except Exception as e2:
                signal.alarm(0)
                logger.error(f"{component_name}: fallback also failed ({type(e2).__name__}: {e2})")
        
        if fallback_value is not None:
            logger.warning(f"{component_name}: returning default fallback value")
            return fallback_value
        
        raise
    
    finally:
        signal.signal(signal.SIGALRM, old_handler)
```

### Pattern 2: Exponential Backoff Retry
```python
import time
import logging
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar('T')

def fetch_with_retry(
    fn: Callable[..., T],
    max_retries: int = 3,
    initial_backoff_seconds: float = 1.0,
    component_name: str = "api_call",
) -> T:
    """
    Retry a function with exponential backoff.
    
    Backoff schedule: 1s, 2s, 4s, ...
    
    Example:
        trades = fetch_with_retry(
            fn=lambda: quiver_client.congress_trades(ticker),
            max_retries=3,
            initial_backoff_seconds=1.0,
            component_name="congress_trades"
        )
    """
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = initial_backoff_seconds * (2 ** attempt)
                logger.info(
                    f"{component_name}: attempt {attempt + 1} failed ({type(e).__name__}); "
                    f"retrying in {wait_time}s..."
                )
                time.sleep(wait_time)
            else:
                logger.error(
                    f"{component_name}: failed after {max_retries} attempts: {type(e).__name__}: {e}"
                )
                raise
```

### Pattern 3: Staleness Checking in Cache
```python
import time
import json
from pathlib import Path
from datetime import datetime, timezone

class StalenessAwareCacheEntry:
    """Cache entry with data age tracking."""
    
    def __init__(self, key: str, value: dict, ttl_seconds: int, data_published_at: float | None = None):
        self.key = key
        self.value = value
        self.cached_at = time.time()
        self.expires_at = self.cached_at + ttl_seconds if ttl_seconds > 0 else 0
        self.data_published_at = data_published_at or self.cached_at
    
    @property
    def age_seconds(self) -> float:
        """How old is the underlying data (not the cache)?"""
        return time.time() - self.data_published_at
    
    @property
    def is_expired(self) -> bool:
        """Has the cache TTL expired?"""
        return self.expires_at > 0 and self.expires_at < time.time()
    
    @property
    def is_stale(self, max_age_seconds: int) -> bool:
        """Is the data itself older than acceptable?"""
        return self.age_seconds > max_age_seconds
    
    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "cached_at": self.cached_at,
            "expires_at": self.expires_at,
            "data_published_at": self.data_published_at,
            "age_seconds": self.age_seconds,
        }

def get_cache_with_freshness(
    key: str,
    max_age_seconds: int | None = None,
) -> dict | None:
    """
    Get cached value, optionally checking staleness.
    
    Args:
        key: Cache key
        max_age_seconds: Max acceptable data age; None = skip check
    
    Returns:
        Value if fresh, None if expired or stale
    """
    entry = _fetch_cache_entry(key)
    if entry is None:
        return None
    
    if entry.is_expired:
        logger.debug(f"Cache {key}: TTL expired ({entry.age_seconds}s old)")
        return None
    
    if max_age_seconds and entry.is_stale(max_age_seconds):
        logger.warning(
            f"Cache {key}: data {entry.age_seconds}s old exceeds max {max_age_seconds}s; "
            "forcing refresh"
        )
        return None
    
    logger.debug(f"Cache {key}: serving {entry.age_seconds:.0f}s old data")
    return entry.value
```

### Pattern 4: Circuit Breaker State Machine
```python
import time
import logging
from enum import Enum

logger = logging.getLogger(__name__)

class CircuitBreakerState(Enum):
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Failing; reject calls
    HALF_OPEN = "half_open"  # Testing recovery

class CircuitBreaker:
    """
    Circuit breaker pattern for APIs.
    
    CLOSED → OPEN: after failure_threshold consecutive failures
    OPEN → HALF_OPEN: after timeout_seconds
    HALF_OPEN → CLOSED: if single call succeeds
    HALF_OPEN → OPEN: if single call fails
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout_seconds: int = 60,
        success_threshold: int = 2,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.success_threshold = success_threshold
        
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
    
    def call(self, fn, *args, **kwargs):
        """Execute fn through circuit breaker."""
        if self.state == CircuitBreakerState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitBreakerState.HALF_OPEN
                logger.info(f"{self.name}: circuit breaker entering HALF_OPEN (recovery attempt)")
            else:
                raise CircuitBreakerOpenError(
                    f"{self.name}: circuit breaker OPEN; failing fast"
                )
        
        try:
            result = fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
    
    def _on_success(self):
        self.failure_count = 0
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self.state = CircuitBreakerState.CLOSED
                self.success_count = 0
                logger.info(f"{self.name}: circuit breaker recovered → CLOSED")
    
    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        self.success_count = 0
        
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN
            logger.error(
                f"{self.name}: circuit breaker OPEN after {self.failure_count} failures"
            )
    
    def _should_attempt_reset(self) -> bool:
        return (
            self.last_failure_time is not None
            and time.time() - self.last_failure_time >= self.recovery_timeout_seconds
        )

class CircuitBreakerOpenError(Exception):
    pass
```

### Pattern 5: Data Quality Scoring
```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class DataQualityReport:
    """
    Track data freshness and reliability of computed signals.
    """
    freshness_score: float  # 0.0 (all stale) to 1.0 (all fresh)
    components_fresh: int   # count of components with fresh data
    components_stale: int   # count of components with stale data
    stale_components: list[str]  # names of stale components
    warnings: list[str]     # human-readable warnings
    
    def to_dict(self) -> dict:
        return {
            "freshness_score": round(self.freshness_score, 2),
            "components_fresh": self.components_fresh,
            "components_stale": self.components_stale,
            "stale_components": self.stale_components,
            "warnings": self.warnings,
        }

def compute_data_quality(
    component_ages: dict[str, float],
    max_ages: dict[str, float],
) -> DataQualityReport:
    """
    Compute data quality report based on component staleness.
    
    Args:
        component_ages: {"technical": 120, "momentum": 180, ...}  (seconds)
        max_ages: {"technical": 3600, "momentum": 7200, ...}      (seconds)
    
    Returns:
        DataQualityReport with freshness metrics
    
    Example:
        quality = compute_data_quality(
            component_ages={
                "technical": 120,
                "momentum": 180,
                "earnings": 86400,  # 24 hours old (stale!)
            },
            max_ages={
                "technical": 3600,
                "momentum": 7200,
                "earnings": 21600,
            }
        )
        # freshness_score = 2/3 = 0.67
        # components_fresh = 2, components_stale = 1
        # warnings = ["Earnings data 24 hours old (max 6 hours)"]
    """
    fresh = []
    stale = []
    warnings = []
    
    for component, age in component_ages.items():
        max_age = max_ages.get(component, float('inf'))
        if age <= max_age:
            fresh.append(component)
        else:
            stale.append(component)
            age_hours = age / 3600
            max_hours = max_age / 3600
            warnings.append(
                f"{component}: data {age_hours:.1f}h old (max {max_hours:.1f}h)"
            )
    
    freshness_score = len(fresh) / len(component_ages) if component_ages else 1.0
    
    return DataQualityReport(
        freshness_score=freshness_score,
        components_fresh=len(fresh),
        components_stale=len(stale),
        stale_components=stale,
        warnings=warnings,
    )
```

---

## Monitoring Checklist: Production Deployment

### Daily Health Checks

**At 8:00 AM ET (before market open):**
- [ ] `/health/data` endpoint: all sources responsive
- [ ] Data age: technical <1h, momentum <2h, news <2h, earnings <6h
- [ ] Polygon API latency <2 seconds (p95)
- [ ] Cache hit rate >70% for repeat tickers
- [ ] Zero circuit breaker triggers overnight

**Every hour (market hours):**
- [ ] VIX data <30 min old
- [ ] Congress trades data <2 hours old
- [ ] News sentiment <1 hour old
- [ ] No more than 1 API timeout per source
- [ ] Fallback sources not being triggered

**At 4:00 PM ET (post-market):**
- [ ] All caches refreshed for next day
- [ ] Earnings calendar updated (check for next week's announcements)
- [ ] Quarterly fundamentals cross-checked (post-earnings)

### Weekly Health Checks

- [ ] Analyze 30-day failure rate per API source
- [ ] Identify trending API issues (latency increase, timeouts, rate limits)
- [ ] Review circuit breaker trigger log; assess need for threshold tuning
- [ ] Validate fallback source accuracy (compare Polygon vs yfinance bars)
- [ ] Spot-check 10 random tickers: verify data consistency across sources

### Monthly Health Checks

- [ ] Comprehensive end-to-end test with synthetic API failures
- [ ] Measure signal stability under data degradation
- [ ] Review data staleness metrics; optimize TTLs if needed
- [ ] Validate circuit breaker state transitions
- [ ] Load test: 1000 concurrent /analyze requests; measure degradation
- [ ] Audit log for false-positive alerts (tuning thresholds)

### Alerting Rules (Slack Integration)

| Alert Level | Condition | Action |
|-----------|-----------|--------|
| CRIT (🚨) | 3+ data sources fail in 5 min | Halt trading; requires manual override |
| CRIT (🚨) | Any component data >2× max age | Log; flag signal as unreliable |
| WARN (⚠️) | Any API >2 consecutive timeouts | Activate fallback; monitor |
| WARN (⚠️) | Circuit breaker triggers | Log; operator review |
| INFO (ℹ️) | Data source switches to fallback | Log context; no immediate action |
| INFO (ℹ️) | Cache hit rate drops <60% | Monitor for trending issue |

### Metrics to Export (Prometheus/CloudWatch)

```
trading_analyst_data.api_latency{source=polygon,percentile=p95} = 1.2s
trading_analyst_data.api_timeout_count{source=yfinance} = 2 (per hour)
trading_analyst_data.cache_hit_rate = 0.78
trading_analyst_data.circuit_breaker_open_count{source=quiver} = 1
trading_analyst_data.component_staleness{component=earnings} = 3600s
trading_analyst_data.signal_quality_score = 0.91  (out of 1.0)
trading_analyst_data.fallback_activation_count = 3 (per day)
```

---

## Effort Estimation Summary

| Task | Complexity | Effort | Risk |
|------|-----------|--------|------|
| yfinance timeout enforcement | Low | 3h | Low |
| Polygon → yfinance fallback | Medium | 2h | Medium |
| Congress trades fallback (EDGAR) | Medium | 4h | Medium |
| Earnings cache reduction | Low | 2h | Low |
| Staleness monitoring foundation | Medium | 4h | Low |
| Data quality metadata | Low | 2h | Low |
| Exponential backoff wrapper | Low | 3h | Low |
| Dual-source news tracking | Low | 2h | Low |
| VIX regime improvements | Low | 2h | Low |
| Health check endpoint | Medium | 3h | Low |
| Automated staleness alerts | Medium | 4h | Low |
| Multi-source Congress API | Medium | 2h | Medium |
| **Total Phase 1 + 2** | **Medium** | **~33 hours** | **Low** |

**Recommended Allocation:**
- **Week 1:** 16 hours (Phase 1 critical fixes)
- **Week 2:** 17 hours (Phase 2 resilience infrastructure)
- **Week 3+:** Ongoing staging validation & production hardening

---

## Comparison: Current vs. Proposed State

### Current State: Fragile, Single-Point Failures
```
Technical Layer:
  └─ Polygon (primary) → Times out → Signal generation FAILS
  
Momentum Layer:
  └─ yfinance (primary, no timeout) → Hangs forever → Score = 0.5 (neutral)
  
News Layer:
  └─ Newsdata.io → rate limit → NewsAPI → also rate limit → Score = 0.5
  
Earnings Layer:
  └─ yfinance calendar (24h cache) → Stale date → Bad modifier applied
```

### Proposed State: Resilient, Dual-Source, Graceful Degradation
```
Technical Layer:
  └─ Polygon (primary, 15s timeout) ✓
     └─ yfinance fallback (15s timeout) ✓
     └─ Cache-based neutral (0.5) fallback ⚠️
  
Momentum Layer:
  └─ yfinance (primary, 15s timeout) ✓
     └─ Polygon 12M history fallback ✓
     └─ Neutral (0.5) fallback ⚠️
  
News Layer:
  └─ Newsdata.io (primary, 15s timeout) ✓
     └─ NewsAPI fallback (15s timeout) ✓
     └─ Use cached (1h old) ⚠️
     └─ Neutral (0.5) fallback ⚠️
  
Earnings Layer:
  └─ yfinance calendar (6h cache, timeout 15s) ✓
     └─ Skip earnings modifier if stale ⚠️
     └─ Alert "earnings data stale" ⚠️
  
VIX/Regime Layer:
  └─ yfinance ^VIX (primary, 15s timeout) ✓
     └─ Use previous regime (5m old) ⚠️
     └─ Hardcoded "normal" fallback ⚠️

Circuit Breaker:
  └─ Monitors all sources; triggers STOP if 3+ fail in 5 min ✓
  
Data Quality:
  └─ Returns freshness_score with every signal ✓
  └─ Alerts on components >1.5× max age ✓
```

---

## Conclusion & Next Steps

**The Trading Analyst system is currently unsuitable for production trading at any scale.**

Critical vulnerabilities:
1. **Polygon API is a single point of failure** — no fallback wired
2. **yfinance calls lack timeout enforcement** — can hang indefinitely
3. **No staleness monitoring** — can serve data days/weeks old without alerting
4. **No circuit breaker** — multiple failures cause cascading signal degradation
5. **No data quality reporting** — users unaware of freshness trade-offs

**With Phase 1 fixes (16 hours this week), the system becomes suitable for:**
- Small paper trading (<$10K notional)
- Daily rebalancing (intraday staleness acceptable)
- Operator oversight (can monitor alerts & intervene)

**With Phase 2 infrastructure (17 hours next week), the system becomes suitable for:**
- Live trading up to $100K notional
- 4-hour rebalancing frequency
- Reduced operator supervision (automated fallbacks)

**Production deployment timeline:**
1. **Week 1:** Implement Phase 1 critical fixes
2. **Week 2:** Implement Phase 2 resilience infrastructure
3. **Week 3-4:** Staging validation with synthetic failures
4. **Week 5:** Go-live Phase 2 with $2.5K initial capital (per config.PHASE2_LIVE_CAPITAL)

**Immediate action:** Assign developer to yfinance timeout enforcement + Polygon fallback (start Monday).

