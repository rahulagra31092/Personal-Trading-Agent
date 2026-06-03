import logging
from typing import Optional

import yfinance as yf

from data.cache import get_cache, set_cache

logger = logging.getLogger(__name__)

# Factor weights — must sum to 1.0
_WEIGHTS = {"roe": 0.35, "fcf": 0.30, "gm": 0.20, "debt": 0.15}


def _roe_score(roe: float) -> float:
    """ROE → [0,1]: 25% ROE = 1.0, 0% = 0.5, -25% = 0.0."""
    return min(1.0, max(0.0, 0.5 + roe * 2.0))


def _fcf_score(fcf_margin: float) -> float:
    """FCF/revenue → [0,1]: 10% margin = 1.0, 0% = 0.5, -10% = 0.0."""
    return min(1.0, max(0.0, 0.5 + fcf_margin * 5.0))


def _gm_score(gm: float) -> float:
    """Gross margin → [0,1]: 80% = 1.0, 0% = 0.0, linear."""
    return min(1.0, max(0.0, gm * 1.25))


def _debt_score(de: float) -> float:
    """D/E ratio → [0,1]: 0x = 1.0, 3x = 0.55, 6.7x+ = 0.0."""
    return min(1.0, max(0.0, 1.0 - de * 0.15))


def compute_quality_score(ticker: str) -> float:
    """
    Quality factor: ROE 35% · FCF margin 30% · Gross margin 20% · Debt 15%.
    Missing factors are excluded and weights renormalized — partial data is fine.
    Cached 7 days (fundamental data changes quarterly).
    """
    cache_key = f"quality:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    try:
        info = yf.Ticker(ticker).info or {}
        scores: dict[str, float] = {}

        roe: Optional[float] = info.get("returnOnEquity")
        if roe is not None:
            scores["roe"] = _roe_score(float(roe))

        fcf = info.get("freeCashflow")
        rev = info.get("totalRevenue")
        if fcf is not None and rev is not None and float(rev) > 0:
            scores["fcf"] = _fcf_score(float(fcf) / float(rev))

        gm: Optional[float] = info.get("grossMargins")
        if gm is not None:
            scores["gm"] = _gm_score(float(gm))

        # yfinance returns debtToEquity as a percentage (45 = 0.45x D/E).
        # Skip for financial companies where extreme leverage is structural (de_raw > 500).
        de_raw: Optional[float] = info.get("debtToEquity")
        if de_raw is not None:
            de_raw_f = float(de_raw)
            if 0.0 <= de_raw_f <= 500.0:
                scores["debt"] = _debt_score(de_raw_f / 100.0)

        if not scores:
            return 0.5

        total_w = sum(_WEIGHTS[k] for k in scores)
        score = sum(scores[k] * _WEIGHTS[k] / total_w for k in scores)
        result = round(min(1.0, max(0.0, score)), 4)
        set_cache(cache_key, result, ttl_seconds=604800)
        return result

    except Exception as exc:
        logger.warning("quality score failed for %s: %s", ticker, exc)
        return 0.5
