import logging

from data.news import get_ticker_news

logger = logging.getLogger(__name__)

_BULLISH = {"upgrade", "beat", "strong", "bullish", "buy", "outperform", "growth", "surge", "rally", "profit", "record"}
_BEARISH = {"downgrade", "miss", "weak", "bearish", "sell", "underperform", "decline", "loss", "crash", "cut", "layoff"}


def compute_news_score(ticker: str, days: int = 3) -> float:
    try:
        articles = get_ticker_news(ticker, days=days)
    except Exception as exc:
        logger.warning("News fetch failed for %s: %s", ticker, exc)
        return 0.5

    if not articles:
        return 0.5

    scores = []
    for article in articles:
        text = (
            (article.get("title") or "") + " " + (article.get("description") or "")
        ).lower()
        bull = sum(1 for w in _BULLISH if w in text)
        bear = sum(1 for w in _BEARISH if w in text)
        if bull + bear == 0:
            scores.append(0.5)
        else:
            scores.append(bull / (bull + bear))

    return round(sum(scores) / len(scores), 4)
