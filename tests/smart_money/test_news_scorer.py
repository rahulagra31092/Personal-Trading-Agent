from unittest.mock import patch
from smart_money.news_scorer import compute_news_score


def _articles(titles: list[str]) -> list[dict]:
    return [{"title": t, "description": "", "publishedAt": "2024-01-01"} for t in titles]


def test_score_bounded():
    with patch("smart_money.news_scorer.get_ticker_news", return_value=_articles(["stock rallies on strong earnings"])):
        assert 0.0 <= compute_news_score("AAPL") <= 1.0


def test_bullish_headlines_score_above_half():
    headlines = ["strong buy upgrade", "beats earnings growth rally"]
    with patch("smart_money.news_scorer.get_ticker_news", return_value=_articles(headlines)):
        assert compute_news_score("AAPL") > 0.5


def test_bearish_headlines_score_below_half():
    headlines = ["downgrade miss weak sell", "loss decline bearish"]
    with patch("smart_money.news_scorer.get_ticker_news", return_value=_articles(headlines)):
        assert compute_news_score("AAPL") < 0.5


def test_no_news_returns_neutral():
    with patch("smart_money.news_scorer.get_ticker_news", return_value=[]):
        assert compute_news_score("AAPL") == 0.5


def test_mixed_news_returns_near_half():
    headlines = ["strong buy upgrade", "downgrade miss weak sell"]
    with patch("smart_money.news_scorer.get_ticker_news", return_value=_articles(headlines)):
        score = compute_news_score("AAPL")
        assert 0.3 <= score <= 0.7
