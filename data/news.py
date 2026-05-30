import requests
from datetime import date, timedelta
from data.cache import get_cache, set_cache
import config


def get_ticker_news(ticker: str, days: int = 3) -> list[dict]:
    cache_key = f"news:{ticker}:{days}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    from_date = (date.today() - timedelta(days=days)).isoformat()
    resp = requests.get(
        "https://newsapi.org/v2/everything",
        params={
            "q": ticker,
            "from": from_date,
            "sortBy": "relevancy",
            "language": "en",
            "pageSize": 10,
            "apiKey": config.NEWS_API_KEY,
        },
        timeout=10,
    )
    resp.raise_for_status()

    result = [
        {
            "title": a.get("title") or "",
            "description": a.get("description") or "",
            "publishedAt": a.get("publishedAt") or "",
        }
        for a in resp.json().get("articles", [])
        if a.get("title")  # skip [Removed] placeholder articles
    ]
    set_cache(cache_key, result, ttl_seconds=3600)
    return result
