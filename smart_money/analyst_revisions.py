import logging
from datetime import datetime, timedelta, timezone
import yfinance as yf

from data.cache import get_cache, set_cache
from util.timeout import timeout
from util.data_health import record_fetch

logger = logging.getLogger(__name__)

_ET = timezone(timedelta(hours=-5))


@timeout(15, default=[])
def get_analyst_revisions_history(ticker: str, days: int = 1095) -> list[dict]:
    """
    Fetch historical analyst estimate revisions from yfinance.

    Returns list of analyst activity over past 1095 days (3 years).
    yfinance.Ticker.info includes:
    - numberOfAnalystRatings
    - targetMeanPrice
    - targetMedianPrice
    - targetHighPrice
    - targetLowPrice

    We treat changes to these targets as "revision signals" for backtesting.
    """
    ticker = ticker.strip().upper()
    cache_key = f"analyst_revisions_history:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    try:
        t = yf.Ticker(ticker)
        info = t.info

        if not info:
            logger.debug("No analyst info for %s", ticker)
            return []

        # Extract analyst consensus snapshot
        # NOTE: yfinance only gives current consensus, not historical revisions
        # For true historical revisions, would need paid API (Morningstar, FactSet)
        # For now, store current consensus as a point-in-time snapshot

        revisions = []

        current_consensus = {
            "date": datetime.now(_ET).isoformat(),
            "num_analysts": info.get("numberOfAnalystRatings", 0),
            "target_mean": info.get("targetMeanPrice"),
            "target_median": info.get("targetMedianPrice"),
            "target_high": info.get("targetHighPrice"),
            "target_low": info.get("targetLowPrice"),
            "recommendation": info.get("recommendationKey", "hold"),  # strong_buy, buy, hold, sell, strong_sell
        }

        # Filter out None values
        current_consensus = {k: v for k, v in current_consensus.items() if v is not None}

        if current_consensus.get("num_analysts", 0) > 0:
            revisions.append(current_consensus)

        record_fetch("analyst_revisions", success=True)
        set_cache(cache_key, revisions, ttl_seconds=86400)  # 24h cache
        return revisions

    except Exception as exc:
        logger.warning("Analyst revisions fetch failed for %s: %s", ticker, exc)
        record_fetch("analyst_revisions", success=False)
        return []


def compute_analyst_revision_trend(ticker: str) -> float:
    """
    Score analyst revisions trend [0, 1].

    LIMITATION: yfinance does not provide historical revision changes.
    This function returns 0.5 (neutral) as placeholder.

    For production backtesting, would need:
    - Morningstar API (paid)
    - Yahoo Finance Premium (paid)
    - Manual SEC Edgar filing parsing (complex)

    Current implementation: Compare current consensus to known baseline (not available).
    """
    revisions = get_analyst_revisions_history(ticker)
    if not revisions:
        return 0.5

    # For now, return neutral
    # Real implementation would track analyst estimate revisions over time
    # and score upward when estimates are being raised, downward when cut
    return 0.5
