import os
import tempfile
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from data.holdings import load_holdings, save_holdings
from api.main import app

client = TestClient(app)

_FAKE_BARS = [
    {
        "t": 1700000000000 + i * 86400000,
        "o": 100.0,
        "h": 105.0,
        "l": 98.0,
        "c": 102.0 + i * 0.1,
        "v": 1_000_000,
    }
    for i in range(30)
]


def test_load_holdings_returns_empty_when_file_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = load_holdings(os.path.join(tmpdir, "holdings.csv"))
        assert result == []


def test_save_and_load_holdings_roundtrip():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
        tmppath = f.name
    try:
        holdings = [{"ticker": "AAPL", "shares": 10.0, "cost_basis": 150.0}]
        save_holdings(holdings, tmppath)
        loaded = load_holdings(tmppath)
        assert loaded[0]["ticker"] == "AAPL"
        assert loaded[0]["shares"] == 10.0
        assert loaded[0]["cost_basis"] == 150.0
    finally:
        os.unlink(tmppath)


def test_portfolio_pnl_empty_holdings():
    with patch("api.portfolio.load_holdings", return_value=[]):
        resp = client.get("/portfolio/pnl")
    assert resp.status_code == 200
    assert resp.json()["positions"] == []


def test_portfolio_pnl_returns_positions():
    holdings = [{"ticker": "AAPL", "shares": 10.0, "cost_basis": 150.0}]
    with patch("api.portfolio.load_holdings", return_value=holdings), \
         patch("api.portfolio.get_daily_bars", return_value=_FAKE_BARS):
        resp = client.get("/portfolio/pnl")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["positions"]) == 1
    pos = data["positions"][0]
    assert pos["ticker"] == "AAPL"
    assert "pnl" in pos
    assert "atr_stop" in pos
    assert "below_stop" in pos


def test_portfolio_pnl_computes_totals():
    holdings = [
        {"ticker": "AAPL", "shares": 10.0, "cost_basis": 100.0},
        {"ticker": "MSFT", "shares": 5.0, "cost_basis": 200.0},
    ]
    with patch("api.portfolio.load_holdings", return_value=holdings), \
         patch("api.portfolio.get_daily_bars", return_value=_FAKE_BARS):
        resp = client.get("/portfolio/pnl")
    data = resp.json()
    assert "total_value" in data
    assert "total_pnl" in data
    assert "total_pnl_pct" in data
    assert data["total_cost"] == pytest.approx(10.0 * 100.0 + 5.0 * 200.0)


def test_portfolio_pnl_fetch_failure_returns_none_fields():
    holdings = [{"ticker": "AAPL", "shares": 10.0, "cost_basis": 150.0}]
    with patch("api.portfolio.load_holdings", return_value=holdings), \
         patch("api.portfolio.get_daily_bars", side_effect=RuntimeError("timeout")):
        resp = client.get("/portfolio/pnl")
    assert resp.status_code == 200
    pos = resp.json()["positions"][0]
    assert pos["current_price"] is None
    assert pos["atr_stop"] is None
    assert pos["below_stop"] is None
