import logging
from typing import Optional

import yfinance as yf
import pandas as pd

from data.cache import get_cache, set_cache
import config

logger = logging.getLogger(__name__)

_FALLBACK = {"regime": "normal", "vix": 20.0, "position_factor": 1.0, "max_positions": 70}

_THRESHOLDS = [
    (15,  "low_vol",  1.00, 70),
    (20,  "normal",   1.00, 70),
    (25,  "elevated", 0.85, 60),
    (30,  "high",     0.70, 50),
    (999, "crisis",   0.50, 35),
]


def _classify(vix: float) -> dict:
    for threshold, regime, factor, max_pos in _THRESHOLDS:
        if vix < threshold:
            return {"regime": regime, "vix": round(vix, 2),
                    "position_factor": factor, "max_positions": max_pos}
    return {**_FALLBACK, "vix": round(vix, 2)}


def get_regime_weights(regime_name: str) -> dict[str, float]:
    """Return the signal weight dict for the given regime name."""
    return config.REGIME_WEIGHTS.get(regime_name, config.SIGNAL_WEIGHTS)


def get_market_regime(as_of_date: Optional[str] = None) -> dict:
    """VIX-based market regime. Cached 1 hour. Returns regime/vix/position_factor/max_positions."""
    cache_key = f"regime:{as_of_date or 'live'}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    try:
        end = as_of_date if as_of_date else None
        hist: pd.DataFrame = yf.download("^VIX", period="5d", progress=False,
                                          auto_adjust=True, end=end)

        if hist is None or hist.empty:
            return _FALLBACK

        if isinstance(hist.columns, pd.MultiIndex):
            close_col = hist["Close"]
            if isinstance(close_col, pd.DataFrame):
                close_col = close_col.iloc[:, 0]
            hist = close_col.to_frame(name="Close")

        closes = hist["Close"].dropna()
        if closes.empty:
            return _FALLBACK

        vix = float(closes.iloc[-1])
        result = _classify(vix)
        set_cache(cache_key, result, ttl_seconds=3600)
        return result

    except Exception as exc:
        logger.warning("regime detection failed: %s", exc)
        return _FALLBACK
