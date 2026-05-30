import numpy as np
import pytest
from quant.backtest import run_backtest


def _trending_bars(n: int, trend: float = 0.002, seed: int = 42) -> list[dict]:
    rng = np.random.default_rng(seed)
    price = 100.0
    bars = []
    for i in range(n):
        price = price * (1 + trend + rng.normal(0, 0.008))
        bars.append({
            "t": 1700000000000 + i * 86400000,
            "o": price * 0.999,
            "h": price * 1.004,
            "l": price * 0.996,
            "c": price,
            "v": 1_500_000,
        })
    return bars


def test_returns_required_keys():
    result = run_backtest("AMZN", _trending_bars(80))
    for key in ("ticker", "total_signals", "win_rate", "correct_signals", "avg_return_pct"):
        assert key in result


def test_ticker_preserved_in_result():
    assert run_backtest("TSLA", _trending_bars(80))["ticker"] == "TSLA"


def test_win_rate_bounded():
    result = run_backtest("AMZN", _trending_bars(100))
    assert 0.0 <= result["win_rate"] <= 1.0


def test_too_few_bars_returns_zero_signals():
    result = run_backtest("AMZN", _trending_bars(20))
    assert result["total_signals"] == 0
    assert result["win_rate"] == 0.0


def test_correct_signals_le_total():
    result = run_backtest("AMZN", _trending_bars(100))
    assert result["correct_signals"] <= result["total_signals"]
