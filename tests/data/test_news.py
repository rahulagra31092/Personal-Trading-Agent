import pytest
from unittest.mock import patch
from data.news import get_ticker_news, prefetch_sector_news
from data.cache import get_cache


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr("data.cache.DB_PATH", tmp_path / "test_cache.db")
    from data.cache import init_db
    init_db()


def _mock_fetch(articles):
    """Helper: patch _fetch_news to return a fixed article list."""
    return patch("data.news._fetch_news", return_value=articles)


def test_returns_list_of_articles():
    articles = [
        {"title": "AMZN AWS deal", "description": "Big contract", "publishedAt": "2026-05-18T10:00:00Z"},
        {"title": "AMZN beats Q1", "description": "Strong results", "publishedAt": "2026-05-17T14:00:00Z"},
    ]
    with _mock_fetch(articles):
        result = get_ticker_news("AMZN", days=3)
    assert len(result) == 2
    assert result[0]["title"] == "AMZN AWS deal"
    assert "publishedAt" in result[0]


def test_empty_response_returns_empty_list():
    with _mock_fetch([]):
        assert get_ticker_news("GOOG", days=1) == []


def test_caches_on_second_call():
    articles = [{"title": "META earnings beat", "description": "Strong ad revenue", "publishedAt": "2026-05-18"}]
    with _mock_fetch(articles) as mock_fn:
        get_ticker_news("META", days=1)
        get_ticker_news("META", days=1)   # should hit cache
    assert mock_fn.call_count == 1


def test_prefetch_populates_cache_for_each_ticker():
    articles = [
        {"title": "AAPL hits record high", "description": "Apple stock surges", "publishedAt": "2026-05-18"},
        {"title": "MSFT cloud growth", "description": "Microsoft Azure expands", "publishedAt": "2026-05-18"},
    ]
    with _mock_fetch(articles):
        with patch("data.news.set_cache") as mock_set:
            with patch("data.news.get_cache", return_value=None):
                prefetch_sector_news({"tech": ["AAPL", "MSFT"]}, days=7)
    tickers_cached = {call.args[0] for call in mock_set.call_args_list}
    assert "news:AAPL:7" in tickers_cached
    assert "news:MSFT:7" in tickers_cached


def test_prefetch_skips_sector_if_already_cached():
    with patch("data.news.get_cache", return_value=[{"title": "old", "description": "cached"}]):
        with _mock_fetch([]) as mock_fn:
            prefetch_sector_news({"tech": ["AAPL", "MSFT"]}, days=7)
    mock_fn.assert_not_called()


def test_prefetch_writes_empty_list_for_ticker_with_no_matches():
    articles = [{"title": "AAPL record high", "description": "Apple surges", "publishedAt": "2026-05-18"}]
    with _mock_fetch(articles):
        with patch("data.news.get_cache", return_value=None):
            with patch("data.news.set_cache") as mock_set:
                prefetch_sector_news({"tech": ["AAPL", "MSFT"]}, days=7)
    msft_call = next(c for c in mock_set.call_args_list if c.args[0] == "news:MSFT:7")
    assert msft_call.args[1] == []
