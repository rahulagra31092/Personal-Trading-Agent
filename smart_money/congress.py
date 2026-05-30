import logging
from datetime import datetime, timedelta, timezone

import requests

from data.cache import get_cache, set_cache
import config

logger = logging.getLogger(__name__)

_QUIVER_API_KEY: str | None = config.QUIVER_API_KEY
_QUIVER_BASE = "https://api.quiverquant.com/beta"


def get_congress_trades(ticker: str) -> list[dict]:
    ticker = ticker.strip().upper()
    cache_key = f"congress:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    if not _QUIVER_API_KEY:
        return []

    try:
        resp = requests.get(
            f"{_QUIVER_BASE}/historical/congresstrading/{ticker}",
            headers={"Authorization": f"Token {_QUIVER_API_KEY}"},
            timeout=10,
        )
        resp.raise_for_status()
        trades = resp.json()
    except Exception as exc:
        logger.warning("Congress trades fetch failed for %s: %s", ticker, exc)
        return []

    set_cache(cache_key, trades, ttl_seconds=6 * 3600)
    return trades


def compute_congress_score(ticker: str, lookback_days: int = 90) -> float:
    trades = get_congress_trades(ticker)
    if not trades:
        return 0.5

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    buys = 0
    sells = 0

    for trade in trades:
        try:
            date_str = trade.get("Date") or trade.get("TransactionDate") or ""
            if not date_str:
                continue
            trade_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if trade_date.tzinfo is None:
                trade_date = trade_date.replace(tzinfo=timezone.utc)
            if trade_date < cutoff:
                continue
            txn = (trade.get("Transaction") or "").lower()
            if "purchase" in txn or "buy" in txn:
                buys += 1
            elif "sale" in txn or "sell" in txn:
                sells += 1
        except Exception:
            continue

    total = buys + sells
    if total == 0:
        return 0.5

    # Scale to [0.3, 0.7]: 0.3 = all sells, 0.7 = all buys
    return round(0.3 + (buys / total) * 0.4, 4)
