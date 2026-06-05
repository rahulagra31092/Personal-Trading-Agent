"""Market intelligence: index snapshot, news fetch, and investor-advisor narration."""
import logging
import re

import requests
import anthropic

from data.cache import get_cache, set_cache
import config

logger = logging.getLogger(__name__)


def get_index_snapshot() -> dict:
    """SPY/QQQ/DIA/VIX daily % changes and prices. Cached 1 hour."""
    cache_key = "market_intel:index_snapshot"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    import yfinance as yf
    import pandas as pd

    symbols = {"SPY": "S&P 500", "QQQ": "Nasdaq 100", "DIA": "Dow Jones", "^VIX": "VIX"}
    result = {}
    try:
        data = yf.download(
            list(symbols.keys()), period="2d", progress=False, auto_adjust=True
        )
        for sym, name in symbols.items():
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    closes = data["Close"][sym].dropna()
                else:
                    closes = data["Close"].dropna()
                if len(closes) >= 2:
                    prev = float(closes.iloc[-2])
                    curr = float(closes.iloc[-1])
                    pct = (curr - prev) / prev * 100
                    result[sym] = {
                        "name": name,
                        "price": round(curr, 2),
                        "pct_change": round(pct, 2),
                    }
            except Exception:
                pass
    except Exception as exc:
        logger.warning("Index snapshot failed: %s", exc)

    if result:
        set_cache(cache_key, result, ttl_seconds=3600)
    return result


def get_sector_snapshot() -> dict:
    """Major sector ETF % changes. Cached 1 hour."""
    cache_key = "market_intel:sector_snapshot"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    import yfinance as yf
    import pandas as pd

    sectors = {
        "XLK": "Tech", "XLF": "Financials", "XLE": "Energy",
        "XLV": "Healthcare", "XLI": "Industrials", "XLC": "Comms",
    }
    result = {}
    try:
        data = yf.download(
            list(sectors.keys()), period="2d", progress=False, auto_adjust=True
        )
        for sym, name in sectors.items():
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    closes = data["Close"][sym].dropna()
                else:
                    closes = data["Close"].dropna()
                if len(closes) >= 2:
                    prev = float(closes.iloc[-2])
                    curr = float(closes.iloc[-1])
                    result[sym] = {
                        "name": name,
                        "pct_change": round((curr - prev) / prev * 100, 2),
                    }
            except Exception:
                pass
    except Exception as exc:
        logger.warning("Sector snapshot failed: %s", exc)

    if result:
        set_cache(cache_key, result, ttl_seconds=3600)
    return result


def get_market_news(n: int = 12) -> list[dict]:
    """General market/business news from Newsdata.io. Cached 1 hour."""
    cache_key = "market_intel:market_news"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached[:n]

    if not config.NEWSDATA_API_KEY:
        return []

    articles = []
    # Two focused queries to stay within free-tier credit budget
    queries = [
        "stock market Federal Reserve earnings investors",
        "S&P 500 Wall Street economy interest rates",
    ]
    seen_titles: set[str] = set()

    for query in queries:
        try:
            resp = requests.get(
                "https://newsdata.io/api/1/news",
                params={
                    "apikey": config.NEWSDATA_API_KEY,
                    "q": query,
                    "language": "en",
                    "category": "business",
                },
                timeout=15,
            )
            resp.raise_for_status()
            for a in resp.json().get("results") or []:
                title = (a.get("title") or "").strip()
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    articles.append(
                        {
                            "title": title,
                            "description": (a.get("description") or "").strip(),
                            "source": a.get("source_id", ""),
                            "publishedAt": a.get("pubDate", ""),
                        }
                    )
        except Exception as exc:
            logger.warning("Market news fetch failed for %r: %s", query, exc)

    result = articles[:20]  # store up to 20, slice on return
    if result:
        set_cache(cache_key, result, ttl_seconds=3600)
    return result[:n]


def build_market_brief(
    index_snapshot: dict,
    sector_snapshot: dict,
    news: list[dict],
    top_buys: list[dict],
    top_avoids: list[dict],
    regime: dict,
    vix: float,
) -> str:
    """
    Call Claude Haiku to produce an Ivy League investor-advisor style morning brief.
    Returns plain text (no markdown bullets); 200-250 words.
    """
    # Format index line
    index_parts = []
    for sym in ("SPY", "QQQ", "DIA"):
        if sym in index_snapshot:
            d = index_snapshot[sym]
            sign = "+" if d["pct_change"] >= 0 else ""
            index_parts.append(f"{d['name']} {sign}{d['pct_change']:.1f}%")
    vix_val = index_snapshot.get("^VIX", {}).get("price", vix)
    index_line = "  |  ".join(index_parts) if index_parts else "Market data unavailable"

    # Sector leaders/laggards
    if sector_snapshot:
        sorted_sectors = sorted(sector_snapshot.values(), key=lambda x: x["pct_change"], reverse=True)
        leaders = ", ".join(f"{s['name']} {s['pct_change']:+.1f}%" for s in sorted_sectors[:2])
        laggards = ", ".join(f"{s['name']} {s['pct_change']:+.1f}%" for s in sorted_sectors[-2:])
        sector_line = f"Leading: {leaders}  |  Lagging: {laggards}"
    else:
        sector_line = ""

    # News headlines (first 10)
    news_block = "\n".join(f"- {a['title']}" for a in news[:10]) if news else "No news available."

    # Top model picks (non-technical)
    buy_names = ", ".join(r["ticker"] for r in top_buys[:5])
    avoid_names = ", ".join(r["ticker"] for r in top_avoids[:3]) if top_avoids else "none"

    regime_label = regime.get("regime", "normal").replace("_", " ")

    try:
        client = anthropic.Anthropic(api_key=config.CLAUDE_API_KEY)
        prompt = (
            f"You are an Ivy League-educated investment advisor giving your client their morning briefing. "
            f"Your client is a busy professional — smart but not a Wall Street expert. "
            f"Write in clear, confident, flowing paragraphs. No bullet points. No jargon. No emojis.\n\n"
            f"TODAY'S DATA:\n"
            f"Markets: {index_line}\n"
            f"VIX: {vix_val:.1f} ({regime_label} volatility environment)\n"
            f"{('Sectors: ' + sector_line) if sector_line else ''}\n\n"
            f"TODAY'S NEWS HEADLINES:\n{news_block}\n\n"
            f"OUR MODEL'S TOP PICKS TODAY: {buy_names or 'none yet'}\n"
            f"STOCKS WE'RE AVOIDING: {avoid_names}\n\n"
            f"WRITE A MORNING BRIEF WITH EXACTLY THESE 5 PARTS (each 1-2 sentences, no labels):\n"
            f"1. What happened in markets today and the single most important reason why.\n"
            f"2. What this news means for investors — connect the dots beyond the headline.\n"
            f"3. What institutional investors and smart money appear to be doing right now.\n"
            f"4. Why our model likes the top picks and what they have in common.\n"
            f"5. The single most important thing to watch this week.\n\n"
            f"Max 220 words total. Sound like a trusted advisor, not a newsletter."
        )
        msg = client.messages.create(
            model=config.CLAUDE_MODEL_HAIKU,
            max_tokens=350,
            messages=[{"role": "user", "content": prompt}],
        )
        if not msg.content or not msg.content[0].text:
            raise ValueError("Empty response from Claude API")
        return msg.content[0].text.strip()
    except Exception as exc:
        logger.warning("Claude market brief failed: %s", exc)
        return f"Markets: {index_line}. VIX at {vix_val:.1f} ({regime_label} volatility)."
