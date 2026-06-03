import numpy as np
import pytest
import pandas as pd
from quant.indicators import (
    compute_indicators,
    _rsi_score,
    _macd_score,
    _volume_score,
    _high52_score,
    _rs_score,
    _atr_modifier,
)


def _make_bars(n: int, start_price: float = 100.0, trend: float = 0.0, seed: int = 42) -> list[dict]:
    rng = np.random.default_rng(seed)
    price = start_price
    bars = []
    for i in range(n):
        price = price * (1 + trend + rng.normal(0, 0.01))
        high = price * (1 + abs(rng.normal(0, 0.005)))
        low = price * (1 - abs(rng.normal(0, 0.005)))
        bars.append({
            "t": 1700000000000 + i * 86400000,
            "o": price * 0.999,
            "h": high,
            "l": low,
            "c": price,
            "v": int(1_000_000 + rng.integers(-100_000, 100_000)),
        })
    return bars


# ---------------------------------------------------------------------------
# compute_indicators — structural / existing tests
# ---------------------------------------------------------------------------

def test_compute_indicators_returns_required_keys():
    result = compute_indicators(_make_bars(50))
    for key in ("rsi", "macd_bullish", "bb_position", "ema_trend", "atr_stop", "volume_confirmed", "technical_score"):
        assert key in result


def test_technical_score_bounded():
    assert 0.0 <= compute_indicators(_make_bars(60))["technical_score"] <= 1.0


def test_rsi_bounded():
    rsi = compute_indicators(_make_bars(60))["rsi"]
    assert 0.0 <= rsi <= 100.0


def test_too_few_bars_raises():
    with pytest.raises(ValueError, match="at least 20 bars"):
        compute_indicators(_make_bars(10))


def test_atr_stop_below_current_price():
    bars = _make_bars(60, start_price=100.0)
    result = compute_indicators(bars)
    assert result["atr_stop"] < bars[-1]["c"]


def test_volume_confirmed_is_bool():
    assert isinstance(compute_indicators(_make_bars(60))["volume_confirmed"], bool)


def test_bb_position_bounded():
    assert 0.0 <= compute_indicators(_make_bars(60))["bb_position"] <= 1.0


def test_minimum_bars_boundary():
    result = compute_indicators(_make_bars(20))
    assert "technical_score" in result
    assert 0.0 <= result["rsi"] <= 100.0
    assert 0.0 <= result["technical_score"] <= 1.0


def test_flat_price_raises_or_returns_half():
    bars = [{"t": i, "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "v": 1_000_000}
            for i in range(30)]
    try:
        result = compute_indicators(bars)
        assert result["bb_position"] == 0.5
    except ValueError:
        pass  # NaN guard triggered — acceptable


def test_monotone_uptrend_no_nan():
    bars = _make_bars(30, trend=0.01, seed=1)
    result = compute_indicators(bars)
    assert not (result["rsi"] != result["rsi"])  # NaN check: NaN != NaN is True


# ---------------------------------------------------------------------------
# compute_indicators — new behaviour
# ---------------------------------------------------------------------------

def test_uptrend_scores_higher_than_downtrend():
    up = compute_indicators(_make_bars(60, trend=0.005, seed=10))["technical_score"]
    down = compute_indicators(_make_bars(60, trend=-0.005, seed=10))["technical_score"]
    assert up > down


def test_spy_return_param_accepted():
    bars = _make_bars(60)
    result_no_spy = compute_indicators(bars)
    result_spy = compute_indicators(bars, spy_return_3m=0.05)
    assert 0.0 <= result_spy["technical_score"] <= 1.0
    # Both paths return same dict keys
    assert set(result_no_spy.keys()) == set(result_spy.keys())


def test_outperforming_spy_boosts_score():
    bars = _make_bars(100, trend=0.005, seed=5)
    spy_same = compute_indicators(bars, spy_return_3m=0.0)
    spy_lagging = compute_indicators(bars, spy_return_3m=0.20)   # SPY up 20%, stock up less
    assert spy_same["technical_score"] >= spy_lagging["technical_score"]


# ---------------------------------------------------------------------------
# _rsi_score
# ---------------------------------------------------------------------------

def test_rsi_score_sweet_spot():
    assert _rsi_score(65.0) == 1.0


def test_rsi_score_exhaustion():
    assert _rsi_score(82.0) == pytest.approx(0.3)


def test_rsi_score_neutral():
    assert _rsi_score(50.0) == pytest.approx(0.5)


def test_rsi_score_weak():
    assert _rsi_score(38.0) == pytest.approx(0.15)


def test_rsi_score_bearish():
    assert _rsi_score(25.0) == 0.0


def test_rsi_score_boundary_55():
    assert _rsi_score(55.0) == 1.0


def test_rsi_score_boundary_45():
    assert _rsi_score(45.0) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# _macd_score
# ---------------------------------------------------------------------------

def test_macd_score_positive_histogram():
    score = _macd_score(2.0, 100.0)   # +2% histogram → score = 1.0
    assert score == pytest.approx(1.0)


def test_macd_score_zero_histogram():
    score = _macd_score(0.0, 100.0)
    assert score == pytest.approx(0.5)


def test_macd_score_negative_histogram():
    score = _macd_score(-2.0, 100.0)  # -2% histogram → score = 0.0
    assert score == pytest.approx(0.0)


def test_macd_score_bounded():
    assert 0.0 <= _macd_score(100.0, 50.0) <= 1.0
    assert 0.0 <= _macd_score(-100.0, 50.0) <= 1.0


def test_macd_score_zero_price_returns_half():
    assert _macd_score(1.0, 0.0) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# _volume_score
# ---------------------------------------------------------------------------

def test_volume_score_double_average():
    assert _volume_score(2_000_000, 1_000_000) == pytest.approx(1.0)


def test_volume_score_at_average():
    assert _volume_score(1_000_000, 1_000_000) == pytest.approx(0.5)


def test_volume_score_zero_volume():
    assert _volume_score(0, 1_000_000) == pytest.approx(0.0)


def test_volume_score_bounded():
    assert 0.0 <= _volume_score(5_000_000, 1_000_000) <= 1.0
    assert 0.0 <= _volume_score(100, 1_000_000) <= 1.0


def test_volume_score_zero_avg_returns_half():
    assert _volume_score(1_000_000, 0) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# _high52_score
# ---------------------------------------------------------------------------

def _make_high_series(n: int, peak_at: int, peak_val: float, base: float = 80.0) -> pd.Series:
    vals = [base] * n
    vals[peak_at] = peak_val
    return pd.Series(vals, dtype=float)


def test_high52_at_peak():
    highs = _make_high_series(30, 20, 100.0)
    score = _high52_score(highs, 100.0)
    assert score == pytest.approx(1.0)


def test_high52_at_60_pct():
    highs = _make_high_series(30, 20, 100.0)
    score = _high52_score(highs, 60.0)
    assert score == pytest.approx(0.0)


def test_high52_midpoint():
    highs = _make_high_series(30, 20, 100.0)
    score = _high52_score(highs, 80.0)   # 80% of peak → (0.8 - 0.6) / 0.4 = 0.5
    assert score == pytest.approx(0.5)


def test_high52_bounded():
    highs = pd.Series([100.0] * 30, dtype=float)
    assert 0.0 <= _high52_score(highs, 50.0) <= 1.0
    assert 0.0 <= _high52_score(highs, 110.0) <= 1.0


def test_high52_uses_max_252_bars():
    # Series longer than 252 — peak in older history should not count
    old_bars = [50.0] * 300     # old peak at 50
    recent = [80.0] * 252       # recent peak at 80; latest close at 80
    highs = pd.Series(old_bars + recent, dtype=float)
    score = _high52_score(highs, 80.0)
    assert score == pytest.approx(1.0)   # 80/80 = 100% of 252-bar high


# ---------------------------------------------------------------------------
# _rs_score
# ---------------------------------------------------------------------------

def test_rs_score_strong_outperformance():
    assert _rs_score(0.20) == pytest.approx(1.0)


def test_rs_score_neutral():
    assert _rs_score(0.0) == pytest.approx(0.5)


def test_rs_score_underperformance():
    assert _rs_score(-0.20) == pytest.approx(0.0)


def test_rs_score_bounded():
    assert 0.0 <= _rs_score(1.0) <= 1.0
    assert 0.0 <= _rs_score(-1.0) <= 1.0


# ---------------------------------------------------------------------------
# _atr_modifier
# ---------------------------------------------------------------------------

def test_atr_modifier_tightening_bullish():
    # atr5 < atr14 * 0.85 AND bullish → 1.05
    assert _atr_modifier(0.80, 1.0, "bullish") == pytest.approx(1.05)


def test_atr_modifier_expanding_bullish():
    # atr5 > atr14 * 1.15 AND bullish → 0.97
    assert _atr_modifier(1.20, 1.0, "bullish") == pytest.approx(0.97)


def test_atr_modifier_expanding_bearish():
    # atr5 > atr14 * 1.15 AND bearish → 0.95
    assert _atr_modifier(1.20, 1.0, "bearish") == pytest.approx(0.95)


def test_atr_modifier_neutral():
    assert _atr_modifier(1.0, 1.0, "neutral") == pytest.approx(1.0)


def test_atr_modifier_zero_atr14_returns_one():
    assert _atr_modifier(0.5, 0.0, "bullish") == pytest.approx(1.0)
