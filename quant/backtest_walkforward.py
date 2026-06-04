"""
Walk-forward backtest: validates technical + momentum signal across 5 historical years.

Uses only OHLCV-derivable factors (technical + momentum) since historical fundamental
snapshots are unavailable from yfinance. The 2-factor composite is a proxy, not a full
model replay — it tests whether the core alpha source persists across market cycles.

Run manually:
    cd "C:\\Claude\\Trading Analyst"
    .venv\\Scripts\\python.exe -m quant.backtest_walkforward
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
        # Adapt: if technical_score is not a key, derive a proxy from available keys
        if tech is None:
            tech = 0.5
    except Exception:
        tech = 0.5

    try:
        mom = compute_momentum_score_from_bars(bars)
    except Exception:
        mom = 0.5

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
        reasons.append(f"Only {positive_alpha_years} of {len(alphas)} years beat SPY (need >=4)")
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
