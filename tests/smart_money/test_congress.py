import pytest
from unittest.mock import patch, MagicMock
from smart_money.congress import compute_congress_score, get_congress_trades


def _sample_trades(n_buys: int, n_sells: int, days_ago: int = 10) -> list[dict]:
    from datetime import datetime, timedelta, timezone
    date = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    return (
        [{"Transaction": "Purchase", "Date": date, "Ticker": "AAPL"} for _ in range(n_buys)]
        + [{"Transaction": "Sale (Full)", "Date": date, "Ticker": "AAPL"} for _ in range(n_sells)]
    )


def test_score_bounded():
    with patch("smart_money.congress.get_congress_trades", return_value=_sample_trades(3, 1)):
        assert 0.0 <= compute_congress_score("AAPL") <= 1.0


def test_all_buys_score_above_half():
    with patch("smart_money.congress.get_congress_trades", return_value=_sample_trades(5, 0)):
        assert compute_congress_score("AAPL") > 0.5


def test_all_sells_score_below_half():
    with patch("smart_money.congress.get_congress_trades", return_value=_sample_trades(0, 5)):
        assert compute_congress_score("AAPL") < 0.5


def test_no_trades_returns_neutral():
    with patch("smart_money.congress.get_congress_trades", return_value=[]):
        assert compute_congress_score("AAPL") == 0.5


def test_old_trades_excluded():
    # Trades older than 90 days should not affect the score
    with patch("smart_money.congress.get_congress_trades", return_value=_sample_trades(5, 0, days_ago=120)):
        assert compute_congress_score("AAPL") == 0.5


def test_get_congress_trades_returns_list_without_api_key(monkeypatch):
    monkeypatch.setattr("smart_money.congress._QUIVER_API_KEY", None)
    with patch("smart_money.congress.get_cache", return_value=None):
        result = get_congress_trades("AAPL")
    assert result == []
