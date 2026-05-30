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


def test_analyze_returns_required_keys():
    with patch("api.analyze.get_daily_bars", return_value=_FAKE_BARS), \
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
         patch("api.analyze.compute_congress_score", return_value=0.5), \
         patch("api.analyze.compute_news_score", return_value=0.5), \
         patch("api.analyze.compute_earnings_score", return_value=0.5):
        resp = client.get("/analyze/MSFT")
    assert resp.json()["signal"]["label"] in ("BUY", "WATCH", "AVOID")


def test_analyze_confidence_has_prob_success():
    with patch("api.analyze.get_daily_bars", return_value=_FAKE_BARS), \
         patch("api.analyze.compute_congress_score", return_value=0.5), \
         patch("api.analyze.compute_news_score", return_value=0.5), \
         patch("api.analyze.compute_earnings_score", return_value=0.5):
        resp = client.get("/analyze/NVDA")
    conf = resp.json()["confidence"]
    assert "prob_success" in conf
    assert 0.0 <= conf["prob_success"] <= 1.0
