# Group 5: Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the quarterly regression engine against statistical noise: raise the closed-position threshold to 40, add holdout validation so weight nudges are checked on unseen data before applying, and track cumulative annual weight drift so no single factor accumulates more than 8 percentage-point shift in any 12-month window.

**Architecture:** Three layered changes to `api/quarterly_review.py` and `api/paper_portfolio.py`. `run_quarterly_review` gains a 75/25 train/holdout split. `_recommend_weights` gains two new optional parameters (`holdout_correlations`, `annual_deltas`) and applies halved nudges where holdout disagrees in direction. A new `weight_changes` SQLite table in `paper_portfolio.db` tracks every weight update; `get_annual_weight_delta` returns the signed net shift per factor over the last 365 days.

**Tech Stack:** Python 3.12, SQLite (sqlite3), existing `paper_portfolio.py` pattern.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `api/paper_portfolio.py` | Modify | Add `weight_changes` table, `log_weight_change()`, `get_annual_weight_delta()` |
| `api/quarterly_review.py` | Modify | Raise `min_closed` default to 40; add 75/25 holdout split; wire annual-cap params |
| `tests/api/test_quarterly_review.py` | Modify | Update existing tests for new threshold; add holdout + annual-cap tests |
| `tests/api/test_paper_portfolio.py` | Modify | Add tests for new weight-tracking functions |

---

## Task 1: Raise min_closed to 40

**Files:**
- Modify: `api/quarterly_review.py`
- Modify: `tests/api/test_quarterly_review.py`

- [ ] **Step 1: Write the failing test**

In `tests/api/test_quarterly_review.py`, add after `test_run_quarterly_review_skipped_when_too_few`:

```python
def test_run_quarterly_review_skipped_at_35_with_new_default():
    # 35 positions < default 40 → must skip
    with patch("api.quarterly_review.get_closed_outcomes", return_value=_make_closed(35)):
        result = run_quarterly_review()   # no min_closed arg → uses new default
    assert result["skipped"] is True


def test_run_quarterly_review_runs_at_45_with_new_default():
    with patch("api.quarterly_review.get_closed_outcomes", return_value=_make_closed(45)):
        result = run_quarterly_review()
    assert result["skipped"] is False
    assert result["n"] == 45
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd "C:\Claude\Trading Analyst"
.\.venv\Scripts\pytest.exe tests/api/test_quarterly_review.py::test_run_quarterly_review_skipped_at_35_with_new_default -v
```

Expected: `FAILED` — `run_quarterly_review()` does not skip at 35 because default is still 15.

- [ ] **Step 3: Change default in `run_quarterly_review`**

In `api/quarterly_review.py`, line 120:

```python
# Before
def run_quarterly_review(min_closed: int = 15) -> dict:

# After
def run_quarterly_review(min_closed: int = 40) -> dict:
```

- [ ] **Step 4: Run the full quarterly-review test suite**

```
.\.venv\Scripts\pytest.exe tests/api/test_quarterly_review.py -v
```

Expected: 2 new tests pass. All old tests still pass because they use `min_closed=15` explicitly.

- [ ] **Step 5: Commit**

```
git add api/quarterly_review.py tests/api/test_quarterly_review.py
git commit -m "feat(governance): raise quarterly review min_closed default from 15 → 40"
```

---

## Task 2: Holdout Validation

**Files:**
- Modify: `api/quarterly_review.py`
- Modify: `tests/api/test_quarterly_review.py`

### Background
After this task, `run_quarterly_review` splits `closed` positions (sorted by `exit_date`) 75/25: the older 75% trains correlations; the newer 25% validates direction. If a factor's correlation sign in the holdout disagrees with its training correlation AND the holdout magnitude exceeds 0.10, that factor's nudge is halved to express less confidence. The report gains `holdout_n` and `holdout_warnings` keys.

- [ ] **Step 1: Write failing tests**

Add to `tests/api/test_quarterly_review.py`:

```python
def _make_closed_dated(n: int, avg_ret: float = 5.0) -> list[dict]:
    """Same as _make_closed but with varying exit_dates so holdout split is deterministic."""
    base_row = {col: 0.6 for col, _ in FACTORS}
    base_row.update({
        "score_composite": 0.65, "vix_at_entry": 18.0, "regime_at_entry": "normal",
        "sector": "Tech", "entry_price": 100.0, "days_held": 45,
        "exit_reason": "rank_drop", "realized_return_pct": avg_ret,
    })
    rows = []
    for i in range(n):
        row = {**base_row, "ticker": f"T{i}",
               "entry_date": "2025-01-01",
               "exit_date": f"2025-{(i % 12) + 1:02d}-15",
               "exit_price": 100.0 * (1 + avg_ret / 100)}
        rows.append(row)
    return rows


def test_run_quarterly_review_has_holdout_keys():
    with patch("api.quarterly_review.get_closed_outcomes", return_value=_make_closed_dated(45)):
        result = run_quarterly_review()
    assert "holdout_n" in result
    assert "holdout_warnings" in result
    # 25% of 45 = 11 or 12
    assert 10 <= result["holdout_n"] <= 12


def test_holdout_warnings_is_list():
    with patch("api.quarterly_review.get_closed_outcomes", return_value=_make_closed_dated(45)):
        result = run_quarterly_review()
    assert isinstance(result["holdout_warnings"], list)
```

- [ ] **Step 2: Run tests to verify they fail**

```
.\.venv\Scripts\pytest.exe tests/api/test_quarterly_review.py::test_run_quarterly_review_has_holdout_keys -v
```

Expected: `KeyError` or `AssertionError` — `holdout_n` not in result.

- [ ] **Step 3: Update `_recommend_weights` signature and logic**

In `api/quarterly_review.py`, replace `_recommend_weights` with:

```python
def _recommend_weights(
    correlations: dict[str, float],
    holdout_correlations: dict[str, float] | None = None,
    annual_deltas: dict[str, float] | None = None,
) -> dict[str, float]:
    """
    Nudge current weights toward factors that predicted returns.
    Constraints:
      - No weight below _MIN_WEIGHT or above _MAX_WEIGHT
      - No weight changes more than _MAX_DELTA per quarter
      - If holdout_correlations provided: halve nudge when holdout sign disagrees
      - If annual_deltas provided: cap cumulative annual shift at 0.08 per factor
      - Weights sum to exactly 1.0
    """
    current = dict(config.SIGNAL_WEIGHTS)

    col_to_cfg: dict[str, str] = {}
    for col, _ in FACTORS:
        stub = col.replace("score_", "")
        for cfg_key in current:
            if stub in cfg_key:
                col_to_cfg[col] = cfg_key
                break

    nudges: dict[str, float] = {}
    for col, cfg_key in col_to_cfg.items():
        r = correlations.get(col, 0.0)
        nudge = round(r * 0.04, 4)
        nudge = max(-_MAX_DELTA, min(_MAX_DELTA, nudge))

        # Holdout validation: halve nudge if holdout direction disagrees
        if holdout_correlations and nudge != 0.0:
            h_r = holdout_correlations.get(col, 0.0)
            if r * h_r < 0 and abs(h_r) > 0.10:
                nudge = nudge * 0.5

        # Annual cap: limit cumulative signed drift per factor to ±8pp per year
        if annual_deltas is not None:
            annual_used = annual_deltas.get(cfg_key, 0.0)
            remaining = max(0.0, 0.08 - abs(annual_used))
            if abs(nudge) > remaining:
                nudge = math.copysign(remaining, nudge)

        nudges[cfg_key] = nudge

    raw: dict[str, float] = {}
    for key, w in current.items():
        delta = nudges.get(key, 0.0)
        raw[key] = max(_MIN_WEIGHT, min(_MAX_WEIGHT, round(w + delta, 4)))

    total = sum(raw.values())
    return {k: round(v / total, 4) for k, v in raw.items()}
```

- [ ] **Step 4: Update `run_quarterly_review` to split training/holdout**

In `api/quarterly_review.py`, replace the body of `run_quarterly_review` from the `closed = get_closed_outcomes(...)` line through the `correlations` dict comprehension:

```python
    closed = get_closed_outcomes(min_closed=min_closed)
    n = len(closed)

    if n < min_closed:
        return {
            "n": n,
            "skipped": True,
            "reason": f"Only {n} closed positions — need {min_closed} for regression.",
        }

    # 75/25 temporal split — older positions train, newer validate
    closed_sorted = sorted(closed, key=lambda r: r.get("exit_date") or "")
    holdout_n = max(1, n // 4)
    holdout = closed_sorted[-holdout_n:]
    training = closed_sorted[:-holdout_n]

    returns_train = [r["realized_return_pct"] for r in training]
    returns_hold  = [r["realized_return_pct"] for r in holdout]

    def _compute_correlations(rows: list[dict], returns: list[float]) -> dict[str, float]:
        result = {}
        for col, label in FACTORS:
            scores = [r.get(col) for r in rows]
            pairs = [(s, ret) for s, ret in zip(scores, returns) if s is not None]
            if len(pairs) < 5:
                result[col] = 0.0
            else:
                xs, ys = zip(*pairs)
                result[col] = round(_spearman(list(xs), list(ys)), 4)
        return result

    correlations         = _compute_correlations(training, returns_train)
    holdout_correlations = _compute_correlations(holdout,  returns_hold)

    # Build holdout warning list (factors where direction disagrees meaningfully)
    holdout_warnings = [
        col for col in correlations
        if correlations[col] * holdout_correlations.get(col, 0.0) < 0
        and abs(holdout_correlations.get(col, 0.0)) > 0.10
    ]
```

Then replace the old `returns = [r["realized_return_pct"] for r in closed]` usage. The rest of `run_quarterly_review` (winners/losers, best/worst, annualised return) should use all `closed` rows (not just training). Update the block:

```python
    returns = [r["realized_return_pct"] for r in closed]
    winners = [r for r in returns if r > 0]
    losers  = [r for r in returns if r <= 0]
    win_rate = round(len(winners) / n * 100, 1) if n else 0.0
    avg_winner = round(sum(winners) / len(winners), 2) if winners else 0.0
    avg_loser  = round(sum(losers)  / len(losers),  2) if losers  else 0.0

    best  = max(closed, key=lambda r: r["realized_return_pct"] or 0)
    worst = min(closed, key=lambda r: r["realized_return_pct"] or 0)

    recommended_weights = _recommend_weights(correlations, holdout_correlations)
    current_weights     = dict(config.SIGNAL_WEIGHTS)

    avg_days = sum(r.get("days_held") or 30 for r in closed) / n
    avg_ret  = sum(returns) / n
    ann_ret  = round(avg_ret * (365 / max(avg_days, 1)), 1) if avg_days else 0.0
    on_track = ann_ret >= 18.0

    return {
        "n": n,
        "skipped": False,
        "correlations": correlations,
        "holdout_n": holdout_n,
        "holdout_warnings": holdout_warnings,
        "win_rate": win_rate,
        "avg_winner": avg_winner,
        "avg_loser": avg_loser,
        "best": {"ticker": best["ticker"], "return": best["realized_return_pct"]},
        "worst": {"ticker": worst["ticker"], "return": worst["realized_return_pct"]},
        "annualised_return_est": ann_ret,
        "on_track_18pct": on_track,
        "current_weights": current_weights,
        "recommended_weights": recommended_weights,
    }
```

- [ ] **Step 5: Run full quarterly-review tests**

```
.\.venv\Scripts\pytest.exe tests/api/test_quarterly_review.py -v
```

Expected: All existing tests pass + 2 new holdout tests pass.

- [ ] **Step 6: Commit**

```
git add api/quarterly_review.py tests/api/test_quarterly_review.py
git commit -m "feat(governance): holdout validation in quarterly review (75/25 temporal split)"
```

---

## Task 3: Annual Weight Change Cap

**Files:**
- Modify: `api/paper_portfolio.py`
- Modify: `api/quarterly_review.py`
- Modify: `tests/api/test_paper_portfolio.py`
- Modify: `tests/api/test_quarterly_review.py`

### Background
A `weight_changes` SQLite table tracks every quarterly weight update with a timestamp. `get_annual_weight_delta(factor)` returns the net signed sum of all changes in the past 365 days. `_recommend_weights` caps any single nudge so the rolling annual total stays within ±0.08 (8pp). After recommendations are applied, `run_quarterly_review` calls `log_weight_change` for each factor that changed.

- [ ] **Step 1: Write failing tests for paper_portfolio functions**

Add to `tests/api/test_paper_portfolio.py`:

```python
from api.paper_portfolio import log_weight_change, get_annual_weight_delta


def test_log_weight_change_and_retrieve():
    log_weight_change("momentum", 0.25, 0.28, as_of="2026-01-10")
    delta = get_annual_weight_delta("momentum", as_of="2026-01-10")
    assert abs(delta - 0.03) < 0.001


def test_get_annual_weight_delta_no_history_returns_zero():
    delta = get_annual_weight_delta("unknown_factor_xyz", as_of="2026-01-10")
    assert delta == 0.0


def test_get_annual_weight_delta_sums_multiple_changes():
    log_weight_change("technical", 0.20, 0.23, as_of="2026-01-10")
    log_weight_change("technical", 0.23, 0.25, as_of="2026-04-01")
    delta = get_annual_weight_delta("technical", as_of="2026-04-01")
    assert abs(delta - 0.05) < 0.001


def test_get_annual_weight_delta_ignores_changes_older_than_365_days():
    log_weight_change("quality", 0.15, 0.18, as_of="2025-01-01")
    log_weight_change("quality", 0.18, 0.20, as_of="2026-04-01")
    # Only the 2026-04-01 change is within 365 days of 2026-04-01
    delta = get_annual_weight_delta("quality", as_of="2026-04-01")
    assert abs(delta - 0.02) < 0.001


def test_log_weight_change_defaults_to_today():
    from datetime import date
    today = date.today().isoformat()
    log_weight_change("earnings", 0.15, 0.17)
    delta = get_annual_weight_delta("earnings")
    assert abs(delta - 0.02) < 0.001
```

- [ ] **Step 2: Run tests to verify they fail**

```
.\.venv\Scripts\pytest.exe tests/api/test_paper_portfolio.py::test_log_weight_change_and_retrieve -v
```

Expected: `ImportError` — `log_weight_change` not yet defined.

- [ ] **Step 3: Add `weight_changes` table to `init_paper_db`**

In `api/paper_portfolio.py`, in the `executescript` inside `init_paper_db`, add after the `signal_outcomes` table:

```sql
            CREATE TABLE IF NOT EXISTS weight_changes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                factor      TEXT NOT NULL,
                changed_at  TEXT NOT NULL,
                old_weight  REAL NOT NULL,
                new_weight  REAL NOT NULL
            );
```

- [ ] **Step 4: Add `log_weight_change` and `get_annual_weight_delta` to `paper_portfolio.py`**

Add after `get_open_outcome_tickers()`:

```python
def log_weight_change(
    factor: str,
    old_weight: float,
    new_weight: float,
    as_of: str | None = None,
) -> None:
    """Record a quarterly weight update. as_of: ISO date, defaults to today."""
    if as_of is None:
        as_of = date.today().isoformat()
    init_paper_db()
    try:
        with _conn() as con:
            con.execute(
                """INSERT INTO weight_changes (factor, changed_at, old_weight, new_weight)
                   VALUES (?, ?, ?, ?)""",
                (factor, as_of, round(float(old_weight), 4), round(float(new_weight), 4)),
            )
    except Exception as exc:
        logger.warning("log_weight_change failed for %s: %s", factor, exc)


def get_annual_weight_delta(factor: str, as_of: str | None = None) -> float:
    """
    Net signed weight drift for factor over the past 365 days from as_of.
    Returns sum(new_weight - old_weight) for qualifying rows.
    """
    if as_of is None:
        as_of = date.today().isoformat()
    init_paper_db()
    try:
        with _conn() as con:
            rows = con.execute(
                """SELECT old_weight, new_weight FROM weight_changes
                   WHERE factor = ?
                     AND changed_at <= ?
                     AND changed_at >= date(?, '-365 days')
                   ORDER BY changed_at""",
                (factor, as_of, as_of),
            ).fetchall()
    except Exception as exc:
        logger.warning("get_annual_weight_delta failed for %s: %s", factor, exc)
        return 0.0

    return round(sum(r["new_weight"] - r["old_weight"] for r in rows), 4)
```

- [ ] **Step 5: Run paper_portfolio tests — new tests must pass**

```
.\.venv\Scripts\pytest.exe tests/api/test_paper_portfolio.py -v
```

Expected: All original + 5 new weight-tracking tests pass.

- [ ] **Step 6: Wire annual cap into `quarterly_review._recommend_weights` call**

In `api/quarterly_review.py`, add import at top:

```python
from api.paper_portfolio import get_closed_outcomes, log_weight_change, get_annual_weight_delta
```

In `run_quarterly_review`, before calling `_recommend_weights`, compute annual deltas for each config key:

```python
    # Gather annual drift for each factor
    annual_deltas: dict[str, float] = {}
    for col, _ in FACTORS:
        stub = col.replace("score_", "")
        for cfg_key in config.SIGNAL_WEIGHTS:
            if stub in cfg_key:
                annual_deltas[cfg_key] = get_annual_weight_delta(cfg_key)
                break

    recommended_weights = _recommend_weights(correlations, holdout_correlations, annual_deltas)
    current_weights = dict(config.SIGNAL_WEIGHTS)

    # Log weight changes that differ from current by at least 0.005
    for key, new_w in recommended_weights.items():
        cur_w = current_weights.get(key, new_w)
        if abs(new_w - cur_w) >= 0.005:
            log_weight_change(key, cur_w, new_w)
```

- [ ] **Step 7: Write quarterly-review test for annual-cap integration**

Add to `tests/api/test_quarterly_review.py`:

```python
def test_recommend_weights_annual_cap_limits_nudge():
    from api.quarterly_review import _recommend_weights
    # Simulate a factor that has already used 7pp of its 8pp annual cap
    # A full positive nudge should be capped to the remaining 1pp
    corrs = {col: 0.0 for col, _ in FACTORS}
    # Find the "momentum" column name
    mom_col = next(col for col, _ in FACTORS if "momentum" in col)
    corrs[mom_col] = 1.0  # max positive correlation → max nudge

    # annual_deltas: momentum already used 0.07 of its 0.08 cap
    annual_deltas = {"momentum": 0.07}
    rw = _recommend_weights(corrs, annual_deltas=annual_deltas)

    current_mom = config.SIGNAL_WEIGHTS.get("momentum", 0.0)
    # The nudge should be at most 0.01 (0.08 - 0.07 = 0.01 remaining)
    new_mom = rw.get("momentum", current_mom)
    assert (new_mom - current_mom) <= 0.012  # small tolerance for rounding
```

- [ ] **Step 8: Run full quarterly-review + paper_portfolio tests**

```
.\.venv\Scripts\pytest.exe tests/api/test_quarterly_review.py tests/api/test_paper_portfolio.py -v
```

Expected: All tests pass.

- [ ] **Step 9: Commit**

```
git add api/paper_portfolio.py api/quarterly_review.py
git add tests/api/test_paper_portfolio.py tests/api/test_quarterly_review.py
git commit -m "feat(governance): annual weight-change cap (8pp/yr); weight_changes table + log/get functions"
```

---

## Self-Review

**Spec coverage:**
- [x] Raise min_closed to 40 → Task 1
- [x] Holdout validation 25% → Task 2 (75/25 temporal split, warnings in report)
- [x] Annual weight change cap 8pp/year → Task 3 (`weight_changes` table + enforcement in `_recommend_weights`)
- [x] `log_weight_change` called automatically after each quarterly run → Task 3 Step 6

**Placeholder scan:** None.

**Type consistency:** `get_annual_weight_delta` returns `float`; `annual_deltas` dict maps `cfg_key → float` matching `config.SIGNAL_WEIGHTS` keys. `log_weight_change` accepts the same `cfg_key` strings. ✓
