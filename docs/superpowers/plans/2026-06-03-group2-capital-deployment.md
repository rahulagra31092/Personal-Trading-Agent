# Group 2: Capital Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the orphaned position-sizing module into the live system — sizes scale with signal conviction, GARCH volatility, and regime factor. Add a cash-deployment trigger so trailing-stop proceeds are redeployed the same day.

**Architecture:** A new `compute_conviction_position_size()` function in `position_sizing.py` combines three multipliers: conviction tier (0.65×/1.0×/1.4× based on composite score), GARCH vol scalar (from `forecast.py`), and regime factor (from `regime.py`). `briefing.py` replaces all hardcoded `POSITION_SIZE / price` calculations with this function. A post-sell cash-check in `send_daily_briefing` deploys freed cash immediately.

**Tech Stack:** Python 3.12, existing `quant/position_sizing.py`, `quant/forecast.py`, `quant/regime.py`.

**PREREQUISITE:** Group 1 plan must be fully implemented before starting this plan (trailing stop integration is needed for the cash-deployment trigger).

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `quant/position_sizing.py` | Modify | Add `compute_conviction_position_size()` |
| `api/briefing.py` | Modify | Replace flat $500 sizing with conviction sizing; add cash-deployment trigger |
| `api/analyze.py` | Modify | Add `garch_vol_scalar` to returned dict so briefing can use it |
| `tests/quant/test_position_sizing.py` | Modify | Tests for new conviction sizing function |
| `tests/api/test_briefing.py` | No change | Existing tests mock `analyze_ticker` — no update needed |

---

## Task 1: `compute_conviction_position_size` Function

**Files:**
- Modify: `quant/position_sizing.py`
- Modify: `tests/quant/test_position_sizing.py`

### Background
Formula: `size = base_size × conviction_mult × regime_factor × vol_mult`
- `conviction_mult`: composite 0.58–0.65 → 0.65×, 0.65–0.75 → 1.00×, >0.75 → 1.40×
- `vol_mult`: GARCH vol_scalar maps linearly: `0.75 + 0.50 × garch_vol_scalar`
  - low vol (scalar=0.8) → 1.15×, medium (0.5) → 1.00×, high (0.2) → 0.85×
- Hard cap: `min(size, total_capital × max_capital_pct)` where `max_capital_pct=0.08`

The existing `compute_position_size()` function is NOT modified — it remains for the volatility-targeted sizing tests that already pass.

- [ ] **Step 1: Write the failing tests**

Add to `tests/quant/test_position_sizing.py`:

```python
from quant.position_sizing import compute_conviction_position_size

CAPITAL = 10_000.0
BASE = 500.0


def test_low_conviction_reduces_size():
    size = compute_conviction_position_size(BASE, composite_score=0.60, total_capital=CAPITAL)
    assert size == round(BASE * 0.65)


def test_medium_conviction_uses_base_size():
    size = compute_conviction_position_size(BASE, composite_score=0.70, total_capital=CAPITAL)
    assert size == BASE


def test_high_conviction_increases_size():
    size = compute_conviction_position_size(BASE, composite_score=0.80, total_capital=CAPITAL)
    assert size == round(BASE * 1.40)


def test_regime_factor_scales_size():
    full = compute_conviction_position_size(BASE, composite_score=0.70, regime_factor=1.0, total_capital=CAPITAL)
    crisis = compute_conviction_position_size(BASE, composite_score=0.70, regime_factor=0.50, total_capital=CAPITAL)
    assert crisis < full
    assert abs(crisis / full - 0.50) < 0.05


def test_low_vol_scalar_increases_size():
    med = compute_conviction_position_size(BASE, composite_score=0.70, garch_vol_scalar=0.5, total_capital=CAPITAL)
    low = compute_conviction_position_size(BASE, composite_score=0.70, garch_vol_scalar=0.8, total_capital=CAPITAL)
    assert low > med


def test_high_vol_scalar_decreases_size():
    med = compute_conviction_position_size(BASE, composite_score=0.70, garch_vol_scalar=0.5, total_capital=CAPITAL)
    high = compute_conviction_position_size(BASE, composite_score=0.70, garch_vol_scalar=0.2, total_capital=CAPITAL)
    assert high < med


def test_hard_cap_at_8pct_of_capital():
    # Very large base, high conviction → must be capped at 8% = $800
    size = compute_conviction_position_size(
        base_size=2000.0, composite_score=0.90,
        regime_factor=1.0, garch_vol_scalar=0.8,
        total_capital=CAPITAL, max_capital_pct=0.08,
    )
    assert size <= CAPITAL * 0.08


def test_conviction_boundary_exactly_065():
    # Exactly at 0.65 → medium conviction (>=0.65 tier)
    size = compute_conviction_position_size(BASE, composite_score=0.65, total_capital=CAPITAL)
    assert size == BASE  # 1.0× multiplier


def test_conviction_boundary_exactly_075():
    # Exactly at 0.75 → high conviction (>=0.75 tier)
    size = compute_conviction_position_size(BASE, composite_score=0.75, total_capital=CAPITAL)
    assert size == round(BASE * 1.40)
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd "C:\Claude\Trading Analyst"
.\.venv\Scripts\pytest.exe tests/quant/test_position_sizing.py::test_low_conviction_reduces_size -v
```

Expected: `ImportError` — `compute_conviction_position_size` does not exist yet.

- [ ] **Step 3: Add `compute_conviction_position_size` to `position_sizing.py`**

Append to `quant/position_sizing.py` (after `compute_short_position_size`):

```python
def compute_conviction_position_size(
    base_size: float,
    composite_score: float,
    regime_factor: float = 1.0,
    garch_vol_scalar: float = 0.5,
    total_capital: float = 10_000.0,
    max_capital_pct: float = 0.08,
) -> float:
    """
    Conviction-adjusted position size in dollars.

    conviction_mult:
      composite >= 0.75 → 1.40×  (Very High / High conviction)
      composite >= 0.65 → 1.00×  (Moderate conviction — base size)
      composite <  0.65 → 0.65×  (entry-level conviction)

    vol_mult: linear map of garch_vol_scalar → [0.85, 1.15]
      scalar=0.2 (high vol)    → 0.85×
      scalar=0.5 (medium vol)  → 1.00×
      scalar=0.8 (low vol)     → 1.15×
      formula: 0.75 + 0.50 * garch_vol_scalar

    Hard cap: min(size, total_capital * max_capital_pct)
    """
    if composite_score >= 0.75:
        conviction_mult = 1.40
    elif composite_score >= 0.65:
        conviction_mult = 1.00
    else:
        conviction_mult = 0.65

    vol_mult = 0.75 + 0.50 * garch_vol_scalar
    size = base_size * conviction_mult * regime_factor * vol_mult
    max_size = total_capital * max_capital_pct
    return round(min(size, max_size))
```

- [ ] **Step 4: Run position sizing tests — all must pass**

```
.\.venv\Scripts\pytest.exe tests/quant/test_position_sizing.py -v
```

Expected: All 9 existing + 9 new tests pass (18 total).

---

## Task 2: Wire Conviction Sizing into the Rebalance Engine

**Files:**
- Modify: `api/briefing.py`
- Modify: `api/analyze.py`

### Background
`analyze_ticker` already computes `garch` via `compute_garch_volatility`. We need to expose `garch["vol_scalar"]` in the returned dict so `briefing.py` can use it without re-running GARCH.

Then in `_run_monthly_rebalance` and the auto-init block, replace `POSITION_SIZE / price` with `compute_conviction_position_size(...)`.

- [ ] **Step 1: Expose `garch_vol_scalar` in `analyze_ticker` return value**

In `api/analyze.py`, find the `return` dict at the bottom:

```python
    return {
        "ticker": ticker,
        "signal": sig,
        "confidence": mc,
        "current_price": round(current_price, 2),
        "atr_stop": ind["atr_stop"],
        "vol_regime": garch["vol_regime"],
        "rsi": ind["rsi"],
        "trend_regime": ind["ema_trend"],
        "trade_card": trade_card,
        "market_regime": regime.get("regime", "normal"),
        "vix": regime.get("vix", 0.0),
    }
```

Add `"garch_vol_scalar": garch["vol_scalar"],` to the dict:

```python
    return {
        "ticker": ticker,
        "signal": sig,
        "confidence": mc,
        "current_price": round(current_price, 2),
        "atr_stop": ind["atr_stop"],
        "vol_regime": garch["vol_regime"],
        "garch_vol_scalar": garch["vol_scalar"],
        "rsi": ind["rsi"],
        "trend_regime": ind["ema_trend"],
        "trade_card": trade_card,
        "market_regime": regime.get("regime", "normal"),
        "vix": regime.get("vix", 0.0),
    }
```

- [ ] **Step 2: Add import and wire sizing into `_run_monthly_rebalance`**

Add import at top of `api/briefing.py` (with other quant imports):
```python
from quant.position_sizing import compute_conviction_position_size
```

In `_run_monthly_rebalance`, find the buy-appending code:

```python
        buys.append({
            "ticker": t,
            "shares": round(POSITION_SIZE / price, 6),
            "price": price,
            "score": score,
            "conviction": _conviction(score),
        })
```

Replace with:

```python
        regime_factor = float(get_market_regime().get("position_factor", 1.0))
        vol_scalar = score_map.get(t, {}).get("garch_vol_scalar", 0.5)
        dollar_size = compute_conviction_position_size(
            base_size=POSITION_SIZE,
            composite_score=score,
            regime_factor=regime_factor,
            garch_vol_scalar=vol_scalar,
            total_capital=get_account().get("starting_capital", STARTING_CAPITAL),
        )
        buys.append({
            "ticker": t,
            "shares": round(dollar_size / price, 6),
            "price": price,
            "score": score,
            "conviction": _conviction(score),
            "dollar_size": dollar_size,
        })
```

Also add `from api.paper_portfolio import get_account` if not already imported (check — `get_account` is not yet imported in briefing.py). Add it to the existing import line:

```python
from api.paper_portfolio import (
    get_portfolio_value, is_initialized, POSITION_SIZE, STARTING_CAPITAL,
    log_trade_entry, log_trade_exit, get_open_outcome_tickers, get_account,
)
```

- [ ] **Step 3: Wire sizing into auto-init block**

In `send_daily_briefing`, find the auto-init block:

```python
        buys = [
            {
                "ticker": r["ticker"],
                "shares": round(POSITION_SIZE / r["current_price"], 6) if r["current_price"] > 0 else 0,
                "price": r["current_price"],
            }
            for r in top20
            if r["current_price"] > 0
        ]
```

Replace with:

```python
        regime_factor = float(regime.get("position_factor", 1.0))
        buys = [
            {
                "ticker": r["ticker"],
                "shares": round(
                    compute_conviction_position_size(
                        base_size=POSITION_SIZE,
                        composite_score=r["signal"]["composite_score"],
                        regime_factor=regime_factor,
                        garch_vol_scalar=r.get("garch_vol_scalar", 0.5),
                        total_capital=STARTING_CAPITAL,
                    ) / r["current_price"],
                    6,
                ),
                "price": r["current_price"],
            }
            for r in top20
            if r["current_price"] > 0
        ]
```

- [ ] **Step 4: Run full test suite**

```
.\.venv\Scripts\pytest.exe tests/ -q
```

Expected: All tests pass. (Briefing tests mock `analyze_ticker` and `rebalance` so the new sizing path is exercised only in live runs.)

---

## Task 3: Cash-Deployment Trigger

**Files:**
- Modify: `api/briefing.py`

### Background
When trailing stops fire mid-day, they free cash. Without this trigger, that cash sits idle until the next monthly rebalance (up to 30 days). The trigger runs after trailing stop execution: if `cash > 2 × POSITION_SIZE`, find the top unowned BUY-qualified ticker and buy it immediately.

- [ ] **Step 1: Add cash-deployment helper to `briefing.py`**

Add this function in `briefing.py`, after `_log_new_entries`:

```python
def _deploy_idle_cash(
    all_results: list[dict],
    score_map: dict[str, dict],
    now: datetime,
    regime: dict,
) -> None:
    """
    If cash exceeds 2 × POSITION_SIZE after trailing-stop sells, buy the top
    unowned BUY-qualified ticker immediately (no waiting for monthly rebalance).
    """
    from api.paper_portfolio import get_account, get_raw_positions, rebalance as _execute_rebalance

    account = get_account()
    cash = account.get("cash", 0.0)
    if cash < 2 * POSITION_SIZE:
        return

    held = {p["ticker"] for p in get_raw_positions()}
    regime_factor = float(regime.get("position_factor", 1.0))
    total_capital = account.get("starting_capital", STARTING_CAPITAL)

    ranked = sorted(
        [r for r in all_results if r["signal"]["label"] == "BUY"],
        key=lambda r: r["signal"]["composite_score"],
        reverse=True,
    )

    for r in ranked:
        t = r["ticker"]
        if t in held:
            continue
        score = r["signal"]["composite_score"]
        if score < _BUY_SCORE_MIN:
            break
        price = r["current_price"]
        if price <= 0:
            continue

        dollar_size = compute_conviction_position_size(
            base_size=POSITION_SIZE,
            composite_score=score,
            regime_factor=regime_factor,
            garch_vol_scalar=r.get("garch_vol_scalar", 0.5),
            total_capital=total_capital,
        )
        dollar_size = min(dollar_size, cash)  # don't deploy more than available
        shares = round(dollar_size / price, 6)
        _execute_rebalance([], [{"ticker": t, "shares": shares, "price": price}])
        _log_new_entries(
            [t], score_map, now.date().isoformat(),
            float(regime.get("vix", 0.0)), regime.get("regime", "unknown"),
        )
        logger.info("Cash-deployment trigger: bought %s (%.0f shares @ $%.2f)", t, shares, price)
        break  # deploy one position per trigger to avoid over-concentration
```

- [ ] **Step 2: Call `_deploy_idle_cash` in `send_daily_briefing` after trailing-stop block**

Find the trailing-stop integration block added in Group 1 (Task 4 Step 1). Immediately after it, add:

```python
    # Cash deployment: redeploy trailing-stop proceeds same day
    if is_initialized() and all_results:
        _deploy_idle_cash(all_results, score_map, now, regime)
```

Note: `score_map` and `all_results` and `regime` are already in scope at this point in `send_daily_briefing`.

- [ ] **Step 3: Run full test suite**

```
.\.venv\Scripts\pytest.exe tests/ -q
```

Expected: All tests pass.

- [ ] **Step 4: Commit**

```
git add quant/position_sizing.py api/analyze.py api/briefing.py
git add tests/quant/test_position_sizing.py
git commit -m "feat(sizing): wire conviction + GARCH + regime position sizing; cash-deployment trigger"
```

---

## Self-Review

**Spec coverage:**
- [x] Conviction multiplier (0.65×/1.0×/1.4×) → Task 1
- [x] GARCH vol scalar wired in → Task 1 formula + Task 2 Step 1 (expose vol_scalar)
- [x] Regime factor wired in → Task 2 Step 2
- [x] 8% hard cap per position → Task 1 (max_capital_pct=0.08)
- [x] Cash-deployment trigger (cash > 2× POSITION_SIZE) → Task 3

**Placeholder scan:** None — all steps have complete code.

**Type consistency:** `compute_conviction_position_size` returns `float` (rounded int via `round()`). All callers divide by `price` to get shares. ✓
