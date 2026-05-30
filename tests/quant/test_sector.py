from unittest.mock import patch
import pandas as pd
import pytest

from quant.sector import (
    SECTOR_ETF_MAP,
    NARROW_SUB_SECTORS,
    get_sector_momentum,
    sector_weight_multiplier,
    apply_concentration_cap,
    _find_cluster,
)


# --- SECTOR_ETF_MAP ---

def test_sector_etf_map_has_required_keys():
    required = {"tech", "financials", "healthcare", "energy", "industrials"}
    assert required.issubset(SECTOR_ETF_MAP.keys())


def test_sector_etf_map_values_are_strings():
    for sector, etf in SECTOR_ETF_MAP.items():
        assert isinstance(etf, str) and len(etf) >= 2


# --- get_sector_momentum ---

def _make_hist(first_close: float, last_close: float) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=20, freq="B")
    closes = [first_close] + [first_close] * 18 + [last_close]
    return pd.DataFrame({"Close": closes, "Open": closes,
                         "High": closes, "Low": closes, "Volume": [1_000_000] * 20},
                        index=dates)


def test_get_sector_momentum_positive_trend():
    hist = _make_hist(100.0, 110.0)
    with patch("quant.sector.get_cache", return_value=None), \
         patch("quant.sector.set_cache"), \
         patch("quant.sector.yf.download", return_value=hist):
        result = get_sector_momentum("tech")
    assert result == pytest.approx(0.10, abs=0.001)


def test_get_sector_momentum_negative_trend():
    hist = _make_hist(100.0, 90.0)
    with patch("quant.sector.get_cache", return_value=None), \
         patch("quant.sector.set_cache"), \
         patch("quant.sector.yf.download", return_value=hist):
        result = get_sector_momentum("tech")
    assert result == pytest.approx(-0.10, abs=0.001)


def test_get_sector_momentum_unknown_sector_returns_none():
    result = get_sector_momentum("unknown_sector_xyz")
    assert result is None


def test_get_sector_momentum_cache_hit_skips_download():
    with patch("quant.sector.get_cache", return_value=0.07), \
         patch("quant.sector.yf.download") as mock_dl:
        result = get_sector_momentum("tech")
    assert result == 0.07
    mock_dl.assert_not_called()


def test_get_sector_momentum_handles_multilevel_columns():
    import pandas as pd
    dates = pd.date_range("2025-01-01", periods=20, freq="B")
    # Simulate yfinance multi-level: (field, ticker)
    arrays = [["Close"] * 20, ["XLK"] * 20]
    midx = pd.MultiIndex.from_arrays(
        [["Close", "Open", "High", "Low", "Volume"],
         ["XLK", "XLK", "XLK", "XLK", "XLK"]]
    )
    data = {("Close", "XLK"): [100.0] * 19 + [110.0],
            ("Open", "XLK"): [100.0] * 20,
            ("High", "XLK"): [101.0] * 20,
            ("Low", "XLK"): [99.0] * 20,
            ("Volume", "XLK"): [1_000_000] * 20}
    hist = pd.DataFrame(data, index=dates)
    with patch("quant.sector.get_cache", return_value=None), \
         patch("quant.sector.set_cache"), \
         patch("quant.sector.yf.download", return_value=hist):
        result = get_sector_momentum("tech")
    assert result == pytest.approx(0.10, abs=0.001)


# --- sector_weight_multiplier ---

def test_sector_weight_multiplier_strong_up_returns_105():
    with patch("quant.sector.get_sector_momentum", return_value=0.08):
        assert sector_weight_multiplier("tech") == 1.05


def test_sector_weight_multiplier_strong_down_returns_090():
    with patch("quant.sector.get_sector_momentum", return_value=-0.07):
        assert sector_weight_multiplier("tech") == 0.90


def test_sector_weight_multiplier_neutral_returns_100():
    with patch("quant.sector.get_sector_momentum", return_value=0.02):
        assert sector_weight_multiplier("tech") == 1.0


# --- apply_concentration_cap ---

def test_apply_concentration_cap_limits_cluster_to_two():
    tickers = ["KKR", "BX", "ARES", "APO"]  # all in alt_asset_managers cluster
    result = apply_concentration_cap(tickers, max_per_sub_sector=2)
    assert result == ["KKR", "BX"]  # top 2 kept, rest dropped


def test_apply_concentration_cap_preserves_non_cluster_tickers():
    tickers = ["AAPL", "KKR", "BX", "ARES", "MSFT"]
    # AAPL is in mega-cap cluster, KKR/BX/ARES in alt-asset cluster, MSFT in mega-cap
    # mega-cap: AAPL kept (1), MSFT kept (2) -> both under cap
    # alt-asset: KKR kept (1), BX kept (2), ARES dropped
    result = apply_concentration_cap(tickers, max_per_sub_sector=2)
    assert "KKR" in result
    assert "BX" in result
    assert "ARES" not in result
    assert "AAPL" in result
    assert "MSFT" in result
