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
    # 4 quarters: 3 beats (5.0, 3.0, 8.0), 1 miss (-2.0); avg = 3.5
    mock_ticker.earnings_history = pd.DataFrame({"surprisePercent": [5.0, -2.0, 3.0, 8.0]})
    mocker.patch("data.earnings.yf.Ticker", return_value=mock_ticker)

    result = get_earnings_calendar("AMZN")

    assert result["eps_estimate"] == 1.25
    assert result["eps_beat_rate"] == 0.75
    assert result["next_earnings_date"] == "2026-05-22"
    assert result["avg_surprise_pct"] == pytest.approx(3.5, abs=0.01)
    assert result["last_beat"] is True           # iloc[0] = 5.0 > 0
    assert result["earnings_quarterly_growth"] is None  # not in info mock


def test_earnings_quarterly_growth_included(mocker):
    mock_ticker = MagicMock()
    mock_ticker.info = {"earningsQuarterlyGrowth": 0.15}
    mock_ticker.calendar = None
    mock_ticker.earnings_history = pd.DataFrame({"surprisePercent": [10.0, 5.0]})
    mocker.patch("data.earnings.yf.Ticker", return_value=mock_ticker)

    result = get_earnings_calendar("MSFT")
    assert result["earnings_quarterly_growth"] == pytest.approx(0.15)


def test_last_beat_false_when_most_recent_miss(mocker):
    mock_ticker = MagicMock()
    mock_ticker.info = {}
    mock_ticker.calendar = None
    mock_ticker.earnings_history = pd.DataFrame({"surprisePercent": [-3.0, 5.0, 8.0]})
    mocker.patch("data.earnings.yf.Ticker", return_value=mock_ticker)

    result = get_earnings_calendar("XYZ")
    assert result["last_beat"] is False  # iloc[0] = -3.0 < 0


def test_days_to_earnings_returns_correct_count(mocker):
    future = (date.today() + timedelta(days=5)).isoformat()
    mocker.patch("data.earnings.get_earnings_calendar", return_value={
        "next_earnings_date": future, "eps_estimate": 1.0, "eps_beat_rate": 0.7,
        "avg_surprise_pct": 5.0, "last_beat": True, "earnings_quarterly_growth": 0.1,
    })
    assert days_to_earnings("AMZN") == 5


def test_days_to_earnings_none_when_no_date(mocker):
    mocker.patch("data.earnings.get_earnings_calendar", return_value={
        "next_earnings_date": None, "eps_estimate": None, "eps_beat_rate": None,
        "avg_surprise_pct": None, "last_beat": None, "earnings_quarterly_growth": None,
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
    assert result["avg_surprise_pct"] is None
    assert result["last_beat"] is None


def test_all_beats_avg_positive(mocker):
    mock_ticker = MagicMock()
    mock_ticker.info = {}
    mock_ticker.calendar = None
    mock_ticker.earnings_history = pd.DataFrame({"surprisePercent": [10.0, 5.0, 8.0, 12.0]})
    mocker.patch("data.earnings.yf.Ticker", return_value=mock_ticker)

    result = get_earnings_calendar("NVDA")
    assert result["eps_beat_rate"] == 1.0
    assert result["avg_surprise_pct"] == pytest.approx(8.75, abs=0.01)
    assert result["last_beat"] is True
