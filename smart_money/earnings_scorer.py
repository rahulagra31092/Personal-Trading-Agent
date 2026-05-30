import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from data.earnings import get_earnings_calendar

_ET = ZoneInfo("America/New_York")

logger = logging.getLogger(__name__)


def compute_earnings_score(ticker: str) -> float:
    try:
        cal = get_earnings_calendar(ticker)
    except Exception as exc:
        logger.warning("earnings calendar failed for %s: %s", ticker, exc)
        return 0.5

    beat_rate = cal.get("eps_beat_rate")
    if beat_rate is None:
        return 0.5

    base = 0.25 + beat_rate * 0.5

    modifier = 0.0
    raw_date = cal.get("next_earnings_date")
    if raw_date:
        try:
            days = (date.fromisoformat(raw_date) - datetime.now(_ET).date()).days
            if -60 <= days <= 0 and beat_rate > 0.5:
                # PEAD: post-earnings drift favors recent beaters for up to 60 days
                modifier = 0.05
            elif 1 <= days <= 7:
                # Pre-earnings uncertainty discount
                modifier = -0.05
        except Exception:
            pass

    return round(max(0.20, min(0.80, base + modifier)), 4)
