import math
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from data.earnings import get_earnings_calendar
from util.timeout import timeout
from util.data_health import record_fetch

_ET = ZoneInfo("America/New_York")
logger = logging.getLogger(__name__)

_WEIGHTS = {"beat_rate": 0.45, "surprise": 0.35, "growth": 0.20}


def _beat_rate_score(rate: float) -> float:
    """Map EPS beat rate [0,1] → score [0,1]. 50% beat rate → 0.5, 75% → 1.0."""
    return min(1.0, max(0.0, 0.5 + (rate - 0.5) * 2.0))


def _surprise_score(avg_pct: float) -> float:
    """Map average EPS surprise % → [0,1] via tanh. +25% avg → ~0.88, 0% → 0.5."""
    return round(0.5 + 0.5 * math.tanh(avg_pct / 25.0), 4)


def _growth_score(growth: float) -> float:
    """Map earningsQuarterlyGrowth → [0,1]. +25% growth → 1.0, 0% → 0.5, -25% → 0.0."""
    return min(1.0, max(0.0, 0.5 + growth * 2.0))


@timeout(15, default=0.5)
def compute_earnings_score(ticker: str) -> float:
    """
    EPS quality signal [0, 1].
    Composite of beat rate (45%), average surprise magnitude (35%), earnings growth (20%).
    PEAD modifier applied when last quarter result is known; pre-earnings uncertainty discount
    applied when earnings are 1-7 days out. Missing factors renormalize weights automatically.
    """
    try:
        cal = get_earnings_calendar(ticker)
        record_fetch("earnings_calendar", success=True)
    except Exception as exc:
        logger.warning("earnings calendar failed for %s: %s", ticker, exc)
        record_fetch("earnings_calendar", success=False)
        return 0.5

    scores: dict[str, float] = {}

    beat_rate = cal.get("eps_beat_rate")
    if beat_rate is not None:
        scores["beat_rate"] = _beat_rate_score(beat_rate)

    avg_surprise = cal.get("avg_surprise_pct")
    if avg_surprise is not None:
        scores["surprise"] = _surprise_score(avg_surprise)

    growth = cal.get("earnings_quarterly_growth")
    if growth is not None:
        scores["growth"] = _growth_score(growth)

    if not scores:
        return 0.5

    total_w = sum(_WEIGHTS[k] for k in scores)
    base = sum(scores[k] * _WEIGHTS[k] / total_w for k in scores)

    modifier = 0.0
    raw_date = cal.get("next_earnings_date")
    last_beat = cal.get("last_beat")
    if raw_date:
        try:
            today = datetime.now(_ET).date()
            days = (date.fromisoformat(raw_date) - today).days
            if -60 <= days <= 0:
                if last_beat is True:
                    modifier = 0.07   # PEAD: post-beat momentum
                elif last_beat is False:
                    modifier = -0.05  # Post-miss drift
            elif 1 <= days <= 3:
                modifier = -0.07  # Imminent earnings uncertainty
            elif 4 <= days <= 7:
                modifier = -0.05  # Near-term uncertainty
        except Exception:
            pass

    return round(min(1.0, max(0.0, base + modifier)), 4)
