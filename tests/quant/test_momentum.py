import math
from unittest.mock import patch
import pandas as pd
import pytest

from quant.momentum import compute_momentum_score, compute_momentum_score_from_bars


def _make_bars(n: int, start_price: float, end_price: float) -> list[dict]:
    """Create n bars with linear price from start to end."""
    prices = [start_price + (end_price - start_price) * i / max(n - 1, 1) for i in range(n)]
    return [{"c": p, "h": p * 1.01, "l": p * 0.99, "v": 1_000_000} for p in prices]


def _make_hist_df(n: int, price_1m: float, price_12m: float) -> pd.DataFrame:
    """Create a DataFrame with controlled price_12m and price_1m."""
    # n = 260 bars total; bar[-252] = price_12m, bar[-21] = price_1m, rest interpolated
    prices = [100.0] * n
    prices[-252] = price_12m
    prices[-21] = price_1m
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({"Close": prices, "Open": prices, "High": prices,
                         "Low": prices, "Volume": [1_000_000] * n}, index=dates)


# --- compute_momentum_score_from_bars ---

def test_momentum_from_bars_positive_trend():
    bars = _make_bars(260, 100.0, 130.0)
    score = compute_momentum_score_from_bars(bars)
    assert score > 0.5, "Uptrend should score above 0.5"


def test_momentum_from_bars_negative_trend():
    bars = _make_bars(260, 130.0, 100.0)
    score = compute_momentum_score_from_bars(bars)
    assert score < 0.5, "Downtrend should score below 0.5"


def test_momentum_from_bars_flat_near_neutral():
    bars = _make_bars(260, 100.0, 100.0)
    score = compute_momentum_score_from_bars(bars)
    assert abs(score - 0.5) < 0.05, "Flat price should score near 0.5"


def test_momentum_from_bars_insufficient_data():
    bars = _make_bars(150, 100.0, 110.0)  # < 200 bars
    assert compute_momentum_score_from_bars(bars) == 0.5


def test_momentum_from_bars_score_bounded():
    bars = _make_bars(260, 10.0, 500.0)  # extreme uptrend
    score = compute_momentum_score_from_bars(bars)
    assert 0.0 <= score <= 1.0


# --- compute_momentum_score (ticker-based) ---

def test_momentum_score_cache_hit_skips_download():
    with patch("quant.momentum.get_cache", return_value=0.72), \
         patch("quant.momentum.yf.download") as mock_dl:
        result = compute_momentum_score("AAPL")
    assert result == 0.72
    mock_dl.assert_not_called()


def test_momentum_score_positive_momentum():
    hist = _make_hist_df(260, price_1m=130.0, price_12m=100.0)
    with patch("quant.momentum.get_cache", return_value=None), \
         patch("quant.momentum.set_cache"), \
         patch("quant.momentum.yf.download", return_value=hist):
        score = compute_momentum_score("AAPL")
    assert score > 0.5


def test_momentum_score_negative_momentum():
    hist = _make_hist_df(260, price_1m=80.0, price_12m=100.0)
    with patch("quant.momentum.get_cache", return_value=None), \
         patch("quant.momentum.set_cache"), \
         patch("quant.momentum.yf.download", return_value=hist):
        score = compute_momentum_score("AAPL")
    assert score < 0.5


def test_momentum_score_exception_returns_neutral():
    with patch("quant.momentum.get_cache", return_value=None), \
         patch("quant.momentum.yf.download", side_effect=RuntimeError("network")):
        score = compute_momentum_score("AAPL")
    assert score == 0.5


def test_momentum_score_insufficient_bars_returns_neutral():
    short_hist = _make_hist_df(260, price_1m=110.0, price_12m=100.0)
    short_hist = short_hist.iloc[:150]  # trim to < 200 bars
    with patch("quant.momentum.get_cache", return_value=None), \
         patch("quant.momentum.set_cache"), \
         patch("quant.momentum.yf.download", return_value=short_hist):
        score = compute_momentum_score("AAPL")
    assert score == 0.5
