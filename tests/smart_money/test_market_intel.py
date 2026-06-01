import pytest
from unittest.mock import patch, MagicMock
from smart_money.market_intel import get_market_news, build_market_brief


@pytest.fixture(autouse=True)
def fresh_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("data.cache.DB_PATH", tmp_path / "test_cache.db")
    from data.cache import init_db
    init_db()


def test_get_market_news_returns_list():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "results": [
            {"title": "Fed holds rates steady", "description": "FOMC meeting outcome", "pubDate": "2026-06-01"},
            {"title": "S&P 500 hits record", "description": "Tech leads gains", "pubDate": "2026-06-01"},
        ]
    }
    with patch("smart_money.market_intel.requests.get", return_value=mock_response):
        news = get_market_news(n=5)
    assert isinstance(news, list)
    assert len(news) >= 1
    assert "title" in news[0]


def test_get_market_news_deduplicates():
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "results": [
            {"title": "Same headline", "description": "dupe", "pubDate": "2026-06-01"},
            {"title": "Same headline", "description": "dupe2", "pubDate": "2026-06-01"},
        ]
    }
    with patch("smart_money.market_intel.requests.get", return_value=mock_response):
        news = get_market_news(n=10)
    titles = [a["title"] for a in news]
    assert len(titles) == len(set(titles))


def test_get_market_news_empty_when_no_key(monkeypatch):
    monkeypatch.setattr("config.NEWSDATA_API_KEY", None)
    from smart_money import market_intel
    monkeypatch.setattr(market_intel.config, "NEWSDATA_API_KEY", None)
    news = get_market_news()
    assert news == []


def test_build_market_brief_fallback_on_claude_failure():
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("API error")
    with patch("smart_money.market_intel.anthropic.Anthropic", return_value=mock_client):
        result = build_market_brief(
            index_snapshot={"SPY": {"name": "S&P 500", "price": 590.0, "pct_change": 0.3}},
            sector_snapshot={},
            news=[],
            top_buys=[],
            top_avoids=[],
            regime={"regime": "normal", "vix": 15.9},
            vix=15.9,
        )
    assert isinstance(result, str)
    assert len(result) > 0


def test_build_market_brief_returns_claude_text():
    mock_client = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="Markets rose today. Tech led gains. Watch NVDA closely.")]
    mock_client.messages.create.return_value = mock_msg

    _FAKE_BUY = {
        "ticker": "NVDA",
        "signal": {"label": "BUY", "composite_score": 0.71},
        "confidence": {"prob_success": 0.55},
        "current_price": 131.0,
    }
    with patch("smart_money.market_intel.anthropic.Anthropic", return_value=mock_client):
        result = build_market_brief(
            index_snapshot={},
            sector_snapshot={},
            news=[{"title": "Nvidia beats estimates"}],
            top_buys=[_FAKE_BUY],
            top_avoids=[],
            regime={"regime": "normal", "vix": 15.9},
            vix=15.9,
        )
    assert "Markets rose today" in result
