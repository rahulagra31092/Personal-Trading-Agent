import logging
import warnings
import numpy as np
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA

try:
    from arch import arch_model as _arch_model
except ImportError as exc:
    raise ImportError("arch library is required: pip install arch") from exc

logger = logging.getLogger(__name__)

# Scales 5-day forecast pct_change to [0, 1].
# A multiplier of 5 means a +/-10% predicted move saturates the score.
_ARIMA_SCORE_MULTIPLIER = 5

_DIRECTION_THRESHOLD = 0.005   # 0.5% 5-day move to declare directional signal
_VOL_LOW_THRESHOLD = 0.015     # ~24% annualized daily vol
_VOL_HIGH_THRESHOLD = 0.03     # ~48% annualized daily vol


def compute_arima_score(prices: list[float]) -> dict:
    _neutral = {"arima_score": 0.5, "direction": "flat", "probability": 0.5}
    if len(prices) < 20:
        return _neutral

    series = pd.Series(prices)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = ARIMA(series, order=(1, 1, 1)).fit()
            forecast_5d = float(fit.forecast(steps=5).iloc[-1])

        current = float(series.iloc[-1])
        pct_change = (forecast_5d - current) / current
        arima_score = round(max(0.0, min(1.0, 0.5 + pct_change * _ARIMA_SCORE_MULTIPLIER)), 4)
        direction = (
            "up" if pct_change > _DIRECTION_THRESHOLD
            else ("down" if pct_change < -_DIRECTION_THRESHOLD else "flat")
        )
        probability = round(min(abs(arima_score - 0.5) * 2, 1.0), 4)
        return {"arima_score": arima_score, "direction": direction, "probability": probability}
    except Exception as exc:
        logger.warning("compute_arima_score failed, returning neutral: %s", exc)
        return _neutral


def compute_garch_volatility(prices: list[float]) -> dict:
    _fallback = {"daily_vol": 0.02, "vol_regime": "medium", "vol_scalar": 0.5}
    if len(prices) < 30:
        return _fallback

    try:
        returns = pd.Series(prices).pct_change().dropna() * 100
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = _arch_model(returns, vol="Garch", p=1, q=1).fit(disp="off")
            variance = float(fit.forecast(horizon=1).variance.iloc[-1, 0])

        daily_vol = round(float(np.sqrt(variance)) / 100, 6)
        if daily_vol < _VOL_LOW_THRESHOLD:
            return {"daily_vol": daily_vol, "vol_regime": "low", "vol_scalar": 0.8}
        if daily_vol < _VOL_HIGH_THRESHOLD:
            return {"daily_vol": daily_vol, "vol_regime": "medium", "vol_scalar": 0.5}
        return {"daily_vol": daily_vol, "vol_regime": "high", "vol_scalar": 0.2}
    except Exception as exc:
        logger.warning("compute_garch_volatility failed, returning fallback: %s", exc)
        return _fallback
