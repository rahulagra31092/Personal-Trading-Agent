from unittest.mock import patch
import pytest
from quant.portfolio_risk import get_ticker_beta, compute_portfolio_beta
from data.cache import get_cache, set_cache


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear relevant cache entries before each test."""
    import sqlite3
    from pathlib import Path
    cache_db = Path(__file__).parent.parent.parent / "data" / "cache.db"
    if cache_db.exists():
        with sqlite3.connect(cache_db) as conn:
            conn.execute("DELETE FROM cache WHERE key LIKE 'beta:%'")
    yield


def test_get_ticker_beta_returns_float():
    with patch("quant.portfolio_risk.yf.Ticker") as mock_t:
        mock_t.return_value.info = {"beta": 1.45}
        beta = get_ticker_beta("NVDA")
    assert isinstance(beta, float)
    assert beta == pytest.approx(1.45)


def test_get_ticker_beta_defaults_to_one_on_missing_data():
    with patch("quant.portfolio_risk.yf.Ticker") as mock_t:
        mock_t.return_value.info = {}
        beta = get_ticker_beta("UNKNOWN")
    assert beta == pytest.approx(1.0)


def test_get_ticker_beta_defaults_to_one_on_exception():
    with patch("quant.portfolio_risk.yf.Ticker", side_effect=RuntimeError("network")):
        beta = get_ticker_beta("NVDA")
    assert beta == pytest.approx(1.0)


def test_get_ticker_beta_clamps_extreme_values():
    with patch("quant.portfolio_risk.yf.Ticker") as mock_t:
        mock_t.return_value.info = {"beta": 99.0}
        beta = get_ticker_beta("MEME")
    assert beta <= 5.0


def test_compute_portfolio_beta_empty_list():
    assert compute_portfolio_beta([]) == pytest.approx(1.0)


def test_compute_portfolio_beta_equal_weights_average():
    with patch("quant.portfolio_risk.get_ticker_beta", side_effect=[1.2, 0.8]):
        beta = compute_portfolio_beta(["NVDA", "KO"])
    assert beta == pytest.approx(1.0)


def test_compute_portfolio_beta_high_beta_portfolio():
    with patch("quant.portfolio_risk.get_ticker_beta", return_value=1.6):
        beta = compute_portfolio_beta(["NVDA", "AMD", "META"])
    assert beta > 1.25


def test_compute_portfolio_beta_uses_cache():
    from data.cache import get_cache, set_cache
    set_cache("beta:CACHED", {"value": 1.35}, ttl_seconds=86400)
    beta = get_ticker_beta("CACHED")
    assert beta == pytest.approx(1.35)
