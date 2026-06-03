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


def _trend_r2(closes: list[float]) -> float:
    """
    Pearson R² of log-prices vs time over the last 12 months.
    1.0 = perfectly smooth trend; 0.0 = random walk; 0.5 returned when undefined.
    Captures whether the momentum was earned consistently or via a spike-and-stall.
    """
    n = min(len(closes), _LOOKBACK_12M)
    if n < 20:
        return 0.5
    log_prices = [math.log(c) for c in closes[-n:] if c > 0]
    n = len(log_prices)
    if n < 20:
        return 0.5
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(log_prices) / n
    num = sum((xs[i] - x_mean) * (log_prices[i] - y_mean) for i in range(n))
    den_x = sum((x - x_mean) ** 2 for x in xs)
    den_y = sum((y - y_mean) ** 2 for y in log_prices)
    if den_x == 0 or den_y == 0:
        return 0.5
    r = num / math.sqrt(den_x * den_y)
    return min(1.0, max(0.0, r * r))


def _accel_bonus(r3m: float | None, r6m: float | None) -> float:
    """
    Momentum acceleration: compares 3M vs 6M annualized return rates.
    Positive → momentum building (+0.05 max). Negative → fading (−0.05 max).
    """
    if r3m is None or r6m is None:
        return 0.0
    rate_3m = r3m * (252 / _LOOKBACK_3M)
    rate_6m = r6m * (252 / _LOOKBACK_6M)
    accel = rate_3m - rate_6m
    return min(0.05, max(-0.05, accel * 0.20))


def _blended_score(closes: list[float]) -> float:
    """
    Multi-timeframe momentum: 3M·20% + 6M·30% + 12M·50% (skip-adjusted) → sigmoid.
    Adjusted by:
      - Trend quality multiplier (R²): 0.65 at R²=0 → 1.00 at R²=1, scaled by signal strength.
      - Acceleration bonus: ±0.05 based on whether 3M rate is outpacing 6M rate.
    """
    weights = [(_LOOKBACK_12M, 0.50), (_LOOKBACK_6M, 0.30), (_LOOKBACK_3M, 0.20)]
    signals = []
    for lookback, w in weights:
        r = _momentum_ret(closes, lookback)
        if r is not None:
            signals.append((lookback, r, w))
    if not signals:
        return 0.5

    total_w = sum(w for _, _, w in signals)
    blended = sum(r * w for _, r, w in signals) / total_w
    base = _sigmoid(blended * 3)

    # Quality multiplier: applied proportionally to signal strength.
    # Neutral signals (base ≈ 0.5) are unaffected; strong signals bear the full penalty.
    r2 = _trend_r2(closes)
    quality_mult = 0.65 + 0.35 * r2  # 0.65 (random walk) → 1.00 (smooth trend)
    strength = abs(base - 0.5)        # 0 = neutral, 0.5 = maximum
    quality_factor = 1.0 - (1.0 - quality_mult) * (strength / 0.5)

    r3m = next((r for lb, r, _ in signals if lb == _LOOKBACK_3M), None)
    r6m = next((r for lb, r, _ in signals if lb == _LOOKBACK_6M), None)
    bonus = _accel_bonus(r3m, r6m)

    return round(min(1.0, max(0.0, base * quality_factor + bonus)), 4)


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
