import math
from unittest.mock import patch
import numpy as np
import pandas as pd
import pytest

from quant.momentum import (
    compute_momentum_score,
    compute_momentum_score_from_bars,
    _trend_r2,
    _accel_bonus,
)


def _make_bars(n: int, start_price: float, end_price: float) -> list[dict]:
    """Create n bars with linear price from start to end."""
    prices = [start_price + (end_price - start_price) * i / max(n - 1, 1) for i in range(n)]
    return [{"c": p, "h": p * 1.01, "l": p * 0.99, "v": 1_000_000} for p in prices]


def _make_hist_df(n: int, price_1m: float, price_12m: float) -> pd.DataFrame:
    """Create a DataFrame with controlled price_12m and price_1m."""
    prices = [100.0] * n
    prices[-252] = price_12m
    prices[-21] = price_1m
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({"Close": prices, "Open": prices, "High": prices,
                         "Low": prices, "Volume": [1_000_000] * n}, index=dates)


# ---------------------------------------------------------------------------
# compute_momentum_score_from_bars — existing tests
# ---------------------------------------------------------------------------

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
    bars = _make_bars(50, 100.0, 110.0)  # < 84 bars (3M + skip minimum)
    assert compute_momentum_score_from_bars(bars) == 0.5


def test_momentum_from_bars_score_bounded():
    bars = _make_bars(260, 10.0, 500.0)  # extreme uptrend
    score = compute_momentum_score_from_bars(bars)
    assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# compute_momentum_score (ticker-based) — existing tests
# ---------------------------------------------------------------------------

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
    short_hist = short_hist.iloc[:50]  # trim to < 84 bars (3M + skip minimum)
    with patch("quant.momentum.get_cache", return_value=None), \
         patch("quant.momentum.set_cache"), \
         patch("quant.momentum.yf.download", return_value=short_hist):
        score = compute_momentum_score("AAPL")
    assert score == 0.5


# ---------------------------------------------------------------------------
# _trend_r2 — trend consistency
# ---------------------------------------------------------------------------

def test_trend_r2_exponential_near_one():
    # Pure exponential growth = perfect linear log-price series → R² ≈ 1.0
    closes = [100.0 * (1.001 ** i) for i in range(260)]
    r2 = _trend_r2(closes)
    assert r2 > 0.99


def test_trend_r2_flat_returns_half():
    # Constant price: log-prices are constant → den_y = 0 → fallback 0.5
    closes = [100.0] * 260
    r2 = _trend_r2(closes)
    assert r2 == pytest.approx(0.5)


def test_trend_r2_too_short_returns_half():
    closes = [100.0 + i for i in range(10)]
    assert _trend_r2(closes) == pytest.approx(0.5)


def test_trend_r2_bounded():
    rng = np.random.default_rng(3)
    closes = [max(1.0, 100.0 + float(rng.normal(0, 20))) for _ in range(260)]
    r2 = _trend_r2(closes)
    assert 0.0 <= r2 <= 1.0


def test_trend_r2_downtrend_also_high():
    # A smooth downtrend has equally high R² — quality is direction-agnostic
    closes = [200.0 * (0.999 ** i) for i in range(260)]
    r2 = _trend_r2(closes)
    assert r2 > 0.99


# ---------------------------------------------------------------------------
# _accel_bonus — momentum acceleration
# ---------------------------------------------------------------------------

def test_accel_bonus_accelerating_positive():
    # 3M rate >> 6M rate → momentum building → positive bonus
    bonus = _accel_bonus(r3m=0.15, r6m=0.05)
    assert bonus > 0.0


def test_accel_bonus_decelerating_negative():
    # 3M rate << 6M rate → momentum fading → negative bonus
    bonus = _accel_bonus(r3m=0.05, r6m=0.15)
    assert bonus < 0.0


def test_accel_bonus_equal_annualized_rates_zero():
    # r3m * 4 == r6m * 2 → same annualized pace → no bonus
    # r3m = 0.05 → annualized 0.20; r6m = 0.10 → annualized 0.20
    bonus = _accel_bonus(r3m=0.05, r6m=0.10)
    assert bonus == pytest.approx(0.0, abs=1e-9)


def test_accel_bonus_bounded():
    assert _accel_bonus(r3m=0.50, r6m=-0.50) == pytest.approx(0.05)
    assert _accel_bonus(r3m=-0.50, r6m=0.50) == pytest.approx(-0.05)


def test_accel_bonus_none_r3m_returns_zero():
    assert _accel_bonus(None, 0.10) == 0.0


def test_accel_bonus_none_r6m_returns_zero():
    assert _accel_bonus(0.10, None) == 0.0


# ---------------------------------------------------------------------------
# Integration: quality and acceleration affect the composite score
# ---------------------------------------------------------------------------

def test_smooth_uptrend_scores_higher_than_flat():
    # Deterministic: smooth exponential uptrend must score above neutral 0.5
    smooth = [100.0 * (1.001 ** i) for i in range(260)]
    flat = [100.0] * 260
    smooth_bars = [{"c": p, "h": p * 1.005, "l": p * 0.995, "v": 1_000_000} for p in smooth]
    flat_bars = [{"c": p, "h": p * 1.005, "l": p * 0.995, "v": 1_000_000} for p in flat]
    assert compute_momentum_score_from_bars(smooth_bars) > compute_momentum_score_from_bars(flat_bars)


def test_accelerating_momentum_outscores_decelerating():
    """
    Two series with same 12M return but different 3M momentum:
    accelerating = strong recent move; decelerating = strong early move, weak recent.
    """
    n = 260
    # Accelerating: slow first half, fast second half
    half = n // 2
    accel = [100.0 + i * 0.05 for i in range(half)] + \
            [100.0 + half * 0.05 + i * 0.20 for i in range(n - half)]
    # Decelerating: fast first half, slow second half
    decel = [100.0 + i * 0.20 for i in range(half)] + \
            [100.0 + half * 0.20 + i * 0.05 for i in range(n - half)]

    accel_bars = [{"c": p, "h": p * 1.005, "l": p * 0.995, "v": 1_000_000} for p in accel]
    decel_bars = [{"c": p, "h": p * 1.005, "l": p * 0.995, "v": 1_000_000} for p in decel]

    accel_score = compute_momentum_score_from_bars(accel_bars)
    decel_score = compute_momentum_score_from_bars(decel_bars)
    assert accel_score > decel_score
