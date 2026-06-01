# Performance Metrics & Trade Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Sharpe ratio, max drawdown, and CAGR to the backtest engine; add a structured trade card (entry / stop / take-profit / R:R) and formal trend regime label to the `/analyze` endpoint.

**Architecture:** Three independent additions — (1) extend `quant/backtest.py` with equity-curve metrics using only stdlib `math`, (2) create `quant/trade_setup.py` as a self-contained pure-function module, (3) wire `trade_card` and `trend_regime` into `api/analyze.py` by importing `compute_trade_setup` and returning both keys. No database changes, no new API routes, no new dependencies.

**Tech Stack:** Python 3.12, FastAPI, pytest — all already installed at `C:\Claude\Trading Analyst\.venv`.

Run all tests with: `.venv\Scripts\pytest.exe tests/ -v` from `C:\Claude\Trading Analyst\`.

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Modify | `quant/backtest.py` | Add `sharpe_ratio`, `max_drawdown`, `cagr` to `run_backtest()` return dict |
| Create | `quant/trade_setup.py` | `compute_trade_setup(entry, atr_stop) → dict` — ATR-based stop, 3:1 take-profit, R:R |
| Modify | `api/analyze.py` | Import `compute_trade_setup`; add `trade_card` + `trend_regime` to response |
| Modify | `tests/quant/test_backtest.py` | 6 new tests for the three new backtest metrics |
| Create | `tests/quant/test_trade_setup.py` | 9 unit tests for `compute_trade_setup()` |
| Modify | `tests/api/test_analyze.py` | 3 new tests for `trade_card` + `trend_regime` in `/analyze` response |

---

### Task 1: Add Sharpe ratio, max drawdown, CAGR to `quant/backtest.py`

**Files:**
- Modify: `quant/backtest.py`
- Modify: `tests/quant/test_backtest.py`

The current `run_backtest()` returns `total_signals / win_rate / correct_signals / avg_return_pct`. We add three equity-curve metrics:
- **Sharpe ratio** — annualised: `(avg_return / std_return) * sqrt(252 / hold_days)`
- **Max drawdown** — worst peak-to-trough decline of the compounded equity curve, 0–1
- **CAGR** — compound annual growth rate: `equity_final ^ (252 / total_trading_days) - 1`

All three return `0.0` when `total_signals == 0`.

- [ ] **Step 1: Add the 6 failing tests to `tests/quant/test_backtest.py`**

Append after the existing `test_lookahead_safe` function (keep all existing tests intact):

```python
def test_returns_new_metric_keys():
    result = run_backtest("AMZN", _trending_bars(80))
    for key in ("sharpe_ratio", "max_drawdown", "cagr"):
        assert key in result


def test_max_drawdown_non_negative():
    result = run_backtest("AMZN", _trending_bars(100))
    assert result["max_drawdown"] >= 0.0


def test_max_drawdown_le_one():
    result = run_backtest("AMZN", _trending_bars(100))
    assert result["max_drawdown"] <= 1.0


def test_zero_signals_new_metrics_are_zero():
    result = run_backtest("AMZN", _trending_bars(20))
    assert result["sharpe_ratio"] == 0.0
    assert result["max_drawdown"] == 0.0
    assert result["cagr"] == 0.0


def test_sharpe_is_float():
    result = run_backtest("AMZN", _trending_bars(100))
    assert isinstance(result["sharpe_ratio"], float)


def test_cagr_reasonable_range():
    result = run_backtest("AMZN", _trending_bars(100))
    assert -1.0 <= result["cagr"] <= 10.0
```

- [ ] **Step 2: Run to confirm the new tests fail**

```
cd "C:\Claude\Trading Analyst"
.venv\Scripts\pytest.exe tests/quant/test_backtest.py::test_returns_new_metric_keys tests/quant/test_backtest.py::test_zero_signals_new_metrics_are_zero -v
```

Expected: FAIL with `KeyError: 'sharpe_ratio'`

- [ ] **Step 3: Replace `quant/backtest.py` with the extended implementation**

```python
import math
import logging

from quant.indicators import compute_indicators
from quant.forecast import compute_arima_score
from quant.signals import compute_signal

logger = logging.getLogger(__name__)


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
        except Exception as exc:
            logger.debug("Skipping bar %d: %s", i, exc)
            continue

        if sig["label"] == "WATCH":
            continue

        signal_price = float(bars[i]["c"])
        future_price = float(bars[i + hold_days]["c"])
        if sig["label"] == "BUY":
            strategy_return = (future_price - signal_price) / signal_price
        else:  # AVOID
            strategy_return = (signal_price - future_price) / signal_price

        signals_log.append({
            "label": sig["label"],
            "signal_price": signal_price,
            "future_price": future_price,
            "return_pct": round(strategy_return, 6),
            "correct": strategy_return > 0,
        })

    if not signals_log:
        return {
            "ticker": ticker,
            "total_signals": 0,
            "win_rate": 0.0,
            "correct_signals": 0,
            "avg_return_pct": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "cagr": 0.0,
        }

    rets = [s["return_pct"] for s in signals_log]
    total = len(signals_log)
    correct_count = sum(1 for s in signals_log if s["correct"])
    avg_ret = sum(rets) / total

    # Annualised Sharpe: scale per-trade Sharpe to 252-day year
    periods_per_year = 252.0 / hold_days
    if total > 1:
        variance = sum((r - avg_ret) ** 2 for r in rets) / (total - 1)
        std_ret = math.sqrt(variance)
        sharpe = round(avg_ret / std_ret * math.sqrt(periods_per_year), 4) if std_ret > 0 else 0.0
    else:
        sharpe = 0.0

    # Build equity curve → max drawdown and CAGR
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in rets:
        equity *= (1.0 + r)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak
        if dd > max_dd:
            max_dd = dd

    total_trading_days = total * hold_days
    if equity > 0 and total_trading_days > 0:
        cagr = round((equity ** (252.0 / total_trading_days)) - 1.0, 4)
    else:
        cagr = 0.0

    return {
        "ticker": ticker,
        "total_signals": total,
        "win_rate": round(correct_count / total, 4),
        "correct_signals": correct_count,
        "avg_return_pct": round(avg_ret, 4),
        "sharpe_ratio": sharpe,
        "max_drawdown": round(max_dd, 4),
        "cagr": cagr,
    }
```

- [ ] **Step 4: Run all backtest tests**

```
.venv\Scripts\pytest.exe tests/quant/test_backtest.py -v
```

Expected: All 12 tests PASS (6 existing + 6 new)

- [ ] **Step 5: Commit**

```bash
git add quant/backtest.py tests/quant/test_backtest.py
git commit -m "feat: add sharpe_ratio, max_drawdown, cagr to run_backtest"
```

---

### Task 2: Create `quant/trade_setup.py`

**Files:**
- Create: `quant/trade_setup.py`
- Create: `tests/quant/test_trade_setup.py`

`compute_trade_setup(current_price, atr_stop)` derives the ATR from the already-computed stop (`atr = (current_price - atr_stop) / 2` reverses `atr_stop = current_price - 2*ATR`), then sets:
- `stop_loss = atr_stop`
- `risk = max(current_price - atr_stop, 0.01)` — clamped so zero-risk edge cases don't divide by zero
- `take_profit = current_price + 3 * risk` (3:1 reward:risk, industry standard)
- `risk_reward_ratio = reward / risk = 3.0`

- [ ] **Step 1: Create `tests/quant/test_trade_setup.py`**

```python
from quant.trade_setup import compute_trade_setup


def test_returns_required_keys():
    result = compute_trade_setup(100.0, 90.0)
    for key in ("entry_price", "stop_loss", "take_profit", "risk_per_share",
                "reward_per_share", "risk_reward_ratio"):
        assert key in result


def test_stop_loss_equals_atr_stop():
    result = compute_trade_setup(100.0, 90.0)
    assert result["stop_loss"] == 90.0


def test_risk_per_share_correct():
    result = compute_trade_setup(100.0, 90.0)
    assert result["risk_per_share"] == 10.0


def test_reward_per_share_is_3x_risk():
    result = compute_trade_setup(100.0, 90.0)
    assert result["reward_per_share"] == 30.0


def test_take_profit_correct():
    result = compute_trade_setup(100.0, 90.0)
    assert result["take_profit"] == 130.0


def test_risk_reward_ratio_is_3():
    result = compute_trade_setup(100.0, 90.0)
    assert result["risk_reward_ratio"] == 3.0


def test_entry_price_rounded():
    result = compute_trade_setup(123.456, 110.0)
    assert result["entry_price"] == 123.46


def test_zero_risk_uses_minimum():
    # atr_stop == current_price → risk clamped to 0.01
    result = compute_trade_setup(100.0, 100.0)
    assert result["risk_per_share"] == 0.01
    assert result["risk_reward_ratio"] == 3.0


def test_atr_stop_above_price_clamped():
    # atr_stop > current_price → should not crash
    result = compute_trade_setup(100.0, 105.0)
    assert result["risk_per_share"] == 0.01
    assert result["take_profit"] > result["entry_price"]
```

- [ ] **Step 2: Run to confirm tests fail**

```
.venv\Scripts\pytest.exe tests/quant/test_trade_setup.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'quant.trade_setup'`

- [ ] **Step 3: Create `quant/trade_setup.py`**

```python
def compute_trade_setup(current_price: float, atr_stop: float) -> dict:
    risk = max(current_price - atr_stop, 0.01)
    reward = 3.0 * risk
    return {
        "entry_price": round(current_price, 2),
        "stop_loss": round(atr_stop, 2),
        "take_profit": round(current_price + reward, 2),
        "risk_per_share": round(risk, 2),
        "reward_per_share": round(reward, 2),
        "risk_reward_ratio": round(reward / risk, 2),
    }
```

- [ ] **Step 4: Run all trade_setup tests**

```
.venv\Scripts\pytest.exe tests/quant/test_trade_setup.py -v
```

Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add quant/trade_setup.py tests/quant/test_trade_setup.py
git commit -m "feat: add compute_trade_setup with 3:1 R/R and ATR-based stop/target"
```

---

### Task 3: Wire `trade_card` and `trend_regime` into `/analyze` endpoint

**Files:**
- Modify: `api/analyze.py`
- Modify: `tests/api/test_analyze.py`

Changes to `analyze_ticker()`:
- Import `compute_trade_setup` from `quant.trade_setup`
- Call `compute_trade_setup(current_price, ind["atr_stop"])` and add the result as `trade_card`
- Rename `ema_trend` → `trend_regime` in the returned dict (same value from `ind["ema_trend"]`, clearer name)

Existing tests don't check for `ema_trend` so the rename is safe. The old tests that don't mock `compute_trade_setup` will call the real function — that's fine since `current_price` (~100) and `atr_stop` (95.0 from `_FAKE_IND`) are valid inputs.

- [ ] **Step 1: Add `_FAKE_TRADE_CARD` and 3 new tests to `tests/api/test_analyze.py`**

Add the constant at module level after the existing `_FAKE_MC` block:

```python
_FAKE_TRADE_CARD = {
    "entry_price": 100.0,
    "stop_loss": 95.0,
    "take_profit": 115.0,
    "risk_per_share": 5.0,
    "reward_per_share": 15.0,
    "risk_reward_ratio": 3.0,
}
```

Add three test functions at the end of the file:

```python
def test_analyze_trade_card_present():
    with patch("api.analyze.get_daily_bars", return_value=_FAKE_BARS), \
         patch("api.analyze.compute_indicators", return_value=_FAKE_IND), \
         patch("api.analyze.compute_arima_score", return_value=_FAKE_FCAST), \
         patch("api.analyze.compute_garch_volatility", return_value=_FAKE_GARCH), \
         patch("api.analyze.run_monte_carlo", return_value=_FAKE_MC), \
         patch("api.analyze.compute_congress_score", return_value=0.5), \
         patch("api.analyze.compute_news_score", return_value=0.5), \
         patch("api.analyze.compute_earnings_score", return_value=0.5), \
         patch("api.analyze.compute_trade_setup", return_value=_FAKE_TRADE_CARD):
        resp = client.get("/analyze/AAPL")
    assert resp.status_code == 200
    data = resp.json()
    assert "trade_card" in data
    for key in ("entry_price", "stop_loss", "take_profit", "risk_reward_ratio"):
        assert key in data["trade_card"]


def test_analyze_trend_regime_present():
    with patch("api.analyze.get_daily_bars", return_value=_FAKE_BARS), \
         patch("api.analyze.compute_indicators", return_value=_FAKE_IND), \
         patch("api.analyze.compute_arima_score", return_value=_FAKE_FCAST), \
         patch("api.analyze.compute_garch_volatility", return_value=_FAKE_GARCH), \
         patch("api.analyze.run_monte_carlo", return_value=_FAKE_MC), \
         patch("api.analyze.compute_congress_score", return_value=0.5), \
         patch("api.analyze.compute_news_score", return_value=0.5), \
         patch("api.analyze.compute_earnings_score", return_value=0.5), \
         patch("api.analyze.compute_trade_setup", return_value=_FAKE_TRADE_CARD):
        resp = client.get("/analyze/AAPL")
    data = resp.json()
    assert "trend_regime" in data
    assert data["trend_regime"] in ("bullish", "bearish", "neutral")


def test_analyze_trade_card_rr_ratio():
    with patch("api.analyze.get_daily_bars", return_value=_FAKE_BARS), \
         patch("api.analyze.compute_indicators", return_value=_FAKE_IND), \
         patch("api.analyze.compute_arima_score", return_value=_FAKE_FCAST), \
         patch("api.analyze.compute_garch_volatility", return_value=_FAKE_GARCH), \
         patch("api.analyze.run_monte_carlo", return_value=_FAKE_MC), \
         patch("api.analyze.compute_congress_score", return_value=0.5), \
         patch("api.analyze.compute_news_score", return_value=0.5), \
         patch("api.analyze.compute_earnings_score", return_value=0.5), \
         patch("api.analyze.compute_trade_setup", return_value=_FAKE_TRADE_CARD):
        resp = client.get("/analyze/AAPL")
    assert resp.json()["trade_card"]["risk_reward_ratio"] == 3.0
```

- [ ] **Step 2: Run to confirm new tests fail**

```
.venv\Scripts\pytest.exe tests/api/test_analyze.py::test_analyze_trade_card_present tests/api/test_analyze.py::test_analyze_trend_regime_present -v
```

Expected: FAIL — `AssertionError: 'trade_card' not in response`

- [ ] **Step 3: Replace `api/analyze.py`**

```python
import logging
import re

from fastapi import APIRouter, HTTPException

from data.market import get_daily_bars
from quant.indicators import compute_indicators
from quant.forecast import compute_arima_score, compute_garch_volatility
from quant.signals import compute_signal
from quant.confidence import run_monte_carlo
from quant.trade_setup import compute_trade_setup
from smart_money.congress import compute_congress_score
from smart_money.news_scorer import compute_news_score
from smart_money.earnings_scorer import compute_earnings_score
import config

logger = logging.getLogger(__name__)

router = APIRouter()

_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")


def analyze_ticker(ticker: str) -> dict:
    ticker = ticker.strip().upper()
    if not _TICKER_RE.match(ticker):
        raise ValueError(f"Invalid ticker format: {ticker!r}")
    if config.is_excluded(ticker):
        raise ValueError(f"{ticker} is excluded from analysis")

    bars = get_daily_bars(ticker, days=250)
    if len(bars) < 60:
        raise ValueError(f"Insufficient history for {ticker}: {len(bars)} bars (need 60)")

    prices = [b["c"] for b in bars]
    current_price = float(bars[-1]["c"])

    ind = compute_indicators(bars)
    fcast = compute_arima_score(prices)
    garch = compute_garch_volatility(prices)

    smart_money_score = compute_congress_score(ticker)
    news_score = compute_news_score(ticker)
    earnings_score = compute_earnings_score(ticker)

    sig = compute_signal(
        technical_score=ind["technical_score"],
        arima_score=fcast["arima_score"],
        smart_money_score=smart_money_score,
        news_score=news_score,
        earnings_score=earnings_score,
    )

    mc = run_monte_carlo(current_price, max(garch["daily_vol"], 0.001))
    trade_card = compute_trade_setup(current_price, ind["atr_stop"])

    return {
        "ticker": ticker,
        "signal": sig,
        "confidence": mc,
        "current_price": round(current_price, 2),
        "trend_regime": ind["ema_trend"],
        "atr_stop": ind["atr_stop"],
        "vol_regime": garch["vol_regime"],
        "rsi": ind["rsi"],
        "trade_card": trade_card,
    }


@router.get("/analyze/{ticker}")
def get_analyze(ticker: str):
    try:
        return analyze_ticker(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("Analysis failed for %s", ticker)
        raise HTTPException(status_code=500, detail="Internal analysis error. Check server logs.")
```

- [ ] **Step 4: Run all analyze tests**

```
.venv\Scripts\pytest.exe tests/api/test_analyze.py -v
```

Expected: All 9 tests PASS (6 existing + 3 new)

- [ ] **Step 5: Run the full test suite**

```
.venv\Scripts\pytest.exe tests/ -v
```

Expected: All 114 tests PASS (96 baseline + 6 backtest + 9 trade_setup + 3 analyze)

- [ ] **Step 6: Commit**

```bash
git add api/analyze.py tests/api/test_analyze.py
git commit -m "feat: add trade_card and trend_regime to /analyze endpoint"
```

---

## Self-Review

**Spec coverage:**
- Sharpe ratio → Task 1 ✅
- Max drawdown → Task 1 ✅
- CAGR → Task 1 ✅
- Take-profit target → Task 2 (`compute_trade_setup`) ✅
- R:R ratio (3:1) → Task 2 ✅
- Trade card as structured output → Task 3 (`trade_card` key in `/analyze`) ✅
- Trend regime formally exposed → Task 3 (`trend_regime` key, replaces `ema_trend`) ✅

**Placeholder scan:** No TBD, TODO, or "add appropriate handling" patterns. All code shown in full.

**Type consistency:**
- `compute_trade_setup(current_price: float, atr_stop: float)` used identically in Task 2 and Task 3
- `run_backtest` returns `sharpe_ratio / max_drawdown / cagr` — all float, `0.0` on zero-signal path ✅
- `_FAKE_TRADE_CARD` matches the actual return shape of `compute_trade_setup` ✅
