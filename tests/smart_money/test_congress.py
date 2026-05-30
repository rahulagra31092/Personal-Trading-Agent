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
    with patch("smart_money.congress.get_cache", return_value=None), \
         patch("smart_money.congress.set_cache"), \
         patch("smart_money.congress._institutional_adjustment", return_value=0.0), \
         patch("smart_money.congress.compute_trump_modifier", return_value=0.0), \
         patch("smart_money.congress.get_congress_trades", return_value=_sample_trades(3, 1)):
        assert 0.0 <= compute_congress_score("AAPL") <= 1.0


def test_all_buys_score_above_half():
    with patch("smart_money.congress.get_cache", return_value=None), \
         patch("smart_money.congress.set_cache"), \
         patch("smart_money.congress._institutional_adjustment", return_value=0.0), \
         patch("smart_money.congress.compute_trump_modifier", return_value=0.0), \
         patch("smart_money.congress.get_congress_trades", return_value=_sample_trades(5, 0)):
        assert compute_congress_score("AAPL") > 0.5


def test_all_sells_score_below_half():
    with patch("smart_money.congress.get_cache", return_value=None), \
         patch("smart_money.congress.set_cache"), \
         patch("smart_money.congress._institutional_adjustment", return_value=0.0), \
         patch("smart_money.congress.compute_trump_modifier", return_value=0.0), \
         patch("smart_money.congress.get_congress_trades", return_value=_sample_trades(0, 5)):
        assert compute_congress_score("AAPL") < 0.5


def test_no_trades_returns_neutral():
    with patch("smart_money.congress.get_cache", return_value=None), \
         patch("smart_money.congress.set_cache"), \
         patch("smart_money.congress._institutional_adjustment", return_value=0.0), \
         patch("smart_money.congress.compute_trump_modifier", return_value=0.0), \
         patch("smart_money.congress.get_congress_trades", return_value=[]):
        assert compute_congress_score("AAPL") == 0.5


def test_old_trades_excluded():
    # Trades older than 180 days should not affect the score
    with patch("smart_money.congress.get_cache", return_value=None), \
         patch("smart_money.congress.set_cache"), \
         patch("smart_money.congress._institutional_adjustment", return_value=0.0), \
         patch("smart_money.congress.compute_trump_modifier", return_value=0.0), \
         patch("smart_money.congress.get_congress_trades", return_value=_sample_trades(5, 0, days_ago=200)):
        assert compute_congress_score("AAPL") == 0.5


def test_get_congress_trades_returns_list_without_api_key(monkeypatch):
    monkeypatch.setattr("smart_money.congress._QUIVER_API_KEY", None)
    with patch("smart_money.congress.get_cache", return_value=None):
        result = get_congress_trades("AAPL")
    assert result == []


def test_institutional_adjustment_high_ownership_returns_positive():
    from smart_money.congress import _institutional_adjustment
    import pandas as pd
    holders_df = pd.DataFrame(
        {"Value": [0.0005, 0.75, 0.76, 5432]},
        index=["insidersPercentHeld", "institutionsPercentHeld",
               "institutionsFloatPercentHeld", "institutionsCount"],
    )
    with patch("smart_money.congress.get_cache", return_value=None), \
         patch("smart_money.congress.set_cache"), \
         patch("smart_money.congress.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.major_holders = holders_df
        result = _institutional_adjustment("AAPL")
    assert result == 0.05


def test_institutional_adjustment_low_ownership_returns_negative():
    from smart_money.congress import _institutional_adjustment
    import pandas as pd
    holders_df = pd.DataFrame(
        {"Value": [0.0005, 0.25, 0.27, 5432]},
        index=["insidersPercentHeld", "institutionsPercentHeld",
               "institutionsFloatPercentHeld", "institutionsCount"],
    )
    with patch("smart_money.congress.get_cache", return_value=None), \
         patch("smart_money.congress.set_cache"), \
         patch("smart_money.congress.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.major_holders = holders_df
        result = _institutional_adjustment("AAPL")
    assert result == -0.05


def test_institutional_adjustment_mid_ownership_returns_zero():
    from smart_money.congress import _institutional_adjustment
    import pandas as pd
    holders_df = pd.DataFrame(
        {"Value": [0.0005, 0.55, 0.58, 5432]},
        index=["insidersPercentHeld", "institutionsPercentHeld",
               "institutionsFloatPercentHeld", "institutionsCount"],
    )
    with patch("smart_money.congress.get_cache", return_value=None), \
         patch("smart_money.congress.set_cache"), \
         patch("smart_money.congress.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.major_holders = holders_df
        result = _institutional_adjustment("AAPL")
    assert result == 0.0


def test_institutional_adjustment_none_holders_returns_zero():
    from smart_money.congress import _institutional_adjustment
    with patch("smart_money.congress.get_cache", return_value=None), \
         patch("smart_money.congress.set_cache"), \
         patch("smart_money.congress.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.major_holders = None
        result = _institutional_adjustment("AAPL")
    assert result == 0.0


def test_institutional_adjustment_exception_returns_zero():
    from smart_money.congress import _institutional_adjustment
    with patch("smart_money.congress.get_cache", return_value=None), \
         patch("smart_money.congress.set_cache"), \
         patch("smart_money.congress.yf.Ticker", side_effect=RuntimeError("api error")):
        result = _institutional_adjustment("AAPL")
    assert result == 0.0
