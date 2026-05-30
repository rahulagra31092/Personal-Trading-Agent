from unittest.mock import patch
import numpy as np
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


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


_FAKE_BARS = _make_bars(100)

_FAKE_IND = {
    "technical_score": 0.60,
    "rsi": 48.0,
    "ema_trend": "bullish",
    "atr_stop": 95.0,
    "bb_position": 0.5,
    "macd_bullish": True,
    "volume_confirmed": True,
}
_FAKE_FCAST = {"arima_score": 0.55, "direction": "up", "probability": 0.6}
_FAKE_GARCH = {"daily_vol": 0.018, "vol_regime": "low", "vol_scalar": 0.8}
_FAKE_MC = {
    "base_target": 101.0,
    "lower_80": 97.0,
    "upper_80": 105.0,
    "downside_pct": -0.03,
    "upside_pct": 0.05,
    "prob_success": 0.54,
    "daily_vol_expected": 0.018,
}


def test_analyze_returns_required_keys():
    with patch("api.analyze.get_daily_bars", return_value=_FAKE_BARS), \
         patch("api.analyze.compute_indicators", return_value=_FAKE_IND), \
         patch("api.analyze.compute_arima_score", return_value=_FAKE_FCAST), \
         patch("api.analyze.compute_garch_volatility", return_value=_FAKE_GARCH), \
         patch("api.analyze.run_monte_carlo", return_value=_FAKE_MC), \
         patch("api.analyze.compute_congress_score", return_value=0.5), \
         patch("api.analyze.compute_news_score", return_value=0.5), \
         patch("api.analyze.compute_earnings_score", return_value=0.5):
        resp = client.get("/analyze/AAPL")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("ticker", "signal", "confidence", "current_price", "atr_stop", "vol_regime"):
        assert key in data


def test_analyze_excluded_ticker_returns_400():
    resp = client.get("/analyze/FUBO")
    assert resp.status_code == 400


def test_analyze_signal_has_label():
    with patch("api.analyze.get_daily_bars", return_value=_FAKE_BARS), \
         patch("api.analyze.compute_indicators", return_value=_FAKE_IND), \
         patch("api.analyze.compute_arima_score", return_value=_FAKE_FCAST), \
         patch("api.analyze.compute_garch_volatility", return_value=_FAKE_GARCH), \
         patch("api.analyze.run_monte_carlo", return_value=_FAKE_MC), \
         patch("api.analyze.compute_congress_score", return_value=0.5), \
         patch("api.analyze.compute_news_score", return_value=0.5), \
         patch("api.analyze.compute_earnings_score", return_value=0.5):
        resp = client.get("/analyze/MSFT")
    assert resp.json()["signal"]["label"] in ("BUY", "WATCH", "AVOID")


def test_analyze_confidence_has_prob_success():
    with patch("api.analyze.get_daily_bars", return_value=_FAKE_BARS), \
         patch("api.analyze.compute_indicators", return_value=_FAKE_IND), \
         patch("api.analyze.compute_arima_score", return_value=_FAKE_FCAST), \
         patch("api.analyze.compute_garch_volatility", return_value=_FAKE_GARCH), \
         patch("api.analyze.run_monte_carlo", return_value=_FAKE_MC), \
         patch("api.analyze.compute_congress_score", return_value=0.5), \
         patch("api.analyze.compute_news_score", return_value=0.5), \
         patch("api.analyze.compute_earnings_score", return_value=0.5):
        resp = client.get("/analyze/NVDA")
    conf = resp.json()["confidence"]
    assert "prob_success" in conf
    assert 0.0 <= conf["prob_success"] <= 1.0


def test_analyze_insufficient_history_returns_400():
    short_bars = [
        {
            "t": 1700000000000 + i * 86400000,
            "o": 100.0,
            "h": 105.0,
            "l": 98.0,
            "c": 102.0 + i * 0.1,
            "v": 1_000_000,
        }
        for i in range(30)
    ]
    with patch("api.analyze.get_daily_bars", return_value=short_bars):
        resp = client.get("/analyze/TSLA")
    assert resp.status_code == 400
    assert "Insufficient" in resp.json()["detail"]


def test_analyze_system_error_returns_500():
    with patch("api.analyze.get_daily_bars", side_effect=RuntimeError("polygon down")):
        resp = client.get("/analyze/TSLA")
    assert resp.status_code == 500
