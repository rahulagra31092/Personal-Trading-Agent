import logging
import math
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

from data.cache import get_cache, set_cache

logger = logging.getLogger(__name__)

# Maps broad sector names to a representative ETF ticker
SECTOR_ETF_MAP: dict[str, str] = {
    "tech": "XLK",
    "financials": "XLF",
    "healthcare": "XLV",
    "consumer_discretionary": "XLY",
    "consumer_staples": "XLP",
    "energy": "XLE",
    "industrials": "XLI",
    "materials": "XLB",
    "real_estate": "XLRE",
    "utilities": "XLU",
    "comm_services": "XLC",
}

# Narrow sub-sectors where concentration risk is high — limit 2 picks per group
NARROW_SUB_SECTORS: list[list[str]] = [
    ["KKR", "BX", "ARES", "APO", "CG"],      # alternative asset managers
    ["LRCX", "AMAT", "KLAC", "ANET"],         # semiconductor equipment
    ["PANW", "CRWD", "ZS", "FTNT", "NET"],    # cybersecurity
    ["MU", "NVDA", "AMD", "AVGO", "QCOM"],    # semis
    ["AMZN", "MSFT", "GOOGL", "META", "AAPL"],# mega-cap tech
]

MAX_PER_SUB_SECTOR = 2


def get_sector_momentum(sector: str) -> Optional[float]:
    """Return trailing 3-month return for the sector's ETF, or None on failure."""
    etf = SECTOR_ETF_MAP.get(sector)
    if etf is None:
        return None

    cache_key = f"sector_momentum:{sector}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    try:
        end = date.today()
        start = end - timedelta(days=92)  # ~3 months + buffer
        hist = yf.download(etf, start=str(start), end=str(end),
                           progress=False, auto_adjust=True)
        if hist is None or hist.empty or len(hist) < 10:
            return None

        # Handle multi-level columns from yfinance
        if isinstance(hist.columns, pd.MultiIndex):
            # yfinance may have (field, ticker) or (ticker, field) as level order
            if "Close" in hist.columns.get_level_values(0):
                hist.columns = hist.columns.get_level_values(0)
            else:
                hist.columns = hist.columns.get_level_values(1)

        close = hist["Close"].dropna()
        if len(close) < 10:
            return None
        first_close = float(close.iloc[0])
        last_close = float(close.iloc[-1])
        if first_close == 0 or not math.isfinite(first_close) or not math.isfinite(last_close):
            return None
        momentum = (last_close - first_close) / first_close

        set_cache(cache_key, momentum, ttl_seconds=86400)
        return momentum

    except Exception as exc:
        logger.warning("sector momentum failed for %s (%s): %s", sector, etf, exc)
        return None


def sector_weight_multiplier(sector: str) -> float:
    """Return a position-weight multiplier based on sector momentum.

    Top tercile (momentum >= 0.05):  1.05  (add 5% to weight)
    Bottom tercile (momentum <= -0.05): 0.90  (cut 10% from weight)
    Middle:                              1.00  (no change)
    """
    momentum = get_sector_momentum(sector)
    if momentum is None:
        return 1.0
    if momentum >= 0.05:
        return 1.05
    if momentum <= -0.05:
        return 0.90
    return 1.0


def apply_concentration_cap(
    ranked_tickers: list[str],
    max_per_sub_sector: int = MAX_PER_SUB_SECTOR,
) -> list[str]:
    """Remove tickers beyond max_per_sub_sector within each narrow sub-sector cluster.

    ranked_tickers is ordered best-first. The top N tickers in each cluster
    are kept; excess tickers are removed from the list entirely.

    Returns a new list preserving original order of survivors.
    """
    cluster_counts: dict[int, int] = {}  # cluster_index -> count of kept tickers
    result = []

    for ticker in ranked_tickers:
        cluster_idx = _find_cluster(ticker)
        if cluster_idx is None:
            # Not in any narrow sub-sector — always keep
            result.append(ticker)
        else:
            count = cluster_counts.get(cluster_idx, 0)
            if count < max_per_sub_sector:
                result.append(ticker)
                cluster_counts[cluster_idx] = count + 1
            # else: drop (over cap)

    return result


def _find_cluster(ticker: str) -> Optional[int]:
    """Return the cluster index for ticker, or None if not in any cluster."""
    for idx, cluster in enumerate(NARROW_SUB_SECTORS):
        if ticker in cluster:
            return idx
    return None
