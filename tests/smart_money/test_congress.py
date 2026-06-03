import pytest
from unittest.mock import patch, MagicMock
from smart_money.congress import (
    compute_congress_score,
    get_congress_trades,
    _recency_weight,
    _parse_trade_size,
)
from datetime import datetime, timedelta, timezone


def _sample_trades(n_buys: int, n_sells: int, days_ago: int = 10,
                   range_str: str = "", member: str = "") -> list[dict]:
    date = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    return (
        [{"Transaction": "Purchase", "Date": date, "Ticker": "AAPL",
          "Range": range_str, "Representative": member} for _ in range(n_buys)]
        + [{"Transaction": "Sale (Full)", "Date": date, "Ticker": "AAPL",
            "Range": range_str, "Representative": member} for _ in range(n_sells)]
    )


# ---------------------------------------------------------------------------
# compute_congress_score — existing behaviour
# ---------------------------------------------------------------------------

def test_score_bounded():
    with patch("smart_money.congress.get_cache", return_value=None), \
         patch("smart_money.congress.set_cache"), \
         patch("smart_money.congress._institutional_adjustment", return_value=0.0), \
         patch("smart_money.congress.get_congress_trades", return_value=_sample_trades(3, 1)):
        assert 0.0 <= compute_congress_score("AAPL") <= 1.0


def test_all_buys_score_above_half():
    with patch("smart_money.congress.get_cache", return_value=None), \
         patch("smart_money.congress.set_cache"), \
         patch("smart_money.congress._institutional_adjustment", return_value=0.0), \
         patch("smart_money.congress.get_congress_trades", return_value=_sample_trades(5, 0)):
        assert compute_congress_score("AAPL") > 0.5


def test_all_sells_score_below_half():
    with patch("smart_money.congress.get_cache", return_value=None), \
         patch("smart_money.congress.set_cache"), \
         patch("smart_money.congress._institutional_adjustment", return_value=0.0), \
         patch("smart_money.congress.get_congress_trades", return_value=_sample_trades(0, 5)):
        assert compute_congress_score("AAPL") < 0.5


def test_no_trades_returns_neutral():
    with patch("smart_money.congress.get_cache", return_value=None), \
         patch("smart_money.congress.set_cache"), \
         patch("smart_money.congress._institutional_adjustment", return_value=0.0), \
         patch("smart_money.congress.get_congress_trades", return_value=[]):
        assert compute_congress_score("AAPL") == 0.5


def test_old_trades_excluded():
    with patch("smart_money.congress.get_cache", return_value=None), \
         patch("smart_money.congress.set_cache"), \
         patch("smart_money.congress._institutional_adjustment", return_value=0.0), \
         patch("smart_money.congress.get_congress_trades",
               return_value=_sample_trades(5, 0, days_ago=200)):
        assert compute_congress_score("AAPL") == 0.5


def test_get_congress_trades_returns_list_without_api_key(monkeypatch):
    monkeypatch.setattr("smart_money.congress._QUIVER_API_KEY", None)
    with patch("smart_money.congress.get_cache", return_value=None):
        result = get_congress_trades("AAPL")
    assert result == []


# ---------------------------------------------------------------------------
# _recency_weight
# ---------------------------------------------------------------------------

def test_recency_weight_fresh_trade():
    now = datetime.now(timezone.utc)
    trade_date = now - timedelta(days=5)
    assert _recency_weight(trade_date, now) == pytest.approx(1.0)


def test_recency_weight_middle_band():
    now = datetime.now(timezone.utc)
    trade_date = now - timedelta(days=60)
    assert _recency_weight(trade_date, now) == pytest.approx(0.7)


def test_recency_weight_old_trade():
    now = datetime.now(timezone.utc)
    trade_date = now - timedelta(days=150)
    assert _recency_weight(trade_date, now) == pytest.approx(0.3)


def test_recency_weight_boundary_30_days():
    now = datetime.now(timezone.utc)
    trade_date = now - timedelta(days=30)
    assert _recency_weight(trade_date, now) == pytest.approx(1.0)


def test_recency_weight_boundary_31_days():
    now = datetime.now(timezone.utc)
    trade_date = now - timedelta(days=31)
    assert _recency_weight(trade_date, now) == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# _parse_trade_size
# ---------------------------------------------------------------------------

def test_parse_trade_size_small():
    assert _parse_trade_size("$1,001 - $15,000") == pytest.approx(1.0)


def test_parse_trade_size_medium():
    assert _parse_trade_size("$15,001 - $50,000") == pytest.approx(2.0)


def test_parse_trade_size_large():
    assert _parse_trade_size("$250,001 - $500,000") == pytest.approx(8.0)


def test_parse_trade_size_very_large():
    assert _parse_trade_size("$500,001 - $1,000,000") == pytest.approx(15.0)


def test_parse_trade_size_over_million():
    assert _parse_trade_size("Over $1,000,000") == pytest.approx(30.0)


def test_parse_trade_size_empty_returns_one():
    assert _parse_trade_size("") == pytest.approx(1.0)


def test_parse_trade_size_no_numbers_returns_one():
    assert _parse_trade_size("unknown range") == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# New weighted behaviour integration tests
# ---------------------------------------------------------------------------

def test_recency_weighting_recent_buys_old_sells_vs_inverse():
    """Recent buys + old sells outscores old buys + recent sells — only tests recency
    in a mixed-direction context where the weighting actually affects the ratio."""
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=5)).strftime("%Y-%m-%d")
    old = (now - timedelta(days=150)).strftime("%Y-%m-%d")

    # 3 recent buys + 2 old sells
    bullish = [{"Transaction": "Purchase", "Date": recent, "Representative": "", "Range": ""}
               for _ in range(3)] + \
              [{"Transaction": "Sale (Full)", "Date": old, "Representative": "", "Range": ""}
               for _ in range(2)]

    # 3 old buys + 2 recent sells
    bearish = [{"Transaction": "Purchase", "Date": old, "Representative": "", "Range": ""}
               for _ in range(3)] + \
              [{"Transaction": "Sale (Full)", "Date": recent, "Representative": "", "Range": ""}
               for _ in range(2)]

    with patch("smart_money.congress._institutional_adjustment", return_value=0.0), \
         patch("smart_money.congress.get_congress_trades", return_value=bullish):
        score_bullish = compute_congress_score("AAPL")

    with patch("smart_money.congress._institutional_adjustment", return_value=0.0), \
         patch("smart_money.congress.get_congress_trades", return_value=bearish):
        score_bearish = compute_congress_score("AAPL")

    assert score_bullish > score_bearish


def test_large_buy_dominates_small_sells():
    """One large buy should outweigh two small sells — size weighting in a mixed scenario."""
    now = datetime.now(timezone.utc)
    d = (now - timedelta(days=5)).strftime("%Y-%m-%d")

    # 1 large buy + 2 small sells → large buy dominates
    bullish = [{"Transaction": "Purchase", "Date": d, "Representative": "",
                "Range": "Over $1,000,000"}] + \
              [{"Transaction": "Sale (Full)", "Date": d, "Representative": "",
                "Range": "$1,001 - $15,000"} for _ in range(2)]

    # 1 small buy + 2 small sells → sells dominate
    bearish = [{"Transaction": "Purchase", "Date": d, "Representative": "",
                "Range": "$1,001 - $15,000"}] + \
              [{"Transaction": "Sale (Full)", "Date": d, "Representative": "",
                "Range": "$1,001 - $15,000"} for _ in range(2)]

    with patch("smart_money.congress._institutional_adjustment", return_value=0.0), \
         patch("smart_money.congress.get_congress_trades", return_value=bullish):
        score_bullish = compute_congress_score("AAPL")

    with patch("smart_money.congress._institutional_adjustment", return_value=0.0), \
         patch("smart_money.congress.get_congress_trades", return_value=bearish):
        score_bearish = compute_congress_score("AAPL")

    assert score_bullish > score_bearish


def test_consensus_from_multiple_members_boosts_score():
    # Same buy count but spread across 5 different members vs 1 member
    one_member = _sample_trades(5, 0, member="Alice")
    five_members = [
        {"Transaction": "Purchase", "Date": (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d"),
         "Representative": m, "Range": ""}
        for m in ["Alice", "Bob", "Carol", "Dave", "Eve"]
    ]

    with patch("smart_money.congress._institutional_adjustment", return_value=0.0), \
         patch("smart_money.congress.get_congress_trades", return_value=one_member):
        score_one = compute_congress_score("AAPL")

    with patch("smart_money.congress._institutional_adjustment", return_value=0.0), \
         patch("smart_money.congress.get_congress_trades", return_value=five_members):
        score_five = compute_congress_score("AAPL")

    assert score_five > score_one


# ---------------------------------------------------------------------------
# Institutional adjustment tests (unchanged)
# ---------------------------------------------------------------------------

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
