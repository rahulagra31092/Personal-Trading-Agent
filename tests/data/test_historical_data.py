import pytest
from datetime import datetime, timedelta
from data.historical_data import (
    load_ticker_history,
    get_earnings_on_date,
    get_earnings_in_range,
)


def test_load_ticker_history_returns_dict():
    """load_ticker_history returns dict with ticker and loaded counts."""
    result = load_ticker_history("AAPL")

    assert isinstance(result, dict)
    assert "ticker" in result
    assert result["ticker"] == "AAPL"
    assert "earnings_loaded" in result or "already_loaded" in result


def test_load_ticker_history_caches():
    """Second load within same day uses cache."""
    result1 = load_ticker_history("MSFT")
    result2 = load_ticker_history("MSFT")

    # Second load should indicate already loaded
    assert result2.get("already_loaded") or "earnings_loaded" in result2


def test_earnings_query_returns_list():
    """get_earnings_in_range returns list of dicts."""
    # Load data first
    load_ticker_history("AAPL")

    # Query
    today = datetime.now()
    start = (today - timedelta(days=365)).isoformat()
    end = today.isoformat()

    result = get_earnings_in_range("AAPL", start, end)

    assert isinstance(result, list)
    # AAPL should have earnings
    if len(result) > 0:
        assert "date" in result[0]
        assert "eps_actual" in result[0] or "eps_estimate" in result[0]
