import yfinance as yf
import pandas as pd
from datetime import date, datetime, timedelta, timezone  # date kept for days_to_earnings arithmetic
from zoneinfo import ZoneInfo
from data.cache import get_cache, set_cache
from util.timeout import timeout
from util.data_health import record_fetch
import logging

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")


def get_earnings_calendar(ticker: str) -> dict:
    cache_key = f"earnings:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    t = yf.Ticker(ticker)
    info = t.info or {}

    result: dict = {
        "next_earnings_date": None,
        "eps_estimate": info.get("forwardEps"),
        "earnings_quarterly_growth": info.get("earningsQuarterlyGrowth"),
        **_calculate_eps_stats(t),
    }

    try:
        cal = t.calendar
        if cal is not None and not cal.empty and "Earnings Date" in cal.index:
            raw = cal.loc["Earnings Date"].iloc[0]
            if pd.notna(raw):
                ts = pd.Timestamp(raw)
                result["next_earnings_date"] = str(
                    ts.tz_convert(_ET).date() if ts.tzinfo else ts.date()
                )
    except Exception:
        pass

    set_cache(cache_key, result, ttl_seconds=21600)  # 6 hours for freshness on earnings calendar
    return result


def days_to_earnings(ticker: str) -> int | None:
    cal = get_earnings_calendar(ticker)
    if not cal.get("next_earnings_date"):
        return None
    today_et = datetime.now(_ET).date()
    return (date.fromisoformat(cal["next_earnings_date"]) - today_et).days


def get_eps_beat_rate(ticker: str) -> float | None:
    """Return fraction of last N quarters where EPS beat estimate, or None if unavailable.

    Propagates any exception raised by get_earnings_calendar (e.g. network errors).
    """
    cal = get_earnings_calendar(ticker)
    return cal.get("eps_beat_rate")


def _calculate_eps_stats(ticker_obj: yf.Ticker) -> dict:
    """Return eps_beat_rate, avg_surprise_pct, last_beat from earnings_history."""
    base = {"eps_beat_rate": None, "avg_surprise_pct": None, "last_beat": None}
    try:
        history = ticker_obj.earnings_history
        if history is None or history.empty:
            return base
        pcts = history["surprisePercent"].dropna()
        if pcts.empty:
            return base
        total = len(pcts)
        beats = int((pcts > 0).sum())
        return {
            "eps_beat_rate": round(beats / total, 2),
            "avg_surprise_pct": round(float(pcts.mean()), 4),
            "last_beat": bool(pcts.iloc[0] > 0),
        }
    except Exception:
        return base


@timeout(15, default=[])
def get_earnings_calendar_history(ticker: str, years: int = 3) -> list[dict]:
    """
    Fetch historical earnings dates from yfinance (past 3 years).

    This returns past earnings announcement dates for backtesting.
    yfinance's Ticker.earnings_dates is a pandas DataFrame with:
    - Index: date of earnings announcement
    - Columns: EPS estimate, EPS actual, surprise %
    """
    ticker = ticker.strip().upper()
    cache_key = f"earnings_history:{ticker}:{years}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    try:
        t = yf.Ticker(ticker)
        earnings_df = t.earnings_dates  # pandas DataFrame

        if earnings_df is None or earnings_df.empty:
            logger.debug("No earnings history for %s", ticker)
            record_fetch("earnings_calendar", success=True)
            return []

        # Convert DataFrame to list of dicts
        earnings = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=365 * years)

        for date_idx, row in earnings_df.iterrows():
            try:
                # Handle pandas Timestamp
                if hasattr(date_idx, 'to_pydatetime'):
                    parsed_date = date_idx.to_pydatetime()
                else:
                    parsed_date = date_idx

                # Compare dates properly
                if hasattr(parsed_date, 'replace'):
                    if parsed_date.tzinfo is None:
                        parsed_date = parsed_date.replace(tzinfo=timezone.utc)
                    if parsed_date < cutoff:
                        continue
                else:
                    continue

                earnings.append({
                    "date": parsed_date.isoformat() if hasattr(parsed_date, "isoformat") else str(parsed_date),
                    "eps_estimate": float(row.get("Estimated Earnings", 0)) if row.get("Estimated Earnings") else None,
                    "eps_actual": float(row.get("Reported Earnings", 0)) if row.get("Reported Earnings") else None,
                    "surprise_pct": float(row.get("Surprise(%)", 0)) if row.get("Surprise(%)") else None,
                })
            except Exception as e:
                logger.debug("Failed to parse earnings row: %s", e)
                continue

        record_fetch("earnings_calendar", success=True)
        set_cache(cache_key, earnings, ttl_seconds=604800)  # 7-day cache for history
        return earnings

    except Exception as exc:
        logger.warning("Earnings history fetch failed for %s: %s", ticker, exc)
        record_fetch("earnings_calendar", success=False)
        return []
