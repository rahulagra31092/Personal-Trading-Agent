import math
import numpy as np
import pandas as pd


def _require_finite(val: float, name: str) -> float:
    if math.isnan(val) or math.isinf(val):
        raise ValueError(f"Indicator '{name}' produced NaN/Inf — input data may be degenerate or insufficient.")
    return val


def compute_indicators(bars: list[dict], spy_return_3m: float | None = None) -> dict:
    """
    Compute technical indicators and a weighted composite score.

    spy_return_3m: optional 3-month SPY return (decimal). When provided, enables
    a relative-strength sub-signal and shifts weights accordingly.
    """
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
    atr14 = _atr(high, low, close, 14)
    atr5 = _atr(high, low, close, 5)
    atr_val = _require_finite(float(atr14.iloc[-1]), "atr")
    atr5_val = float(atr5.iloc[-1])
    if math.isnan(atr5_val):
        atr5_val = atr_val

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

    ema_trend_str = _ema_trend(ema20, ema50, ema200)

    # --- weighted sub-scores ---
    rsi_s = _rsi_score(rsi_val)
    macd_s = _macd_score(latest_macd - latest_signal, latest_close)
    ema_s = _ema_score(ema20, ema50, ema200)
    vol_s = _volume_score(latest_volume, avg_vol_20)
    h52_s = _high52_score(high, latest_close)

    if spy_return_3m is not None:
        stock_3m = _return_over(close, 63)
        rs_s = _rs_score(stock_3m - spy_return_3m)
        # EMA 28% · MACD 22% · RSI 18% · RS 12% · 52wk 8% · Vol 8% · BB 4%
        raw = (0.28 * ema_s + 0.22 * macd_s + 0.18 * rsi_s +
               0.12 * rs_s + 0.08 * h52_s + 0.08 * vol_s + 0.04 * bb_position)
    else:
        # EMA 30% · MACD 25% · RSI 20% · 52wk 10% · Vol 10% · BB 5%
        raw = (0.30 * ema_s + 0.25 * macd_s + 0.20 * rsi_s +
               0.10 * h52_s + 0.10 * vol_s + 0.05 * bb_position)

    atr_mod = _atr_modifier(atr5_val, atr_val, ema_trend_str)
    technical_score = round(max(0.0, min(1.0, raw * atr_mod)), 4)

    return {
        "rsi": round(float(rsi_val), 2),
        "macd_bullish": latest_macd > latest_signal,
        "bb_position": round(bb_position, 4),
        "ema_trend": ema_trend_str,
        "atr_stop": round(latest_close - 2 * atr_val, 2),
        "volume_confirmed": bool(volume_confirmed),
        "technical_score": technical_score,
    }


def _rsi_score(rsi_val: float) -> float:
    """4-zone RSI: sweet spot 55-80 = 1.0, exhaustion >80 = 0.3, bearish <35 = 0.0."""
    if rsi_val >= 80:
        return 0.3
    if rsi_val >= 55:
        return 1.0
    if rsi_val >= 45:
        return 0.5
    if rsi_val >= 35:
        return 0.15
    return 0.0


def _macd_score(histogram: float, price: float) -> float:
    """Continuous MACD: histogram magnitude as fraction of 2% price band → 0-1."""
    if price <= 0:
        return 0.5
    norm = histogram / (price * 0.02)
    return min(1.0, max(0.0, 0.5 + norm * 0.5))


def _volume_score(latest_vol: float, avg_vol: float) -> float:
    """Continuous volume: 1x average = 0.5, 2x average = 1.0, 0x = 0.0."""
    if avg_vol <= 0 or math.isnan(avg_vol):
        return 0.5
    ratio = latest_vol / avg_vol
    return min(1.0, max(0.0, ratio / 2.0))


def _high52_score(high: pd.Series, latest_close: float) -> float:
    """Proximity to 52-week (252-bar) high: at peak = 1.0, 60% of peak = 0.0."""
    window = high.iloc[-252:] if len(high) >= 252 else high
    peak = float(window.max())
    if peak <= 0:
        return 0.5
    proximity = latest_close / peak
    return min(1.0, max(0.0, (proximity - 0.60) / 0.40))


def _rs_score(excess_return: float) -> float:
    """Relative strength vs SPY: +20% outperformance = 1.0, -20% = 0.0."""
    return min(1.0, max(0.0, 0.5 + excess_return / 0.40))


def _return_over(close: pd.Series, periods: int) -> float:
    if len(close) < periods + 1:
        return 0.0
    start = float(close.iloc[-(periods + 1)])
    end = float(close.iloc[-1])
    return (end - start) / start if start > 0 else 0.0


def _atr_modifier(atr5: float, atr14: float, ema_trend: str) -> float:
    """
    Quality modifier based on ATR compression/expansion vs trend.
    Tightening ATR in bullish trend = energy building → +5%.
    Expanding ATR in bearish trend = volatility breakdown → -5%.
    """
    if atr14 <= 0 or math.isnan(atr5) or math.isnan(atr14):
        return 1.0
    tightening = atr5 < atr14 * 0.85
    expanding = atr5 > atr14 * 1.15
    if ema_trend == "bullish" and tightening:
        return 1.05
    if ema_trend == "bullish" and expanding:
        return 0.97
    if ema_trend == "bearish" and expanding:
        return 0.95
    return 1.0


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
