import logging
from typing import Optional
import pandas as pd
import yfinance as yf

from data.cache import get_cache, set_cache

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400  # 24h — analyst revisions change slowly

_UPGRADE_WORDS = frozenset({"buy", "outperform", "overweight", "strong buy", "accumulate", "positive"})
_DOWNGRADE_WORDS = frozenset({"sell", "underperform", "underweight", "strong sell", "reduce", "negative"})


def _grade_direction(grade: str) -> int:
    """Return +1 for upgrade-type grade, -1 for downgrade-type, 0 for neutral."""
    g = grade.lower().strip()
    if any(w in g for w in _UPGRADE_WORDS):
        return 1
    if any(w in g for w in _DOWNGRADE_WORDS):
        return -1
    return 0


def _score_from_grades(df: pd.DataFrame) -> Optional[float]:
    """
    Score from recent analyst grade changes. Returns None if insufficient data.
    Filters to last 30 days. Net score: 0.5 + (upgrades - downgrades) / total * 0.40.
    """
    if df is None or df.empty:
        return None

    try:
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30)
        idx = df.index
        if idx.tz is None:
            cutoff = cutoff.tz_localize(None)
        recent = df[idx >= cutoff]
    except Exception:
        return None

    if recent.empty:
        return None

    if "ToGrade" not in recent.columns:
        return None
    to_col = "ToGrade"

    directions = [_grade_direction(str(g)) for g in recent[to_col]]
    total = len(directions)
    if total == 0:
        return None

    upgrades = sum(1 for d in directions if d == 1)
    downgrades = sum(1 for d in directions if d == -1)
    net = 0.5 + (upgrades - downgrades) / total * 0.40
    return round(min(0.95, max(0.05, net)), 4)


def _score_from_rec_mean(info: dict) -> Optional[float]:
    """Fallback: map recommendationMean (1=Strong Buy, 5=Strong Sell) → [0,1]."""
    rec_mean = info.get("recommendationMean")
    if rec_mean is None:
        return None
    return round(min(1.0, max(0.0, (5.0 - float(rec_mean)) / 4.0)), 4)


def compute_estimate_revision_score(ticker: str) -> float:
    """
    Analyst estimate revision signal [0, 1].
    Primary: net analyst grade changes (upgrades vs downgrades) in last 30 days.
    Fallback: consensus recommendation mean from yfinance info.
    Returns 0.5 (neutral) when data is unavailable.
    Cached 24h.
    """
    cache_key = f"est_revision:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return float(cached)

    try:
        t = yf.Ticker(ticker)
        grade_score = _score_from_grades(t.upgrades_downgrades)

        if grade_score is not None:
            result = grade_score
        else:
            rec_score = _score_from_rec_mean(t.info or {})
            result = rec_score if rec_score is not None else 0.5

        set_cache(cache_key, result, ttl_seconds=_CACHE_TTL)
        return result

    except Exception as exc:
        logger.warning("Estimate revision score failed for %s: %s", ticker, exc, exc_info=True)
        return 0.5
