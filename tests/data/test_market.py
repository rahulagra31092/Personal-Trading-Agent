import pytest
import pandas as pd
from unittest.mock import MagicMock
from data.market import get_daily_bars, get_historical_prices, get_crypto_price

@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr("data.cache.DB_PATH", tmp_path / "test_cache.db")
    from data.cache import init_db
    init_db()

def _make_bar(close: float = 183.0, volume: int = 1_000_000):
    bar = MagicMock()
    bar.timestamp = 1_700_000_000_000
    bar.open = close - 1
    bar.high = close + 2
    bar.low = close - 2
    bar.close = close
    bar.volume = volume
    return bar

def test_get_daily_bars_returns_list(mocker):
    mocker.patch("data.market.RESTClient").return_value.list_aggs.return_value = [_make_bar()]
    result = get_daily_bars("AMZN", days=1)
    assert isinstance(result, list)
    assert result[0]["c"] == 183.0
    assert result[0]["v"] == 1_000_000

def test_get_daily_bars_caches_result(mocker):
    mock_client = mocker.patch("data.market.RESTClient").return_value
    mock_client.list_aggs.return_value = [_make_bar()]
    get_daily_bars("AMZN", days=1)
    get_daily_bars("AMZN", days=1)
    assert mock_client.list_aggs.call_count == 1

def test_excluded_ticker_raises_on_bars():
    with pytest.raises(ValueError, match="FUBO is excluded"):
        get_daily_bars("FUBO", days=5)

def test_excluded_ticker_raises_on_historical():
    with pytest.raises(ValueError, match="FUBO is excluded"):
        get_historical_prices("FUBO")

def test_get_crypto_price_returns_float(mocker):
    mock_hist = pd.DataFrame({"Close": [95_000.0]})
    mocker.patch("data.market.yf.Ticker").return_value.history.return_value = mock_hist
    assert get_crypto_price("BTC") == 95_000.0

def test_get_crypto_price_caches(mocker):
    mock_ticker = mocker.patch("data.market.yf.Ticker").return_value
    mock_ticker.history.return_value = pd.DataFrame({"Close": [50_000.0]})
    get_crypto_price("ETH")
    get_crypto_price("ETH")
    assert mock_ticker.history.call_count == 1
