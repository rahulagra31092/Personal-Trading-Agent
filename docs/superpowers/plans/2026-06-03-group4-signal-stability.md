# Group 4: Signal Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store daily composite scores per ticker in a lightweight SQLite table. Compute 5-day score delta and surface it in the morning Slack briefing. This gives visibility into whether a signal is building conviction or fading — purely informational for now, not fed back into the composite.

**Architecture:** A new `score_history` table in the existing `paper_portfolio.db`. `log_daily_scores()` writes one row per ticker per day during the morning run. `get_score_trend()` returns the 5-day delta. The briefing picks section shows `↑ +0.06` or `↓ -0.04` next to each ticker score.

**Tech Stack:** Python 3.12, SQLite (sqlite3), existing `paper_portfolio.py` pattern.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `api/paper_portfolio.py` | Modify | Add `score_history` table, `log_daily_scores()`, `get_score_trend()` |
| `api/briefing.py` | Modify | Call `log_daily_scores()` daily; add delta display in picks blocks |
| `tests/api/test_paper_portfolio.py` | Modify | Tests for score history functions |

---

## Task 1: Score History Table and Functions

**Files:**
- Modify: `api/paper_portfolio.py`
- Modify: `tests/api/test_paper_portfolio.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/api/test_paper_portfolio.py`:

```python
from api.paper_portfolio import log_daily_scores, get_score_trend


def test_log_daily_scores_stores_records():
    scores = {"NVDA": 0.72, "AAPL": 0.55, "XOM": 0.38}
    log_daily_scores(scores, date_str="2026-01-10")
    trend = get_score_trend("NVDA", as_of="2026-01-10")
    assert trend["latest_score"] == pytest.approx(0.72)


def test_get_score_trend_no_history_returns_none_delta():
    trend = get_score_trend("UNKNOWN_TICKER", as_of="2026-01-10")
    assert trend["delta_5d"] is None
    assert trend["latest_score"] is None


def test_get_score_trend_rising_signal():
    # Score rises from 0.50 to 0.65 over 6 days
    for i, score in enumerate([0.50, 0.53, 0.56, 0.58, 0.61, 0.65]):
        log_daily_scores({"MSFT": score}, date_str=f"2026-01-0{i+1}")
    trend = get_score_trend("MSFT", as_of="2026-01-06")
    assert trend["delta_5d"] == pytest.approx(0.65 - 0.50, abs=0.001)
    assert trend["direction"] == "rising"


def test_get_score_trend_falling_signal():
    for i, score in enumerate([0.70, 0.67, 0.64, 0.61, 0.58, 0.54]):
        log_daily_scores({"AMZN": score}, date_str=f"2026-01-0{i+1}")
    trend = get_score_trend("AMZN", as_of="2026-01-06")
    assert trend["delta_5d"] < 0
    assert trend["direction"] == "falling"


def test_get_score_trend_flat_signal():
    for i in range(6):
        log_daily_scores({"META": 0.60}, date_str=f"2026-01-0{i+1}")
    trend = get_score_trend("META", as_of="2026-01-06")
    assert trend["direction"] == "flat"


def test_log_daily_scores_idempotent_same_day():
    # Writing the same ticker/date twice should update (upsert)
    log_daily_scores({"NVDA": 0.60}, date_str="2026-01-15")
    log_daily_scores({"NVDA": 0.65}, date_str="2026-01-15")
    trend = get_score_trend("NVDA", as_of="2026-01-15")
    assert trend["latest_score"] == pytest.approx(0.65)
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd "C:\Claude\Trading Analyst"
.\.venv\Scripts\pytest.exe tests/api/test_paper_portfolio.py::test_log_daily_scores_stores_records -v
```

Expected: `ImportError` — `log_daily_scores` not yet defined.

- [ ] **Step 3: Add `score_history` table to `init_paper_db`**

In `api/paper_portfolio.py`, in the `executescript` inside `init_paper_db`, add the new table definition after `signal_outcomes`:

```python
            CREATE TABLE IF NOT EXISTS score_history (
                ticker      TEXT NOT NULL,
                score_date  TEXT NOT NULL,
                composite_score REAL NOT NULL,
                PRIMARY KEY (ticker, score_date)
            );
```

Full updated `init_paper_db` executescript block (add just this table at the end of the script):
```sql
... existing tables ...

CREATE TABLE IF NOT EXISTS score_history (
    ticker          TEXT NOT NULL,
    score_date      TEXT NOT NULL,
    composite_score REAL NOT NULL,
    PRIMARY KEY (ticker, score_date)
);
```

- [ ] **Step 4: Add `log_daily_scores` and `get_score_trend` functions**

Add to `api/paper_portfolio.py`, after `get_open_outcome_tickers()`:

```python
def log_daily_scores(scores: dict[str, float], date_str: str | None = None) -> None:
    """
    Write composite scores for all scored tickers to score_history.
    Upserts — safe to call multiple times per day.
    date_str: ISO date string e.g. "2026-01-15". Defaults to today.
    """
    if not scores:
        return
    if date_str is None:
        date_str = date.today().isoformat()
    init_paper_db()
    try:
        with _conn() as con:
            con.executemany(
                """INSERT INTO score_history (ticker, score_date, composite_score)
                   VALUES (?, ?, ?)
                   ON CONFLICT(ticker, score_date) DO UPDATE SET composite_score = excluded.composite_score""",
                [(t.upper(), date_str, round(float(s), 4)) for t, s in scores.items()],
            )
    except Exception as exc:
        logger.warning("log_daily_scores failed: %s", exc)


def get_score_trend(ticker: str, as_of: str | None = None) -> dict:
    """
    Return the latest composite score and 5-day delta for ticker.
    as_of: ISO date string for testing (defaults to today).
    Returns: {latest_score, delta_5d, direction}
    direction: "rising" | "falling" | "flat" | "insufficient_data"
    """
    init_paper_db()
    if as_of is None:
        as_of = date.today().isoformat()
    try:
        with _conn() as con:
            rows = con.execute(
                """SELECT composite_score FROM score_history
                   WHERE ticker = ? AND score_date <= ?
                   ORDER BY score_date DESC LIMIT 6""",
                (ticker.upper(), as_of),
            ).fetchall()
    except Exception as exc:
        logger.warning("get_score_trend failed for %s: %s", ticker, exc)
        return {"latest_score": None, "delta_5d": None, "direction": "insufficient_data"}

    if not rows:
        return {"latest_score": None, "delta_5d": None, "direction": "insufficient_data"}

    scores_desc = [r[0] for r in rows]
    latest = scores_desc[0]

    if len(scores_desc) < 6:
        return {"latest_score": latest, "delta_5d": None, "direction": "insufficient_data"}

    oldest = scores_desc[-1]
    delta = round(latest - oldest, 4)

    if delta > 0.02:
        direction = "rising"
    elif delta < -0.02:
        direction = "falling"
    else:
        direction = "flat"

    return {"latest_score": latest, "delta_5d": delta, "direction": direction}
```

- [ ] **Step 5: Run tests — all must pass**

```
.\.venv\Scripts\pytest.exe tests/api/test_paper_portfolio.py -v
```

Expected: All original + 6 new score history tests pass.

---

## Task 2: Wire Score Logging and Delta Display into Briefing

**Files:**
- Modify: `api/briefing.py`

### Background
`send_daily_briefing` already builds `score_map` over all results. We just need to:
1. Call `log_daily_scores({ticker: composite_score})` at the end of each daily run.
2. Show the 5-day delta in the picks blocks next to each ticker's score.

- [ ] **Step 1: Log scores at the end of `send_daily_briefing`**

In `api/briefing.py`, add import at top:
```python
from api.paper_portfolio import (
    ..., log_daily_scores, get_score_trend,   # add these two
)
```

At the very end of `send_daily_briefing`, just before `return all_results`, add:

```python
    # Log today's composite scores for trend tracking
    try:
        from api.paper_portfolio import log_daily_scores as _log_scores
        daily_score_map = {
            r["ticker"]: r["signal"]["composite_score"] for r in all_results
        }
        _log_scores(daily_score_map)
    except Exception as exc:
        logger.warning("Daily score logging failed: %s", exc)

    return all_results
```

- [ ] **Step 2: Add delta display to `_picks_blocks`**

In `api/briefing.py`, find the `_picks_blocks` function. Find the line that builds each ticker line:

```python
        lines.append(
            f"*{i}. {r['ticker']}* — {sig['label']} — {score:.2f} ({conviction}) — {price_str}"
        )
```

Replace with:

```python
        # 5-day score trend
        trend = get_score_trend(r["ticker"])
        delta = trend.get("delta_5d")
        if delta is not None and abs(delta) >= 0.02:
            arrow = "up" if delta > 0 else "dn"
            trend_str = f"  [{arrow} {delta:+.2f}]"
        else:
            trend_str = ""

        lines.append(
            f"*{i}. {r['ticker']}* — {sig['label']} — {score:.2f} ({conviction}){trend_str} — {price_str}"
        )
```

- [ ] **Step 3: Run full test suite**

```
.\.venv\Scripts\pytest.exe tests/ -q
```

Expected: All tests pass. (`_picks_blocks` tests check for BUY/WATCH label in output — they don't check the trend string — so no test updates needed.)

- [ ] **Step 4: Commit**

```
git add api/paper_portfolio.py api/briefing.py
git add tests/api/test_paper_portfolio.py
git commit -m "feat(stability): daily score history table, 5-day trend tracking, picks delta display"
```

---

## Self-Review

**Spec coverage:**
- [x] Score history table (ticker, date, composite_score) → Task 1 Step 3
- [x] `log_daily_scores()` writes scores daily → Task 2 Step 1
- [x] `get_score_trend()` returns 5-day delta → Task 1 Step 4
- [x] Trend shown in Slack picks output → Task 2 Step 2
- [x] Score trend is informational only (not fed back into composite) → confirmed: `get_score_trend` is called only in display, not in `compute_signal`

**Placeholder scan:** None.

**Type consistency:** `log_daily_scores` takes `dict[str, float]`. `get_score_trend` returns `dict` with keys `latest_score`, `delta_5d`, `direction`. Both used consistently across Task 1 and Task 2. ✓
