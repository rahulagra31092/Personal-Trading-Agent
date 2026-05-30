import numpy as np
import pytest
from quant.indicators import compute_indicators


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
