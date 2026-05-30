import numpy as np
from unittest.mock import patch
from quant.backtest import run_backtest

# Pre-computed expected values with seed=42, trend=0.002, hold_days=5, all BUY signals
EXPECTED_CAGR = 3.5772
EXPECTED_SHARPE = 3.1336


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


def test_lookahead_safe():
    bars = _trending_bars(40)
    call_sizes = []

    import quant.backtest as bt
    _real = bt.compute_indicators
    def spy(history):
        call_sizes.append(len(history))
        return _real(history)
    bt.compute_indicators = spy
    try:
        run_backtest("TEST", bars, min_bars=30, hold_days=5)
    finally:
        bt.compute_indicators = _real

    # At i=30 (first iteration), history = bars[:30], length must be 30
    # If bars[:i+1] were used, call_sizes[0] would be 31
    assert call_sizes, "No iterations ran — check min_bars/hold_days"
    assert call_sizes[0] == 30


def test_returns_new_metric_keys():
    result = run_backtest("AMZN", _trending_bars(80))
    for key in ("sharpe_ratio", "max_drawdown", "cagr"):
        assert key in result


def test_max_drawdown_bounded():
    result = run_backtest("AMZN", _trending_bars(100))
    assert 0.0 <= result["max_drawdown"] <= 1.0


def test_zero_signals_new_metrics_are_zero():
    result = run_backtest("AMZN", _trending_bars(20))
    assert result["sharpe_ratio"] == 0.0
    assert result["max_drawdown"] == 0.0
    assert result["cagr"] == 0.0


def test_sharpe_is_float():
    result = run_backtest("AMZN", _trending_bars(100))
    assert isinstance(result["sharpe_ratio"], float)


def _mock_signal(technical_score, arima_score, **kwargs):
    """Mock signal generator that always returns BUY for pinned tests."""
    return {
        "composite_score": 0.8,
        "label": "BUY",
        "layer_scores": {
            "technical": 0.8,
            "arima": 0.8,
            "smart_money": 0.5,
            "news_reaction": 0.5,
            "earnings": 0.5,
        },
    }


def test_cagr_known_value():
    import quant.backtest as bt
    with patch.object(bt, "compute_signal", side_effect=_mock_signal):
        result = run_backtest("AMZN", _trending_bars(100))
        # Pre-computed from seed=42, trend=0.002, hold_days=5, all BUY signals
        assert abs(result["cagr"] - EXPECTED_CAGR) < 0.01, f"got {result['cagr']}"


def test_sharpe_known_value():
    import quant.backtest as bt
    with patch.object(bt, "compute_signal", side_effect=_mock_signal):
        result = run_backtest("AMZN", _trending_bars(100))
        # Pre-computed from seed=42, trend=0.002, hold_days=5, all BUY signals
        assert abs(result["sharpe_ratio"] - EXPECTED_SHARPE) < 0.01, f"got {result['sharpe_ratio']}"


def test_max_drawdown_capped_at_one_on_catastrophic_loss():
    """A sequence leading to large negative equity must not push max_drawdown above 1.0"""
    import quant.backtest as bt

    # Craft bars where prices crash dramatically
    crash_bars = []
    price = 100.0
    for i in range(50):
        if i == 35:
            price = 0.01  # crash to near-zero
        crash_bars.append({
            "t": 1700000000000 + i * 86400000,
            "o": price * 0.999,
            "h": price * 1.004,
            "l": price * 0.996,
            "c": price,
            "v": 1_500_000,
        })

    result = run_backtest("TEST", crash_bars)
    assert result["max_drawdown"] <= 1.0, f"max_drawdown exceeded 1.0: {result['max_drawdown']}"
