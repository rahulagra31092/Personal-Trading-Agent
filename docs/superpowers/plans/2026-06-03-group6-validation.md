# Group 6: Validation (Walk-Forward Backtest) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a walk-forward backtest engine that scores the universe of 83 tickers using 2 durable, OHLCV-derivable factors (technical and momentum) and measures year-by-year alpha vs SPY for 2019–2023. This validates that the model's core signal engine — not just its current in-sample tuning — selects tickers that outperform the index, producing evidence for or against the 18-20% CAGR hypothesis before committing to paper money.

**Architecture:** A new `quant/backtest_walkforward.py` module. Key functions are `fetch_bars(ticker, start, end)` (yfinance wrapper), `_score_bars(bars)` (technical + momentum composite), `run_walkforward_year(tickers, year, fetch_fn)` (score at year N-1, measure return in year N vs SPY), and `run_walkforward(tickers, years, fetch_fn)` (multi-year loop). All scoring logic is pure-Python and tested with injected synthetic data — no network calls in the test suite. A `__main__` block lets you run the real 5-year sweep from the terminal.

**Tech Stack:** Python 3.12, yfinance, existing `compute_indicators` and `compute_momentum_score_from_bars`.

**Important scope note:** Quality and earnings factors require fundamental snapshots at each measurement date, which yfinance does not provide historically. This backtest intentionally uses only technical + momentum — the 2 factors derivable purely from price history. This is NOT a full-model replay; it is a validation that the alpha source (momentum + technical confirmation) persists across market cycles.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `quant/backtest_walkforward.py` | Create | `fetch_bars`, `_score_bars`, `run_walkforward_year`, `run_walkforward`, `check_success_criteria` |
| `tests/quant/test_backtest_walkforward.py` | Create | Unit tests using injected `fetch_fn` — zero network calls |

---

## Task 1: Core Walk-Forward Engine

**Files:**
- Create: `quant/backtest_walkforward.py`
- Create: `tests/quant/test_backtest_walkforward.py`

- [ ] **Step 1: Write all failing tests**

Create `tests/quant/test_backtest_walkforward.py`:

```python
"""Walk-forward backtest tests — all use injected fetch_fn, no network calls."""
import math
import pytest
from quant.backtest_walkforward import (
    _score_bars,
    _annual_return,
    run_walkforward_year,
    run_walkforward,
    check_success_criteria,
)


# ---------------------------------------------------------------------------
# Synthetic bar helpers
# ---------------------------------------------------------------------------

def _bars(n: int, trend: float = 0.001, start_price: float = 100.0) -> list[dict]:
    """Generate synthetic OHLCV bars with a linear trend."""
    price = start_price
    bars = []
    for i in range(n):
        price = price * (1 + trend)
        bars.append({
            "t": 1546300800000 + i * 86400000,  # Jan 1 2019 + i days
            "o": price * 0.999,
            "h": price * 1.005,
            "l": price * 0.995,
            "c": float(price),
            "v": 1_000_000,
        })
    return bars


def _flat_bars(n: int, price: float = 100.0) -> list[dict]:
    """Generate flat price bars (no trend → low momentum score)."""
    return [
        {"t": 1546300800000 + i * 86400000,
         "o": price, "h": price * 1.001, "l": price * 0.999, "c": price, "v": 500_000}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# _score_bars
# ---------------------------------------------------------------------------

def test_score_bars_returns_float_in_range():
    score = _score_bars(_bars(300))
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_score_bars_too_few_bars_returns_neutral():
    score = _score_bars(_bars(10))
    assert score == 0.5


def test_score_bars_uptrend_scores_higher_than_flat():
    up = _score_bars(_bars(300, trend=0.002))
    flat = _score_bars(_flat_bars(300))
    assert up > flat


def test_score_bars_downtrend_scores_lower_than_uptrend():
    up = _score_bars(_bars(300, trend=0.002))
    down = _score_bars(_bars(300, trend=-0.002))
    assert up > down


# ---------------------------------------------------------------------------
# _annual_return
# ---------------------------------------------------------------------------

def _make_fetch_fn(bars_by_key: dict[str, list[dict]]):
    """Returns a fetch_fn that serves bars from a pre-built dict keyed by ticker."""
    def _fetch(ticker: str, start: str, end: str) -> list[dict]:
        return bars_by_key.get(ticker, [])
    return _fetch


def test_annual_return_computes_pct_change():
    # bars with 0.001 daily trend over 252 bars → ~28% annual
    bars = _bars(252, trend=0.001, start_price=100.0)
    fetch = _make_fetch_fn({"AAPL": bars})
    r = _annual_return("AAPL", 2023, fetch)
    assert r is not None
    assert r > 0.20  # 0.001 × 252 compounded ≈ 28%


def test_annual_return_none_on_empty_bars():
    fetch = _make_fetch_fn({})
    assert _annual_return("MISSING", 2023, fetch) is None


def test_annual_return_none_on_single_bar():
    fetch = _make_fetch_fn({"X": _bars(1)})
    assert _annual_return("X", 2023, fetch) is None


# ---------------------------------------------------------------------------
# run_walkforward_year
# ---------------------------------------------------------------------------

def _build_universe_fetch(n_tickers: int = 5) -> tuple[list[str], callable]:
    """
    Build a small synthetic universe.
    Tickers 0-2: strong uptrend (score ≈ 0.7) → top picks.
    Tickers 3-4: flat (score ≈ 0.5) → ranked lower.
    All tickers: 5% annual return in the measurement year.
    """
    tickers = [f"T{i}" for i in range(n_tickers)]
    # Scoring bars: 15 months ending Dec 31 of scoring year
    scoring_bars = {
        "T0": _bars(300, trend=0.002),  # strong trend
        "T1": _bars(300, trend=0.0015),
        "T2": _bars(300, trend=0.0012),
        "T3": _flat_bars(300),
        "T4": _flat_bars(300),
        "SPY": _bars(252, trend=0.0004),  # SPY modest return
    }
    # Return bars: full year measurement
    # Same keys serve both scoring and return queries (fetch_fn is called twice per ticker)
    fetch = _make_fetch_fn(scoring_bars)
    return tickers, fetch


def test_run_walkforward_year_returns_required_keys():
    tickers, fetch = _build_universe_fetch()
    result = run_walkforward_year(tickers, measurement_year=2023, fetch_fn=fetch)
    for key in ("model_return", "spy_return", "alpha", "portfolio_size", "top_picks"):
        assert key in result


def test_run_walkforward_year_top_picks_are_uptrend_tickers():
    tickers, fetch = _build_universe_fetch()
    result = run_walkforward_year(tickers, measurement_year=2023, fetch_fn=fetch)
    # Top picks should include T0, T1, T2 (uptrend), not T3/T4 (flat)
    if result["top_picks"]:
        for t in result["top_picks"]:
            assert t in ("T0", "T1", "T2")


def test_run_walkforward_year_alpha_is_model_minus_spy():
    tickers, fetch = _build_universe_fetch()
    result = run_walkforward_year(tickers, measurement_year=2023, fetch_fn=fetch)
    if result["model_return"] is not None and result["spy_return"] is not None:
        assert abs(result["alpha"] - (result["model_return"] - result["spy_return"])) < 0.001


def test_run_walkforward_year_empty_tickers_returns_none_alpha():
    fetch = _make_fetch_fn({"SPY": _bars(252)})
    result = run_walkforward_year([], measurement_year=2023, fetch_fn=fetch)
    assert result["alpha"] is None


# ---------------------------------------------------------------------------
# run_walkforward (multi-year)
# ---------------------------------------------------------------------------

def _multi_year_fetch(years: list[int]) -> callable:
    """Returns bars for any ticker/year pair — consistent 5% model return, 3% SPY."""
    def _fetch(ticker: str, start: str, end: str) -> list[dict]:
        if ticker == "SPY":
            return _bars(252, trend=0.00011)  # ≈ 3% annual
        return _bars(300, trend=0.00015)  # ≈ 5% annual for all portfolio tickers
    return _fetch


def test_run_walkforward_returns_all_years():
    tickers = [f"T{i}" for i in range(5)]
    fetch = _multi_year_fetch([2019, 2020, 2021, 2022, 2023])
    results = run_walkforward(tickers, years=[2019, 2020, 2021], fetch_fn=fetch)
    assert set(results["years"].keys()) == {2019, 2020, 2021}


def test_run_walkforward_has_summary_key():
    tickers = [f"T{i}" for i in range(5)]
    fetch = _multi_year_fetch([2019, 2020, 2021])
    results = run_walkforward(tickers, years=[2019, 2020, 2021], fetch_fn=fetch)
    assert "summary" in results


# ---------------------------------------------------------------------------
# check_success_criteria
# ---------------------------------------------------------------------------

def test_check_success_criteria_passes_4_of_5_positive_alpha():
    results = {
        "years": {
            2019: {"alpha": 0.05, "model_return": 0.30},
            2020: {"alpha": 0.08, "model_return": 0.25},
            2021: {"alpha": 0.03, "model_return": 0.20},
            2022: {"alpha": -0.02, "model_return": -0.10},
            2023: {"alpha": 0.06, "model_return": 0.18},
        }
    }
    criteria = check_success_criteria(results)
    assert criteria["passes"] is True
    assert criteria["positive_alpha_years"] == 4


def test_check_success_criteria_fails_on_catastrophic_drawdown():
    results = {
        "years": {
            2019: {"alpha": 0.05, "model_return": 0.30},
            2020: {"alpha": 0.08, "model_return": -0.25},  # worse than -18%
            2021: {"alpha": 0.03, "model_return": 0.20},
            2022: {"alpha": 0.02, "model_return": 0.10},
            2023: {"alpha": 0.06, "model_return": 0.18},
        }
    }
    criteria = check_success_criteria(results)
    assert criteria["passes"] is False


def test_check_success_criteria_fails_on_3_positive_alpha_years():
    results = {
        "years": {
            2019: {"alpha": -0.02, "model_return": 0.10},
            2020: {"alpha": -0.05, "model_return": -0.05},
            2021: {"alpha": 0.03, "model_return": 0.20},
            2022: {"alpha": 0.02, "model_return": 0.10},
            2023: {"alpha": 0.06, "model_return": 0.18},
        }
    }
    criteria = check_success_criteria(results)
    assert criteria["passes"] is False
    assert criteria["positive_alpha_years"] == 3
```

- [ ] **Step 2: Run tests to verify they all fail**

```
cd "C:\Claude\Trading Analyst"
.\.venv\Scripts\pytest.exe tests/quant/test_backtest_walkforward.py -v
```

Expected: `ImportError` — `quant.backtest_walkforward` does not exist yet.

- [ ] **Step 3: Create `quant/backtest_walkforward.py`**

Create the file with all functions:

```python
"""
Walk-forward backtest: validates technical + momentum signal across 5 historical years.

Uses only OHLCV-derivable factors (technical + momentum) since historical fundamental
snapshots are unavailable from yfinance. The 2-factor composite is a proxy, not a full
model replay — it tests whether the core alpha source persists across market cycles.

Run manually:
    cd "C:\Claude\Trading Analyst"
    .\.venv\Scripts\python.exe -m quant.backtest_walkforward
"""
import logging
from typing import Callable

import pandas as pd
import yfinance as yf

from quant.indicators import compute_indicators
from quant.momentum import compute_momentum_score_from_bars

logger = logging.getLogger(__name__)

# Weights: momentum 2× technical (reflects live model ratio of 30% vs 15%)
_TECH_WEIGHT = 0.33
_MOM_WEIGHT  = 0.67
_MIN_SCORE_FOR_PORTFOLIO = 0.55  # only buy tickers with meaningful signal


# ---------------------------------------------------------------------------
# Data layer (injectable for tests)
# ---------------------------------------------------------------------------

def fetch_bars(ticker: str, start: str, end: str) -> list[dict]:
    """
    Download OHLCV bars from yfinance for [start, end] (ISO date strings).
    Returns list of {t, o, h, l, c, v} dicts matching compute_indicators format.
    Returns [] on failure.
    """
    try:
        hist: pd.DataFrame = yf.download(
            ticker, start=start, end=end, auto_adjust=True, progress=False
        )
        if len(hist) == 0:
            return []

        if isinstance(hist.columns, pd.MultiIndex):
            def _col(name: str) -> pd.Series:
                data = hist[name]
                return data.iloc[:, 0] if isinstance(data, pd.DataFrame) else data
        else:
            def _col(name: str) -> pd.Series:
                return hist[name]

        bars = []
        for ts, o, h, l, c, v in zip(
            hist.index,
            _col("Open"), _col("High"), _col("Low"), _col("Close"), _col("Volume"),
        ):
            bars.append({
                "t": int(ts.timestamp() * 1000),
                "o": float(o), "h": float(h), "l": float(l),
                "c": float(c), "v": float(v),
            })
        return bars

    except Exception as exc:
        logger.warning("fetch_bars failed for %s [%s %s]: %s", ticker, start, end, exc)
        return []


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_bars(bars: list[dict]) -> float:
    """
    2-factor composite from OHLCV bars (technical 33% + momentum 67%).
    Returns 0.5 (neutral) when insufficient data.
    """
    if len(bars) < 84:  # minimum for momentum's 3M + 21-day skip
        return 0.5

    try:
        ind = compute_indicators(bars)
        tech = ind.get("technical_score", 0.5)
    except Exception:
        tech = 0.5

    mom = compute_momentum_score_from_bars(bars)
    return round(_TECH_WEIGHT * tech + _MOM_WEIGHT * mom, 4)


# ---------------------------------------------------------------------------
# Return measurement
# ---------------------------------------------------------------------------

def _annual_return(
    ticker: str,
    year: int,
    fetch_fn: Callable,
) -> float | None:
    """Measure ticker's price return from first to last trading day of year."""
    bars = fetch_fn(ticker, f"{year}-01-01", f"{year}-12-31")
    if len(bars) < 2:
        return None
    p0 = bars[0]["c"]
    p1 = bars[-1]["c"]
    if p0 <= 0:
        return None
    return round((p1 - p0) / p0, 4)


# ---------------------------------------------------------------------------
# Single-year walk-forward
# ---------------------------------------------------------------------------

def run_walkforward_year(
    tickers: list[str],
    measurement_year: int,
    top_n: int = 20,
    fetch_fn: Callable = fetch_bars,
) -> dict:
    """
    Score tickers using 15 months of OHLCV ending Dec 31 of (measurement_year - 1).
    Build top_n portfolio (score > _MIN_SCORE_FOR_PORTFOLIO).
    Measure equal-weighted return vs SPY during measurement_year.

    Returns:
        model_return: float | None  — equal-weighted avg return of portfolio
        spy_return:   float | None  — SPY return same year
        alpha:        float | None  — model_return - spy_return
        portfolio_size: int
        top_picks:    list[str]     — up to 5 tickers with highest scores
    """
    if not tickers:
        return {"model_return": None, "spy_return": None, "alpha": None,
                "portfolio_size": 0, "top_picks": []}

    scoring_year = measurement_year - 1
    score_start  = f"{scoring_year - 1}-10-01"   # ~15 months of history
    score_end    = f"{scoring_year}-12-31"

    # Score all tickers
    scored = []
    for ticker in tickers:
        bars = fetch_fn(ticker, score_start, score_end)
        score = _score_bars(bars)
        scored.append({"ticker": ticker, "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)

    portfolio = [s for s in scored[:top_n] if s["score"] >= _MIN_SCORE_FOR_PORTFOLIO]
    if not portfolio:
        return {"model_return": None, "spy_return": None, "alpha": None,
                "portfolio_size": 0, "top_picks": [s["ticker"] for s in scored[:5]]}

    # Measure forward returns
    returns = []
    for pos in portfolio:
        r = _annual_return(pos["ticker"], measurement_year, fetch_fn)
        if r is not None:
            returns.append(r)

    spy_return = _annual_return("SPY", measurement_year, fetch_fn)

    if not returns or spy_return is None:
        return {"model_return": None, "spy_return": spy_return, "alpha": None,
                "portfolio_size": len(portfolio), "top_picks": [s["ticker"] for s in portfolio[:5]]}

    model_return = round(sum(returns) / len(returns), 4)
    alpha = round(model_return - spy_return, 4)

    return {
        "model_return": model_return,
        "spy_return":   round(spy_return, 4),
        "alpha":        alpha,
        "portfolio_size": len(returns),
        "top_picks":    [s["ticker"] for s in portfolio[:5]],
    }


# ---------------------------------------------------------------------------
# Multi-year runner
# ---------------------------------------------------------------------------

def run_walkforward(
    tickers: list[str],
    years: list[int],
    top_n: int = 20,
    fetch_fn: Callable = fetch_bars,
) -> dict:
    """
    Run year-by-year walk-forward for each measurement year.
    Returns {"years": {year: result_dict}, "summary": check_success_criteria(...)}
    """
    year_results = {}
    for year in years:
        logger.info("Walk-forward: scoring for measurement year %d ...", year)
        result = run_walkforward_year(tickers, year, top_n=top_n, fetch_fn=fetch_fn)
        year_results[year] = result
        alpha_str = f"{result['alpha']:+.1%}" if result["alpha"] is not None else "N/A"
        logger.info("  Year %d: model=%s  SPY=%s  alpha=%s  n=%d",
                    year,
                    f"{result['model_return']:.1%}" if result["model_return"] is not None else "N/A",
                    f"{result['spy_return']:.1%}"   if result["spy_return"]   is not None else "N/A",
                    alpha_str,
                    result["portfolio_size"])

    combined = {"years": year_results}
    combined["summary"] = check_success_criteria(combined)
    return combined


# ---------------------------------------------------------------------------
# Success criteria
# ---------------------------------------------------------------------------

def check_success_criteria(results: dict) -> dict:
    """
    Evaluate whether the walk-forward meets the 18-20% CAGR validation bar:
      - Positive alpha (model > SPY) in >= 4 of N years
      - No annual model return worse than -18%

    results: dict with "years" key → {year: {alpha, model_return, ...}}
    """
    year_data = results.get("years", {})
    alphas        = [v["alpha"]        for v in year_data.values() if v.get("alpha")        is not None]
    model_returns = [v["model_return"] for v in year_data.values() if v.get("model_return") is not None]

    if not alphas:
        return {"passes": False, "positive_alpha_years": 0,
                "worst_annual_return": None, "avg_alpha": None,
                "reason": "No valid years to evaluate."}

    positive_alpha_years = sum(1 for a in alphas if a > 0)
    worst_return         = round(min(model_returns), 4) if model_returns else 0.0
    avg_alpha            = round(sum(alphas) / len(alphas), 4)

    passes = positive_alpha_years >= 4 and worst_return >= -0.18

    reasons = []
    if positive_alpha_years < 4:
        reasons.append(f"Only {positive_alpha_years} of {len(alphas)} years beat SPY (need ≥4)")
    if worst_return < -0.18:
        reasons.append(f"Worst year {worst_return:.1%} exceeds -18% drawdown limit")

    return {
        "passes": passes,
        "positive_alpha_years": positive_alpha_years,
        "worst_annual_return":  worst_return,
        "avg_alpha":            avg_alpha,
        "reason":               "; ".join(reasons) if reasons else "All criteria met",
    }


# ---------------------------------------------------------------------------
# Manual runner — execute as: python -m quant.backtest_walkforward
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    from api.briefing import BLUE_CHIP_UNIVERSE, MIDCAP_UNIVERSE

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    universe = list(set(BLUE_CHIP_UNIVERSE + MIDCAP_UNIVERSE))
    years    = [2019, 2020, 2021, 2022, 2023]

    print(f"Running 5-year walk-forward on {len(universe)} tickers...")
    results = run_walkforward(universe, years=years)

    print("\n=== YEAR-BY-YEAR RESULTS ===")
    for year in sorted(results["years"]):
        r = results["years"][year]
        print(f"{year}: model={r['model_return']:.1%}  SPY={r['spy_return']:.1%}  "
              f"alpha={r['alpha']:+.1%}  n={r['portfolio_size']}  "
              f"picks={r['top_picks'][:3]}")

    print("\n=== SUCCESS CRITERIA ===")
    s = results["summary"]
    print(f"Passes: {s['passes']}")
    print(f"Positive-alpha years: {s['positive_alpha_years']} / {len(years)}")
    print(f"Worst annual return:  {s['worst_annual_return']:.1%}")
    print(f"Average alpha:        {s['avg_alpha']:+.1%}")
    print(f"Reason: {s['reason']}")

    with open("walkforward_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nSaved to walkforward_results.json")
```

- [ ] **Step 4: Run all tests — they must pass**

```
.\.venv\Scripts\pytest.exe tests/quant/test_backtest_walkforward.py -v
```

Expected: All 20 tests pass.

- [ ] **Step 5: Run full suite to check no regressions**

```
.\.venv\Scripts\pytest.exe tests/ -q
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```
git add quant/backtest_walkforward.py tests/quant/test_backtest_walkforward.py
git commit -m "feat(validation): walk-forward backtest engine (2-factor, 5-year, alpha vs SPY)"
```

---

## Task 2: Run the Real Backtest (Manual Step)

**Files:** No code changes — this is a manual execution step.

### Background
Running on real yfinance data takes 5-10 minutes (830 HTTP calls for 83 tickers × 2 calls per year × 5 years). This is a one-time analysis run to validate the model before committing to paper trading. Results are saved to `walkforward_results.json` for review.

- [ ] **Step 1: Run the backtest from the terminal**

```
cd "C:\Claude\Trading Analyst"
.\.venv\Scripts\python.exe -m quant.backtest_walkforward
```

Expected output (approximate — actual numbers depend on real data):
```
Running 5-year walk-forward on 83 tickers...
2019: model=+31%  SPY=+28%  alpha=+0.03  n=20  picks=['NVDA', 'MSFT', ...]
2020: model=+24%  SPY=+16%  alpha=+0.08  n=18  picks=['AAPL', 'AMD', ...]
2021: model=+28%  SPY=+26%  alpha=+0.02  n=20  picks=[...]
2022: model=-16%  SPY=-18%  alpha=+0.02  n=15  picks=[...]
2023: model=+30%  SPY=+24%  alpha=+0.06  n=20  picks=[...]

=== SUCCESS CRITERIA ===
Passes: True
Positive-alpha years: 5 / 5
Worst annual return: -16.4%
Average alpha: +4.2%
```

**If the criteria are NOT met** (`passes: False`): Review `walkforward_results.json`. If alpha is negative in 2+ years, check which years and which tickers dragged performance. This may indicate that the momentum + technical signal is not sufficient alone, or that the current universe needs trimming. Report findings before proceeding to paper trading.

- [ ] **Step 2: Record findings**

Save the key output numbers as a comment in `walkforward_results.json` or paste into a new doc at `docs/walkforward-findings.md`. This is the validation artifact that justifies starting paper trading.

---

## Self-Review

**Spec coverage:**
- [x] Walk-forward backtest engine → Task 1 Step 3 (`run_walkforward`, `run_walkforward_year`)
- [x] 2 durable factors from OHLCV (technical + momentum) → `_score_bars` with inject-safe `fetch_bars`
- [x] Performance measurement vs SPY → `_annual_return("SPY", ...)` in `run_walkforward_year`
- [x] Success criteria: positive alpha ≥ 4 of 5 years, worst year ≥ -18% → `check_success_criteria`
- [x] Zero network calls in tests → all tests use `_make_fetch_fn` with synthetic bars
- [x] 5-year real data run → Task 2 (`python -m quant.backtest_walkforward`)

**Placeholder scan:** None. Task 2 is intentionally a manual execution step — the expected output block is indicative, not prescriptive, because actual values depend on real yfinance data.

**Type consistency:**
- `fetch_fn` signature: `(ticker: str, start: str, end: str) -> list[dict]` — consistent in `run_walkforward_year`, `run_walkforward`, and `_annual_return`.
- `run_walkforward` returns `{"years": {int: dict}, "summary": dict}` — `check_success_criteria` expects this exact shape.
- `_score_bars` returns `float` in [0.0, 1.0] — `_MIN_SCORE_FOR_PORTFOLIO = 0.55` comparison is valid. ✓
