import logging
from typing import Optional

import yfinance as yf

from data.cache import get_cache, set_cache

logger = logging.getLogger(__name__)


def _roe_score(roe: float) -> float:
    return max(0.20, min(0.85, 0.35 + roe * 1.5))


def _gm_score(gm: float) -> float:
    return max(0.20, min(0.85, 0.20 + gm * 0.8125))


def compute_quality_score(ticker: str) -> float:
    """Quality factor score in [0.20, 0.85] using ROE and gross margin. Cached 7 days."""
    cache_key = f"quality:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    try:
        info = yf.Ticker(ticker).info or {}
        roe: Optional[float] = info.get("returnOnEquity")
        gm: Optional[float] = info.get("grossMargins")

        if roe is None and gm is None:
            return 0.5

        scores = []
        if roe is not None:
            scores.append(_roe_score(float(roe)))
        if gm is not None:
            scores.append(_gm_score(float(gm)))

        score = round(sum(scores) / len(scores), 4)
        set_cache(cache_key, score, ttl_seconds=604800)  # 7 days
        return score

    except Exception as exc:
        logger.warning("quality score failed for %s: %s", ticker, exc)
        return 0.5
