# TODAY'S FIXES — Priority Checklist
**Date:** June 5, 2026 | **Target:** All fixes by EOD | **Effort:** 16 hours

---

## FIX STATUS CHECK

### ✅ FIX #1: Layer-5 Mis-Wiring — ALREADY DONE
- Config key: `estimate_revisions` ✓ (config.py:45)
- Quarterly factors list: `score_estimate_revisions` ✓ (quarterly_review.py:24)
- DB schema: migrated from `score_trump_policy` ✓ (paper_portfolio.py)
- **Status:** VERIFIED COMPLETE

**To confirm:** Run test
```bash
pytest tests/quant/test_signals.py::test_analyze_signal_has_estimate_revisions_key_not_trump_policy -v
```

---

## FIXES THAT NEED TO BE DONE

### 🔴 FIX #2: Data Freshness Tracking (2 hours)
**Severity:** CRITICAL | **Status:** ⏳ TO DO

**What to do:**
1. Create `util/data_health.py` with staleness tracking
2. Modify `api/analyze.py` to track fetch times for each scorer
3. Add `data_health` dict to response showing age of each data source
4. Add alert if any source >24h old

**Files to create:**
- `util/data_health.py` (new file, 50 lines)
- `tests/util/test_data_health.py` (new tests, 40 lines)

**Files to modify:**
- `api/analyze.py` (add ~30 lines to track freshness)
- `quant/indicators.py` (add timestamp on fetch)
- `smart_money/congress.py` (add timestamp on fetch)
- `smart_money/earnings_scorer.py` (add timestamp on fetch)

**Priority:** HIGH — Enables visibility into data quality

---

### 🔴 FIX #3: yfinance Timeout Enforcement (3 hours)
**Severity:** CRITICAL | **Status:** ⏳ TO DO

**What to do:**
1. Create timeout decorator in `util/timeout.py`
2. Apply to all yfinance.download() calls
3. Apply to all yfinance.Ticker().info calls
4. Fall back to 0.5 (neutral) if timeout

**Files to create:**
- `util/timeout.py` (50 lines, timeout decorator)
- `tests/util/test_timeout.py` (30 lines)

**Files to modify:**
- `quant/indicators.py` (wrap yfinance calls, ~5 lines)
- `quant/momentum.py` (wrap yfinance calls, ~5 lines)
- `quant/quality.py` (wrap yfinance calls, ~5 lines)
- `smart_money/earnings_scorer.py` (wrap yfinance calls, ~5 lines)

**Priority:** CRITICAL — Prevents hanging requests

---

### 🔴 FIX #4: Congress Trades Fallback to SEC EDGAR (4 hours)
**Severity:** CRITICAL | **Status:** ⏳ TO DO

**What to do:**
1. Create `smart_money/congress_fallback.py` with SEC EDGAR parser
2. Update `smart_money/congress.py` to try Quiver first, SEC EDGAR second
3. Implement SEC EDGAR FORM 4 parsing
4. Cache SEC results 12h

**Files to create:**
- `smart_money/congress_fallback.py` (80 lines, SEC EDGAR integration)
- `tests/smart_money/test_congress_fallback.py` (50 lines)

**Files to modify:**
- `smart_money/congress.py` (add fallback call, ~10 lines)

**Data source:** SEC EDGAR free API (no rate limits)

**Priority:** CRITICAL — Removes single-point-of-failure

---

### 🔴 FIX #5: Earnings Calendar TTL Reduction (2 hours)
**Severity:** CRITICAL | **Status:** ⏳ TO DO

**What to do:**
1. Change cache TTL from 24h to 6h in `smart_money/earnings_scorer.py`
2. Add staleness warning if >6h old
3. Add test to verify cache refresh

**Files to modify:**
- `smart_money/earnings_scorer.py` (change 1 constant, ~10 lines for freshness check)
- `tests/smart_money/test_earnings_scorer.py` (add staleness test, 20 lines)

**Priority:** HIGH — Reduces stale earnings signal impact

---

### 🔴 FIX #6: Circuit Breaker for Data Quality (4 hours)
**Severity:** HIGH | **Status:** ⏳ TO DO

**What to do:**
1. Create `util/circuit_breaker.py` with state machine
2. Track API failures across all sources
3. Halt signal generation (return 503) if 3+ consecutive failures
4. Auto-recover on successful fetch

**Files to create:**
- `util/circuit_breaker.py` (70 lines, state machine)
- `tests/util/test_circuit_breaker.py` (60 lines)

**Files to modify:**
- `api/analyze.py` (integrate circuit breaker, ~15 lines)
- `api/main.py` (add health check endpoint, ~15 lines)

**Priority:** HIGH — Prevents cascading failures

---

## IMPLEMENTATION TIMELINE

### TODAY — Hours 0-8 (MORNING/AFTERNOON)

**0-2h:** FIX #2 — Data Freshness Tracking
- Create `util/data_health.py`
- Modify `api/analyze.py` to track staleness
- Test end-to-end

**2-5h:** FIX #3 — yfinance Timeout
- Create `util/timeout.py` decorator
- Apply to 4 scorers (indicators, momentum, quality, earnings)
- Test timeout triggers correctly

**5-6h:** FIX #5 — Earnings TTL Reduction
- Change TTL constant
- Add freshness check
- Quick test

### TOMORROW — Hours 8-16 (MORNING)

**0-4h:** FIX #4 — Congress Fallback to SEC EDGAR
- Create SEC EDGAR integration
- Wire Quiver → SEC EDGAR fallback
- Test both primary and fallback paths

**4-8h:** FIX #6 — Circuit Breaker
- Create state machine
- Integrate into analyze_ticker()
- Test failure scenarios + recovery

---

## VALIDATION CHECKLIST (End of Day)

✅ All 6 fixes implemented and tested  
✅ 520+ tests passing (including 40 new tests)  
✅ `pytest tests/ -v` runs cleanly  
✅ Data freshness visible in `/analyze/{ticker}` response  
✅ Timeout decorator kills yfinance requests at 15s  
✅ Congress fallback to SEC EDGAR working  
✅ Earnings cache refreshes every 6h  
✅ Circuit breaker halts on 3 failures, recovers on success  
✅ Paper trading launcher ready (no blockers)  

---

## SUCCESS LOOKS LIKE

**Response from `/analyze/AAPL`:**
```json
{
  "ticker": "AAPL",
  "signal": {
    "composite_score": 0.68,
    "label": "BUY",
    "layer_scores": {...}
  },
  "data_health": {
    "yfinance_age_seconds": 3600,
    "quiver_age_seconds": 1800,
    "earnings_cache_age_seconds": 7200,
    "staleness_warnings": [],
    "circuit_breaker_state": "HEALTHY"
  },
  "market_regime": "normal",
  "vix": 18.5
}
```

✅ All data sources tracked  
✅ Freshness visible  
✅ No warnings (data fresh)  
✅ Circuit breaker healthy  

---

## NEXT PHASE (June 9-30, 2026)

**Phase 2: Adaptive Learning & Regime Resilience**
- Implement factor quality scoring
- Weekly Spearman correlation review
- Monthly auto-weight rebalancing (max ±3pp)
- Stress-test on synthetic regimes (stagflation, crash)

**Goal:** A-grade model by July 1, 2026

---

**START NOW — First fix in 30 minutes**