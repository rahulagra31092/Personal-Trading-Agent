import math
import logging
from typing import Optional

import yfinance as yf
import pandas as pd

from data.cache import get_cache, set_cache

logger = logging.getLogger(__name__)

_LOOKBACK_12M = 252
_LOOKBACK_6M  = 126
_LOOKBACK_3M  = 63
_SKIP         = 21   # skip most recent month — Jegadeesh-Titman reversal avoidance
_MIN_BARS     = 84   # 3M lookback + skip


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _momentum_ret(closes: list[float], lookback: int) -> float | None:
    """Skip-adjusted momentum: price[-(lookback+skip)] → price[-skip]."""
    if len(closes) < lookback + _SKIP:
        return None
    base = closes[-(lookback + _SKIP)]
    recent = closes[-_SKIP]
    if base <= 0:
        return None
    return (recent - base) / base


def _blended_score(closes: list[float]) -> float:
    """3M·20% + 6M·30% + 12M·50%, all skip-adjusted. Weights renormalised if lookback unavailable."""
    weights = [(_LOOKBACK_12M, 0.50), (_LOOKBACK_6M, 0.30), (_LOOKBACK_3M, 0.20)]
    signals = []
    for lookback, w in weights:
        r = _momentum_ret(closes, lookback)
        if r is not None:
            signals.append((r, w))
    if not signals:
        return 0.5
    total_w = sum(w for _, w in signals)
    blended = sum(r * w for r, w in signals) / total_w
    return round(_sigmoid(blended * 3), 4)


def compute_momentum_score_from_bars(bars: list[dict]) -> float:
    """Multi-timeframe momentum (3M/6M/12M, skip-adjusted) from pre-loaded OHLCV bars."""
    if len(bars) < _MIN_BARS:
        return 0.5
    try:
        closes = [b["c"] for b in bars]
        return _blended_score(closes)
    except Exception:
        return 0.5


def compute_momentum_score(ticker: str, signal_date: Optional[str] = None) -> float:
    """Multi-timeframe price momentum factor score in [0, 1]. Cached 24h."""
    cache_key = f"momentum:{ticker}:{signal_date or 'live'}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    try:
        end = signal_date if signal_date else None
        hist: pd.DataFrame = yf.download(ticker, period="15mo", progress=False,
                                          auto_adjust=True, end=end)

        if isinstance(hist.columns, pd.MultiIndex):
            close_data = hist["Close"]
            if isinstance(close_data, pd.DataFrame):
                close_data = close_data.iloc[:, 0]
            hist = close_data.to_frame(name="Close")

        if "Close" not in hist.columns or len(hist) < _MIN_BARS:
            return 0.5

        closes = hist["Close"].dropna().tolist()
        if len(closes) < _MIN_BARS:
            return 0.5

        score = _blended_score(closes)
        set_cache(cache_key, score, ttl_seconds=86400)
        return score

    except Exception as exc:
        logger.warning("momentum score failed for %s: %s", ticker, exc)
        return 0.5
