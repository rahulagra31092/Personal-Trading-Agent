import logging
import re
import requests
from datetime import date, timedelta
from data.cache import get_cache, set_cache
import config

logger = logging.getLogger(__name__)


def _newsdata_fetch(query: str, days: int = 3) -> list[dict]:
    """Fetch from Newsdata.io. Returns normalised article list.
    Note: from_date filtering requires a paid plan; free tier returns recent news."""
    if not config.NEWSDATA_API_KEY:
        return []
    try:
        resp = requests.get(
            "https://newsdata.io/api/1/news",
            params={
                "apikey": config.NEWSDATA_API_KEY,
                "q": query,
                "language": "en",
            },
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
        return [
            {
                "title": a.get("title") or "",
                "description": a.get("description") or "",
                "publishedAt": a.get("pubDate") or "",
            }
            for a in results
            if a.get("title")
        ]
    except Exception as exc:
        logger.warning("Newsdata.io fetch failed for %r: %s", query, exc)
        return []


def _newsapi_fetch(query: str, days: int = 3) -> list[dict]:
    """Fallback: fetch from NewsAPI. Returns normalised article list."""
    if not config.NEWS_API_KEY:
        return []
    from_date = (date.today() - timedelta(days=days)).isoformat()
    try:
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "from": from_date,
                "sortBy": "relevancy",
                "language": "en",
                "pageSize": 10,
                "apiKey": config.NEWS_API_KEY,
            },
            timeout=10,
        )
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
        return [
            {
                "title": a.get("title") or "",
                "description": a.get("description") or "",
                "publishedAt": a.get("publishedAt") or "",
            }
            for a in articles
            if a.get("title")
        ]
    except Exception as exc:
        logger.warning("NewsAPI fetch failed for %r: %s", query, exc)
        return []


def _fetch_news(query: str, days: int = 3) -> list[dict]:
    """Try Newsdata.io first, fall back to NewsAPI, then return empty."""
    articles = _newsdata_fetch(query, days)
    if not articles:
        articles = _newsapi_fetch(query, days)
    return articles


def get_ticker_news(ticker: str, days: int = 3) -> list[dict]:
    cache_key = f"news:{ticker}:{days}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    articles = _fetch_news(ticker, days)
    set_cache(cache_key, articles, ttl_seconds=3600)
    return articles


def prefetch_sector_news(sector_groups: dict[str, list[str]], days: int = 7) -> None:
    """Batch-prefetch news for entire sectors, fan results to per-ticker cache."""
    for sector, tickers in sector_groups.items():
        if not tickers:
            continue

        first_key = f"news:{tickers[0]}:{days}"
        if get_cache(first_key) is not None:
            continue

        q = " OR ".join(tickers)
        try:
            articles = _fetch_news(q, days)
        except Exception as exc:
            logger.warning("prefetch_sector_news failed for %s: %s", sector, exc)
            continue

        patterns = {t: re.compile(rf"\b{re.escape(t)}\b") for t in tickers}
        for ticker in tickers:
            pat = patterns[ticker]
            ticker_articles = [
                a for a in articles
                if a.get("title") and pat.search(
                    f"{a.get('title','')} {a.get('description','')}"
                )
            ]
            set_cache(f"news:{ticker}:{days}", ticker_articles, ttl_seconds=86400)
