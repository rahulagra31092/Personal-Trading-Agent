# Signal Quality Improvements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the three signal layers that return 0.50 for most tickers (earnings, news, congress), then add a sector momentum overlay and concentration cap so the model makes better portfolio construction decisions.

**Architecture:** Each of the first three tasks repairs one signal module independently. Task 4 adds a new `quant/sector.py` module for portfolio-level logic. Task 5 wires everything into the backtest script to verify the full pipeline. Each task ships with tests and a commit before moving on.

**Tech Stack:** Python 3.12, yfinance, NewsAPI (free tier, 100 req/day), Quiver Quant API, pytest, SQLite cache (`data/cache.py`).

**Working directory:** `C:\Claude\Trading Analyst\`
**Run tests:** `.venv\Scripts\pytest.exe tests/ -v`
**117 tests currently passing — must stay green after every task.**

---

## Context — Why Each Signal Breaks

| Layer | Weight | Problem |
|-------|--------|---------|
| Earnings (E) | 15% | Returns 0.50 when next earnings >30 days away — permanently neutral for 11 months/year |
| News (N) | 15% | NewsAPI free tier = 100 req/day; hits limit at ticker ~70, leaving 120+ tickers at 0.50 |
| Congress (C) | 20% | 90-day lookback misses trades; returns 0.50 when no activity; no institutional ownership signal |

## File Map

| File | Change |
|------|--------|
| `smart_money/earnings_scorer.py` | Rewrite to use EPS beat rate instead of proximity |
| `data/earnings.py` | Add `get_eps_beat_rate(ticker)` public helper |
| `tests/smart_money/test_earnings_scorer.py` | Replace all 12 tests with new beat-rate tests |
| `data/news.py` | Add `prefetch_sector_news(sector_groups, days)` |
| `tests/data/test_news.py` | Add 3 prefetch tests |
| `smart_money/congress.py` | Expand lookback 90→180 days; add `_institutional_adjustment()` |
| `tests/smart_money/test_congress.py` | Add 5 tests for new behaviour |
| `quant/sector.py` | New file: ETF map, `get_sector_momentum()`, `apply_concentration_cap()` |
| `tests/quant/test_sector.py` | New file: 8 tests |
| `scripts/backtest_jan1.py` | Call `prefetch_sector_news()` before loop; call `apply_concentration_cap()` after ranking |

---

## Task 1: Earnings scorer — EPS beat rate replaces proximity

**Files:**
- Modify: `data/earnings.py`
- Rewrite: `smart_money/earnings_scorer.py`
- Rewrite: `tests/smart_money/test_earnings_scorer.py`

The data layer (`data/earnings.py`) already computes `eps_beat_rate` (fraction of last N quarters where actual EPS beat estimate) and stores it in the SQLite cache. The scorer just ignores it. We fix that now.

Scoring formula:
- `base = 0.25 + beat_rate * 0.5` → maps 0%→0.25, 50%→0.50, 100%→0.75
- Proximity modifier: `days 0–3` (just reported) → +0.05; `days 1–7` (pre-earnings tension) → -0.05; otherwise 0
- Final: `clamp(base + modifier, 0.20, 0.80)`

- [ ] **Step 1: Add `get_eps_beat_rate()` to `data/earnings.py`**

```python
def get_eps_beat_rate(ticker: str) -> float | None:
    """Return fraction of last N quarters where EPS beat estimate, or None if unavailable."""
    cal = get_earnings_calendar(ticker)
    return cal.get("eps_beat_rate")
```

Add this function after `days_to_earnings()` at line 46.

- [ ] **Step 2: Write failing tests for the new scorer**

Replace the entire contents of `tests/smart_money/test_earnings_scorer.py` with:

```python
from unittest.mock import patch
from smart_money.earnings_scorer import compute_earnings_score


def _cal(beat_rate, next_date=None):
    return {"eps_beat_rate": beat_rate, "next_earnings_date": next_date, "eps_estimate": 1.0}


def test_full_beat_rate_returns_high():
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=_cal(1.0)):
        assert compute_earnings_score("AAPL") == 0.75


def test_zero_beat_rate_returns_low():
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=_cal(0.0)):
        assert compute_earnings_score("AAPL") == 0.25


def test_half_beat_rate_returns_neutral():
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=_cal(0.5)):
        assert compute_earnings_score("AAPL") == 0.50


def test_three_quarter_beat_rate():
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=_cal(0.75)):
        assert abs(compute_earnings_score("AAPL") - 0.625) < 0.001


def test_none_beat_rate_returns_neutral():
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=_cal(None)):
        assert compute_earnings_score("AAPL") == 0.5


def test_post_earnings_adds_modifier():
    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=_cal(0.75, yesterday)):
        # base=0.625, modifier=+0.05 → 0.675
        assert abs(compute_earnings_score("AAPL") - 0.675) < 0.001


def test_pre_earnings_subtracts_modifier():
    from datetime import date, timedelta
    in_3_days = (date.today() + timedelta(days=3)).isoformat()
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=_cal(0.75, in_3_days)):
        # base=0.625, modifier=-0.05 → 0.575
        assert abs(compute_earnings_score("AAPL") - 0.575) < 0.001


def test_far_earnings_no_modifier():
    from datetime import date, timedelta
    in_45_days = (date.today() + timedelta(days=45)).isoformat()
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=_cal(0.75, in_45_days)):
        assert abs(compute_earnings_score("AAPL") - 0.625) < 0.001


def test_score_bounded_low_end():
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=_cal(0.0)):
        score = compute_earnings_score("AAPL")
        assert score >= 0.20


def test_score_bounded_high_end():
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=_cal(1.0)):
        score = compute_earnings_score("AAPL")
        assert score <= 0.80


def test_exception_returns_neutral():
    with patch("smart_money.earnings_scorer.get_earnings_calendar", side_effect=RuntimeError("api down")):
        assert compute_earnings_score("AAPL") == 0.5


def test_missing_beat_rate_key_returns_neutral():
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value={"eps_estimate": 1.5}):
        assert compute_earnings_score("AAPL") == 0.5
```

- [ ] **Step 3: Run tests to confirm they all fail**

```
.venv\Scripts\pytest.exe tests/smart_money/test_earnings_scorer.py -v
```

Expected: all 12 FAIL (scorer still uses old proximity logic).

- [ ] **Step 4: Rewrite `smart_money/earnings_scorer.py`**

Replace the entire file:

```python
import logging
from datetime import date

from data.earnings import get_earnings_calendar

logger = logging.getLogger(__name__)


def compute_earnings_score(ticker: str) -> float:
    try:
        cal = get_earnings_calendar(ticker)
    except Exception as exc:
        logger.warning("earnings calendar failed for %s: %s", ticker, exc)
        return 0.5

    beat_rate = cal.get("eps_beat_rate")
    if beat_rate is None:
        return 0.5

    # Historical beat rate: 0%→0.25, 50%→0.50, 100%→0.75
    base = 0.25 + beat_rate * 0.5

    # Small proximity modifier
    modifier = 0.0
    raw_date = cal.get("next_earnings_date")
    if raw_date:
        try:
            days = (date.fromisoformat(raw_date) - date.today()).days
            if -3 <= days <= 0:
                modifier = 0.05   # just reported: positive momentum
            elif 1 <= days <= 7:
                modifier = -0.05  # imminent: uncertainty discount
        except Exception:
            pass

    return round(max(0.20, min(0.80, base + modifier)), 4)
```

- [ ] **Step 5: Run tests to confirm they all pass**

```
.venv\Scripts\pytest.exe tests/smart_money/test_earnings_scorer.py -v
```

Expected: 12 PASS.

- [ ] **Step 6: Run full suite to confirm nothing regressed**

```
.venv\Scripts\pytest.exe tests/ -q
```

Expected: 117 passed (old tests deleted and replaced — count stays same).

- [ ] **Step 7: Commit**

```
git add smart_money/earnings_scorer.py data/earnings.py tests/smart_money/test_earnings_scorer.py
git commit -m "feat: earnings scorer uses EPS beat rate instead of proximity signal"
```

---

## Task 2: News scorer — sector-batched prefetch

**Files:**
- Modify: `data/news.py`
- Modify: `tests/data/test_news.py`

The core `compute_news_score(ticker)` function in `smart_money/news_scorer.py` and the `get_ticker_news(ticker)` function in `data/news.py` stay **unchanged**. The fix is a new `prefetch_sector_news(sector_groups)` function that:
1. Accepts a dict mapping sector name → list of tickers
2. Makes one API call per sector with `q="TICK1 OR TICK2 OR ..."` and `pageSize=100`
3. Distributes matched articles to per-ticker cache entries (`news:{ticker}:{days}`)
4. Tickers with zero individual mentions get the top 10 sector articles as fallback

After prefetch runs, all subsequent `get_ticker_news()` calls hit cache — no more 429 errors.

- [ ] **Step 1: Write failing tests for `prefetch_sector_news`**

Add to `tests/data/test_news.py` (after the existing tests):

```python
from data.news import prefetch_sector_news

def test_prefetch_populates_individual_ticker_cache(mocker):
    mock_get = mocker.patch("data.news.requests.get")
    mock_get.return_value.raise_for_status = lambda: None
    mock_get.return_value.json.return_value = {
        "articles": [
            {"title": "AAPL surges on iPhone sales", "description": "Apple record quarter", "publishedAt": "2026-01-02"},
            {"title": "MSFT Azure growth strong", "description": "Cloud momentum", "publishedAt": "2026-01-02"},
        ]
    }

    prefetch_sector_news({"big_tech": ["AAPL", "MSFT"]}, days=3)

    # One API call for the sector, not two individual calls
    assert mock_get.call_count == 1

    # Individual cache should now return without hitting API
    mock_get.reset_mock()
    result = get_ticker_news("AAPL", days=3)
    assert mock_get.call_count == 0  # served from cache
    assert len(result) > 0


def test_prefetch_graceful_on_429(mocker):
    mock_get = mocker.patch("data.news.requests.get")
    import requests as req_lib
    mock_get.return_value.raise_for_status.side_effect = req_lib.exceptions.HTTPError("429")

    # Should not raise — just logs warning
    prefetch_sector_news({"semis": ["NVDA", "AMD"]}, days=3)


def test_prefetch_skips_already_cached_sectors(mocker):
    mock_get = mocker.patch("data.news.requests.get")
    mock_get.return_value.raise_for_status = lambda: None
    mock_get.return_value.json.return_value = {"articles": []}

    prefetch_sector_news({"energy": ["XOM", "CVX"]}, days=3)
    prefetch_sector_news({"energy": ["XOM", "CVX"]}, days=3)  # second call

    # Sector-level API only called once (second call hits cache guard)
    assert mock_get.call_count == 1
```

- [ ] **Step 2: Run tests to confirm they fail**

```
.venv\Scripts\pytest.exe tests/data/test_news.py -v
```

Expected: 3 new tests FAIL (`prefetch_sector_news` not defined).

- [ ] **Step 3: Add `prefetch_sector_news` to `data/news.py`**

Add this function at the end of `data/news.py`, after `get_ticker_news()`:

```python
import logging as _logging

_logger = _logging.getLogger(__name__)


def prefetch_sector_news(sector_groups: dict[str, list[str]], days: int = 3) -> None:
    """
    One API call per sector; distributes articles to per-ticker cache entries.
    Call this before the per-ticker screening loop to avoid hitting the 100 req/day limit.
    """
    from_date = (date.today() - timedelta(days=days)).isoformat()

    for sector_name, tickers in sector_groups.items():
        guard_key = f"news_prefetch:{sector_name}:{days}"
        if get_cache(guard_key) is not None:
            continue  # already fetched today

        query = " OR ".join(tickers)
        try:
            resp = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "from": from_date,
                    "sortBy": "relevancy",
                    "language": "en",
                    "pageSize": 100,
                    "apiKey": config.NEWS_API_KEY,
                },
                timeout=10,
            )
            resp.raise_for_status()
        except Exception as exc:
            _logger.warning("Sector news prefetch failed for %s: %s", sector_name, exc)
            continue

        articles = [
            {
                "title": a.get("title") or "",
                "description": a.get("description") or "",
                "publishedAt": a.get("publishedAt") or "",
            }
            for a in resp.json().get("articles", [])
            if a.get("title")
        ]

        # Distribute: each ticker gets articles that mention it by name
        for ticker in tickers:
            ticker_cache_key = f"news:{ticker}:{days}"
            if get_cache(ticker_cache_key) is not None:
                continue  # already individually cached — don't overwrite
            matched = [
                a for a in articles
                if ticker.upper() in (a["title"] + " " + a["description"]).upper()
            ]
            # Fall back to first 10 sector articles when none mention the ticker
            set_cache(ticker_cache_key, matched or articles[:10], ttl_seconds=3600)

        set_cache(guard_key, True, ttl_seconds=3600)
```

- [ ] **Step 4: Run tests to confirm all pass**

```
.venv\Scripts\pytest.exe tests/data/test_news.py -v
```

Expected: all 6 tests (3 existing + 3 new) PASS.

- [ ] **Step 5: Run full suite**

```
.venv\Scripts\pytest.exe tests/ -q
```

Expected: 120 passed (117 + 3 new).

- [ ] **Step 6: Commit**

```
git add data/news.py tests/data/test_news.py
git commit -m "feat: news prefetch batches sector queries to avoid API rate limit"
```

---

## Task 3: Congress scorer — 180-day lookback + institutional ownership signal

**Files:**
- Modify: `smart_money/congress.py`
- Modify: `tests/smart_money/test_congress.py`

Two changes:
1. Expand lookback from 90 → 180 days so trades from 3–6 months ago are included
2. Add `_institutional_adjustment(ticker)` that reads `yfinance.Ticker.major_holders` and returns a small additive in [-0.05, +0.05] based on institutional ownership %

The adjustment is small by design: it differentiates the many tickers stuck at 0.50 (no congressional trades) without overwhelming the core signal.

- [ ] **Step 1: Write failing tests**

Add these tests to `tests/smart_money/test_congress.py` after the existing tests:

```python
import yfinance as yf
import pandas as pd


def test_180_day_lookback_includes_older_trades():
    # A trade 120 days ago should count with 180-day lookback
    from datetime import datetime, timedelta, timezone
    date_120_ago = (datetime.now(timezone.utc) - timedelta(days=120)).strftime("%Y-%m-%d")
    old_trades = [{"Transaction": "Purchase", "Date": date_120_ago, "Ticker": "AAPL"}]
    with patch("smart_money.congress.get_congress_trades", return_value=old_trades):
        score = compute_congress_score("AAPL")
    # With lookback=180, the trade is included → score > 0.5
    assert score > 0.5


def test_high_institutional_ownership_positive_adjustment(mocker):
    mock_ticker = mocker.MagicMock()
    # major_holders row 1 col 0 = % held by institutions
    mock_ticker.major_holders = pd.DataFrame([[0.05], [0.88]], columns=["Value"])
    mocker.patch("smart_money.congress.yf.Ticker", return_value=mock_ticker)
    with patch("smart_money.congress.get_congress_trades", return_value=[]):
        with patch("smart_money.congress.get_cache", return_value=None):
            score = compute_congress_score("AAPL")
    # No congressional trades → base 0.5 + institutional +0.05 = 0.55
    assert score == 0.55


def test_low_institutional_ownership_negative_adjustment(mocker):
    mock_ticker = mocker.MagicMock()
    mock_ticker.major_holders = pd.DataFrame([[0.10], [0.35]], columns=["Value"])
    mocker.patch("smart_money.congress.yf.Ticker", return_value=mock_ticker)
    with patch("smart_money.congress.get_congress_trades", return_value=[]):
        with patch("smart_money.congress.get_cache", return_value=None):
            score = compute_congress_score("AAPL")
    # No trades → base 0.5 + institutional -0.03 = 0.47
    assert score == 0.47


def test_institutional_adjustment_error_returns_zero(mocker):
    mocker.patch("smart_money.congress.yf.Ticker", side_effect=RuntimeError("network"))
    with patch("smart_money.congress.get_congress_trades", return_value=[]):
        with patch("smart_money.congress.get_cache", return_value=None):
            score = compute_congress_score("AAPL")
    # Error in institutional lookup → base 0.5 + 0.0 = 0.5
    assert score == 0.5


def test_congress_score_clamped_to_0_25_0_75(mocker):
    mock_ticker = mocker.MagicMock()
    mock_ticker.major_holders = pd.DataFrame([[0.02], [0.92]], columns=["Value"])
    mocker.patch("smart_money.congress.yf.Ticker", return_value=mock_ticker)
    # All buys → base 0.7 + 0.05 = 0.75 (clamped)
    all_buys = _sample_trades(10, 0, days_ago=10)
    with patch("smart_money.congress.get_congress_trades", return_value=all_buys):
        with patch("smart_money.congress.get_cache", return_value=None):
            score = compute_congress_score("AAPL")
    assert score <= 0.75
```

- [ ] **Step 2: Run to confirm failure**

```
.venv\Scripts\pytest.exe tests/smart_money/test_congress.py -v
```

Expected: 5 new tests FAIL.

- [ ] **Step 3: Update `smart_money/congress.py`**

Replace the entire file:

```python
import logging
from datetime import datetime, timedelta, timezone

import requests
import yfinance as yf

from data.cache import get_cache, set_cache
import config

logger = logging.getLogger(__name__)

_QUIVER_API_KEY: str | None = config.QUIVER_API_KEY
_QUIVER_BASE = "https://api.quiverquant.com/beta"


def get_congress_trades(ticker: str) -> list[dict]:
    ticker = ticker.strip().upper()
    cache_key = f"congress:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    if not _QUIVER_API_KEY:
        return []

    try:
        resp = requests.get(
            f"{_QUIVER_BASE}/historical/congresstrading/{ticker}",
            headers={"Authorization": f"Token {_QUIVER_API_KEY}"},
            timeout=10,
        )
        resp.raise_for_status()
        trades = resp.json()
    except Exception as exc:
        logger.warning("Congress trades fetch failed for %s: %s", ticker, exc)
        return []

    set_cache(cache_key, trades, ttl_seconds=6 * 3600)
    return trades


def _institutional_adjustment(ticker: str) -> float:
    """Return small additive in [-0.05, +0.05] based on institutional ownership %."""
    cache_key = f"institutional:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    adj = 0.0
    try:
        t = yf.Ticker(ticker)
        mh = t.major_holders
        if mh is not None and not mh.empty:
            pct_inst = float(mh.iloc[1, 0])
            if pct_inst > 0.80:
                adj = 0.05
            elif pct_inst < 0.50:
                adj = -0.03
    except Exception as exc:
        logger.debug("Institutional holders fetch failed for %s: %s", ticker, exc)

    set_cache(cache_key, adj, ttl_seconds=86400)
    return adj


def compute_congress_score(ticker: str, lookback_days: int = 180) -> float:
    trades = get_congress_trades(ticker)

    congress_base = 0.5
    if trades:
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        buys = 0
        sells = 0
        for trade in trades:
            try:
                date_str = trade.get("Date") or trade.get("TransactionDate") or ""
                if not date_str:
                    continue
                trade_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                if trade_date.tzinfo is None:
                    trade_date = trade_date.replace(tzinfo=timezone.utc)
                if trade_date < cutoff:
                    continue
                txn = (trade.get("Transaction") or "").lower()
                if "purchase" in txn or "buy" in txn:
                    buys += 1
                elif "sale" in txn or "sell" in txn:
                    sells += 1
            except Exception:
                continue

        total = buys + sells
        if total > 0:
            congress_base = 0.3 + (buys / total) * 0.4

    adj = _institutional_adjustment(ticker)
    return round(max(0.25, min(0.75, congress_base + adj)), 4)
```

- [ ] **Step 4: Run tests to confirm all pass**

```
.venv\Scripts\pytest.exe tests/smart_money/test_congress.py -v
```

Expected: all 11 tests (6 existing + 5 new) PASS.

- [ ] **Step 5: Run full suite**

```
.venv\Scripts\pytest.exe tests/ -q
```

Expected: 125 passed.

- [ ] **Step 6: Commit**

```
git add smart_money/congress.py tests/smart_money/test_congress.py
git commit -m "feat: congress scorer expands to 180-day lookback and adds institutional ownership signal"
```

---

## Task 4: Sector module — ETF momentum + concentration cap

**Files:**
- Create: `quant/sector.py`
- Create: `tests/quant/test_sector.py`

`quant/sector.py` provides:
1. `SECTOR_ETF_MAP` — ticker → GICS sector ETF symbol
2. `get_sector_momentum(etf, lookback_days=63)` — trailing 3-month return of the sector ETF, normalized to [0.0, 1.0]
3. `sector_weight_multiplier(ticker, lookback_days=63)` — returns 1.05 (top tercile), 1.00 (middle), or 0.90 (bottom tercile)
4. `NARROW_SUB_SECTORS` — dict of name → set of tickers that are effectively correlated bets
5. `apply_concentration_cap(ranked, max_per_sub_sector=2)` — reorders ranked list so no sub-sector has more than N picks in the top positions

- [ ] **Step 1: Write failing tests**

Create `tests/quant/test_sector.py`:

```python
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest
from quant.sector import (
    SECTOR_ETF_MAP,
    get_sector_momentum,
    sector_weight_multiplier,
    apply_concentration_cap,
    NARROW_SUB_SECTORS,
)


def test_known_tickers_have_etf_mapping():
    for ticker in ["AAPL", "JPM", "LLY", "XOM", "GE", "PG", "NEE", "T", "FCX", "AMT"]:
        assert SECTOR_ETF_MAP.get(ticker) is not None, f"{ticker} missing from SECTOR_ETF_MAP"


def test_unknown_ticker_returns_none():
    assert SECTOR_ETF_MAP.get("ZZZZ") is None


def _make_price_series(start, end, n=70):
    import numpy as np
    prices = np.linspace(start, end, n)
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    df = pd.DataFrame({"Close": prices}, index=idx)
    return df


def test_sector_momentum_rising_market_above_half():
    with patch("quant.sector.yf.download", return_value=_make_price_series(100, 115)):
        score = get_sector_momentum("XLK")
    assert score > 0.5


def test_sector_momentum_falling_market_below_half():
    with patch("quant.sector.yf.download", return_value=_make_price_series(115, 100)):
        score = get_sector_momentum("XLK")
    assert score < 0.5


def test_sector_momentum_bounded():
    with patch("quant.sector.yf.download", return_value=_make_price_series(100, 200)):
        score = get_sector_momentum("XLK")
    assert 0.0 <= score <= 1.0


def test_sector_weight_top_tercile_returns_1_05():
    with patch("quant.sector.get_sector_momentum", return_value=0.75):
        assert sector_weight_multiplier("AAPL") == 1.05


def test_sector_weight_bottom_tercile_returns_0_90():
    with patch("quant.sector.get_sector_momentum", return_value=0.25):
        assert sector_weight_multiplier("AAPL") == 0.90


def test_apply_concentration_cap_demotes_third_alt_manager():
    ranked = [
        {"ticker": "A", "composite_score": 0.80},
        {"ticker": "KKR", "composite_score": 0.75},
        {"ticker": "BX", "composite_score": 0.70},
        {"ticker": "ARES", "composite_score": 0.65},  # 3rd alt_manager — demoted
        {"ticker": "Z", "composite_score": 0.60},
    ]
    result = apply_concentration_cap(ranked, max_per_sub_sector=2)
    top_tickers = [r["ticker"] for r in result[:4]]
    assert "ARES" not in top_tickers
    assert "A" in top_tickers and "Z" in top_tickers


def test_apply_concentration_cap_preserves_uncapped_tickers():
    ranked = [
        {"ticker": "AAPL", "composite_score": 0.80},
        {"ticker": "MSFT", "composite_score": 0.75},
        {"ticker": "NVDA", "composite_score": 0.70},
    ]
    result = apply_concentration_cap(ranked, max_per_sub_sector=2)
    assert [r["ticker"] for r in result] == ["AAPL", "MSFT", "NVDA"]
```

- [ ] **Step 2: Run to confirm all fail**

```
.venv\Scripts\pytest.exe tests/quant/test_sector.py -v
```

Expected: all 10 FAIL (module not found).

- [ ] **Step 3: Create `quant/sector.py`**

```python
import logging
import yfinance as yf

logger = logging.getLogger(__name__)

# GICS sector ETF for each universe ticker
SECTOR_ETF_MAP: dict[str, str] = {
    # XLK — Technology
    "AAPL": "XLK", "MSFT": "XLK", "NVDA": "XLK", "AVGO": "XLK", "ORCL": "XLK",
    "CRM": "XLK", "ADBE": "XLK", "AMD": "XLK", "QCOM": "XLK", "TXN": "XLK",
    "INTC": "XLK", "MU": "XLK", "AMAT": "XLK", "LRCX": "XLK", "KLAC": "XLK",
    "MRVL": "XLK", "NOW": "XLK", "PLTR": "XLK", "PANW": "XLK", "FTNT": "XLK",
    "CRWD": "XLK", "ZS": "XLK", "NET": "XLK", "DDOG": "XLK", "MDB": "XLK",
    "ARM": "XLK", "CSCO": "XLK", "IBM": "XLK", "DELL": "XLK", "ANET": "XLK",
    "HPE": "XLK", "SMCI": "XLK", "CDNS": "XLK", "SNPS": "XLK", "ANSS": "XLK",
    "EPAM": "XLK",
    # XLC — Communication Services
    "GOOGL": "XLC", "META": "XLC", "T": "XLC", "VZ": "XLC", "TMUS": "XLC",
    "CHTR": "XLC", "CMCSA": "XLC", "DIS": "XLC", "NFLX": "XLC", "SPOT": "XLC",
    "SNAP": "XLC", "PINS": "XLC",
    # XLF — Financials
    "JPM": "XLF", "BAC": "XLF", "WFC": "XLF", "GS": "XLF", "MS": "XLF",
    "BLK": "XLF", "C": "XLF", "AXP": "XLF", "COF": "XLF", "USB": "XLF",
    "TFC": "XLF", "PNC": "XLF", "SCHW": "XLF", "CME": "XLF", "ICE": "XLF",
    "MCO": "XLF", "SPGI": "XLF", "V": "XLF", "MA": "XLF", "PYPL": "XLF",
    "KKR": "XLF", "APO": "XLF", "BX": "XLF", "CG": "XLF", "ARES": "XLF",
    # XLV — Health Care
    "LLY": "XLV", "UNH": "XLV", "JNJ": "XLV", "ABBV": "XLV", "MRK": "XLV",
    "PFE": "XLV", "BMY": "XLV", "AMGN": "XLV", "GILD": "XLV", "ISRG": "XLV",
    "MDT": "XLV", "ABT": "XLV", "TMO": "XLV", "DHR": "XLV", "SYK": "XLV",
    "BSX": "XLV", "ELV": "XLV", "CVS": "XLV", "CI": "XLV", "HUM": "XLV",
    "VRTX": "XLV", "REGN": "XLV", "BIIB": "XLV", "MRNA": "XLV", "ZBH": "XLV",
    # XLY — Consumer Discretionary
    "AMZN": "XLY", "TSLA": "XLY", "HD": "XLY", "LOW": "XLY", "TGT": "XLY",
    "MCD": "XLY", "SBUX": "XLY", "NKE": "XLY", "TJX": "XLY", "BKNG": "XLY",
    "MAR": "XLY", "HLT": "XLY", "LVS": "XLY", "WYNN": "XLY", "MGM": "XLY",
    "F": "XLY", "GM": "XLY", "RIVN": "XLY", "LCID": "XLY", "POOL": "XLY",
    "UBER": "XLY", "LYFT": "XLY", "DASH": "XLY", "ABNB": "XLY",
    # XLP — Consumer Staples
    "WMT": "XLP", "COST": "XLP", "PG": "XLP", "KO": "XLP", "PEP": "XLP",
    "PM": "XLP", "MO": "XLP", "CL": "XLP", "MDLZ": "XLP", "GIS": "XLP",
    "K": "XLP", "STZ": "XLP",
    # XLE — Energy
    "XOM": "XLE", "CVX": "XLE", "COP": "XLE", "EOG": "XLE", "SLB": "XLE",
    "MPC": "XLE", "VLO": "XLE", "PSX": "XLE", "DVN": "XLE", "HAL": "XLE",
    # XLI — Industrials
    "GE": "XLI", "HON": "XLI", "UPS": "XLI", "FDX": "XLI", "CAT": "XLI",
    "DE": "XLI", "LMT": "XLI", "RTX": "XLI", "NOC": "XLI", "GD": "XLI",
    "BA": "XLI", "MMM": "XLI", "EMR": "XLI", "ETN": "XLI", "PH": "XLI",
    "ROK": "XLI", "ITW": "XLI", "IR": "XLI", "AME": "XLI", "CARR": "XLI",
    # XLB — Materials
    "FCX": "XLB", "NEM": "XLB", "APD": "XLB", "LIN": "XLB", "SHW": "XLB",
    "ECL": "XLB", "DD": "XLB", "DOW": "XLB", "ALB": "XLB", "MP": "XLB",
    # XLRE — Real Estate
    "AMT": "XLRE", "PLD": "XLRE", "EQIX": "XLRE", "SPG": "XLRE", "CBRE": "XLRE",
    "WELL": "XLRE", "O": "XLRE", "DLR": "XLRE", "PSA": "XLRE", "AVB": "XLRE",
    # XLU — Utilities
    "NEE": "XLU", "DUK": "XLU", "SO": "XLU", "AEP": "XLU", "EXC": "XLU",
    "SRE": "XLU", "PCG": "XLU", "XEL": "XLU", "WEC": "XLU", "ES": "XLU",
}

# Correlated sub-sector clusters — cap at 2 picks each to avoid hidden concentration
NARROW_SUB_SECTORS: dict[str, frozenset[str]] = {
    "alt_asset_managers": frozenset({"KKR", "BX", "ARES", "APO", "CG"}),
    "ev_startups":        frozenset({"RIVN", "LCID"}),
    "gig_economy":        frozenset({"UBER", "LYFT", "DASH", "ABNB"}),
    "casinos":            frozenset({"LVS", "WYNN", "MGM"}),
}

_TICKER_TO_SUB: dict[str, str] = {
    ticker: sub
    for sub, tickers in NARROW_SUB_SECTORS.items()
    for ticker in tickers
}


def get_sector_momentum(etf: str, lookback_days: int = 63) -> float:
    """
    Trailing ~3-month return of sector ETF, normalized to [0.0, 1.0].
    0.5 = flat; >0.5 = positive momentum; <0.5 = negative.
    Normalization range: ±15% maps to ±0.5 (i.e., +15% → 1.0, -15% → 0.0).
    """
    try:
        data = yf.download(etf, period="6mo", progress=False, auto_adjust=True)
        if data.empty or len(data) < lookback_days:
            return 0.5
        price_now = float(data["Close"].iloc[-1])
        price_then = float(data["Close"].iloc[-lookback_days])
        pct_return = (price_now - price_then) / price_then
        score = 0.5 + pct_return / 0.30  # ±15% → ±0.5
        return round(max(0.0, min(1.0, score)), 4)
    except Exception as exc:
        logger.warning("Sector momentum fetch failed for %s: %s", etf, exc)
        return 0.5


def sector_weight_multiplier(ticker: str, lookback_days: int = 63) -> float:
    """
    Returns 1.05 (top tercile), 1.00 (middle), or 0.90 (bottom tercile)
    based on sector ETF trailing momentum. Used to scale final position size.
    """
    etf = SECTOR_ETF_MAP.get(ticker.upper())
    if etf is None:
        return 1.0
    momentum = get_sector_momentum(etf, lookback_days)
    if momentum > 0.60:
        return 1.05
    if momentum < 0.40:
        return 0.90
    return 1.00


def apply_concentration_cap(
    ranked: list[dict], max_per_sub_sector: int = 2
) -> list[dict]:
    """
    Reorders ranked list so no narrow sub-sector has more than max_per_sub_sector
    picks in the top positions. Excess picks are appended at the end.
    Input list must be sorted by composite_score descending (highest first).
    """
    counts: dict[str, int] = {}
    selected: list[dict] = []
    demoted: list[dict] = []

    for stock in ranked:
        sub = _TICKER_TO_SUB.get(stock["ticker"])
        if sub is None:
            selected.append(stock)
        else:
            counts[sub] = counts.get(sub, 0) + 1
            if counts[sub] <= max_per_sub_sector:
                selected.append(stock)
            else:
                demoted.append(stock)

    return selected + demoted
```

- [ ] **Step 4: Run tests to confirm all pass**

```
.venv\Scripts\pytest.exe tests/quant/test_sector.py -v
```

Expected: all 10 PASS.

- [ ] **Step 5: Run full suite**

```
.venv\Scripts\pytest.exe tests/ -q
```

Expected: 135 passed.

- [ ] **Step 6: Commit**

```
git add quant/sector.py tests/quant/test_sector.py
git commit -m "feat: sector ETF map, momentum scoring, and concentration cap"
```

---

## Task 5: Wire everything into `scripts/backtest_jan1.py`

**Files:**
- Modify: `scripts/backtest_jan1.py`

Three wiring changes:
1. Call `prefetch_sector_news(SECTOR_GROUPS)` before the ticker loop so the news scorer gets real data for all tickers within the daily API budget
2. Call `apply_concentration_cap(ranked)` after ranking, before slicing the portfolio
3. Print `sector_weight_multiplier` in the output table for visibility (info only — no position sizing change in this script since all positions are fixed $1K)

No new tests needed — this is a script, not a library function. Run the updated script and verify: BUY signal count increases, Spearman correlation improves vs the -0.107 baseline.

- [ ] **Step 1: Add imports to `scripts/backtest_jan1.py`**

After the existing imports block (after line 22, before `# -- Config`), add:

```python
from data.news import prefetch_sector_news
from quant.sector import apply_concentration_cap, SECTOR_ETF_MAP
```

- [ ] **Step 2: Add `SECTOR_GROUPS` constant and `prefetch_sector_news` call**

Add after the `UNIVERSE` list (after line 64, before `# -- Helper`):

```python
# -- Sector groups for batched news prefetch (one API call per sector) ---------
SECTOR_GROUPS: dict[str, list[str]] = {}
for _t in UNIVERSE:
    _etf = SECTOR_ETF_MAP.get(_t)
    if _etf:
        SECTOR_GROUPS.setdefault(_etf, []).append(_t)
```

Then add right before the `# -- Screening` print block:

```python
print("Pre-fetching sector news (batched to stay within API limit)...")
prefetch_sector_news(SECTOR_GROUPS, days=3)
print(f"  {len(SECTOR_GROUPS)} sector queries issued (vs {len(UNIVERSE)} individual calls)\n")
```

- [ ] **Step 3: Apply concentration cap after ranking**

Find this block (around line 169–172):

```python
ranked = sorted(results, key=lambda x: x["composite_score"], reverse=True)
portfolio   = ranked[:MAX_POSITIONS]
avoided     = ranked[MAX_POSITIONS:]
```

Replace with:

```python
ranked    = sorted(results, key=lambda x: x["composite_score"], reverse=True)
ranked    = apply_concentration_cap(ranked, max_per_sub_sector=2)
portfolio = ranked[:MAX_POSITIONS]
avoided   = ranked[MAX_POSITIONS:]
```

- [ ] **Step 4: Run the script and capture summary**

```
.venv\Scripts\python.exe scripts\backtest_jan1.py 2>$null | Select-Object -Last 50
```

Verify:
- "Pre-fetching sector news" line appears and shows fewer API calls than tickers
- BUY label count is higher than 13 (earnings scorer now active)
- Spearman correlation is positive (closer to +0.1 or better)
- No crashes

- [ ] **Step 5: Run full test suite one final time**

```
.venv\Scripts\pytest.exe tests/ -q
```

Expected: 135 passed.

- [ ] **Step 6: Commit**

```
git add scripts/backtest_jan1.py
git commit -m "feat: wire sector news prefetch and concentration cap into Jan1 backtest"
```

---

## Self-Review

**Spec coverage:**
- ✅ Earnings scorer → Task 1 (EPS beat rate, proximity modifier, bounded output)
- ✅ News batching → Task 2 (prefetch_sector_news, guard key, fallback)
- ✅ Congress 180-day → Task 3 (lookback_days=180 default)
- ✅ Institutional signal → Task 3 (_institutional_adjustment, caching, [-0.05,+0.05])
- ✅ Sector momentum → Task 4 (get_sector_momentum, normalization, tercile multiplier)
- ✅ Concentration cap → Task 4 (apply_concentration_cap, NARROW_SUB_SECTORS)
- ✅ Wiring → Task 5 (backtest_jan1.py updated)

**Placeholder scan:** None found — all steps include complete code.

**Type consistency:**
- `get_earnings_calendar()` returns `dict` with key `eps_beat_rate: float | None` — used correctly in Task 1
- `prefetch_sector_news(sector_groups: dict[str, list[str]], days: int)` → used correctly in Task 5
- `apply_concentration_cap(ranked: list[dict], max_per_sub_sector: int)` → used correctly in Task 5
- `get_sector_momentum(etf: str, lookback_days: int) -> float` → used correctly in Task 4 tests
- `SECTOR_ETF_MAP: dict[str, str]` → used correctly in Task 5 for building SECTOR_GROUPS
