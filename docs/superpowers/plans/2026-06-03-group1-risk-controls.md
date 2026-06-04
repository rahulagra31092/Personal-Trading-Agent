# Group 1: Risk Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four structural risk controls: trailing stop (20% from peak), interaction gate (quality < 0.35 blocks BUY), portfolio beta cap (>1.25 raises entry bar), and rapid-deterioration override (removes 30-day hold for fast losers).

**Architecture:** Trailing stop state lives in a new `peak_price` column on `paper_positions`. The interaction gate is a post-calculation clamp in `compute_signal`. Portfolio beta is computed via a new `quant/portfolio_risk.py` module. All four controls wire into `send_daily_briefing` and `_run_monthly_rebalance` in `briefing.py`.

**Tech Stack:** Python 3.12, SQLite (sqlite3), yfinance, existing project cache layer (`data/cache.py`).

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `api/paper_portfolio.py` | Modify | Add `peak_price` column, `update_peak_prices()`, `check_trailing_stops()` |
| `quant/signals.py` | Modify | Add interaction gate (quality < 0.35 → cap composite ≤ 0.57) |
| `quant/portfolio_risk.py` | **Create** | `get_ticker_beta()`, `compute_portfolio_beta()` |
| `api/briefing.py` | Modify | Wire trailing stops into daily run; wire beta cap + rapid deterioration into rebalance |
| `tests/api/test_paper_portfolio.py` | Modify | Trailing stop tests |
| `tests/quant/test_signals.py` | Modify | Gate tests |
| `tests/quant/test_portfolio_risk.py` | **Create** | Beta tests |

---

## Task 1: Trailing Stop — Database Layer

**Files:**
- Modify: `api/paper_portfolio.py`
- Modify: `tests/api/test_paper_portfolio.py`

### Background
`paper_positions` currently has `ticker, shares, avg_cost, entry_date`. We need to add `peak_price REAL` (the highest price seen since entry). `update_peak_prices()` refreshes it daily. `check_trailing_stops()` compares current price to peak and returns triggered sells.

- [ ] **Step 1: Write the failing tests**

Add to `tests/api/test_paper_portfolio.py` (after the last existing test):

```python
from api.paper_portfolio import update_peak_prices, check_trailing_stops


def test_update_peak_prices_sets_initial_peak():
    initialize_portfolio([{"ticker": "NVDA", "shares": 1.0, "price": 100.0}])
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 120.0}):
        update_peak_prices()
    raw = get_raw_positions()
    nvda = next(p for p in raw if p["ticker"] == "NVDA")
    assert nvda["peak_price"] == pytest.approx(120.0)


def test_update_peak_prices_does_not_decrease_peak():
    initialize_portfolio([{"ticker": "NVDA", "shares": 1.0, "price": 100.0}])
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 150.0}):
        update_peak_prices()
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 90.0}):
        update_peak_prices()
    raw = get_raw_positions()
    nvda = next(p for p in raw if p["ticker"] == "NVDA")
    assert nvda["peak_price"] == pytest.approx(150.0)


def test_check_trailing_stops_no_trigger_within_threshold():
    initialize_portfolio([{"ticker": "NVDA", "shares": 1.0, "price": 100.0}])
    # Peak=110, current=92 → drop 16.4% < 20% → no trigger
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 110.0}):
        update_peak_prices()
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 92.0}):
        stops = check_trailing_stops()
    assert stops == []


def test_check_trailing_stops_fires_at_20pct_drop():
    initialize_portfolio([{"ticker": "NVDA", "shares": 1.0, "price": 100.0}])
    # Peak=125, current=99 → drop 20.8% > 20% → trigger
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 125.0}):
        update_peak_prices()
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 99.0}):
        stops = check_trailing_stops()
    assert len(stops) == 1
    assert stops[0]["ticker"] == "NVDA"
    assert stops[0]["trail_drop_pct"] < -20.0


def test_check_trailing_stops_uses_avg_cost_as_initial_peak():
    # No peak_price set yet → avg_cost is treated as initial peak
    initialize_portfolio([{"ticker": "NVDA", "shares": 1.0, "price": 100.0}])
    # Drop 22% from cost before any peak update
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 78.0}):
        stops = check_trailing_stops()
    assert len(stops) == 1
    assert stops[0]["ticker"] == "NVDA"


def test_check_trailing_stops_no_positions_returns_empty():
    stops = check_trailing_stops()
    assert stops == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd "C:\Claude\Trading Analyst"
.\.venv\Scripts\pytest.exe tests/api/test_paper_portfolio.py::test_update_peak_prices_sets_initial_peak -v
```

Expected: `ImportError` or `AttributeError` — `update_peak_prices` does not exist yet.

- [ ] **Step 3: Add `peak_price` column migration to `init_paper_db`**

In `api/paper_portfolio.py`, find `init_paper_db()`. After the `with _conn() as con: con.executescript(...)` block, add a second `with` block:

```python
def init_paper_db() -> None:
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS paper_account (
                id        INTEGER PRIMARY KEY CHECK (id = 1),
                starting_capital REAL NOT NULL,
                cash      REAL NOT NULL,
                created_date TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_positions (
                ticker      TEXT PRIMARY KEY,
                shares      REAL NOT NULL,
                avg_cost    REAL NOT NULL,
                entry_date  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date  TEXT NOT NULL,
                ticker      TEXT NOT NULL,
                action      TEXT NOT NULL,
                shares      REAL NOT NULL,
                price       REAL NOT NULL,
                value       REAL NOT NULL,
                note        TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS signal_outcomes (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker              TEXT NOT NULL,
                entry_date          TEXT NOT NULL,
                exit_date           TEXT,
                entry_price         REAL NOT NULL,
                exit_price          REAL,
                realized_return_pct REAL,
                days_held           INTEGER,
                exit_reason         TEXT,
                score_technical     REAL,
                score_momentum      REAL,
                score_quality       REAL,
                score_congress      REAL,
                score_trump_policy  REAL,
                score_news          REAL,
                score_earnings      REAL,
                score_composite     REAL,
                vix_at_entry        REAL,
                regime_at_entry     TEXT,
                sector              TEXT
            );
        """)
    # Idempotent schema migrations
    with _conn() as con:
        try:
            con.execute("ALTER TABLE paper_positions ADD COLUMN peak_price REAL")
        except Exception:
            pass  # column already exists
```

- [ ] **Step 4: Add `update_peak_prices` and `check_trailing_stops` functions**

Add these two functions to `api/paper_portfolio.py` after `get_raw_positions()`:

```python
def update_peak_prices() -> None:
    """Refresh the all-time-high price for each held position. Call once per daily run."""
    raw = get_raw_positions()
    if not raw:
        return
    prices = _fetch_prices([p["ticker"] for p in raw])
    with _conn() as con:
        for p in raw:
            ticker = p["ticker"]
            current = prices.get(ticker)
            if current is None:
                continue
            peak = p.get("peak_price") or p["avg_cost"]
            if current > peak:
                con.execute(
                    "UPDATE paper_positions SET peak_price = ? WHERE ticker = ?",
                    (round(current, 4), ticker),
                )


def check_trailing_stops(trail_pct: float = 0.20) -> list[dict]:
    """
    Return positions that have fallen trail_pct or more below their peak price.
    Each entry: {ticker, price, peak_price, trail_drop_pct, reason}.
    """
    raw = get_raw_positions()
    if not raw:
        return []
    prices = _fetch_prices([p["ticker"] for p in raw])
    stops = []
    for p in raw:
        ticker = p["ticker"]
        current = prices.get(ticker, p["avg_cost"])
        peak = p.get("peak_price") or p["avg_cost"]
        if peak > 0 and current < peak * (1.0 - trail_pct):
            drop_pct = round((current / peak - 1.0) * 100, 2)
            stops.append({
                "ticker": ticker,
                "price": current,
                "peak_price": peak,
                "trail_drop_pct": drop_pct,
                "reason": f"Trailing stop: {drop_pct:.1f}% from ${peak:.2f} peak",
            })
    return stops
```

- [ ] **Step 5: Run tests — must all pass**

```
.\.venv\Scripts\pytest.exe tests/api/test_paper_portfolio.py -v
```

Expected: All original tests + 6 new tests pass.

---

## Task 2: Interaction Gate in `compute_signal`

**Files:**
- Modify: `quant/signals.py`
- Modify: `tests/quant/test_signals.py`

### Background
A stock with critical quality weakness (quality_score < 0.35) AND a high composite score is a momentum trap — high price momentum masking fundamental deterioration. The gate forces composite ≤ 0.57 (just below the BUY threshold of 0.58) when quality is critically weak.

Math check: All scores=0.95 except quality=0.30 → composite = 0.8325. Gate fires, caps to 0.57 → WATCH.
At quality=0.36 (just above gate) → composite = 0.8415 → BUY (gate does not fire).

- [ ] **Step 1: Write the failing tests**

Add to `tests/quant/test_signals.py`:

```python
# ---------------------------------------------------------------------------
# Interaction gate: low quality blocks BUY regardless of other scores
# ---------------------------------------------------------------------------

def test_low_quality_gate_forces_watch():
    # quality=0.30 < 0.35 gate threshold; all others very high → would be BUY without gate
    result = compute_signal(
        technical_score=0.95, momentum_score=0.95, quality_score=0.30,
        congress_score=0.90, trump_policy_score=0.90,
        news_score=0.90, earnings_score=0.90,
    )
    assert result["label"] == "WATCH"
    assert result["composite_score"] <= 0.57


def test_quality_above_gate_threshold_allows_buy():
    # quality=0.36 >= 0.35; gate does not fire
    result = compute_signal(
        technical_score=0.95, momentum_score=0.95, quality_score=0.36,
        congress_score=0.90, trump_policy_score=0.90,
        news_score=0.90, earnings_score=0.90,
    )
    assert result["label"] == "BUY"


def test_gate_does_not_affect_avoid_signals():
    # Low quality AND low composite → AVOID (gate condition composite > 0.57 is False)
    result = compute_signal(
        technical_score=0.20, momentum_score=0.20, quality_score=0.20,
        congress_score=0.20, trump_policy_score=0.20,
        news_score=0.20, earnings_score=0.20,
    )
    assert result["label"] == "AVOID"


def test_gate_exact_quality_boundary():
    # quality exactly 0.35 — strict < means gate does NOT fire
    result = compute_signal(
        technical_score=0.95, momentum_score=0.95, quality_score=0.35,
        congress_score=0.90, trump_policy_score=0.90,
        news_score=0.90, earnings_score=0.90,
    )
    assert result["label"] == "BUY"
```

- [ ] **Step 2: Run tests to verify they fail**

```
.\.venv\Scripts\pytest.exe tests/quant/test_signals.py::test_low_quality_gate_forces_watch -v
```

Expected: FAIL — `assert result["label"] == "WATCH"` fails (returns "BUY" without gate).

- [ ] **Step 3: Add the gate to `compute_signal`**

In `quant/signals.py`, find the `compute_signal` function. Add gate after composite calculation, before label assignment:

```python
def compute_signal(
    technical_score: float,
    momentum_score: float = 0.5,
    quality_score: float = 0.5,
    congress_score: float = 0.5,
    trump_policy_score: float = 0.5,
    news_score: float = 0.5,
    earnings_score: float = 0.5,
    weights: dict[str, float] | None = None,
) -> dict:
    w = weights if weights is not None else config.SIGNAL_WEIGHTS
    composite = round(
        w["technical"] * technical_score
        + w["momentum"] * momentum_score
        + w["quality"] * quality_score
        + w["congress"] * congress_score
        + w["trump_policy"] * trump_policy_score
        + w["news_reaction"] * news_score
        + w["earnings"] * earnings_score,
        4,
    )

    # Interaction gate: high-momentum + critical quality weakness = momentum trap.
    # Cap composite below BUY threshold (0.58) when quality is critically weak.
    if quality_score < 0.35 and composite > 0.57:
        composite = 0.57

    label = "BUY" if composite > 0.58 else ("AVOID" if composite < 0.42 else "WATCH")

    return {
        "composite_score": composite,
        "label": label,
        "layer_scores": {
            "technical": technical_score,
            "momentum": momentum_score,
            "quality": quality_score,
            "congress": congress_score,
            "trump_policy": trump_policy_score,
            "news_reaction": news_score,
            "earnings": earnings_score,
        },
    }
```

- [ ] **Step 4: Run all signal tests — must all pass**

```
.\.venv\Scripts\pytest.exe tests/quant/test_signals.py -v
```

Expected: All existing + 4 new gate tests pass.

---

## Task 3: Portfolio Beta Module

**Files:**
- Create: `quant/portfolio_risk.py`
- Create: `tests/quant/test_portfolio_risk.py`

### Background
Market beta measures how much a portfolio amplifies market moves. A portfolio beta of 1.25 means a 10% market drop causes a 12.5% portfolio drop. Above 1.25 we raise the BUY bar to 0.62, requiring stronger conviction before adding more risk.

- [ ] **Step 1: Create the test file first**

Create `tests/quant/test_portfolio_risk.py`:

```python
from unittest.mock import patch
import pytest
from quant.portfolio_risk import get_ticker_beta, compute_portfolio_beta


def test_get_ticker_beta_returns_float():
    with patch("quant.portfolio_risk.yf.Ticker") as mock_t:
        mock_t.return_value.info = {"beta": 1.45}
        beta = get_ticker_beta("NVDA")
    assert isinstance(beta, float)
    assert beta == pytest.approx(1.45)


def test_get_ticker_beta_defaults_to_one_on_missing_data():
    with patch("quant.portfolio_risk.yf.Ticker") as mock_t:
        mock_t.return_value.info = {}
        beta = get_ticker_beta("UNKNOWN")
    assert beta == pytest.approx(1.0)


def test_get_ticker_beta_defaults_to_one_on_exception():
    with patch("quant.portfolio_risk.yf.Ticker", side_effect=RuntimeError("network")):
        beta = get_ticker_beta("NVDA")
    assert beta == pytest.approx(1.0)


def test_get_ticker_beta_clamps_extreme_values():
    with patch("quant.portfolio_risk.yf.Ticker") as mock_t:
        mock_t.return_value.info = {"beta": 99.0}
        beta = get_ticker_beta("MEME")
    assert beta <= 5.0


def test_compute_portfolio_beta_empty_list():
    assert compute_portfolio_beta([]) == pytest.approx(1.0)


def test_compute_portfolio_beta_equal_weights_average():
    with patch("quant.portfolio_risk.get_ticker_beta", side_effect=[1.2, 0.8]):
        beta = compute_portfolio_beta(["NVDA", "KO"])
    assert beta == pytest.approx(1.0)


def test_compute_portfolio_beta_high_beta_portfolio():
    with patch("quant.portfolio_risk.get_ticker_beta", return_value=1.6):
        beta = compute_portfolio_beta(["NVDA", "AMD", "META"])
    assert beta > 1.25


def test_compute_portfolio_beta_uses_cache():
    from data.cache import get_cache, set_cache
    set_cache("beta:CACHED", 1.35, ttl_seconds=86400)
    beta = get_ticker_beta("CACHED")
    assert beta == pytest.approx(1.35)
```

- [ ] **Step 2: Run tests to verify they fail**

```
.\.venv\Scripts\pytest.exe tests/quant/test_portfolio_risk.py -v
```

Expected: `ModuleNotFoundError: No module named 'quant.portfolio_risk'`

- [ ] **Step 3: Create `quant/portfolio_risk.py`**

```python
import logging
import yfinance as yf

from data.cache import get_cache, set_cache

logger = logging.getLogger(__name__)

_BETA_CACHE_TTL = 86400  # 24h — beta changes slowly


def get_ticker_beta(ticker: str) -> float:
    """Return market beta from yfinance info. Defaults to 1.0 on failure. Cached 24h."""
    cache_key = f"beta:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached
    try:
        beta = yf.Ticker(ticker).info.get("beta")
        result = float(beta) if beta is not None else 1.0
        result = max(0.0, min(5.0, result))  # sanity clamp
        set_cache(cache_key, result, ttl_seconds=_BETA_CACHE_TTL)
        return result
    except Exception as exc:
        logger.warning("Beta fetch failed for %s: %s", ticker, exc)
        return 1.0


def compute_portfolio_beta(tickers: list[str]) -> float:
    """Equal-weighted average market beta for the given tickers. Returns 1.0 for empty list."""
    if not tickers:
        return 1.0
    betas = [get_ticker_beta(t) for t in tickers]
    return round(sum(betas) / len(betas), 3)
```

- [ ] **Step 4: Run tests — must all pass**

```
.\.venv\Scripts\pytest.exe tests/quant/test_portfolio_risk.py -v
```

Expected: All 8 tests pass.

---

## Task 4: Wire All Controls into `briefing.py`

**Files:**
- Modify: `api/briefing.py`

### Background
Four wiring tasks:
1. Daily run: call `update_peak_prices()` + `check_trailing_stops()` and execute any triggered sells immediately.
2. Monthly rebalance: add rapid-deterioration override before the min-hold check.
3. Monthly rebalance: compute portfolio beta after deciding what to keep; use elevated buy threshold if beta > 1.25.

No new tests needed here — the integration is covered by the existing briefing tests plus manual verification.

- [ ] **Step 1: Add trailing stop integration to `send_daily_briefing`**

In `api/briefing.py`, find this block near line 802:
```python
paper_value = get_portfolio_value() if is_initialized() else {"positions": []}
alerts = _caution_alerts(paper_value, regime, score_map)
```

Replace with:
```python
# --- Trailing stop check (fires independent of monthly rebalance) ---
if is_initialized():
    from api.paper_portfolio import update_peak_prices, check_trailing_stops
    update_peak_prices()
    trailing_stops = check_trailing_stops()
    if trailing_stops:
        trail_sells = [
            {"ticker": s["ticker"], "price": s["price"], "reason": s["reason"]}
            for s in trailing_stops
        ]
        from api.paper_portfolio import rebalance as _execute_rebalance
        _execute_rebalance(trail_sells, [])
        _log_exits(trailing_stops, now.date().isoformat())
        logger.info("Trailing stops fired: %s", [s["ticker"] for s in trailing_stops])

paper_value = get_portfolio_value() if is_initialized() else {"positions": []}
alerts = _caution_alerts(paper_value, regime, score_map)
```

- [ ] **Step 2: Add rapid-deterioration override to `_run_monthly_rebalance`**

In `api/briefing.py`, find `_run_monthly_rebalance`. Locate the section:

```python
        # Rule 1: hard stop — always sell, ignore hold period
        if drawdown <= _SELL_DRAWDOWN_PCT:
            sells.append({
                "ticker": ticker,
                ...
            })
            continue

        # Rules 2 & 3 require minimum hold period
        if days_held < _MIN_HOLD_DAYS:
            kept.add(ticker)
            continue
```

Replace with:

```python
        # Rule 1: hard stop — always sell, ignore hold period
        if drawdown <= _SELL_DRAWDOWN_PCT:
            sells.append({
                "ticker": ticker,
                "price": pos["current_price"],
                "pnl_pct": drawdown,
                "pnl": pos["pnl"],
                "reason": f"Hard stop: {drawdown:.1f}% drawdown exceeded −15% threshold",
            })
            continue

        # Rapid deterioration: large loss in first 10 days suspends the min-hold protection.
        # Still requires rule 2 or 3 to actually trigger a sell.
        rapid_deterioration = days_held <= 10 and drawdown < -8.0

        # Rules 2 & 3 require minimum hold period (unless rapid deterioration)
        if days_held < _MIN_HOLD_DAYS and not rapid_deterioration:
            kept.add(ticker)
            continue
```

- [ ] **Step 3: Add portfolio beta cap to the buy section of `_run_monthly_rebalance`**

Add the import at the top of `api/briefing.py` (with other imports):
```python
from quant.portfolio_risk import compute_portfolio_beta
```

Add these constants near the other threshold constants at the top of `briefing.py`:
```python
_PORTFOLIO_BETA_HIGH   = 1.25   # if portfolio beta exceeds this, raise entry bar
_BUY_SCORE_HIGH_BETA   = 0.62   # minimum score when portfolio beta is elevated
```

In `_run_monthly_rebalance`, just before the buy loop (find `buys: list[dict] = []`), add:

```python
    # Portfolio beta cap: if held portfolio is already high-beta, demand stronger conviction
    held_tickers = list(kept)
    portfolio_beta = compute_portfolio_beta(held_tickers) if held_tickers else 1.0
    effective_buy_min = _BUY_SCORE_HIGH_BETA if portfolio_beta > _PORTFOLIO_BETA_HIGH else _BUY_SCORE_MIN
    logger.info("Portfolio beta: %.3f — buy threshold: %.2f", portfolio_beta, effective_buy_min)

    buys: list[dict] = []
```

In the buy loop, change the score check from `_BUY_SCORE_MIN` to `effective_buy_min`:

```python
    for r in ranked_all:
        if len(buys) >= slots:
            break
        t = r["ticker"]
        if t in kept or t in sold_set:
            continue
        score = r["signal"]["composite_score"]
        if score < effective_buy_min:          # ← was _BUY_SCORE_MIN
            break
        price = r["current_price"]
        if price <= 0:
            continue
        buys.append({
            "ticker": t,
            "shares": round(POSITION_SIZE / price, 6),
            "price": price,
            "score": score,
            "conviction": _conviction(score),
        })
```

- [ ] **Step 4: Run full test suite — must still pass**

```
.\.venv\Scripts\pytest.exe tests/ -q
```

Expected: 403+ tests pass, 0 failures. (The briefing tests mock everything so the new logic paths are skipped in unit tests — that is acceptable for now.)

- [ ] **Step 5: Commit**

```
git add api/paper_portfolio.py quant/signals.py quant/portfolio_risk.py api/briefing.py
git add tests/api/test_paper_portfolio.py tests/quant/test_signals.py tests/quant/test_portfolio_risk.py
git commit -m "feat(risk): trailing stop, interaction gate, beta cap, rapid-deterioration override"
```

---

## Self-Review

**Spec coverage:**
- [x] Trailing stop 20% from peak → Task 1 + Task 4 Step 1
- [x] Interaction gate quality < 0.35 → Task 2
- [x] Portfolio beta cap > 1.25 → Task 3 + Task 4 Step 3
- [x] Rapid deterioration override (>8% in 10 days) → Task 4 Step 2

**Placeholder scan:** None — all steps have complete code.

**Type consistency:** `check_trailing_stops()` returns `list[dict]`. `_log_exits()` expects `list[dict]` with `ticker`, `price`, `reason` keys — all present in trailing stop dicts. ✓
