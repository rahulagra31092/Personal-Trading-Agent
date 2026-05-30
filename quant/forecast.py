import warnings
import numpy as np
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA


def compute_arima_score(prices: list[float]) -> dict:
    if len(prices) < 20:
        return {"arima_score": 0.5, "direction": "flat", "probability": 0.5}

    series = pd.Series(prices)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = ARIMA(series, order=(1, 1, 1)).fit()
            forecast_5d = float(fit.forecast(steps=5).iloc[-1])

        current = float(series.iloc[-1])
        pct_change = (forecast_5d - current) / current
        arima_score = round(max(0.0, min(1.0, 0.5 + pct_change * 5)), 4)
        direction = "up" if pct_change > 0.005 else ("down" if pct_change < -0.005 else "flat")
        probability = round(min(abs(arima_score - 0.5) * 2, 1.0), 4)
        return {"arima_score": arima_score, "direction": direction, "probability": probability}
    except Exception:
        return {"arima_score": 0.5, "direction": "flat", "probability": 0.5}


def compute_garch_volatility(prices: list[float]) -> dict:
    _fallback = {"daily_vol": 0.02, "vol_regime": "medium", "vol_scalar": 0.5}
    if len(prices) < 30:
        return _fallback

    try:
        from arch import arch_model
        returns = pd.Series(prices).pct_change().dropna() * 100
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = arch_model(returns, vol="Garch", p=1, q=1).fit(disp="off")
            variance = float(fit.forecast(horizon=1).variance.iloc[-1, 0])

        daily_vol = round(float(np.sqrt(variance)) / 100, 6)
        if daily_vol < 0.015:
            return {"daily_vol": daily_vol, "vol_regime": "low", "vol_scalar": 0.8}
        if daily_vol < 0.03:
            return {"daily_vol": daily_vol, "vol_regime": "medium", "vol_scalar": 0.5}
        return {"daily_vol": daily_vol, "vol_regime": "high", "vol_scalar": 0.2}
    except Exception:
        return _fallback
