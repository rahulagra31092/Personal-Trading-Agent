import logging
from datetime import datetime, timedelta, timezone

import requests
import yfinance as yf

from data.cache import get_cache, set_cache
from smart_money.trump_scorer import compute_trump_modifier
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


def _institutional_adjustment(ticker: str) -> float:
    """Return discrete adjustment in {-0.05, 0.0, +0.05}:
    +0.05 if institutional ownership >= 70%, -0.05 if <= 30%, else 0.0.
    """
    cache_key = f"inst_adj:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    try:
        holders = yf.Ticker(ticker).major_holders
        if holders is None or holders.empty:
            return 0.0

        pct: float
        # Try newer named-index shape first (floats 0.0-1.0)
        if hasattr(holders.index, '__contains__') and "institutionsPercentHeld" in holders.index:
            pct = float(holders.loc["institutionsPercentHeld"].iloc[0])
        else:
            # Legacy shape: row 1, col 0 is a percent string like "75.00%"
            raw = holders.iloc[1, 0]
            pct = float(str(raw).replace("%", "").strip()) / 100.0

        if pct >= 0.70:
            result = 0.05
        elif pct <= 0.30:
            result = -0.05
        else:
            result = 0.0

        set_cache(cache_key, result, ttl_seconds=86400)
        return result

    except (IndexError, KeyError, ValueError, TypeError) as exc:
        logger.warning("institutional adjustment parse failed for %s: %s", ticker, exc)
        return 0.0
    except Exception as exc:
        logger.warning("institutional adjustment unexpected error for %s: %s", ticker, exc)
        return 0.0


def compute_congress_score(ticker: str, lookback_days: int = 180) -> float:
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

    # Base signal: 0.3 = all sells, 0.7 = all buys
    base_score = 0.3 + (buys / total) * 0.4
    adjustment = _institutional_adjustment(ticker)

    # Blend in White House policy direction: congress 60%, Trump signal 40%
    # Normalise trump modifier [-0.15, +0.15] -> component centred on 0.5
    trump_component = 0.5 + compute_trump_modifier(ticker)
    blended = base_score * 0.60 + trump_component * 0.40

    score = round(max(0.20, min(0.80, blended + adjustment)), 4)
    return score
