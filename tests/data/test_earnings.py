import pytest
import pandas as pd
from unittest.mock import MagicMock
from datetime import date, timedelta
from data.earnings import get_earnings_calendar, days_to_earnings

@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr("data.cache.DB_PATH", tmp_path / "test_cache.db")
    from data.cache import init_db
    init_db()

def test_returns_dict_with_required_keys(mocker):
    mock_ticker = MagicMock()
    mock_ticker.info = {"forwardEps": 1.25}
    mock_ticker.calendar = pd.DataFrame(
        {"AMZN": [pd.Timestamp("2026-05-22")]}, index=["Earnings Date"]
    )
    mock_ticker.earnings_history = pd.DataFrame({"surprisePercent": [5.0, -2.0, 3.0, 8.0]})
    mocker.patch("data.earnings.yf.Ticker", return_value=mock_ticker)

    result = get_earnings_calendar("AMZN")

    assert result["eps_estimate"] == 1.25
    assert result["eps_beat_rate"] == 0.75
    assert result["next_earnings_date"] == "2026-05-22"

def test_days_to_earnings_returns_correct_count(mocker):
    future = (date.today() + timedelta(days=5)).isoformat()
    mocker.patch("data.earnings.get_earnings_calendar", return_value={
        "next_earnings_date": future, "eps_estimate": 1.0, "eps_beat_rate": 0.7,
    })
    assert days_to_earnings("AMZN") == 5

def test_days_to_earnings_none_when_no_date(mocker):
    mocker.patch("data.earnings.get_earnings_calendar", return_value={
        "next_earnings_date": None, "eps_estimate": None, "eps_beat_rate": None,
    })
    assert days_to_earnings("AMZN") is None

def test_beat_rate_none_on_empty_history(mocker):
    mock_ticker = MagicMock()
    mock_ticker.info = {}
    mock_ticker.calendar = None
    mock_ticker.earnings_history = pd.DataFrame()
    mocker.patch("data.earnings.yf.Ticker", return_value=mock_ticker)

    result = get_earnings_calendar("SHOP")
    assert result["eps_beat_rate"] is None
