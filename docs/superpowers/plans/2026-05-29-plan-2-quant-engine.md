# Trading Analyst — Plan 2: Quant Engine

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the 5 core quant computation layers (technical indicators, ARIMA+GARCH forecasting, signal combiner, Monte Carlo confidence bands, and backtester), producing a `prob_success` field on every recommendation.

**Architecture:** Pure Python computation — no external API calls beyond what Plan 1 already provides. Each layer is an independent module under `quant/`. The signal combiner reads weights from `config.py`; smart money, news, and earnings scores default to 0.5 until Plans 3 and 4 wire them in. All indicators computed from raw OHLCV bars using pandas/numpy (no pandas-ta dependency). ARIMA via statsmodels, GARCH via `arch` library.

**Tech Stack:** Python 3.12, numpy, pandas, statsmodels (ARIMA), arch (GARCH), pytest, pytest-mock

---

## File Map

| File | Responsibility |
|------|---------------|
| `requirements.txt` | Add `arch==6.3.0` |
| `quant/__init__.py` | Empty package marker |
| `quant/indicators.py` | RSI, MACD, Bollinger, EMA 20/50/200, ATR stop, volume confirmation → `technical_score` |
| `quant/forecast.py` | ARIMA price direction + GARCH volatility regime → `arima_score`, `daily_vol`, `vol_scalar` |
| `quant/signals.py` | Weighted composite of all layer scores → `composite_score`, `label` (BUY/WATCH/AVOID) |
| `quant/confidence.py` | 1,000-path Monte Carlo on GBM → confidence bands + `prob_success` |
| `quant/backtest.py` | Walk-forward backtest over historical bars — lookahead-safe |
| `tests/quant/test_indicators.py` | 7 indicator tests |
| `tests/quant/test_forecast.py` | 8 forecast tests |
| `tests/quant/test_signals.py` | 5 signal combiner tests |
| `tests/quant/test_confidence.py` | 6 Monte Carlo tests |
| `tests/quant/test_backtest.py` | 5 backtest tests |

---

### Task 1: arch Dependency + quant Package Scaffold

**Files:**
- Modify: `requirements.txt`
- Create: `quant/__init__.py`

- [ ] **Step 1: Add arch to requirements.txt**

Open `requirements.txt` and add this line after `scipy==1.13.0`:
```
arch==6.3.0
```

Final requirements.txt content:
```
fastapi==0.115.0
uvicorn[standard]==0.30.0
polygon-api-client==1.14.0
yfinance==0.2.40
requests==2.32.3
httpx==0.27.0
pandas==2.2.0
numpy==1.26.0
statsmodels==0.14.2
scipy==1.13.0
arch==6.3.0
anthropic==0.34.0
schwab-py==1.4.0
python-dotenv==1.0.0
pytest==8.3.0
pytest-mock==3.14.0
```

- [ ] **Step 2: Install arch with uv**

```
%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe pip install arch==6.3.0 --python .venv\Scripts\python.exe
```

Verify:
```
.venv\Scripts\python.exe -c "from arch import arch_model; print('arch OK')"
```
Expected: `arch OK`

- [ ] **Step 3: Create quant/__init__.py**

Create empty file `quant/__init__.py`.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt quant/__init__.py
git commit -m "feat: add arch dependency and quant package scaffold"
```

---

### Task 2: Technical Indicators

**Files:**
- Create: `quant/indicators.py`
- Create: `tests/quant/test_indicators.py`

- [ ] **Step 1: Write failing tests**

Create `tests/quant/test_indicators.py`:

```python
import numpy as np
import pytest
from quant.indicators import compute_indicators


def _make_bars(n: int, start_price: float = 100.0, trend: float = 0.0, seed: int = 42) -> list[dict]:
    rng = np.random.default_rng(seed)
    price = start_price
    bars = []
    for i in range(n):
        price = price * (1 + trend + rng.normal(0, 0.01))
        high = price * (1 + abs(rng.normal(0, 0.005)))
        low = price * (1 - abs(rng.normal(0, 0.005)))
        bars.append({
            "t": 1700000000000 + i * 86400000,
            "o": price * 0.999,
            "h": high,
            "l": low,
            "c": price,
            "v": int(1_000_000 + rng.integers(-100_000, 100_000)),
        })
    return bars


def test_compute_indicators_returns_required_keys():
    result = compute_indicators(_make_bars(50))
    for key in ("rsi", "macd_bullish", "bb_position", "ema_trend", "atr_stop", "volume_confirmed", "technical_score"):
        assert key in result


def test_technical_score_bounded():
    assert 0.0 <= compute_indicators(_make_bars(60))["technical_score"] <= 1.0


def test_rsi_bounded():
    rsi = compute_indicators(_make_bars(60))["rsi"]
    assert 0.0 <= rsi <= 100.0


def test_too_few_bars_raises():
    with pytest.raises(ValueError, match="at least 15 bars"):
        compute_indicators(_make_bars(10))


def test_atr_stop_below_current_price():
    bars = _make_bars(60, start_price=100.0)
    result = compute_indicators(bars)
    assert result["atr_stop"] < bars[-1]["c"]


def test_volume_confirmed_is_bool():
    assert isinstance(compute_indicators(_make_bars(60))["volume_confirmed"], bool)


def test_bb_position_bounded():
    assert 0.0 <= compute_indicators(_make_bars(60))["bb_position"] <= 1.0
```

- [ ] **Step 2: Run — expect ModuleNotFoundError**

```
.venv\Scripts\pytest.exe tests/quant/test_indicators.py -v
```
Expected: `ModuleNotFoundError: No module named 'quant.indicators'`

- [ ] **Step 3: Implement quant/indicators.py**

```python
import numpy as np
import pandas as pd


def compute_indicators(bars: list[dict]) -> dict:
    if len(bars) < 15:
        raise ValueError(f"Need at least 15 bars, got {len(bars)}")

    df = pd.DataFrame(bars)
    close = df["c"].astype(float)
    high = df["h"].astype(float)
    low = df["l"].astype(float)
    volume = df["v"].astype(float)

    rsi_val = _rsi(close).iloc[-1]
    macd_line, signal_line = _macd(close)
    bb_upper, _, bb_lower = _bollinger(close)
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean() if len(close) >= 50 else None
    ema200 = close.ewm(span=200, adjust=False).mean() if len(close) >= 200 else None
    atr_val = _atr(high, low, close).iloc[-1]

    latest_close = float(close.iloc[-1])
    latest_macd = float(macd_line.iloc[-1])
    latest_signal = float(signal_line.iloc[-1])
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
    score = _ema_score(ema20, ema50, ema200)
    return "bullish" if score == 1.0 else ("bearish" if score == 0.0 else "neutral")
```

- [ ] **Step 4: Run — expect 7 passed**

```
.venv\Scripts\pytest.exe tests/quant/test_indicators.py -v
```
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add quant/indicators.py tests/quant/test_indicators.py
git commit -m "feat: technical indicators — RSI, MACD, Bollinger, EMA, ATR, volume"
```

---

### Task 3: ARIMA + GARCH Forecasting

**Files:**
- Create: `quant/forecast.py`
- Create: `tests/quant/test_forecast.py`

- [ ] **Step 1: Write failing tests**

Create `tests/quant/test_forecast.py`:

```python
import pytest
from quant.forecast import compute_arima_score, compute_garch_volatility


def _prices(n: int, start: float = 100.0, daily_return: float = 0.001) -> list[float]:
    price = start
    result = []
    for _ in range(n):
        price *= (1 + daily_return)
        result.append(price)
    return result


def test_arima_returns_required_keys():
    result = compute_arima_score(_prices(50))
    for key in ("arima_score", "direction", "probability"):
        assert key in result


def test_arima_score_bounded():
    assert 0.0 <= compute_arima_score(_prices(50))["arima_score"] <= 1.0


def test_arima_direction_valid():
    assert compute_arima_score(_prices(50))["direction"] in ("up", "down", "flat")


def test_arima_too_few_prices_returns_neutral():
    result = compute_arima_score([100.0, 101.0, 99.0])
    assert result["arima_score"] == 0.5
    assert result["direction"] == "flat"


def test_garch_returns_required_keys():
    result = compute_garch_volatility(_prices(60))
    for key in ("daily_vol", "vol_regime", "vol_scalar"):
        assert key in result


def test_garch_vol_regime_valid():
    assert compute_garch_volatility(_prices(60))["vol_regime"] in ("low", "medium", "high")


def test_garch_vol_scalar_bounded():
    assert 0.0 <= compute_garch_volatility(_prices(60))["vol_scalar"] <= 1.0


def test_garch_too_few_prices_returns_fallback():
    result = compute_garch_volatility([100.0, 101.0])
    assert result["daily_vol"] == 0.02
    assert result["vol_regime"] == "medium"
```

- [ ] **Step 2: Run — expect ModuleNotFoundError**

```
.venv\Scripts\pytest.exe tests/quant/test_forecast.py -v
```
Expected: `ModuleNotFoundError: No module named 'quant.forecast'`

- [ ] **Step 3: Implement quant/forecast.py**

```python
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
```

- [ ] **Step 4: Run — expect 8 passed**

```
.venv\Scripts\pytest.exe tests/quant/test_forecast.py -v
```
Expected: `8 passed`

Note: ARIMA/GARCH tests may take 5–10 seconds — they fit real statistical models on small series.

- [ ] **Step 5: Commit**

```bash
git add quant/forecast.py tests/quant/test_forecast.py
git commit -m "feat: ARIMA price direction + GARCH volatility forecasting"
```

---

### Task 4: Signal Combiner

**Files:**
- Create: `quant/signals.py`
- Create: `tests/quant/test_signals.py`

- [ ] **Step 1: Write failing tests**

Create `tests/quant/test_signals.py`:

```python
from quant.signals import compute_signal


def test_buy_signal_above_threshold():
    result = compute_signal(technical_score=0.9, arima_score=0.9,
                            smart_money_score=0.9, news_score=0.9, earnings_score=0.9)
    assert result["label"] == "BUY"
    assert result["composite_score"] > 0.65


def test_avoid_signal_below_threshold():
    result = compute_signal(technical_score=0.1, arima_score=0.1,
                            smart_money_score=0.1, news_score=0.1, earnings_score=0.1)
    assert result["label"] == "AVOID"
    assert result["composite_score"] < 0.40


def test_watch_signal_at_midpoint():
    result = compute_signal(technical_score=0.5, arima_score=0.5,
                            smart_money_score=0.5, news_score=0.5, earnings_score=0.5)
    assert result["label"] == "WATCH"


def test_returns_layer_scores_dict():
    result = compute_signal(technical_score=0.7, arima_score=0.6)
    assert result["layer_scores"]["technical"] == 0.7
    assert result["layer_scores"]["smart_money"] == 0.5


def test_technical_only_weight_is_030():
    result = compute_signal(technical_score=1.0, arima_score=0.0,
                            smart_money_score=0.0, news_score=0.0, earnings_score=0.0)
    assert abs(result["composite_score"] - 0.30) < 0.0001
```

- [ ] **Step 2: Run — expect ModuleNotFoundError**

```
.venv\Scripts\pytest.exe tests/quant/test_signals.py -v
```
Expected: `ModuleNotFoundError: No module named 'quant.signals'`

- [ ] **Step 3: Implement quant/signals.py**

```python
import config


def compute_signal(
    technical_score: float,
    arima_score: float,
    smart_money_score: float = 0.5,
    news_score: float = 0.5,
    earnings_score: float = 0.5,
) -> dict:
    w = config.SIGNAL_WEIGHTS
    composite = round(
        w["technical"] * technical_score
        + w["arima"] * arima_score
        + w["smart_money"] * smart_money_score
        + w["news_reaction"] * news_score
        + w["earnings"] * earnings_score,
        4,
    )

    label = "BUY" if composite > 0.65 else ("AVOID" if composite < 0.40 else "WATCH")

    return {
        "composite_score": composite,
        "label": label,
        "layer_scores": {
            "technical": technical_score,
            "arima": arima_score,
            "smart_money": smart_money_score,
            "news_reaction": news_score,
            "earnings": earnings_score,
        },
    }
```

- [ ] **Step 4: Run — expect 5 passed**

```
.venv\Scripts\pytest.exe tests/quant/test_signals.py -v
```
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add quant/signals.py tests/quant/test_signals.py
git commit -m "feat: signal combiner — weighted composite score, BUY/WATCH/AVOID labels"
```

---

### Task 5: Monte Carlo Confidence Bands + prob_success

**Files:**
- Create: `quant/confidence.py`
- Create: `tests/quant/test_confidence.py`

`prob_success` is defined as P(price_5d > current_price) from 1,000 Geometric Brownian Motion simulations. For BUY signals this is the probability of profit; for AVOID signals use `1 - prob_success`.

- [ ] **Step 1: Write failing tests**

Create `tests/quant/test_confidence.py`:

```python
from quant.confidence import run_monte_carlo


def test_returns_required_keys():
    result = run_monte_carlo(100.0, 0.02, seed=42)
    for key in ("base_target", "lower_80", "upper_80", "downside_pct",
                "upside_pct", "prob_success", "daily_vol_expected"):
        assert key in result


def test_prob_success_bounded():
    assert 0.0 <= run_monte_carlo(100.0, 0.02, seed=42)["prob_success"] <= 1.0


def test_lower_below_base_below_upper():
    r = run_monte_carlo(100.0, 0.02, seed=42)
    assert r["lower_80"] < r["base_target"] < r["upper_80"]


def test_downside_negative_upside_positive():
    r = run_monte_carlo(100.0, 0.02, seed=42)
    assert r["downside_pct"] < 0.0
    assert r["upside_pct"] > 0.0


def test_high_vol_widens_bands():
    low_vol = run_monte_carlo(100.0, 0.01, seed=42)
    high_vol = run_monte_carlo(100.0, 0.05, seed=42)
    assert (high_vol["upper_80"] - high_vol["lower_80"]) > (low_vol["upper_80"] - low_vol["lower_80"])


def test_zero_drift_prob_success_near_half():
    r = run_monte_carlo(100.0, 0.02, days=5, simulations=10_000, seed=42)
    assert 0.40 <= r["prob_success"] <= 0.60
```

- [ ] **Step 2: Run — expect ModuleNotFoundError**

```
.venv\Scripts\pytest.exe tests/quant/test_confidence.py -v
```
Expected: `ModuleNotFoundError: No module named 'quant.confidence'`

- [ ] **Step 3: Implement quant/confidence.py**

```python
import numpy as np


def run_monte_carlo(
    current_price: float,
    daily_vol: float,
    days: int = 5,
    simulations: int = 1_000,
    seed: int | None = None,
) -> dict:
    rng = np.random.default_rng(seed)
    # Geometric Brownian Motion: zero drift (conservative), log-returns ~ N(0, vol)
    log_returns = rng.normal(0.0, daily_vol, size=(simulations, days))
    final_prices = current_price * np.exp(np.cumsum(log_returns, axis=1)[:, -1])

    base_target = float(np.median(final_prices))
    lower_80 = float(np.percentile(final_prices, 10))
    upper_80 = float(np.percentile(final_prices, 90))
    prob_success = float(np.mean(final_prices > current_price))

    return {
        "base_target": round(base_target, 2),
        "lower_80": round(lower_80, 2),
        "upper_80": round(upper_80, 2),
        "downside_pct": round((lower_80 - current_price) / current_price, 4),
        "upside_pct": round((upper_80 - current_price) / current_price, 4),
        "prob_success": round(prob_success, 4),
        "daily_vol_expected": round(daily_vol, 6),
    }
```

- [ ] **Step 4: Run — expect 6 passed**

```
.venv\Scripts\pytest.exe tests/quant/test_confidence.py -v
```
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add quant/confidence.py tests/quant/test_confidence.py
git commit -m "feat: Monte Carlo confidence bands with prob_success (P(price_5d > current))"
```

---

### Task 6: Walk-Forward Backtester

**Files:**
- Create: `quant/backtest.py`
- Create: `tests/quant/test_backtest.py`

Lookahead-bias guard: signal at bar `i` only uses `bars[:i]` — never bar `i` or later.
Survivorship-bias note: yfinance returns split-adjusted prices automatically; delisted tickers are a known limitation and not in scope.

- [ ] **Step 1: Write failing tests**

Create `tests/quant/test_backtest.py`:

```python
import numpy as np
import pytest
from quant.backtest import run_backtest


def _trending_bars(n: int, trend: float = 0.002, seed: int = 42) -> list[dict]:
    rng = np.random.default_rng(seed)
    price = 100.0
    bars = []
    for i in range(n):
        price = price * (1 + trend + rng.normal(0, 0.008))
        bars.append({
            "t": 1700000000000 + i * 86400000,
            "o": price * 0.999,
            "h": price * 1.004,
            "l": price * 0.996,
            "c": price,
            "v": 1_500_000,
        })
    return bars


def test_returns_required_keys():
    result = run_backtest("AMZN", _trending_bars(80))
    for key in ("ticker", "total_signals", "win_rate", "correct_signals", "avg_return_pct"):
        assert key in result


def test_ticker_preserved_in_result():
    assert run_backtest("TSLA", _trending_bars(80))["ticker"] == "TSLA"


def test_win_rate_bounded():
    result = run_backtest("AMZN", _trending_bars(100))
    assert 0.0 <= result["win_rate"] <= 1.0


def test_too_few_bars_returns_zero_signals():
    result = run_backtest("AMZN", _trending_bars(20))
    assert result["total_signals"] == 0
    assert result["win_rate"] == 0.0


def test_correct_signals_le_total():
    result = run_backtest("AMZN", _trending_bars(100))
    assert result["correct_signals"] <= result["total_signals"]
```

- [ ] **Step 2: Run — expect ModuleNotFoundError**

```
.venv\Scripts\pytest.exe tests/quant/test_backtest.py -v
```
Expected: `ModuleNotFoundError: No module named 'quant.backtest'`

- [ ] **Step 3: Implement quant/backtest.py**

```python
from quant.indicators import compute_indicators
from quant.forecast import compute_arima_score
from quant.signals import compute_signal


def run_backtest(
    ticker: str,
    bars: list[dict],
    min_bars: int = 30,
    hold_days: int = 5,
) -> dict:
    signals_log = []

    for i in range(min_bars, len(bars) - hold_days):
        history = bars[:i]  # lookahead-safe: only data available at bar i
        prices = [b["c"] for b in history]
        try:
            ind = compute_indicators(history)
            fcast = compute_arima_score(prices)
            sig = compute_signal(
                technical_score=ind["technical_score"],
                arima_score=fcast["arima_score"],
            )
        except Exception:
            continue

        if sig["label"] == "WATCH":
            continue

        signal_price = float(bars[i]["c"])
        future_price = float(bars[i + hold_days]["c"])
        correct = (
            (sig["label"] == "BUY" and future_price > signal_price)
            or (sig["label"] == "AVOID" and future_price < signal_price)
        )
        signals_log.append({
            "label": sig["label"],
            "signal_price": signal_price,
            "future_price": future_price,
            "return_pct": abs(future_price - signal_price) / signal_price,
            "correct": correct,
        })

    if not signals_log:
        return {"ticker": ticker, "total_signals": 0, "win_rate": 0.0,
                "correct_signals": 0, "avg_return_pct": 0.0}

    total = len(signals_log)
    correct_count = sum(1 for s in signals_log if s["correct"])
    return {
        "ticker": ticker,
        "total_signals": total,
        "win_rate": round(correct_count / total, 4),
        "correct_signals": correct_count,
        "avg_return_pct": round(sum(s["return_pct"] for s in signals_log) / total, 4),
    }
```

- [ ] **Step 4: Run — expect 5 passed**

```
.venv\Scripts\pytest.exe tests/quant/test_backtest.py -v
```
Expected: `5 passed`

Note: This test calls real ARIMA/GARCH models and will take 20–60 seconds depending on bar count. That's expected.

- [ ] **Step 5: Commit**

```bash
git add quant/backtest.py tests/quant/test_backtest.py
git commit -m "feat: walk-forward backtester with lookahead-bias guard"
```

---

### Task 7: Full Suite Verification

**Files:** No new files — verifies all Plan 2 work end-to-end.

- [ ] **Step 1: Run full test suite**

```
.venv\Scripts\pytest.exe tests/ -v --tb=short
```
Expected: `49 passed` (18 from Plan 1 + 7 + 8 + 5 + 6 + 5 from Plan 2)

If any test fails, fix it before continuing.

- [ ] **Step 2: Smoke test — one full signal with confidence bands**

Run from `C:\Claude\Trading Analyst\`:

```python
.venv\Scripts\python.exe -c "
from quant.indicators import compute_indicators
from quant.forecast import compute_arima_score, compute_garch_volatility
from quant.signals import compute_signal
from quant.confidence import run_monte_carlo

# Synthetic 60-bar upward trending data
import numpy as np
rng = np.random.default_rng(42)
price = 100.0
bars = []
for i in range(60):
    price *= (1 + 0.002 + rng.normal(0, 0.01))
    bars.append({'t': i, 'o': price*.999, 'h': price*1.005, 'l': price*.995, 'c': price, 'v': 1_500_000})

ind = compute_indicators(bars)
fcast = compute_arima_score([b['c'] for b in bars])
garch = compute_garch_volatility([b['c'] for b in bars])
sig = compute_signal(ind['technical_score'], fcast['arima_score'])
mc = run_monte_carlo(bars[-1]['c'], garch['daily_vol'], seed=42)

print(f'Signal: {sig[\"label\"]} (score={sig[\"composite_score\"]})')
print(f'prob_success: {mc[\"prob_success\"]:.1%}')
print(f'Target: \${mc[\"base_target\"]:.2f} [{mc[\"lower_80\"]:.2f} - {mc[\"upper_80\"]:.2f}]')
print(f'Downside: {mc[\"downside_pct\"]:.1%} | Upside: {mc[\"upside_pct\"]:.1%}')
print(f'ATR stop: \${ind[\"atr_stop\"]:.2f}')
"
```

Expected output (values approximate):
```
Signal: BUY (score=0.6xxx)
prob_success: 48.x%
Target: $xxx.xx [$xxx.xx - $xxx.xx]
Downside: -x.x% | Upside: x.x%
ATR stop: $xx.xx
```

- [ ] **Step 3: Final commit**

```bash
git add .
git commit -m "chore: Plan 2 complete — quant engine verified, 49 tests passing"
```

---

## What Plan 3 Builds Next

Plan 3 (Smart Money + Portfolio Analyzer) implements:
- `smart_money/sec_13f.py` — 13F filings from SEC EDGAR → `smart_money_score`
- `smart_money/ark_flows.py` — ARK daily CSV → buys/sells for held tickers
- `smart_money/congress.py` — Quiver Quantitative congressional trades
- `smart_money/whale_tracker.py` — Whale Alert on-chain signals
- `portfolio/analyzer.py` — Sharpe ratio, beta, VaR, sector exposure
- `portfolio/holdings.csv` — Initial portfolio setup
- `portfolio/schwab_sync.py` — Schwab OAuth auto-sync

Plan 3 wires `smart_money_score` into `compute_signal()` replacing the 0.5 default.
