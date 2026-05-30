import logging
import re
import requests
from datetime import date, timedelta
from data.cache import get_cache, set_cache
import config


logger = logging.getLogger(__name__)


class _NewsAPIClient:
    """Thin wrapper around the NewsAPI /v2/everything endpoint.

    Exposed as a module-level ``newsapi`` object so callers (and tests) can
    patch ``data.news.newsapi`` to stub network calls.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def get_everything(
        self,
        q: str,
        language: str = "en",
        pageSize: int = 100,
        sortBy: str = "publishedAt",
        from_param: str | None = None,
    ) -> dict:
        params = {
            "q": q,
            "language": language,
            "pageSize": pageSize,
            "sortBy": sortBy,
            "apiKey": self._api_key,
        }
        if from_param is not None:
            params["from"] = from_param
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()


newsapi = _NewsAPIClient(config.NEWS_API_KEY)


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


def prefetch_sector_news(sector_groups: dict[str, list[str]], days: int = 7) -> None:
    """Batch-prefetch news for entire sectors in a single NewsAPI call each.

    For each sector, builds an OR-query of all its tickers, fetches once, then
    fans the relevant articles out to per-ticker cache entries so subsequent
    ``get_ticker_news`` / scoring calls are served from cache instead of
    burning the NewsAPI free-tier quota.

    Args:
        sector_groups: mapping of sector name -> list of ticker symbols.
        days: lookback window in days (also used in cache key).
    """
    for sector, tickers in sector_groups.items():
        if not tickers:
            continue

        # Skip if we already prefetched this sector (first ticker has cache).
        first_key = f"news:{tickers[0]}:{days}"
        if get_cache(first_key) is not None:
            continue

        q = " OR ".join(tickers)
        from_date = (date.today() - timedelta(days=days)).isoformat()

        try:
            response = newsapi.get_everything(
                q=q,
                language="en",
                pageSize=100,
                sortBy="publishedAt",
                from_param=from_date,
            )
        except Exception as exc:  # noqa: BLE001 — silently continue per spec
            logger.warning(
                "prefetch_sector_news failed for sector %s: %s",
                sector,
                exc,
            )
            continue

        articles = response.get("articles", []) if response else []

        patterns = {
            t: re.compile(rf"\b{re.escape(t)}\b")
            for t in tickers
        }

        for ticker in tickers:
            pat = patterns[ticker]
            ticker_articles: list[dict] = []
            for a in articles:
                title = a.get("title") or ""
                description = a.get("description") or ""
                if not title:
                    continue  # skip [Removed] placeholders
                if pat.search(f"{title} {description}"):
                    ticker_articles.append(
                        {
                            "title": title,
                            "description": description,
                            "publishedAt": a.get("publishedAt") or "",
                        }
                    )
            set_cache(
                f"news:{ticker}:{days}",
                ticker_articles,
                ttl_seconds=86400,
            )
