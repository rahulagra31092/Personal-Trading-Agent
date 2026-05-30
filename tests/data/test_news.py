import pytest
from data.news import get_ticker_news

@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr("data.cache.DB_PATH", tmp_path / "test_cache.db")
    from data.cache import init_db
    init_db()

def test_returns_list_of_articles(mocker):
    mock_get = mocker.patch("data.news.requests.get")
    mock_get.return_value.json.return_value = {
        "articles": [
            {"title": "AMZN AWS deal", "description": "Big contract", "publishedAt": "2026-05-18T10:00:00Z"},
            {"title": "AMZN beats Q1", "description": "Strong results", "publishedAt": "2026-05-17T14:00:00Z"},
        ]
    }
    mock_get.return_value.raise_for_status = lambda: None

    result = get_ticker_news("AMZN", days=3)

    assert len(result) == 2
    assert result[0]["title"] == "AMZN AWS deal"
    assert "publishedAt" in result[0]

def test_empty_response_returns_empty_list(mocker):
    mock_get = mocker.patch("data.news.requests.get")
    mock_get.return_value.json.return_value = {"articles": []}
    mock_get.return_value.raise_for_status = lambda: None

    assert get_ticker_news("GOOG", days=1) == []

def test_caches_on_second_call(mocker):
    mock_get = mocker.patch("data.news.requests.get")
    mock_get.return_value.json.return_value = {"articles": []}
    mock_get.return_value.raise_for_status = lambda: None

    get_ticker_news("META", days=1)
    get_ticker_news("META", days=1)

    assert mock_get.call_count == 1
