from unittest.mock import patch
import pandas as pd
import pytest

from quant.regime import get_market_regime


def _vix_hist(vix_value: float) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=3, freq="B")
    return pd.DataFrame(
        {"Close": [vix_value] * 3, "Open": [vix_value] * 3,
         "High": [vix_value] * 3, "Low": [vix_value] * 3,
         "Volume": [0] * 3},
        index=dates,
    )


def test_low_vix_returns_low_vol_regime():
    with patch("quant.regime.get_cache", return_value=None), \
         patch("quant.regime.set_cache"), \
         patch("quant.regime.yf.download", return_value=_vix_hist(12.5)):
        r = get_market_regime()
    assert r["regime"] == "low_vol"
    assert r["position_factor"] == 1.0
    assert r["max_positions"] == 70


def test_normal_vix_returns_normal_regime():
    with patch("quant.regime.get_cache", return_value=None), \
         patch("quant.regime.set_cache"), \
         patch("quant.regime.yf.download", return_value=_vix_hist(18.0)):
        r = get_market_regime()
    assert r["regime"] == "normal"


def test_elevated_vix_reduces_positions():
    with patch("quant.regime.get_cache", return_value=None), \
         patch("quant.regime.set_cache"), \
         patch("quant.regime.yf.download", return_value=_vix_hist(22.0)):
        r = get_market_regime()
    assert r["regime"] == "elevated"
    assert r["position_factor"] == 0.85
    assert r["max_positions"] == 60


def test_high_vix_returns_high_regime():
    with patch("quant.regime.get_cache", return_value=None), \
         patch("quant.regime.set_cache"), \
         patch("quant.regime.yf.download", return_value=_vix_hist(27.0)):
        r = get_market_regime()
    assert r["regime"] == "high"
    assert r["position_factor"] == 0.70


def test_crisis_vix_returns_crisis_regime():
    with patch("quant.regime.get_cache", return_value=None), \
         patch("quant.regime.set_cache"), \
         patch("quant.regime.yf.download", return_value=_vix_hist(35.0)):
        r = get_market_regime()
    assert r["regime"] == "crisis"
    assert r["position_factor"] == 0.50
    assert r["max_positions"] == 35


def test_empty_vix_returns_fallback():
    with patch("quant.regime.get_cache", return_value=None), \
         patch("quant.regime.yf.download", return_value=pd.DataFrame()):
        r = get_market_regime()
    assert r["regime"] == "normal"
    assert r["vix"] == 20.0


def test_exception_returns_fallback():
    with patch("quant.regime.get_cache", return_value=None), \
         patch("quant.regime.yf.download", side_effect=RuntimeError("network")):
        r = get_market_regime()
    assert r["regime"] == "normal"


def test_cache_hit_skips_download():
    cached = {"regime": "elevated", "vix": 23.0, "position_factor": 0.85, "max_positions": 60}
    with patch("quant.regime.get_cache", return_value=cached), \
         patch("quant.regime.yf.download") as mock_dl:
        r = get_market_regime()
    assert r["regime"] == "elevated"
    mock_dl.assert_not_called()
