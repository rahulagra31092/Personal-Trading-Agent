import pytest
from quant.forecast import compute_arima_score, compute_garch_volatility


def _prices(n: int, start: float = 100.0, daily_return: float = 0.001) -> list[float]:
    price = start
    result = []
    for _ in range(n):
        price *= (1 + daily_return)
        result.append(price)
    return result


def test_arima_returns_required_keys():
    result = compute_arima_score(_prices(50))
    for key in ("arima_score", "direction", "probability"):
        assert key in result


def test_arima_score_bounded():
    assert 0.0 <= compute_arima_score(_prices(50))["arima_score"] <= 1.0


def test_arima_direction_valid():
    assert compute_arima_score(_prices(50))["direction"] in ("up", "down", "flat")


def test_arima_too_few_prices_returns_neutral():
    result = compute_arima_score([100.0, 101.0, 99.0])
    assert result["arima_score"] == 0.5
    assert result["direction"] == "flat"


def test_garch_returns_required_keys():
    result = compute_garch_volatility(_prices(60))
    for key in ("daily_vol", "vol_regime", "vol_scalar"):
        assert key in result


def test_garch_vol_regime_valid():
    assert compute_garch_volatility(_prices(60))["vol_regime"] in ("low", "medium", "high")


def test_garch_vol_scalar_bounded():
    assert 0.0 <= compute_garch_volatility(_prices(60))["vol_scalar"] <= 1.0


def test_garch_too_few_prices_returns_fallback():
    result = compute_garch_volatility([100.0, 101.0])
    assert result["daily_vol"] == 0.02
    assert result["vol_regime"] == "medium"
