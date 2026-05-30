import numpy as np
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
