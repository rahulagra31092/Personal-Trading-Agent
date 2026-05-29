# Trading Analyst — Plan 1: Foundation & Data Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Set up the Python project with a working FastAPI server and all data collectors (market prices, news, earnings) backed by a SQLite cache layer.

**Architecture:** Python 3.12 + FastAPI + SQLite for caching. External API calls flow through `data/cache.py` first to avoid redundant requests between morning/evening runs. Each collector is an independent module. FUBO exclusion enforced at the data layer — any attempt to fetch FUBO data raises `ValueError`.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, polygon-api-client, yfinance, requests, pytest, pytest-mock

---

## File Map

| File | Responsibility |
|------|---------------|
| `requirements.txt` | All Python dependencies pinned |
| `.env.example` | Template for secrets (never commit `.env`) |
| `config.py` | Loads env vars, defines constants (weights, phases, exclusions) |
| `data/__init__.py` | Empty package marker |
| `data/cache.py` | SQLite get/set with TTL — used by all collectors |
| `data/market.py` | Polygon.io daily bars + yfinance historical + crypto prices |
| `data/news.py` | NewsAPI articles by ticker |
| `data/earnings.py` | yfinance earnings calendar, beat rate, days-to-earnings |
| `api/__init__.py` | Empty package marker |
| `api/main.py` | FastAPI app with lifespan (init DB) + `/health` endpoint |
| `tests/data/test_cache.py` | Cache unit tests |
| `tests/data/test_market.py` | Market collector unit tests |
| `tests/data/test_news.py` | News collector unit tests |
| `tests/data/test_earnings.py` | Earnings collector unit tests |
| `tests/test_api_health.py` | FastAPI health endpoint test |

---

### Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `config.py`
- Create: `tests/__init__.py`
- Create: `tests/data/__init__.py`
- Create: `tests/quant/__init__.py`
- Create: `tests/smart_money/__init__.py`
- Create: `tests/portfolio/__init__.py`
- Create: `tests/narrator/__init__.py`

- [ ] **Step 1: Create requirements.txt**

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
polygon-api-client==1.14.0
yfinance==0.2.40
requests==2.32.0
httpx==0.27.0
pandas==2.2.0
numpy==1.26.0
pandas-ta==0.3.14b
statsmodels==0.14.2
scipy==1.13.0
anthropic==0.34.0
schwab-py==1.4.0
python-dotenv==1.0.0
pytest==8.3.0
pytest-mock==3.14.0
```

- [ ] **Step 2: Create .env.example**

```
POLYGON_API_KEY=your_polygon_key_here
CLAUDE_API_KEY=your_claude_key_here
NEWS_API_KEY=your_newsapi_key_here
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/your/webhook/url
SCHWAB_CLIENT_ID=your_schwab_client_id
SCHWAB_CLIENT_SECRET=your_schwab_client_secret
```

- [ ] **Step 3: Create config.py**

```python
# config.py
import os
from dotenv import load_dotenv

load_dotenv()

POLYGON_API_KEY = os.environ["POLYGON_API_KEY"]
CLAUDE_API_KEY = os.environ["CLAUDE_API_KEY"]
NEWS_API_KEY = os.environ["NEWS_API_KEY"]
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
SCHWAB_CLIENT_ID = os.environ.get("SCHWAB_CLIENT_ID", "")
SCHWAB_CLIENT_SECRET = os.environ.get("SCHWAB_CLIENT_SECRET", "")

EXCLUDED_TICKERS: set[str] = {"FUBO"}

SIGNAL_WEIGHTS: dict[str, float] = {
    "technical": 0.30,
    "arima": 0.20,
    "smart_money": 0.20,
    "news_reaction": 0.15,
    "earnings": 0.15,
}

PHASE: int = 1
PHASE2_LIVE_CAPITAL: float = 2500.0
PHASE3_LIVE_CAPITAL: float = 5000.0
PHASE2_HARD_STOP: float = 2000.0
PHASE3_HARD_STOP: float = 4000.0
PHASE2_MIN_CONFIDENCE: float = 0.70
PHASE3_MIN_CONFIDENCE: float = 0.65
```

- [ ] **Step 4: Create test directories and init files**

```bash
mkdir -p tests/data tests/quant tests/smart_money tests/portfolio tests/narrator
touch tests/__init__.py
touch tests/data/__init__.py
touch tests/quant/__init__.py
touch tests/smart_money/__init__.py
touch tests/portfolio/__init__.py
touch tests/narrator/__init__.py
```

- [ ] **Step 5: Copy .env.example to .env and fill in keys**

```bash
cp .env.example .env
```
Open `.env` and fill in: `POLYGON_API_KEY`, `CLAUDE_API_KEY`, `NEWS_API_KEY`, `SLACK_WEBHOOK_URL`. Leave Schwab blank for now.

- [ ] **Step 6: Install dependencies and verify**

```bash
pip install -r requirements.txt
python -c "import fastapi, polygon, yfinance, anthropic, pandas_ta; print('All imports OK')"
```
Expected output: `All imports OK`

- [ ] **Step 7: Commit**

```bash
git init
git add requirements.txt .env.example config.py tests/
git commit -m "feat: project scaffold — requirements, config, test structure"
```

---

### Task 2: SQLite Cache Layer

**Files:**
- Create: `data/__init__.py`
- Create: `data/cache.py`
- Create: `tests/data/test_cache.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/data/test_cache.py
import time
import pytest
from data.cache import get_cache, set_cache, init_db

@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr("data.cache.DB_PATH", tmp_path / "test_cache.db")
    init_db()

def test_cache_miss_returns_none():
    assert get_cache("nonexistent_key") is None

def test_cache_hit_returns_value():
    set_cache("key1", {"price": 42.0}, ttl_seconds=60)
    assert get_cache("key1") == {"price": 42.0}

def test_expired_cache_returns_none():
    set_cache("key2", {"price": 99.0}, ttl_seconds=1)
    time.sleep(1.1)
    assert get_cache("key2") is None

def test_overwrite_existing_key():
    set_cache("key3", {"v": 1}, ttl_seconds=60)
    set_cache("key3", {"v": 2}, ttl_seconds=60)
    assert get_cache("key3") == {"v": 2}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/data/test_cache.py -v
```
Expected: `ModuleNotFoundError: No module named 'data'`

- [ ] **Step 3: Create data/__init__.py**

```bash
touch data/__init__.py
```

- [ ] **Step 4: Implement data/cache.py**

```python
# data/cache.py
import sqlite3
import json
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "cache.db"

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                expires_at REAL NOT NULL
            )
        """)

def get_cache(key: str) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        value, expires_at = row
        if expires_at != 0 and expires_at < time.time():
            return None
        return json.loads(value)

def set_cache(key: str, value: dict, ttl_seconds: int = 3600) -> None:
    expires_at = time.time() + ttl_seconds if ttl_seconds > 0 else 0
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), expires_at),
        )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/data/test_cache.py -v
```
Expected: `4 passed`

- [ ] **Step 6: Commit**

```bash
git add data/__init__.py data/cache.py tests/data/test_cache.py
git commit -m "feat: SQLite cache layer with TTL support"
```

---

### Task 3: FastAPI Skeleton

**Files:**
- Create: `api/__init__.py`
- Create: `api/main.py`
- Create: `tests/test_api_health.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_api_health.py
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_api_health.py -v
```
Expected: `ModuleNotFoundError: No module named 'api'`

- [ ] **Step 3: Create api/__init__.py**

```bash
touch api/__init__.py
```

- [ ] **Step 4: Implement api/main.py**

```python
# api/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from data.cache import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="Trading Analyst API", version="1.0.0", lifespan=lifespan)

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_api_health.py -v
```
Expected: `1 passed`

- [ ] **Step 6: Verify server starts manually**

```bash
uvicorn api.main:app --reload --port 8000
```
Expected: `Application startup complete.`
Stop with Ctrl+C.

- [ ] **Step 7: Commit**

```bash
git add api/__init__.py api/main.py tests/test_api_health.py
git commit -m "feat: FastAPI skeleton with /health endpoint and DB lifespan"
```

---

### Task 4: Market Data Collector

**Files:**
- Create: `data/market.py`
- Create: `tests/data/test_market.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/data/test_market.py
import pytest
import pandas as pd
from unittest.mock import MagicMock
from data.market import get_daily_bars, get_historical_prices, get_crypto_price

@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr("data.cache.DB_PATH", tmp_path / "test_cache.db")
    from data.cache import init_db
    init_db()

def _make_bar(close: float = 183.0, volume: int = 1_000_000):
    bar = MagicMock()
    bar.timestamp = 1_700_000_000_000
    bar.open = close - 1
    bar.high = close + 2
    bar.low = close - 2
    bar.close = close
    bar.volume = volume
    return bar

def test_get_daily_bars_returns_list(mocker):
    mocker.patch("data.market.RESTClient").return_value.list_aggs.return_value = [_make_bar()]
    result = get_daily_bars("AMZN", days=1)
    assert isinstance(result, list)
    assert result[0]["c"] == 183.0
    assert result[0]["v"] == 1_000_000

def test_get_daily_bars_caches_result(mocker):
    mock_client = mocker.patch("data.market.RESTClient").return_value
    mock_client.list_aggs.return_value = [_make_bar()]
    get_daily_bars("AMZN", days=1)
    get_daily_bars("AMZN", days=1)
    assert mock_client.list_aggs.call_count == 1

def test_excluded_ticker_raises_on_bars():
    with pytest.raises(ValueError, match="FUBO is excluded"):
        get_daily_bars("FUBO", days=5)

def test_excluded_ticker_raises_on_historical():
    with pytest.raises(ValueError, match="FUBO is excluded"):
        get_historical_prices("FUBO")

def test_get_crypto_price_returns_float(mocker):
    mock_hist = pd.DataFrame({"Close": [95_000.0]})
    mocker.patch("data.market.yf.Ticker").return_value.history.return_value = mock_hist
    assert get_crypto_price("BTC") == 95_000.0

def test_get_crypto_price_caches(mocker):
    mock_ticker = mocker.patch("data.market.yf.Ticker").return_value
    mock_ticker.history.return_value = pd.DataFrame({"Close": [50_000.0]})
    get_crypto_price("ETH")
    get_crypto_price("ETH")
    assert mock_ticker.history.call_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/data/test_market.py -v
```
Expected: `ModuleNotFoundError: No module named 'data.market'`

- [ ] **Step 3: Implement data/market.py**

```python
# data/market.py
import yfinance as yf
from polygon import RESTClient
from datetime import date, timedelta
from data.cache import get_cache, set_cache
import config

def get_daily_bars(ticker: str, days: int = 30) -> list[dict]:
    if ticker in config.EXCLUDED_TICKERS:
        raise ValueError(f"{ticker} is excluded from analysis")

    cache_key = f"bars:{ticker}:{days}"
    cached = get_cache(cache_key)
    if cached:
        return cached

    client = RESTClient(config.POLYGON_API_KEY)
    end = date.today()
    start = end - timedelta(days=days * 2)

    bars = [
        {"t": b.timestamp, "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume}
        for b in client.list_aggs(ticker, 1, "day", str(start), str(end))
    ]

    result = bars[-days:] if len(bars) >= days else bars
    set_cache(cache_key, result, ttl_seconds=3600)
    return result

def get_historical_prices(ticker: str, years: int = 2) -> list[dict]:
    if ticker in config.EXCLUDED_TICKERS:
        raise ValueError(f"{ticker} is excluded from analysis")

    cache_key = f"hist:{ticker}:{years}"
    cached = get_cache(cache_key)
    if cached:
        return cached

    hist = yf.Ticker(ticker).history(period=f"{years}y", auto_adjust=True)
    result = [
        {"date": str(idx.date()), "open": row.Open, "high": row.High,
         "low": row.Low, "close": row.Close, "volume": row.Volume}
        for idx, row in hist.iterrows()
    ]
    set_cache(cache_key, result, ttl_seconds=86400)
    return result

def get_crypto_price(symbol: str) -> float:
    cache_key = f"crypto:{symbol}"
    cached = get_cache(cache_key)
    if cached:
        return cached["price"]

    hist = yf.Ticker(f"{symbol}-USD").history(period="1d")
    if hist.empty:
        raise ValueError(f"No price data for {symbol}")

    price = float(hist["Close"].iloc[-1])
    set_cache(cache_key, {"price": price}, ttl_seconds=300)
    return price
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/data/test_market.py -v
```
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add data/market.py tests/data/test_market.py
git commit -m "feat: market data collector — Polygon.io bars, yfinance historical, crypto prices"
```

---

### Task 5: News Data Collector

**Files:**
- Create: `data/news.py`
- Create: `tests/data/test_news.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/data/test_news.py
import pytest
from data.news import get_ticker_news

@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr("data.cache.DB_PATH", tmp_path / "test_cache.db")
    from data.cache import init_db
    init_db()

def test_returns_list_of_articles(mocker):
    mock_get = mocker.patch("data.news.requests.get")
    mock_get.return_value.json.return_value = {
        "articles": [
            {"title": "AMZN AWS deal", "description": "Big contract", "publishedAt": "2026-05-18T10:00:00Z"},
            {"title": "AMZN beats Q1", "description": "Strong results", "publishedAt": "2026-05-17T14:00:00Z"},
        ]
    }
    mock_get.return_value.raise_for_status = lambda: None

    result = get_ticker_news("AMZN", days=3)

    assert len(result) == 2
    assert result[0]["title"] == "AMZN AWS deal"
    assert "publishedAt" in result[0]

def test_empty_response_returns_empty_list(mocker):
    mock_get = mocker.patch("data.news.requests.get")
    mock_get.return_value.json.return_value = {"articles": []}
    mock_get.return_value.raise_for_status = lambda: None

    assert get_ticker_news("GOOG", days=1) == []

def test_caches_on_second_call(mocker):
    mock_get = mocker.patch("data.news.requests.get")
    mock_get.return_value.json.return_value = {"articles": []}
    mock_get.return_value.raise_for_status = lambda: None

    get_ticker_news("META", days=1)
    get_ticker_news("META", days=1)

    assert mock_get.call_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/data/test_news.py -v
```
Expected: `ModuleNotFoundError: No module named 'data.news'`

- [ ] **Step 3: Implement data/news.py**

```python
# data/news.py
import requests
from datetime import date, timedelta
from data.cache import get_cache, set_cache
import config

def get_ticker_news(ticker: str, days: int = 3) -> list[dict]:
    cache_key = f"news:{ticker}:{days}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    from_date = (date.today() - timedelta(days=days)).isoformat()
    resp = requests.get(
        "https://newsapi.org/v2/everything",
        params={
            "q": ticker,
            "from": from_date,
            "sortBy": "relevancy",
            "language": "en",
            "pageSize": 10,
            "apiKey": config.NEWS_API_KEY,
        },
        timeout=10,
    )
    resp.raise_for_status()

    result = [
        {"title": a["title"], "description": a.get("description", ""), "publishedAt": a["publishedAt"]}
        for a in resp.json().get("articles", [])
    ]
    set_cache(cache_key, result, ttl_seconds=3600)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/data/test_news.py -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add data/news.py tests/data/test_news.py
git commit -m "feat: news data collector — NewsAPI with ticker search and SQLite cache"
```

---

### Task 6: Earnings Data Collector

**Files:**
- Create: `data/earnings.py`
- Create: `tests/data/test_earnings.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/data/test_earnings.py
import pytest
import pandas as pd
from unittest.mock import MagicMock
from datetime import date, timedelta
from data.earnings import get_earnings_calendar, days_to_earnings

@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr("data.cache.DB_PATH", tmp_path / "test_cache.db")
    from data.cache import init_db
    init_db()

def test_returns_dict_with_required_keys(mocker):
    mock_ticker = MagicMock()
    mock_ticker.info = {"forwardEps": 1.25}
    mock_ticker.calendar = pd.DataFrame(
        {"AMZN": [pd.Timestamp("2026-05-22")]}, index=["Earnings Date"]
    )
    mock_ticker.earnings_history = pd.DataFrame({"surprisePercent": [5.0, -2.0, 3.0, 8.0]})
    mocker.patch("data.earnings.yf.Ticker", return_value=mock_ticker)

    result = get_earnings_calendar("AMZN")

    assert result["eps_estimate"] == 1.25
    assert result["eps_beat_rate"] == 0.75
    assert result["next_earnings_date"] == "2026-05-22"

def test_days_to_earnings_returns_correct_count(mocker):
    future = (date.today() + timedelta(days=5)).isoformat()
    mocker.patch("data.earnings.get_earnings_calendar", return_value={
        "next_earnings_date": future, "eps_estimate": 1.0, "eps_beat_rate": 0.7,
    })
    assert days_to_earnings("AMZN") == 5

def test_days_to_earnings_none_when_no_date(mocker):
    mocker.patch("data.earnings.get_earnings_calendar", return_value={
        "next_earnings_date": None, "eps_estimate": None, "eps_beat_rate": None,
    })
    assert days_to_earnings("AMZN") is None

def test_beat_rate_none_on_empty_history(mocker):
    mock_ticker = MagicMock()
    mock_ticker.info = {}
    mock_ticker.calendar = None
    mock_ticker.earnings_history = pd.DataFrame()
    mocker.patch("data.earnings.yf.Ticker", return_value=mock_ticker)

    result = get_earnings_calendar("SHOP")
    assert result["eps_beat_rate"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/data/test_earnings.py -v
```
Expected: `ModuleNotFoundError: No module named 'data.earnings'`

- [ ] **Step 3: Implement data/earnings.py**

```python
# data/earnings.py
import yfinance as yf
import pandas as pd
from datetime import date
from data.cache import get_cache, set_cache

def get_earnings_calendar(ticker: str) -> dict:
    cache_key = f"earnings:{ticker}"
    cached = get_cache(cache_key)
    if cached:
        return cached

    t = yf.Ticker(ticker)
    info = t.info or {}

    result: dict = {
        "next_earnings_date": None,
        "eps_estimate": info.get("forwardEps"),
        "eps_beat_rate": _calculate_beat_rate(t),
    }

    try:
        cal = t.calendar
        if cal is not None and not cal.empty and "Earnings Date" in cal.index:
            raw = cal.loc["Earnings Date"].iloc[0]
            if pd.notna(raw):
                result["next_earnings_date"] = str(pd.Timestamp(raw).date())
    except Exception:
        pass

    set_cache(cache_key, result, ttl_seconds=86400)
    return result

def days_to_earnings(ticker: str) -> int | None:
    cal = get_earnings_calendar(ticker)
    if not cal.get("next_earnings_date"):
        return None
    return (date.fromisoformat(cal["next_earnings_date"]) - date.today()).days

def _calculate_beat_rate(ticker_obj: yf.Ticker) -> float | None:
    try:
        history = ticker_obj.earnings_history
        if history is None or history.empty:
            return None
        total = len(history)
        beats = int((history["surprisePercent"] > 0).sum())
        return round(beats / total, 2) if total > 0 else None
    except Exception:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/data/test_earnings.py -v
```
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add data/earnings.py tests/data/test_earnings.py
git commit -m "feat: earnings data collector — calendar, EPS beat rate, days-to-earnings"
```

---

### Task 7: Full Suite Verification

**Files:** No new files — verifies all Plan 1 work end-to-end.

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short
```
Expected: `18 passed` (4 cache + 6 market + 3 news + 4 earnings + 1 health)

- [ ] **Step 2: Start server and verify /health**

```bash
uvicorn api.main:app --port 8000 &
curl http://localhost:8000/health
```
Expected: `{"status":"ok"}`

```bash
curl http://localhost:8000/docs
```
Expected: HTTP 200 (OpenAPI docs page)

```bash
kill %1
```

- [ ] **Step 3: Smoke test market data with real keys**

```bash
python -c "
from data.market import get_daily_bars, get_crypto_price
bars = get_daily_bars('AMZN', days=5)
print(f'AMZN bars: {len(bars)} days, latest close: {bars[-1][\"c\"]}')
btc = get_crypto_price('BTC')
print(f'BTC price: \${btc:,.2f}')
"
```
Expected: Real prices printed, no errors.

- [ ] **Step 4: Final commit**

```bash
git add .
git commit -m "chore: Plan 1 complete — foundation, cache, FastAPI, all data collectors verified"
```

---

## What Plan 2 Builds Next

Plan 2 (Quant Engine) imports from `data/market.py`, `data/news.py`, and `data/earnings.py` to implement all 8 model layers: technical indicators, ARIMA/GARCH forecasting, signal scoring, Monte Carlo confidence bands, backtester with bias guards, earnings analysis, and Claude-powered news reaction classification.
