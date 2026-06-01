import pytest
from unittest.mock import patch, MagicMock
from data.google_sheets import fetch_google_sheet_portfolio, _header_map, _safe_float


@pytest.fixture(autouse=True)
def fresh_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("data.cache.DB_PATH", tmp_path / "test_cache.db")
    from data.cache import init_db
    init_db()


def test_safe_float_normal():
    assert _safe_float("123.45") == 123.45


def test_safe_float_with_dollar_and_comma():
    assert _safe_float("$1,234.56") == 1234.56


def test_safe_float_invalid():
    assert _safe_float("") == 0.0
    assert _safe_float("N/A") == 0.0


def test_header_map_standard():
    m = _header_map(["Ticker", "Shares", "Avg Cost", "Entry Date"])
    assert m["ticker"] == 0
    assert m["shares"] == 1
    assert m["avg_cost"] == 2
    assert m["entry_date"] == 3


def test_header_map_variants():
    m = _header_map(["Symbol", "Qty", "Entry Price", "Date"])
    assert m["ticker"] == 0
    assert m["shares"] == 1
    assert m["avg_cost"] == 2
    assert m["entry_date"] == 3


def test_header_map_missing_columns():
    m = _header_map(["Ticker", "Notes"])
    assert m["ticker"] == 0
    assert "shares" not in m


def test_fetch_returns_empty_when_no_sheet_id(monkeypatch):
    monkeypatch.setattr("config.GOOGLE_SHEET_ID", None)
    import data.google_sheets as gs
    monkeypatch.setattr(gs.config, "GOOGLE_SHEET_ID", None)
    result = fetch_google_sheet_portfolio(sheet_id=None)
    assert result == []


def test_fetch_parses_csv():
    csv_content = "Ticker,Shares,Avg Cost,Entry Date\nAAPL,10,175.00,2026-01-15\nNVDA,5,120.00,2026-02-01\n"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://docs.google.com/spreadsheets/export"
    mock_resp.text = csv_content
    with patch("data.google_sheets.requests.get", return_value=mock_resp):
        result = fetch_google_sheet_portfolio(sheet_id="fake_id_123")
    assert len(result) == 2
    assert result[0]["ticker"] == "AAPL"
    assert result[0]["shares"] == 10.0
    assert result[0]["avg_cost"] == 175.0
    assert result[1]["ticker"] == "NVDA"


def test_fetch_skips_zero_share_rows():
    csv_content = "Ticker,Shares,Avg Cost\nAAPL,10,175.00\nGOOGL,0,100.00\n"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://docs.google.com/export"
    mock_resp.text = csv_content
    with patch("data.google_sheets.requests.get", return_value=mock_resp):
        result = fetch_google_sheet_portfolio(sheet_id="fake_id")
    assert len(result) == 1
    assert result[0]["ticker"] == "AAPL"


def test_fetch_returns_empty_when_redirected_to_login():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://accounts.google.com/signin/..."
    mock_resp.text = "<html>Login</html>"
    with patch("data.google_sheets.requests.get", return_value=mock_resp):
        result = fetch_google_sheet_portfolio(sheet_id="private_sheet")
    assert result == []
