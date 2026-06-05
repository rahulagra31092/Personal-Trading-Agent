# Integration Fixes #2-6 — Implementation Guide
**Target Completion:** Today (June 5, 2026)  
**Current Status:** Starting Fix #2

---

## FIX #2: Integrate Data Health Monitoring (1 hour)

### Step 1: Modify `api/analyze.py`
Add data_health tracking to `analyze_ticker()` response

```python
from util.data_health import record_fetch, get_health_report, get_staleness_warnings

def analyze_ticker(ticker: str) -> dict:
    # ... existing code ...
    
    # Get health report
    health = get_health_report()
    
    result = {
        # ... existing fields ...
        "data_health": {
            "sources": health["sources"],
            "staleness_warnings": health["staleness_warnings"],
            "is_healthy": health["is_healthy"],
        }
    }
```

### Step 2: Add fetch recording to data sources
Wrap API calls with `record_fetch("source_name", success)`

---

## FIX #3: Apply Timeout Decorators (2 hours)

### Files to modify:
- `data/market.py`: wrap Polygon API call
- `quant/momentum.py`: wrap yfinance calls
- `quant/quality.py`: wrap yfinance calls
- `smart_money/earnings_scorer.py`: wrap yfinance calls

### Pattern:
```python
from util.timeout import timeout

@timeout(15, default=0.5)
def fetch_data():
    # API call here
```

---

## FIX #4: Congress Fallback to SEC EDGAR (4 hours)

### Step 1: Create `smart_money/congress_fallback.py`
- Implement SEC EDGAR FORM 4 parser
- Handle fallback logic

### Step 2: Update `smart_money/congress.py`
- Import and use fallback function
- Try Quiver first, SEC EDGAR second

---

## FIX #5: Earnings TTL Reduction (1 hour)

### Step 1: Modify `smart_money/earnings_scorer.py`
- Change TTL from 24h to 6h
- Add staleness check

---

## FIX #6: Integrate Circuit Breaker (2 hours)

### Step 1: Modify `api/analyze.py`
- Add circuit breaker check at start
- Return 503 if OPEN

### Step 2: Wire into scorers
- Record failures in try/except blocks
- Record successes after completion

---

## Order of Implementation
1. Fix #2: Data health integration (1h)
2. Fix #3: Timeout decorators (2h)
3. Fix #5: Earnings TTL (1h)
4. Fix #4: Congress fallback (4h)
5. Fix #6: Circuit breaker (2h)

**Total: ~10 hours**

---

## Testing
- Run full test suite: `pytest tests/ -v`
- Should have 530+ tests passing
- Specifically test: `pytest tests/api/test_analyze.py -v`

---

## Validation Checklist
- [ ] `/analyze/AAPL` returns with `data_health` dict
- [ ] Timeout decorator kills yfinance at 15s
- [ ] Circuit breaker transitions correctly
- [ ] Congress fallback to SEC EDGAR works
- [ ] All 530+ tests pass
- [ ] Paper trading ready to launch
