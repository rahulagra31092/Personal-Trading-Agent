import pytest
from unittest.mock import patch
from api.paper_portfolio import (
    initialize_portfolio,
    is_initialized,
    get_positions,
    get_portfolio_value,
    get_account,
    rebalance,
    STARTING_CAPITAL,
)


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    import api.paper_portfolio as pp
    monkeypatch.setattr(pp, "PAPER_DB_PATH", tmp_path / "paper_portfolio.db")
    pp.init_paper_db()


_BUYS = [
    {"ticker": "NVDA", "shares": 3.812, "price": 131.20},
    {"ticker": "AVGO", "shares": 2.564, "price": 195.00},
    {"ticker": "MU",   "shares": 4.459, "price": 112.10},
]


def test_not_initialized_by_default():
    assert not is_initialized()


def test_initialize_creates_account():
    initialize_portfolio(_BUYS, capital=STARTING_CAPITAL)
    assert is_initialized()
    acct = get_account()
    assert acct["starting_capital"] == STARTING_CAPITAL
    assert acct["cash"] > 0


def test_cash_equals_unspent_capital():
    initialize_portfolio(_BUYS, capital=STARTING_CAPITAL)
    spent = sum(b["shares"] * b["price"] for b in _BUYS)
    acct = get_account()
    assert abs(acct["cash"] - (STARTING_CAPITAL - spent)) < 0.01


def test_positions_count_matches_buys():
    initialize_portfolio(_BUYS, capital=STARTING_CAPITAL)
    with patch("api.paper_portfolio._fetch_prices", return_value={}):
        positions = get_positions()
    assert len(positions) == len(_BUYS)
    tickers = {p["ticker"] for p in positions}
    assert tickers == {"NVDA", "AVGO", "MU"}


def test_portfolio_value_total():
    initialize_portfolio(_BUYS, capital=STARTING_CAPITAL)
    # Mock prices equal to avg_cost → P&L = 0
    prices = {b["ticker"]: b["price"] for b in _BUYS}
    with patch("api.paper_portfolio._fetch_prices", return_value=prices), \
         patch("api.paper_portfolio._spy_return_since", return_value=0.0):
        pv = get_portfolio_value()
    assert abs(pv["total_pnl"]) < 0.10  # ~0 since prices == cost
    assert pv["total_value"] == pytest.approx(STARTING_CAPITAL, abs=1.0)


def test_portfolio_value_with_gain():
    initialize_portfolio(_BUYS, capital=STARTING_CAPITAL)
    # All positions up 10%
    prices = {b["ticker"]: b["price"] * 1.10 for b in _BUYS}
    with patch("api.paper_portfolio._fetch_prices", return_value=prices), \
         patch("api.paper_portfolio._spy_return_since", return_value=0.0):
        pv = get_portfolio_value()
    assert pv["total_pnl"] > 0
    assert pv["total_pnl_pct"] > 0


def test_rebalance_sell_removes_position():
    initialize_portfolio(_BUYS, capital=STARTING_CAPITAL)
    rebalance(
        sells=[{"ticker": "MU", "price": 112.10, "reason": "test"}],
        buys=[],
    )
    with patch("api.paper_portfolio._fetch_prices", return_value={}):
        positions = get_positions()
    tickers = {p["ticker"] for p in positions}
    assert "MU" not in tickers


def test_rebalance_sell_returns_cash():
    initialize_portfolio(_BUYS, capital=STARTING_CAPITAL)
    cash_before = get_account()["cash"]
    mu = next(b for b in _BUYS if b["ticker"] == "MU")
    rebalance(
        sells=[{"ticker": "MU", "price": mu["price"], "reason": "test"}],
        buys=[],
    )
    cash_after = get_account()["cash"]
    assert cash_after > cash_before


def test_rebalance_buy_adds_position():
    initialize_portfolio(_BUYS, capital=STARTING_CAPITAL)
    rebalance(
        sells=[],
        buys=[{"ticker": "ARM", "shares": 5.0, "price": 98.0}],
    )
    with patch("api.paper_portfolio._fetch_prices", return_value={}):
        positions = get_positions()
    tickers = {p["ticker"] for p in positions}
    assert "ARM" in tickers


def test_initialize_is_idempotent():
    initialize_portfolio(_BUYS, capital=STARTING_CAPITAL)
    # Re-initialize with different buys
    new_buys = [{"ticker": "AAPL", "shares": 5.0, "price": 180.0}]
    initialize_portfolio(new_buys, capital=STARTING_CAPITAL)
    with patch("api.paper_portfolio._fetch_prices", return_value={}):
        positions = get_positions()
    assert len(positions) == 1
    assert positions[0]["ticker"] == "AAPL"
