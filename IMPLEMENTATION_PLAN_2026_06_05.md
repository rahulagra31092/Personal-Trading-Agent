# IMPLEMENTATION PLAN — Model Upgrades to A-Grade
**Date:** June 5, 2026 | **Target Completion:** June 12, 2026 | **Effort:** 16 hours (Phase 1)

---

## CRITICAL FIXES (TODAY - THIS WEEK)

### Fix Priority List

#### FIX #1: Layer-5 Mis-Wiring (Estimate Revisions Slot)
**Severity:** CRITICAL | **Effort:** 1 hour | **Impact:** Quarterly learning loop integrity

**Current Problem:**
- Function `compute_estimate_revision_score()` returns real analyst revision data
- But feeds into DB column `score_estimate_revisions` 
- Config key is `"estimate_revisions"` (correct)
- **But** quarterly review loop references `"trump_policy"` label (wrong)
- Dead code: `smart_money/trump_scorer.py` 300 lines never called

**Files to change:**
1. `config.py:44` — Verify weight key is `"estimate_revisions"` (should already be correct)
2. `api/paper_portfolio.py:64` — Verify DB schema has `score_estimate_revisions` column
3. `api/quarterly_review.py:25-28` — Update factor list to use correct labels
4. `smart_money/trump_scorer.py` — Mark as deprecated or delete

**Testing:**
- New test: `tests/api/test_analyze_factor_slots.py`
  - Call `analyze_ticker("AAPL")`
  - Assert all 7 keys present: `technical, momentum, quality, congress, estimate_revisions, news_reaction, earnings`
  - Assert NO `trump_policy` key present
  - Call `send_daily_briefing()` → inspect DB `signal_outcomes` columns
  - Assert all 7 score columns populated, none NaN

**Status:** ⏳ TO DO

---

#### FIX #2: Add Data Freshness Tracking
**Severity:** CRITICAL | **Effort:** 2 hours | **Impact:** Detect stale data before it corrupts signals

**What to add:**
1. Track `data_fetched_at` timestamp for each API call (yfinance, Quiver, NewsAPI)
2. Add `staleness_warning` to response if data >X hours old
3. Log data age in decision database

**Implementation:**
- Create `util/data_health.py`:
  ```python
  class DataFreshness:
      def __init__(self, source: str):
          self.source = source
          self.last_fetch_time = None
          self.cache_ttl_seconds = {...}  # Per-source TTL
      
      def record_fetch(self, success: bool, fetch_time: datetime):
          self.last_fetch_time = fetch_time
      
      def staleness_seconds(self) -> int:
          if not self.last_fetch_time:
              return float('inf')
          return (now() - self.last_fetch_time).total_seconds()
      
      def is_stale(self) -> bool:
          return self.staleness_seconds() > self.cache_ttl_seconds[self.source]
  ```

- Modify `api/analyze.py`:
  ```python
  def analyze_ticker(ticker: str) -> dict:
      # ... existing code ...
      
      # Track data freshness
      data_health = {
          "yfinance_age_seconds": yfinance_fetch_age,
          "quiver_age_seconds": quiver_fetch_age,
          "earnings_cache_age_seconds": earnings_cache_age,
          "staleness_warnings": [],
      }
      
      # Alert if any source is stale
      if yfinance_fetch_age > 86400:  # >24 hours
          data_health["staleness_warnings"].append("yfinance data >24h old")
      if quiver_fetch_age > 21600:   # >6 hours
          data_health["staleness_warnings"].append("congress trades >6h old")
      
      return {
          ...existing...,
          "data_health": data_health,
      }
  ```

**Testing:**
- Simulate stale data (mock fetch timestamp 48h old)
- Assert `data_health.staleness_warnings` includes warning
- Assert response still contains `0.5` neutral score if stale data used

**Status:** ⏳ TO DO

---

#### FIX #3: yfinance Timeout Enforcement
**Severity:** CRITICAL | **Effort:** 3 hours | **Impact:** Prevent hanging requests

**Current Problem:**
- yfinance calls in 4 layers (indicators, momentum, quality, earnings)
- No timeout; can hang indefinitely
- User waits, API times out, no signal generated

**Implementation:**
- Wrap yfinance calls with timeout decorator:
  ```python
  import signal
  from functools import wraps
  
  def timeout_yfinance(seconds=15):
      def decorator(func):
          @wraps(func)
          def wrapper(*args, **kwargs):
              def timeout_handler(signum, frame):
                  raise TimeoutError(f"yfinance call exceeded {seconds}s")
              
              signal.signal(signal.SIGALRM, timeout_handler)
              signal.alarm(seconds)
              try:
                  result = func(*args, **kwargs)
                  signal.alarm(0)  # Disable alarm
                  return result
              except TimeoutError:
                  logger.error(f"yfinance timeout on {func.__name__}")
                  return None
          return wrapper
      return decorator
  ```

- Apply to all yfinance calls:
  - `quant/indicators.py`: `@timeout_yfinance(15)` on bar fetch
  - `quant/momentum.py`: `@timeout_yfinance(15)` on fetch
  - `quant/quality.py`: `@timeout_yfinance(15)` on info fetch
  - `smart_money/earnings_scorer.py`: `@timeout_yfinance(15)`

- Fallback: If timeout, return `0.5` (neutral) with logging

**Testing:**
- Create mock that sleeps 20 seconds
- Assert timeout fires at 15s
- Assert score returns `0.5`
- Assert warning logged

**Status:** ⏳ TO DO

---

#### FIX #4: Congress Trades Fallback to SEC EDGAR
**Severity:** CRITICAL | **Effort:** 4 hours | **Impact:** Remove single-point-of-failure on Quiver API

**Current Problem:**
- Quiver API is sole source for congress trades
- If offline, congress score defaults to `0.5` for **entire day** (6h cache)
- No backup source

**Implementation:**
- Create `smart_money/congress_fallback.py`:
  ```python
  def compute_congress_score_with_fallback(ticker: str) -> float:
      try:
          # Primary: Quiver API
          return compute_congress_score_quiver(ticker)
      except (Timeout, ConnectionError):
          logger.warning(f"Quiver API failed for {ticker}, trying SEC EDGAR")
          try:
              # Secondary: SEC EDGAR (FORM 4 filings)
              return compute_congress_score_sec_edgar(ticker)
          except Exception as e:
              logger.error(f"SEC EDGAR also failed for {ticker}: {e}")
              return 0.5  # Neutral fallback
  
  def compute_congress_score_sec_edgar(ticker: str) -> float:
      """
      Query SEC EDGAR for recent FORM 4 filings (insider trades).
      Simple heuristic: more insider buys than sells = positive signal.
      """
      try:
          # Fetch recent FORM 4 filings (insider trades)
          cik = ticker_to_cik(ticker)
          filings = fetch_sec_form4s(cik, days=30)
          
          buy_count = sum(1 for f in filings if f["transaction_type"] == "P")  # Purchase
          sell_count = sum(1 for f in filings if f["transaction_type"] == "S")  # Sale
          
          if buy_count + sell_count == 0:
              return 0.5
          
          # Simple scoring: [0.1, 0.9] based on buy/sell ratio
          ratio = buy_count / (buy_count + sell_count)
          return min(0.9, max(0.1, 0.3 + 0.6 * ratio))
      except Exception as e:
          logger.error(f"SEC EDGAR fallback failed: {e}")
          return 0.5
  ```

- Update `smart_money/congress.py`:
  - Import fallback
  - Call fallback version instead of Quiver-only version

**Data source:**
- SEC EDGAR API: `https://data.sec.gov/submissions/CIK{cik}.json` (free, no rate limit)
- Parse FORM 4 filings for insider trades
- Cache 12h (insiders rare, unlikely to change within day)

**Testing:**
- Mock Quiver API timeout
- Assert SEC EDGAR fallback triggers
- Assert score in [0.1, 0.9] range
- Assert Quiver API OK case takes priority

**Status:** ⏳ TO DO

---

#### FIX #5: Earnings Calendar TTL Reduction
**Severity:** CRITICAL | **Effort:** 2 hours | **Impact:** Reduce stale earnings dates

**Current Problem:**
- Earnings calendar cached 24h
- Pre-earnings dates can change within day (moved announcements, cancellations)
- Stale date = wrong signal modifier (−5% for pre, +7% post)

**Implementation:**
- In `smart_money/earnings_scorer.py`, reduce TTL:
  ```python
  EARNINGS_CACHE_TTL = 6 * 3600  # 6 hours (was 24)
  
  def get_earnings_calendar(ticker: str) -> list[dict]:
      cache_key = f"earnings:{ticker}"
      cached = cache.get(cache_key)
      
      if cached and (time.time() - cached["fetched_at"]) < EARNINGS_CACHE_TTL:
          return cached["data"]
      
      # Fetch fresh
      data = yfinance.Ticker(ticker).quarterly_earnings_dates
      cache.set(cache_key, {"data": data, "fetched_at": time.time()})
      return data
  ```

- Add freshness check:
  ```python
  def _get_earnings_score_with_freshness(ticker: str) -> tuple[float, bool]:
      """
      Returns (score, is_fresh).
      is_fresh = True if calendar <6h old.
      """
      if earnings_age_seconds > 21600:  # 6h
          logger.warning(f"Earnings calendar stale ({earnings_age_seconds}s) for {ticker}")
          return 0.5, False
      return score, True
  ```

**Testing:**
- Set time.time() to current - 12 hours
- Assert cache misses
- Assert new fetch occurs
- Assert score marked as fresh

**Status:** ⏳ TO DO

---

#### FIX #6: Circuit Breaker — Stop Trading on Data Quality Failure
**Severity:** HIGH | **Effort:** 4 hours | **Impact:** Prevent trading on incomplete data

**What to implement:**
A state machine that tracks data quality and halts signal generation if quality drops below threshold.

```python
class DataQualityCircuitBreaker:
    """
    Monitors data freshness across all sources.
    Transitions: HEALTHY → DEGRADED → OPEN (trading halted)
    """
    
    def __init__(self):
        self.state = "HEALTHY"
        self.failure_count = 0
        self.threshold = 3  # Halt after 3 consecutive failures
        self.last_failure_time = None
    
    def record_failure(self, source: str, error: str):
        """Record API failure."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        logger.error(f"Data quality failure #{self.failure_count}: {source} - {error}")
        
        if self.failure_count >= self.threshold:
            self.state = "OPEN"
            logger.critical(f"Circuit breaker OPEN — halting signal generation")
        elif self.failure_count >= 2:
            self.state = "DEGRADED"
    
    def record_success(self):
        """Reset on success."""
        if self.failure_count > 0:
            self.failure_count -= 1
        if self.failure_count == 0:
            self.state = "HEALTHY"
    
    def should_generate_signals(self) -> bool:
        """Check if OK to generate signals."""
        return self.state != "OPEN"
    
    def get_status(self) -> dict:
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "last_failure": self.last_failure_time,
        }
```

- Integrate into `api/analyze.py`:
  ```python
  circuit_breaker = DataQualityCircuitBreaker()
  
  def analyze_ticker(ticker: str) -> dict:
      if not circuit_breaker.should_generate_signals():
          raise HTTPException(
              status_code=503,
              detail=f"Data quality degraded — circuit breaker OPEN. Retry in 5 minutes."
          )
      
      try:
          # ... analysis ...
          circuit_breaker.record_success()
          return result
      except DataFetchError as e:
          circuit_breaker.record_failure(e.source, str(e))
          raise HTTPException(status_code=503, detail=str(e))
  ```

**Testing:**
- Simulate 3 consecutive API failures
- Assert state transitions HEALTHY → DEGRADED → OPEN
- Assert /analyze/{ticker} returns 503 when OPEN
- Assert recovery after success

**Status:** ⏳ TO DO

---

## IMPLEMENTATION ORDER

### TODAY (June 5, 2026) — 8 hours
1. **Fix #1: Layer-5 mis-wiring** (1h)
2. **Fix #2: Data freshness tracking** (2h)
3. **Fix #3: yfinance timeout** (3h)
4. **Fix #5: Earnings TTL reduction** (2h)

### TOMORROW (June 6, 2026) — 8 hours
5. **Fix #4: Congress fallback to SEC EDGAR** (4h)
6. **Fix #6: Circuit breaker** (4h)

### TESTING & VALIDATION (June 7-8, 2026)
- Run full test suite (should pass 520+ tests)
- Paper trading validation
- Performance benchmarking (API response time <500ms)

---

## PHASE 2: REGIME SHIFT & FACTOR ROBUSTNESS

After Phase 1 is deployed and paper trading starts, Phase 2 focuses on making the model adaptive to regime changes:

### Mechanism 1: Adaptive Regime Detection
**Goal:** Model detects when market regime changes and auto-adjusts weights

**Implementation:**
- Daily: Compute rolling correlation (30-day window) between each factor and realized returns
- Weekly: If correlation drops >50%, flag factor as degraded
- Monthly: Auto-adjust weights away from degraded factors (max ±3pp per month)

**Example:**
- Technical factor usually correlates +0.35 with returns (backtest)
- If rolling correlation drops to +0.10, reduce weight from 15% to 12%
- Reinvest 3% in other factors

### Mechanism 2: Factor Quality Scoring
**Goal:** Continuous validation of unvalidated factors

**Implementation:**
```python
class FactorQualityScore:
    def __init__(self):
        self.rolling_correlation = {}  # factor → [corr_day1, corr_day2, ...]
        self.quality_score = {}  # factor → 0.0-1.0
    
    def update(self, factor: str, realized_return: float, factor_score: float):
        """Update quality score as trades close."""
        corr = compute_spearman(
            [factor_score for all trades this period],
            [realized_return for all trades this period]
        )
        self.rolling_correlation[factor].append(corr)
        
        # Quality = how well correlation matches historical baseline
        baseline = {"technical": 0.35, "momentum": 0.40, ...}[factor]
        decay = 0.8  # Recent history weighted higher
        self.quality_score[factor] = smooth(
            abs(corr - baseline),
            decay=decay
        )
    
    def get_weight_adjustment(self, factor: str, current_weight: float) -> float:
        """Recommend weight change if quality has degraded."""
        quality = self.quality_score[factor]
        if quality < 0.5:  # Severely degraded
            return current_weight * 0.8  # Reduce by 20%
        elif quality < 0.7:  # Moderately degraded
            return current_weight * 0.9  # Reduce by 10%
        return current_weight  # Keep as-is
```

### Mechanism 3: Behavioral Coaching (Paper Trading)
**Goal:** Build discipline to avoid override during drawdowns

**Implementation:**
- Daily briefing: Show "This is Week X of paper trading. Your commitment: HOLD SIGNALS FOR 6 MONTHS."
- If paper drawdown >15%, send alert: "Natural correction. Historical models recover in X days. HOLD."
- Log every time you're tempted to override (for reflection)

---

## SUCCESS METRICS (End of Phase 1)

✅ All 6 fixes implemented  
✅ 520+ tests passing  
✅ Data freshness monitoring active (alerts on >24h staleness)  
✅ Circuit breaker tested (halts on 3x failures)  
✅ yfinance timeout validated (kills hang-requests at 15s)  
✅ Congress fallback to SEC EDGAR working  
✅ Paper trading ready to start (June 9, 2026)  

---

## DEFINITION OF A-GRADE MODEL

By end of Phase 2 (mid-July), model should achieve:

**✅ Data Resilience:** Dual sources for critical signals, <1h staleness guarantee, circuit breaker  
**✅ Adaptive Learning:** Weekly factor quality review, monthly weight rebalancing  
**✅ Risk Management:** Real-time volatility scaling, regime-based position sizing, behavioral guardrails  
**✅ Transparency:** Every decision logged with rationale, staleness metadata, confidence scores  
**✅ Robustness:** Tested on synthetic regime shifts (stagflation, crashes, sideways), handles 99.9% uptime  

**Grade progression:**
- Current: 6.8/10 (B-)
- After Phase 1: 8.2/10 (A−)
- After Phase 2: 9.0+/10 (A)

---

**Next step:** Execute Fix #1-6 starting now. Commit after each fix is tested.