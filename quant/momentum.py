import math
import logging
from typing import Optional

import yfinance as yf
import pandas as pd

from data.cache import get_cache, set_cache

logger = logging.getLogger(__name__)

_REFERENCE_VOL = 0.02
_MIN_BARS = 200
_LOOKBACK_12M = 252
_LOOKBACK_1M = 21


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def compute_momentum_score_from_bars(bars: list[dict]) -> float:
    """12-1 month cross-sectional momentum from pre-loaded OHLCV bars (dicts with 'c' key)."""
    if len(bars) < _MIN_BARS:
        return 0.5
    try:
        closes = [b["c"] for b in bars]
        price_12m = closes[-_LOOKBACK_12M]
        price_1m = closes[-_LOOKBACK_1M]
        if price_12m <= 0:
            return 0.5
        ret = (price_1m - price_12m) / price_12m
        return round(_sigmoid(ret * 3), 4)
    except Exception:
        return 0.5


def compute_momentum_score(ticker: str, signal_date: Optional[str] = None) -> float:
    """12-1 month price momentum factor score in [0, 1]. Cached 24h."""
    cache_key = f"momentum:{ticker}:{signal_date or 'live'}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    try:
        end = signal_date if signal_date else None
        hist: pd.DataFrame = yf.download(ticker, period="13mo", progress=False,
                                          auto_adjust=True, end=end)

        if isinstance(hist.columns, pd.MultiIndex):
            if "Close" in hist.columns.get_level_values(0):
                hist = hist["Close"].to_frame(name="Close")
            else:
                hist.columns = hist.columns.droplevel(1)

        if "Close" not in hist.columns or len(hist) < _MIN_BARS:
            return 0.5

        closes = hist["Close"].dropna().tolist()
        if len(closes) < _MIN_BARS:
            return 0.5

        price_12m = closes[-_LOOKBACK_12M]
        price_1m = closes[-_LOOKBACK_1M]
        if price_12m <= 0:
            return 0.5

        ret = (price_1m - price_12m) / price_12m
        score = round(_sigmoid(ret * 3), 4)
        set_cache(cache_key, score, ttl_seconds=86400)
        return score

    except Exception as exc:
        logger.warning("momentum score failed for %s: %s", ticker, exc)
        return 0.5
