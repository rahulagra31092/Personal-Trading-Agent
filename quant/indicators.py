import math
import numpy as np
import pandas as pd


def _require_finite(val: float, name: str) -> float:
    if math.isnan(val) or math.isinf(val):
        raise ValueError(f"Indicator '{name}' produced NaN/Inf — input data may be degenerate or insufficient.")
    return val


def compute_indicators(bars: list[dict]) -> dict:
    if len(bars) < 20:
        raise ValueError(f"Need at least 20 bars, got {len(bars)}")

    df = pd.DataFrame(bars)
    close = df["c"].astype(float)
    high = df["h"].astype(float)
    low = df["l"].astype(float)
    volume = df["v"].astype(float)

    rsi_val = _require_finite(float(_rsi(close).iloc[-1]), "rsi")
    macd_line, signal_line = _macd(close)
    bb_upper, _, bb_lower = _bollinger(close)
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean() if len(close) >= 50 else None
    ema200 = close.ewm(span=200, adjust=False).mean() if len(close) >= 200 else None
    atr_val = _require_finite(float(_atr(high, low, close).iloc[-1]), "atr")

    latest_close = float(close.iloc[-1])
    latest_macd = _require_finite(float(macd_line.iloc[-1]), "macd")
    latest_signal = _require_finite(float(signal_line.iloc[-1]), "signal")
    latest_bb_upper = float(bb_upper.iloc[-1])
    latest_bb_lower = float(bb_lower.iloc[-1])
    avg_vol_20 = float(volume.rolling(20).mean().iloc[-1])
    latest_volume = float(volume.iloc[-1])

    bb_range = latest_bb_upper - latest_bb_lower
    bb_position = (latest_close - latest_bb_lower) / bb_range if bb_range > 0 else 0.5
    bb_position = max(0.0, min(1.0, bb_position))
    volume_confirmed = latest_volume > avg_vol_20 if not np.isnan(avg_vol_20) else False

    scores = [
        1.0 if rsi_val < 35 else (0.0 if rsi_val > 65 else 0.5),
        1.0 if latest_macd > latest_signal else 0.0,
        1.0 - bb_position,
        _ema_score(ema20, ema50, ema200),
        1.0 if volume_confirmed else 0.5,
    ]

    return {
        "rsi": round(float(rsi_val), 2),
        "macd_bullish": latest_macd > latest_signal,
        "bb_position": round(bb_position, 4),
        "ema_trend": _ema_trend(ema20, ema50, ema200),
        "atr_stop": round(latest_close - 2 * float(atr_val), 2),
        "volume_confirmed": bool(volume_confirmed),
        "technical_score": round(sum(scores) / len(scores), 4),
    }


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    return macd, macd.ewm(span=9, adjust=False).mean()


def _bollinger(close: pd.Series, period: int = 20) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    return mid + 2 * std, mid, mid - 2 * std


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _ema_score(ema20: pd.Series, ema50: pd.Series | None, ema200: pd.Series | None) -> float:
    v20 = float(ema20.iloc[-1])
    if ema50 is None:
        return 0.5
    v50 = float(ema50.iloc[-1])
    if ema200 is None:
        return 1.0 if v20 > v50 else 0.0
    v200 = float(ema200.iloc[-1])
    if v20 > v50 > v200:
        return 1.0
    if v20 < v50:
        return 0.0
    return 0.5


def _ema_trend(ema20: pd.Series, ema50: pd.Series | None, ema200: pd.Series | None) -> str:
    v20 = float(ema20.iloc[-1])
    if ema50 is None:
        return "neutral"
    v50 = float(ema50.iloc[-1])
    if ema200 is None:
        return "bullish" if v20 > v50 else "bearish"
    v200 = float(ema200.iloc[-1])
    if v20 > v50 > v200:
        return "bullish"
    if v20 < v50:
        return "bearish"
    return "neutral"
