# Plan 3: Earnings Scorer, Analyze Endpoint, Slack Briefing & Portfolio Tracker

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the full 5-layer analysis pipeline into a `/analyze/{ticker}` API endpoint, add an earnings scorer, build a Slack morning briefing, and add a portfolio P&L tracker.

**Architecture:** A shared `analyze_ticker()` function in `api/analyze.py` runs all 5 signal layers and feeds both the REST endpoint and the briefing script. Portfolio tracker loads `data/holdings.csv` and enriches each position with live price and ATR stop data. All external API calls are mocked in tests.

**Tech Stack:** FastAPI, yfinance (via existing `data/market.py`), Polygon (via `get_daily_bars`), requests (Slack webhook), Python csv stdlib.

---

## File Structure

| Action | Path | Purpose |
|--------|------|---------|
| Create | `smart_money/earnings_scorer.py` | `compute_earnings_score(ticker) -> float` |
| Create | `tests/smart_money/test_earnings_scorer.py` | 7 tests |
| Create | `api/analyze.py` | `analyze_ticker()` shared logic + FastAPI router |
| Modify | `api/main.py` | Include analyze + portfolio routers |
| Create | `tests/api/__init__.py` | Package marker |
| Create | `tests/api/test_analyze.py` | 4 tests |
| Create | `api/briefing.py` | `build_briefing_message()`, `send_slack_briefing()` |
| Create | `scripts/slack_briefing.py` | CLI entry for n8n |
| Create | `tests/api/test_briefing.py` | 5 tests |
| Create | `data/holdings.py` | `load_holdings()`, `save_holdings()` |
| Create | `data/holdings.csv` | Sample CSV (user fills in real positions) |
| Create | `api/portfolio.py` | FastAPI router for `/portfolio/pnl` |
| Create | `tests/portfolio/test_portfolio.py` | 5 tests |

---

### Task 1: compute_earnings_score()

**Files:**
- Create: `smart_money/earnings_scorer.py`
- Create: `tests/smart_money/test_earnings_scorer.py`

Signal logic: `days_to_earnings()` returns int|None. Map to a 0–1 score:
- `None` or `> 30` → 0.5 (unknown / too far away, neutral)
- `8–30` → 0.55 (approaching catalyst, slight positive)
- `1–7` → 0.2 (imminent earnings, avoid risk)
- `-3–0` → 0.7 (just reported, uncertainty resolved)
- `< -3` → 0.5 (stale, irrelevant)

- [ ] **Step 1: Write the failing tests**

```python
# tests/smart_money/test_earnings_scorer.py
from unittest.mock import patch
from smart_money.earnings_scorer import compute_earnings_score


def test_none_days_returns_neutral():
    with patch("smart_money.earnings_scorer.days_to_earnings", return_value=None):
        assert compute_earnings_score("AAPL") == 0.5


def test_far_earnings_returns_neutral():
    with patch("smart_money.earnings_scorer.days_to_earnings", return_value=45):
        assert compute_earnings_score("AAPL") == 0.5


def test_approaching_earnings_returns_slight_positive():
    with patch("smart_money.earnings_scorer.days_to_earnings", return_value=15):
        assert compute_earnings_score("AAPL") == 0.55


def test_imminent_earnings_returns_low():
    with patch("smart_money.earnings_scorer.days_to_earnings", return_value=3):
        assert compute_earnings_score("AAPL") == 0.2


def test_post_earnings_returns_high():
    with patch("smart_money.earnings_scorer.days_to_earnings", return_value=-1):
        assert compute_earnings_score("AAPL") == 0.7


def test_stale_earnings_returns_neutral():
    with patch("smart_money.earnings_scorer.days_to_earnings", return_value=-10):
        assert compute_earnings_score("AAPL") == 0.5


def test_exception_returns_neutral():
    with patch(
        "smart_money.earnings_scorer.days_to_earnings",
        side_effect=Exception("network error"),
    ):
        assert compute_earnings_score("AAPL") == 0.5
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd "C:\Claude\Trading Analyst"
.venv\Scripts\pytest.exe tests/smart_money/test_earnings_scorer.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` (file doesn't exist yet).

- [ ] **Step 3: Write the implementation**

```python
# smart_money/earnings_scorer.py
from data.earnings import days_to_earnings


def compute_earnings_score(ticker: str) -> float:
    try:
        days = days_to_earnings(ticker)
    except Exception:
        return 0.5

    if days is None or days > 30:
        return 0.5
    if days > 7:
        return 0.55
    if days >= 1:
        return 0.2
    if days >= -3:
        return 0.7
    return 0.5
```

- [ ] **Step 4: Run tests to confirm they pass**

```
.venv\Scripts\pytest.exe tests/smart_money/test_earnings_scorer.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```
git add smart_money/earnings_scorer.py tests/smart_money/test_earnings_scorer.py
git commit -m "feat: add compute_earnings_score() — days_to_earnings to 0-1 signal"
```

---

### Task 2: GET /analyze/{ticker} Endpoint

**Files:**
- Create: `api/analyze.py`
- Modify: `api/main.py`
- Create: `tests/api/__init__.py`
- Create: `tests/api/test_analyze.py`

The endpoint runs all 5 signal layers and returns the full analysis result. The `analyze_ticker()` function is also imported by the briefing module in Task 3.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/__init__.py
# (empty)
```

```python
# tests/api/test_analyze.py
from unittest.mock import patch
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

_FAKE_BARS = [
    {
        "t": 1700000000000 + i * 86400000,
        "o": 100.0,
        "h": 105.0,
        "l": 98.0,
        "c": 102.0 + i * 0.1,
        "v": 1_000_000,
    }
    for i in range(100)
]


def test_analyze_returns_required_keys():
    with patch("api.analyze.get_daily_bars", return_value=_FAKE_BARS), \
         patch("api.analyze.compute_congress_score", return_value=0.5), \
         patch("api.analyze.compute_news_score", return_value=0.5), \
         patch("api.analyze.compute_earnings_score", return_value=0.5):
        resp = client.get("/analyze/AAPL")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("ticker", "signal", "confidence", "current_price", "atr_stop", "vol_regime"):
        assert key in data


def test_analyze_excluded_ticker_returns_400():
    resp = client.get("/analyze/FUBO")
    assert resp.status_code == 400


def test_analyze_signal_has_label():
    with patch("api.analyze.get_daily_bars", return_value=_FAKE_BARS), \
         patch("api.analyze.compute_congress_score", return_value=0.5), \
         patch("api.analyze.compute_news_score", return_value=0.5), \
         patch("api.analyze.compute_earnings_score", return_value=0.5):
        resp = client.get("/analyze/MSFT")
    assert resp.json()["signal"]["label"] in ("BUY", "WATCH", "AVOID")


def test_analyze_confidence_has_prob_success():
    with patch("api.analyze.get_daily_bars", return_value=_FAKE_BARS), \
         patch("api.analyze.compute_congress_score", return_value=0.5), \
         patch("api.analyze.compute_news_score", return_value=0.5), \
         patch("api.analyze.compute_earnings_score", return_value=0.5):
        resp = client.get("/analyze/NVDA")
    conf = resp.json()["confidence"]
    assert "prob_success" in conf
    assert 0.0 <= conf["prob_success"] <= 1.0
```

- [ ] **Step 2: Run tests to confirm they fail**

```
.venv\Scripts\pytest.exe tests/api/test_analyze.py -v
```

Expected: `ImportError` — `api.analyze` doesn't exist yet.

- [ ] **Step 3: Create api/analyze.py**

```python
# api/analyze.py
import logging

from fastapi import APIRouter, HTTPException

from data.market import get_daily_bars
from quant.indicators import compute_indicators
from quant.forecast import compute_arima_score, compute_garch_volatility
from quant.signals import compute_signal
from quant.confidence import run_monte_carlo
from smart_money.congress import compute_congress_score
from smart_money.news_scorer import compute_news_score
from smart_money.earnings_scorer import compute_earnings_score
import config

logger = logging.getLogger(__name__)

router = APIRouter()


def analyze_ticker(ticker: str) -> dict:
    ticker = ticker.strip().upper()
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

    mc = run_monte_carlo(current_price, max(garch["daily_vol"], 0.001), seed=42)

    return {
        "ticker": ticker,
        "signal": sig,
        "confidence": mc,
        "current_price": round(current_price, 2),
        "atr_stop": ind["atr_stop"],
        "vol_regime": garch["vol_regime"],
        "rsi": ind["rsi"],
        "ema_trend": ind["ema_trend"],
    }


@router.get("/analyze/{ticker}")
def get_analyze(ticker: str):
    try:
        return analyze_ticker(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Analysis failed for %s", ticker)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")
```

- [ ] **Step 4: Modify api/main.py to include the analyze router**

Replace the entire contents of `api/main.py` with:

```python
# api/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from data.cache import init_db
from api.analyze import router as analyze_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Trading Analyst API", version="1.0.0", lifespan=lifespan)
app.include_router(analyze_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 5: Run all tests to confirm no regressions**

```
.venv\Scripts\pytest.exe tests/ -v
```

Expected: all previous tests + 4 new analyze tests pass.

- [ ] **Step 6: Commit**

```
git add api/analyze.py api/main.py tests/api/__init__.py tests/api/test_analyze.py
git commit -m "feat: add GET /analyze/{ticker} — full 5-layer pipeline endpoint"
```

---

### Task 3: Slack Morning Briefing

**Files:**
- Create: `api/briefing.py`
- Create: `scripts/slack_briefing.py`
- Create: `tests/api/test_briefing.py`

The briefing screens a fixed list of tickers, filters to BUY signals, formats a Slack message, and POSTs to the webhook URL. `build_briefing_message()` is a pure function (testable without mocks). `send_slack_briefing()` wires it to Slack.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_briefing.py
from unittest.mock import patch, MagicMock
from api.briefing import build_briefing_message, send_slack_briefing, BRIEFING_TICKERS

_FAKE_BUY = {
    "ticker": "NVDA",
    "signal": {"label": "BUY", "composite_score": 0.72, "layer_scores": {}},
    "confidence": {
        "prob_success": 0.54,
        "base_target": 900.0,
        "lower_80": 860.0,
        "upper_80": 940.0,
        "downside_pct": -0.04,
        "upside_pct": 0.04,
    },
    "current_price": 880.0,
    "atr_stop": 842.0,
    "vol_regime": "medium",
    "rsi": 55.0,
    "ema_trend": "bullish",
}

_FAKE_WATCH = {
    "ticker": "AAPL",
    "signal": {"label": "WATCH", "composite_score": 0.51, "layer_scores": {}},
    "confidence": {
        "prob_success": 0.49,
        "base_target": 195.0,
        "lower_80": 188.0,
        "upper_80": 202.0,
        "downside_pct": -0.03,
        "upside_pct": 0.03,
    },
    "current_price": 193.5,
    "atr_stop": 185.0,
    "vol_regime": "low",
    "rsi": 50.0,
    "ema_trend": "neutral",
}


def test_build_briefing_message_includes_buy_ticker():
    msg = build_briefing_message([_FAKE_BUY, _FAKE_WATCH])
    assert "NVDA" in msg


def test_build_briefing_message_no_buys():
    msg = build_briefing_message([_FAKE_WATCH])
    assert "No BUY signals" in msg


def test_build_briefing_message_shows_screened_count():
    msg = build_briefing_message([_FAKE_BUY, _FAKE_WATCH])
    assert "2 tickers" in msg


def test_send_slack_briefing_posts_to_webhook():
    with patch("api.briefing.screen_tickers", return_value=[_FAKE_BUY]), \
         patch("api.briefing.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status.return_value = None
        send_slack_briefing(["NVDA"])
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert "text" in kwargs["json"]


def test_briefing_tickers_is_nonempty_list():
    assert isinstance(BRIEFING_TICKERS, list)
    assert len(BRIEFING_TICKERS) > 0
```

- [ ] **Step 2: Run tests to confirm they fail**

```
.venv\Scripts\pytest.exe tests/api/test_briefing.py -v
```

Expected: `ImportError` — `api.briefing` doesn't exist yet.

- [ ] **Step 3: Create api/briefing.py**

```python
# api/briefing.py
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from api.analyze import analyze_ticker
import config

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

BRIEFING_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AVGO",
    "AMD", "QCOM", "JPM", "BAC", "GS", "V", "MA", "LLY", "UNH", "JNJ",
    "HD", "COST", "XOM", "CVX", "GE", "CAT", "NEE", "NFLX", "DDOG",
    "CRM", "PLTR", "ARM",
]


def screen_tickers(tickers: list[str]) -> list[dict]:
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker))
        except Exception as exc:
            logger.warning("Skipping %s: %s", ticker, exc)
    return results


def build_briefing_message(results: list[dict]) -> str:
    buys = sorted(
        [r for r in results if r["signal"]["label"] == "BUY"],
        key=lambda r: r["signal"]["composite_score"],
        reverse=True,
    )
    top = buys[:5]
    now_et = datetime.now(_ET).strftime("%Y-%m-%d %H:%M ET")
    lines = [f"*Trading Analyst — Morning Brief* ({now_et})", ""]

    if not top:
        lines.append("No BUY signals today.")
    else:
        lines.append(f"*:green_circle: Top BUY Signals ({len(buys)} found):*")
        for i, r in enumerate(top, 1):
            sig = r["signal"]
            mc = r["confidence"]
            lines.append(
                f"{i}. *{r['ticker']}*  Score: {sig['composite_score']:.2f}"
                f"  Prob: {mc['prob_success']:.0%}"
                f"  Price: ${r['current_price']:.2f}"
                f"  Stop: ${r['atr_stop']:.2f}"
            )

    lines.append("")
    lines.append(f"_Screened {len(results)} tickers_")
    return "\n".join(lines)


def send_slack_briefing(tickers: list[str]) -> None:
    results = screen_tickers(tickers)
    message = build_briefing_message(results)
    resp = requests.post(
        config.SLACK_WEBHOOK_URL,
        json={"text": message},
        timeout=10,
    )
    resp.raise_for_status()
    logger.info("Slack briefing sent: %d tickers screened", len(results))
```

- [ ] **Step 4: Create scripts/slack_briefing.py**

```python
# scripts/slack_briefing.py
#!/usr/bin/env python3
"""
Entry point for n8n to call at 7am ET on weekdays.
n8n command: python C:\Claude\Trading Analyst\scripts\slack_briefing.py
"""
import sys

sys.path.insert(0, r"C:\Claude\Trading Analyst")

from api.briefing import BRIEFING_TICKERS, send_slack_briefing

if __name__ == "__main__":
    send_slack_briefing(BRIEFING_TICKERS)
```

- [ ] **Step 5: Run all tests to confirm no regressions**

```
.venv\Scripts\pytest.exe tests/ -v
```

Expected: all previous tests + 5 new briefing tests pass.

- [ ] **Step 6: Commit**

```
git add api/briefing.py scripts/slack_briefing.py tests/api/test_briefing.py
git commit -m "feat: Slack morning briefing — screens tickers, posts top 5 BUY signals"
```

---

### Task 4: Portfolio Tracker

**Files:**
- Create: `data/holdings.py`
- Create: `data/holdings.csv`
- Create: `api/portfolio.py`
- Modify: `api/main.py`
- Create: `tests/portfolio/test_portfolio.py`

The portfolio tracker loads `data/holdings.csv`, fetches current prices + ATR stops via existing market/indicators modules, and returns a full P&L summary.

- [ ] **Step 1: Write the failing tests**

```python
# tests/portfolio/test_portfolio.py
import os
import tempfile
from unittest.mock import patch
from fastapi.testclient import TestClient
from data.holdings import load_holdings, save_holdings
from api.main import app

client = TestClient(app)

_FAKE_BARS = [
    {
        "t": 1700000000000 + i * 86400000,
        "o": 100.0,
        "h": 105.0,
        "l": 98.0,
        "c": 102.0 + i * 0.1,
        "v": 1_000_000,
    }
    for i in range(30)
]


def test_load_holdings_returns_empty_when_file_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = load_holdings(os.path.join(tmpdir, "holdings.csv"))
        assert result == []


def test_save_and_load_holdings_roundtrip():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
        tmppath = f.name
    try:
        holdings = [{"ticker": "AAPL", "shares": 10.0, "cost_basis": 150.0}]
        save_holdings(holdings, tmppath)
        loaded = load_holdings(tmppath)
        assert loaded[0]["ticker"] == "AAPL"
        assert loaded[0]["shares"] == 10.0
        assert loaded[0]["cost_basis"] == 150.0
    finally:
        os.unlink(tmppath)


def test_portfolio_pnl_empty_holdings():
    with patch("api.portfolio.load_holdings", return_value=[]):
        resp = client.get("/portfolio/pnl")
    assert resp.status_code == 200
    assert resp.json()["positions"] == []


def test_portfolio_pnl_returns_positions():
    holdings = [{"ticker": "AAPL", "shares": 10.0, "cost_basis": 150.0}]
    with patch("api.portfolio.load_holdings", return_value=holdings), \
         patch("api.portfolio.get_daily_bars", return_value=_FAKE_BARS):
        resp = client.get("/portfolio/pnl")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["positions"]) == 1
    pos = data["positions"][0]
    assert pos["ticker"] == "AAPL"
    assert "pnl" in pos
    assert "atr_stop" in pos
    assert "below_stop" in pos


def test_portfolio_pnl_computes_totals():
    holdings = [
        {"ticker": "AAPL", "shares": 10.0, "cost_basis": 100.0},
        {"ticker": "MSFT", "shares": 5.0, "cost_basis": 200.0},
    ]
    with patch("api.portfolio.load_holdings", return_value=holdings), \
         patch("api.portfolio.get_daily_bars", return_value=_FAKE_BARS):
        resp = client.get("/portfolio/pnl")
    data = resp.json()
    assert "total_value" in data
    assert "total_pnl" in data
    assert "total_pnl_pct" in data
    assert data["total_cost"] == pytest.approx(10.0 * 100.0 + 5.0 * 200.0)
```

Wait — `pytest.approx` requires importing pytest. Add this import at the top of the test file:

```python
# tests/portfolio/test_portfolio.py  (complete file — replace the above with this)
import os
import tempfile
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from data.holdings import load_holdings, save_holdings
from api.main import app

client = TestClient(app)

_FAKE_BARS = [
    {
        "t": 1700000000000 + i * 86400000,
        "o": 100.0,
        "h": 105.0,
        "l": 98.0,
        "c": 102.0 + i * 0.1,
        "v": 1_000_000,
    }
    for i in range(30)
]


def test_load_holdings_returns_empty_when_file_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = load_holdings(os.path.join(tmpdir, "holdings.csv"))
        assert result == []


def test_save_and_load_holdings_roundtrip():
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
        tmppath = f.name
    try:
        holdings = [{"ticker": "AAPL", "shares": 10.0, "cost_basis": 150.0}]
        save_holdings(holdings, tmppath)
        loaded = load_holdings(tmppath)
        assert loaded[0]["ticker"] == "AAPL"
        assert loaded[0]["shares"] == 10.0
        assert loaded[0]["cost_basis"] == 150.0
    finally:
        os.unlink(tmppath)


def test_portfolio_pnl_empty_holdings():
    with patch("api.portfolio.load_holdings", return_value=[]):
        resp = client.get("/portfolio/pnl")
    assert resp.status_code == 200
    assert resp.json()["positions"] == []


def test_portfolio_pnl_returns_positions():
    holdings = [{"ticker": "AAPL", "shares": 10.0, "cost_basis": 150.0}]
    with patch("api.portfolio.load_holdings", return_value=holdings), \
         patch("api.portfolio.get_daily_bars", return_value=_FAKE_BARS):
        resp = client.get("/portfolio/pnl")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["positions"]) == 1
    pos = data["positions"][0]
    assert pos["ticker"] == "AAPL"
    assert "pnl" in pos
    assert "atr_stop" in pos
    assert "below_stop" in pos


def test_portfolio_pnl_computes_totals():
    holdings = [
        {"ticker": "AAPL", "shares": 10.0, "cost_basis": 100.0},
        {"ticker": "MSFT", "shares": 5.0, "cost_basis": 200.0},
    ]
    with patch("api.portfolio.load_holdings", return_value=holdings), \
         patch("api.portfolio.get_daily_bars", return_value=_FAKE_BARS):
        resp = client.get("/portfolio/pnl")
    data = resp.json()
    assert "total_value" in data
    assert "total_pnl" in data
    assert "total_pnl_pct" in data
    assert data["total_cost"] == pytest.approx(10.0 * 100.0 + 5.0 * 200.0)
```

- [ ] **Step 2: Run tests to confirm they fail**

```
.venv\Scripts\pytest.exe tests/portfolio/test_portfolio.py -v
```

Expected: `ImportError` — `data.holdings` and `api.portfolio` don't exist yet.

- [ ] **Step 3: Create data/holdings.py**

```python
# data/holdings.py
import csv
import os
from pathlib import Path

_HOLDINGS_PATH = Path(__file__).parent / "holdings.csv"


def load_holdings(path: str | None = None) -> list[dict]:
    target = Path(path) if path else _HOLDINGS_PATH
    if not target.exists():
        return []
    holdings = []
    with target.open(newline="") as f:
        for row in csv.DictReader(f):
            holdings.append({
                "ticker": row["ticker"].strip().upper(),
                "shares": float(row["shares"]),
                "cost_basis": float(row["cost_basis"]),
            })
    return holdings


def save_holdings(holdings: list[dict], path: str | None = None) -> None:
    target = Path(path) if path else _HOLDINGS_PATH
    with target.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ticker", "shares", "cost_basis"])
        writer.writeheader()
        writer.writerows(holdings)
```

- [ ] **Step 4: Create data/holdings.csv (sample — user fills in real positions)**

```csv
ticker,shares,cost_basis
```

This is intentionally empty (just headers). Rahul adds his actual positions here.
Example row format: `AAPL,10,150.00`

- [ ] **Step 5: Create api/portfolio.py**

```python
# api/portfolio.py
import logging

from fastapi import APIRouter

from data.holdings import load_holdings
from data.market import get_daily_bars
from quant.indicators import compute_indicators

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/portfolio/pnl")
def get_portfolio_pnl():
    holdings = load_holdings()
    if not holdings:
        return {
            "positions": [],
            "total_value": 0.0,
            "total_cost": 0.0,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
        }

    positions = []
    total_value = 0.0
    total_cost = 0.0

    for h in holdings:
        ticker = h["ticker"]
        shares = h["shares"]
        cost_basis = h["cost_basis"]

        current_price = None
        atr_stop = None
        below_stop = None

        try:
            bars = get_daily_bars(ticker, days=30)
            current_price = float(bars[-1]["c"])
            ind = compute_indicators(bars)
            atr_stop = ind["atr_stop"]
            below_stop = current_price < atr_stop
        except Exception as exc:
            logger.warning("Could not fetch live data for %s: %s", ticker, exc)

        position_cost = cost_basis * shares
        position_value = (current_price or 0.0) * shares
        pnl = position_value - position_cost
        pnl_pct = round(pnl / position_cost * 100, 2) if position_cost > 0 else 0.0

        total_value += position_value
        total_cost += position_cost

        positions.append({
            "ticker": ticker,
            "shares": shares,
            "cost_basis": cost_basis,
            "current_price": round(current_price, 2) if current_price is not None else None,
            "value": round(position_value, 2),
            "cost": round(position_cost, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": pnl_pct,
            "atr_stop": round(atr_stop, 2) if atr_stop is not None else None,
            "below_stop": below_stop,
        })

    total_pnl = total_value - total_cost
    total_pnl_pct = round(total_pnl / total_cost * 100, 2) if total_cost > 0 else 0.0

    return {
        "positions": positions,
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": total_pnl_pct,
    }
```

- [ ] **Step 6: Modify api/main.py to include the portfolio router**

Replace the entire contents of `api/main.py` with:

```python
# api/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from data.cache import init_db
from api.analyze import router as analyze_router
from api.portfolio import router as portfolio_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Trading Analyst API", version="1.0.0", lifespan=lifespan)
app.include_router(analyze_router)
app.include_router(portfolio_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 7: Run all tests to confirm everything passes**

```
.venv\Scripts\pytest.exe tests/ -v
```

Expected: all previous tests + 5 new portfolio tests pass. Total should be ~88 tests.

- [ ] **Step 8: Commit**

```
git add data/holdings.py data/holdings.csv api/portfolio.py api/main.py tests/portfolio/test_portfolio.py
git commit -m "feat: portfolio tracker — /portfolio/pnl endpoint with ATR stop monitoring"
```

---

## Self-Review

**1. Spec coverage:**
- ✅ `compute_earnings_score()` — Task 1
- ✅ `GET /analyze/{ticker}` full 5-layer pipeline — Task 2
- ✅ Slack morning briefing with top 5 BUY signals — Task 3
- ✅ Portfolio tracker with `holdings.csv` + `/portfolio/pnl` + ATR stop monitoring — Task 4

**2. Placeholder scan:**
- No TBD, TODO, or "add error handling" stubs
- All code blocks are complete
- All test assertions are concrete

**3. Type consistency:**
- `analyze_ticker()` defined in Task 2 and imported in Task 3 ✅
- `load_holdings()` / `save_holdings()` defined in Task 4 and used in Task 4 tests ✅
- `get_daily_bars()` always returns `list[dict]` with `t,o,h,l,c,v` keys — consistent with existing usage ✅
- `compute_indicators()` always returns dict with `atr_stop`, `rsi`, `ema_trend` — used in Task 2 and Task 4 ✅
