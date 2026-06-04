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


def test_run_walkforward_includes_survivorship_note():
    tickers = [f"T{i}" for i in range(5)]
    fetch = _multi_year_fetch([2019, 2020, 2021])
    results = run_walkforward(tickers, years=[2019, 2020, 2021], fetch_fn=fetch)
    assert "survivorship_note" in results


def test_run_walkforward_year_skips_tickers_with_no_scoring_data():
    """Tickers with no pre-period data should be excluded from portfolio entirely."""
    # T0 has data, T1 has NO scoring data (IPO after scoring period)
    def fetch(ticker, start, end):
        if ticker == "T0":
            return _bars(300, trend=0.002)
        if ticker == "SPY":
            return _bars(252, trend=0.0004)
        return []  # T1 has no data
    result = run_walkforward_year(["T0", "T1"], measurement_year=2023, fetch_fn=fetch)
    # T1 gets score 0.5 (below threshold) → not in portfolio
    # T0 with strong trend should be selected
    assert result["portfolio_size"] <= 1  # only T0 (or 0 if T0 return also missing)


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
