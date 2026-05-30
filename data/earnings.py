import yfinance as yf
import pandas as pd
from datetime import date
from data.cache import get_cache, set_cache


def get_earnings_calendar(ticker: str) -> dict:
    cache_key = f"earnings:{ticker}"
    cached = get_cache(cache_key)
    if cached:
        return cached

    t = yf.Ticker(ticker)
    info = t.info or {}

    result: dict = {
        "next_earnings_date": None,
        "eps_estimate": info.get("forwardEps"),
        "eps_beat_rate": _calculate_beat_rate(t),
    }

    try:
        cal = t.calendar
        if cal is not None and not cal.empty and "Earnings Date" in cal.index:
            raw = cal.loc["Earnings Date"].iloc[0]
            if pd.notna(raw):
                result["next_earnings_date"] = str(pd.Timestamp(raw).date())
    except Exception:
        pass

    set_cache(cache_key, result, ttl_seconds=86400)
    return result


def days_to_earnings(ticker: str) -> int | None:
    cal = get_earnings_calendar(ticker)
    if not cal.get("next_earnings_date"):
        return None
    return (date.fromisoformat(cal["next_earnings_date"]) - date.today()).days


def _calculate_beat_rate(ticker_obj: yf.Ticker) -> float | None:
    try:
        history = ticker_obj.earnings_history
        if history is None or history.empty:
            return None
        total = len(history)
        beats = int((history["surprisePercent"] > 0).sum())
        return round(beats / total, 2) if total > 0 else None
    except Exception:
        return None
