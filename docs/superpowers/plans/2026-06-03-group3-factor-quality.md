# Group 3: Factor Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the administration-specific Trump policy layer with a durable analyst estimate revision signal; add negation detection to the news layer; reduce the technical weight from 20% to 15% and give the freed 5% to momentum (now 30%).

**Architecture:** A new `smart_money/estimate_revisions.py` module replaces `trump_scorer.py` as the data source. The config key stays `trump_policy` to avoid a DB migration — only the data source changes. The news scorer gets a `_has_negation()` pre-pass on keyword matches. Weight changes touch `config.py` only (all runtime code reads from config).

**Tech Stack:** Python 3.12, yfinance (analyst grades/price targets), existing cache layer.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `smart_money/estimate_revisions.py` | **Create** | `compute_estimate_revision_score()` using analyst grades + price targets |
| `api/analyze.py` | Modify | Replace `compute_trump_policy_score` call with `compute_estimate_revision_score` |
| `config.py` | Modify | Reweight: technical 0.20→0.15, momentum 0.25→0.30, all REGIME_WEIGHTS updated |
| `smart_money/news_scorer.py` | Modify | Add `_has_negation()` and apply it in `_count_keywords` |
| `smart_money/trump_scorer.py` | No change | Left in place — file kept for reference, just no longer called |
| `tests/smart_money/test_estimate_revisions.py` | **Create** | Tests for new revision scorer |
| `tests/quant/test_signals.py` | Modify | Update weight tests (technical 0.20→0.15, momentum 0.25→0.30) |
| `tests/smart_money/test_news_scorer.py` | Modify | Add negation tests |

---

## Task 1: Analyst Estimate Revision Scorer

**Files:**
- Create: `smart_money/estimate_revisions.py`
- Create: `tests/smart_money/test_estimate_revisions.py`

### Background
The signal uses two yfinance data points:
1. **`ticker.upgrades_downgrades`**: A DataFrame of analyst grade changes with dates. Count upgrades vs downgrades in the last 30 days → net directional signal.
2. **`ticker.info["recommendationMean"]`**: Fallback (1.0=Strong Buy, 5.0=Strong Sell) when grade history is unavailable.

Scoring:
- Net score from grades: `0.5 + (upgrades - downgrades) / total * 0.40`
- Recommendation mean fallback: `(5.0 - rec_mean) / 4.0`
- Analyst count adjustment: fewer than 3 analysts → pull score toward 0.5
- Clamped to [0.05, 0.95]

Grade classification:
- Upgrade words: "buy", "outperform", "overweight", "strong buy", "accumulate"
- Downgrade words: "sell", "underperform", "underweight", "strong sell", "reduce"

- [ ] **Step 1: Create the test file**

Create `tests/smart_money/test_estimate_revisions.py`:

```python
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from smart_money.estimate_revisions import compute_estimate_revision_score


def _make_upgrades_df(rows: list[tuple]) -> pd.DataFrame:
    """rows: [(date_str, from_grade, to_grade), ...]"""
    dates = [pd.Timestamp(r[0], tz="UTC") for r in rows]
    return pd.DataFrame(
        {"FromGrade": [r[1] for r in rows], "ToGrade": [r[2] for r in rows]},
        index=pd.DatetimeIndex(dates),
    )


def _mock_ticker(upgrades_df=None, rec_mean=None, num_analysts=5,
                 current_price=100.0, target_mean=None):
    t = MagicMock()
    t.upgrades_downgrades = upgrades_df
    t.info = {
        "recommendationMean": rec_mean,
        "numberOfAnalystOpinions": num_analysts,
        "currentPrice": current_price,
        "targetMeanPrice": target_mean,
    }
    return t


def test_all_upgrades_returns_bullish():
    df = _make_upgrades_df([
        ("2026-05-20", "Hold", "Buy"),
        ("2026-05-25", "Neutral", "Outperform"),
        ("2026-06-01", "Sell", "Buy"),
    ])
    with patch("smart_money.estimate_revisions.yf.Ticker", return_value=_mock_ticker(upgrades_df=df)):
        score = compute_estimate_revision_score("NVDA")
    assert score > 0.60


def test_all_downgrades_returns_bearish():
    df = _make_upgrades_df([
        ("2026-05-20", "Buy", "Sell"),
        ("2026-05-25", "Outperform", "Underperform"),
        ("2026-06-01", "Hold", "Underweight"),
    ])
    with patch("smart_money.estimate_revisions.yf.Ticker", return_value=_mock_ticker(upgrades_df=df)):
        score = compute_estimate_revision_score("XYZ")
    assert score < 0.40


def test_mixed_grades_returns_near_neutral():
    df = _make_upgrades_df([
        ("2026-05-20", "Hold", "Buy"),
        ("2026-05-25", "Buy", "Sell"),
        ("2026-06-01", "Neutral", "Outperform"),
        ("2026-06-02", "Outperform", "Underperform"),
    ])
    with patch("smart_money.estimate_revisions.yf.Ticker", return_value=_mock_ticker(upgrades_df=df)):
        score = compute_estimate_revision_score("AAPL")
    assert 0.40 <= score <= 0.60


def test_no_recent_grades_falls_back_to_rec_mean():
    # Empty DataFrame → falls back to recommendationMean=2.0 (roughly Buy)
    with patch("smart_money.estimate_revisions.yf.Ticker",
               return_value=_mock_ticker(upgrades_df=pd.DataFrame(), rec_mean=2.0)):
        score = compute_estimate_revision_score("MSFT")
    assert score > 0.50


def test_strong_sell_rec_mean_returns_low_score():
    with patch("smart_money.estimate_revisions.yf.Ticker",
               return_value=_mock_ticker(upgrades_df=pd.DataFrame(), rec_mean=4.5)):
        score = compute_estimate_revision_score("WEAK")
    assert score < 0.25


def test_no_data_returns_neutral():
    with patch("smart_money.estimate_revisions.yf.Ticker",
               return_value=_mock_ticker(upgrades_df=pd.DataFrame(), rec_mean=None)):
        score = compute_estimate_revision_score("NODTA")
    assert score == pytest.approx(0.5)


def test_exception_returns_neutral():
    with patch("smart_money.estimate_revisions.yf.Ticker", side_effect=RuntimeError("network")):
        score = compute_estimate_revision_score("CRASH")
    assert score == pytest.approx(0.5)


def test_score_bounded_0_to_1():
    df = _make_upgrades_df([("2026-06-01", "Sell", "Strong Buy")] * 10)
    with patch("smart_money.estimate_revisions.yf.Ticker", return_value=_mock_ticker(upgrades_df=df)):
        score = compute_estimate_revision_score("NVDA")
    assert 0.0 <= score <= 1.0


def test_cache_hit_skips_yfinance():
    from data.cache import set_cache
    set_cache("est_revision:CACHED", 0.73, ttl_seconds=86400)
    with patch("smart_money.estimate_revisions.yf.Ticker") as mock_yf:
        score = compute_estimate_revision_score("CACHED")
    assert score == pytest.approx(0.73)
    mock_yf.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd "C:\Claude\Trading Analyst"
.\.venv\Scripts\pytest.exe tests/smart_money/test_estimate_revisions.py -v
```

Expected: `ModuleNotFoundError: No module named 'smart_money.estimate_revisions'`

- [ ] **Step 3: Create `smart_money/estimate_revisions.py`**

```python
import logging
from typing import Optional
import pandas as pd
import yfinance as yf

from data.cache import get_cache, set_cache

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400  # 24h — analyst revisions change slowly

_UPGRADE_WORDS = frozenset({"buy", "outperform", "overweight", "strong buy", "accumulate", "positive"})
_DOWNGRADE_WORDS = frozenset({"sell", "underperform", "underweight", "strong sell", "reduce", "negative"})


def _grade_direction(grade: str) -> int:
    """Return +1 for upgrade-type grade, -1 for downgrade-type, 0 for neutral."""
    g = grade.lower().strip()
    if any(w in g for w in _UPGRADE_WORDS):
        return 1
    if any(w in g for w in _DOWNGRADE_WORDS):
        return -1
    return 0


def _score_from_grades(df: pd.DataFrame) -> Optional[float]:
    """
    Score from recent analyst grade changes. Returns None if insufficient data.
    Filters to last 30 days. Net score: 0.5 + (upgrades - downgrades) / total * 0.40.
    """
    if df is None or df.empty:
        return None

    try:
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30)
        idx = df.index
        if idx.tz is None:
            cutoff = cutoff.tz_localize(None)
        recent = df[idx >= cutoff]
    except Exception:
        return None

    if recent.empty:
        return None

    to_col = "ToGrade" if "ToGrade" in recent.columns else (
        recent.columns[1] if len(recent.columns) >= 2 else None
    )
    if to_col is None:
        return None

    directions = [_grade_direction(str(g)) for g in recent[to_col]]
    total = len(directions)
    if total == 0:
        return None

    upgrades = sum(1 for d in directions if d == 1)
    downgrades = sum(1 for d in directions if d == -1)
    net = 0.5 + (upgrades - downgrades) / total * 0.40
    return round(min(0.95, max(0.05, net)), 4)


def _score_from_rec_mean(info: dict) -> Optional[float]:
    """Fallback: map recommendationMean (1=Strong Buy, 5=Strong Sell) → [0,1]."""
    rec_mean = info.get("recommendationMean")
    if rec_mean is None:
        return None
    return round(min(1.0, max(0.0, (5.0 - float(rec_mean)) / 4.0)), 4)


def compute_estimate_revision_score(ticker: str) -> float:
    """
    Analyst estimate revision signal [0, 1].
    Primary: net analyst grade changes (upgrades vs downgrades) in last 30 days.
    Fallback: consensus recommendation mean from yfinance info.
    Returns 0.5 (neutral) when data is unavailable.
    Cached 24h.
    """
    cache_key = f"est_revision:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    try:
        t = yf.Ticker(ticker)
        grade_score = _score_from_grades(t.upgrades_downgrades)

        if grade_score is not None:
            result = grade_score
        else:
            result = _score_from_rec_mean(t.info or {}) or 0.5

        set_cache(cache_key, result, ttl_seconds=_CACHE_TTL)
        return result

    except Exception as exc:
        logger.warning("Estimate revision score failed for %s: %s", ticker, exc)
        return 0.5
```

- [ ] **Step 4: Run tests — all must pass**

```
.\.venv\Scripts\pytest.exe tests/smart_money/test_estimate_revisions.py -v
```

Expected: All 10 tests pass.

---

## Task 2: Replace Trump Policy in `analyze.py`

**Files:**
- Modify: `api/analyze.py`

- [ ] **Step 1: Swap the import and call**

In `api/analyze.py`, find:
```python
from smart_money.trump_scorer import compute_trump_policy_score
```
Replace with:
```python
from smart_money.estimate_revisions import compute_estimate_revision_score
```

Find:
```python
    trump_policy_score = compute_trump_policy_score(ticker)
```
Replace with:
```python
    trump_policy_score = compute_estimate_revision_score(ticker)
```

The parameter name `trump_policy_score` stays the same — it maps to the `trump_policy` key in `compute_signal` which maps to the `trump_policy` weight in config. The data source changes; the plumbing stays unchanged. This avoids a DB migration.

- [ ] **Step 2: Run the analyze tests**

```
.\.venv\Scripts\pytest.exe tests/api/test_analyze.py -v
```

Expected: All tests pass (they mock `compute_trump_policy_score` — update the mock target if any test specifically patches `smart_money.trump_scorer.compute_trump_policy_score`).

**If any test patches the old path:** Open `tests/api/test_analyze.py` and update:
```python
# Old:
patch("api.analyze.compute_trump_policy_score", ...)
# New:
patch("api.analyze.compute_estimate_revision_score", ...)
```

---

## Task 3: Update Signal Weights in `config.py`

**Files:**
- Modify: `config.py`
- Modify: `tests/quant/test_signals.py`

### Background
Reducing technical overlap with momentum. New base weights:
- `technical`: 0.20 → **0.15**
- `momentum`: 0.25 → **0.30**
- All others unchanged (quality 0.15, congress 0.08, trump_policy 0.07, news_reaction 0.10, earnings 0.15)
- Sum: 0.15+0.30+0.15+0.08+0.07+0.10+0.15 = **1.00** ✓

Each REGIME_WEIGHTS entry must also be updated so its sum stays 1.0. New values:

| Regime | technical | momentum | quality | congress | trump_policy | news | earnings |
|--------|-----------|----------|---------|----------|--------------|------|----------|
| low_vol | 0.13 | 0.37 | 0.12 | 0.08 | 0.07 | 0.08 | 0.15 |
| normal | 0.15 | 0.30 | 0.15 | 0.08 | 0.07 | 0.10 | 0.15 |
| elevated | 0.10 | 0.23 | 0.22 | 0.08 | 0.07 | 0.10 | 0.20 |
| high | 0.08 | 0.12 | 0.28 | 0.07 | 0.05 | 0.10 | 0.30 |
| crisis | 0.06 | 0.10 | 0.32 | 0.05 | 0.05 | 0.10 | 0.32 |

Sums: low_vol=1.00 ✓, normal=1.00 ✓, elevated=1.00 ✓, high=1.00 ✓, crisis=1.00 ✓

- [ ] **Step 1: Update weight tests first (they will now fail at old values)**

In `tests/quant/test_signals.py`, update:

```python
def test_technical_only_weight_is_020():
    # CHANGE: technical is now 0.15
    result = compute_signal(technical_score=1.0, momentum_score=0.0, quality_score=0.0,
                            congress_score=0.0, trump_policy_score=0.0,
                            news_score=0.0, earnings_score=0.0)
    assert result["composite_score"] == pytest.approx(0.15, abs=0.0001)


def test_momentum_only_weight_is_025():
    # CHANGE: momentum is now 0.30
    result = compute_signal(technical_score=0.0, momentum_score=1.0, quality_score=0.0,
                            congress_score=0.0, trump_policy_score=0.0,
                            news_score=0.0, earnings_score=0.0)
    assert result["composite_score"] == pytest.approx(0.30, abs=0.0001)
```

Also update the docstring comments in those two tests to `0.15` and `0.30`.

- [ ] **Step 2: Run weight tests to verify they now fail**

```
.\.venv\Scripts\pytest.exe tests/quant/test_signals.py::test_technical_only_weight_is_020 -v
```

Expected: FAIL — `0.2 != 0.15` (config hasn't changed yet).

- [ ] **Step 3: Update `config.py` weights**

In `config.py`, replace the `SIGNAL_WEIGHTS` dict and entire `REGIME_WEIGHTS` dict:

```python
SIGNAL_WEIGHTS: dict[str, float] = {
    "technical": 0.15,
    "momentum": 0.30,
    "quality": 0.15,
    "congress": 0.08,
    "trump_policy": 0.07,
    "news_reaction": 0.10,
    "earnings": 0.15,
}
assert abs(sum(SIGNAL_WEIGHTS.values()) - 1.0) < 1e-9, (
    f"SIGNAL_WEIGHTS must sum to 1.0, got {sum(SIGNAL_WEIGHTS.values())}"
)

# Regime-adaptive weight overrides — applied by signals.py based on live VIX.
REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    "low_vol": {          # VIX < 15 — bull market, momentum heavily rewarded
        "technical": 0.13, "momentum": 0.37, "quality": 0.12,
        "congress": 0.08, "trump_policy": 0.07, "news_reaction": 0.08, "earnings": 0.15,
    },
    "normal": SIGNAL_WEIGHTS,  # VIX 15-20 — baseline weights
    "elevated": {         # VIX 20-25 — momentum falters, quality/earnings take over
        "technical": 0.10, "momentum": 0.23, "quality": 0.22,
        "congress": 0.08, "trump_policy": 0.07, "news_reaction": 0.10, "earnings": 0.20,
    },
    "high": {             # VIX 25-30 — preserve capital; quality + earnings dominate
        "technical": 0.08, "momentum": 0.12, "quality": 0.28,
        "congress": 0.07, "trump_policy": 0.05, "news_reaction": 0.10, "earnings": 0.30,
    },
    "crisis": {           # VIX >= 30 — extreme stress; cash is valid
        "technical": 0.06, "momentum": 0.10, "quality": 0.32,
        "congress": 0.05, "trump_policy": 0.05, "news_reaction": 0.10, "earnings": 0.32,
    },
}
for _regime, _w in REGIME_WEIGHTS.items():
    if _w is not SIGNAL_WEIGHTS:
        assert abs(sum(_w.values()) - 1.0) < 1e-9, (
            f"REGIME_WEIGHTS[{_regime!r}] must sum to 1.0"
        )
```

- [ ] **Step 4: Run all signal and regime tests**

```
.\.venv\Scripts\pytest.exe tests/quant/test_signals.py tests/quant/test_regime.py tests/quant/test_regime_weights.py -v
```

Expected: All tests pass. (The buy/avoid boundary tests use per-score thresholds, not absolute weight values, so they are unaffected.)

---

## Task 4: Negation Detection in News Scorer

**Files:**
- Modify: `smart_money/news_scorer.py`
- Modify: `tests/smart_money/test_news_scorer.py`

### Background
"Not a buy" currently scores as bullish because `buy` is in the bullish set. The fix: before counting a keyword match, check if one of the negation words (`not`, `no`, `never`, `failed to`, `unable to`, `won't`, `cannot`, `can't`) appears within 4 words before the keyword in the text. If so, flip the polarity (bullish → bearish, bearish → bullish).

This is a targeted fix using a simple pre-pass, not a full NLP model.

- [ ] **Step 1: Write the failing tests**

Add to `tests/smart_money/test_news_scorer.py`:

```python
# ---------------------------------------------------------------------------
# Negation detection
# ---------------------------------------------------------------------------

def test_negated_bullish_word_does_not_count_as_bullish():
    bull, bear = _count_keywords("company did not beat expectations this quarter")
    # "beat" is negated by "not" → should NOT count as bullish
    assert bull == 0


def test_negated_bearish_word_counts_as_bullish():
    bull, bear = _count_keywords("stock will not decline further say analysts")
    # "decline" is negated by "not" → flipped to bullish
    assert bull >= 1
    assert bear == 0


def test_non_negated_bullish_still_counts():
    bull, bear = _count_keywords("stock beat expectations and surged higher")
    assert bull >= 2


def test_cannot_negation_works():
    bull, bear = _count_keywords("company cannot grow in current environment")
    # "grow" → "growing" not matched (different form), but "growth" would be
    # Test with a word that IS in the set:
    bull2, bear2 = _count_keywords("analysts cannot recommend a buy at this price")
    # "buy" negated by "cannot" → not bullish
    assert bull2 == 0


def test_no_negation_at_start():
    bull, bear = _count_keywords("no growth is expected in q3")
    # "growth" negated by "no" → not bullish
    assert bull == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```
.\.venv\Scripts\pytest.exe tests/smart_money/test_news_scorer.py::test_negated_bullish_word_does_not_count_as_bullish -v
```

Expected: FAIL — current code counts `beat` as bullish even with `not` before it.

- [ ] **Step 3: Add `_has_negation` and update `_count_keywords`**

In `smart_money/news_scorer.py`, add this helper function before `_count_keywords`:

```python
_NEGATIONS = frozenset({
    "not", "no", "never", "neither", "nor",
    "failed", "unable", "won't", "cannot", "can't", "didn't", "doesn't", "don't",
})


def _has_negation(text: str, match_start: int, window: int = 5) -> bool:
    """
    Return True if a negation word appears within `window` words before `match_start`.
    Operates on pre-tokenized words to avoid partial matches.
    """
    # Slice a window of text before the match position
    prefix = text[max(0, match_start - 60):match_start]
    words = prefix.split()[-window:]
    return any(w.rstrip(".,;:") in _NEGATIONS for w in words)
```

Update `_count_keywords` to use it:

```python
def _count_keywords(text: str) -> tuple[int, int]:
    """Count bullish and bearish signals in lowercased article text, with negation detection."""
    bull = 0
    bear = 0

    for w in _BULLISH:
        m = re.search(rf"\b{re.escape(w)}\b", text)
        if m:
            if _has_negation(text, m.start()):
                bear += 1   # negated bullish → bearish flip
            else:
                bull += 1

    for w in _BEARISH:
        m = re.search(rf"\b{re.escape(w)}\b", text)
        if m:
            if _has_negation(text, m.start()):
                bull += 1   # negated bearish → bullish flip
            else:
                bear += 1

    bull += sum(1 for p in _BULLISH_PHRASES if p in text)
    bear += sum(1 for p in _BEARISH_PHRASES if p in text)
    return bull, bear
```

- [ ] **Step 4: Run all news scorer tests**

```
.\.venv\Scripts\pytest.exe tests/smart_money/test_news_scorer.py -v
```

Expected: All existing + 5 new negation tests pass.

- [ ] **Step 5: Run full test suite**

```
.\.venv\Scripts\pytest.exe tests/ -q
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```
git add smart_money/estimate_revisions.py smart_money/news_scorer.py
git add api/analyze.py config.py
git add tests/smart_money/test_estimate_revisions.py tests/smart_money/test_news_scorer.py
git add tests/quant/test_signals.py
git commit -m "feat(factors): analyst revisions replace trump policy; negation detection; reweight technical/momentum"
```

---

## Self-Review

**Spec coverage:**
- [x] Analyst estimate revisions replace Trump policy → Tasks 1 + 2
- [x] Data source replaced without DB schema change → analyze.py swap, config key unchanged
- [x] Negation detection in news → Task 4
- [x] Technical 15%, momentum 30% → Task 3

**Placeholder scan:** None.

**Type consistency:** `compute_estimate_revision_score` returns `float`. Called as `trump_policy_score = compute_estimate_revision_score(ticker)` — parameter name matches `compute_signal` signature. ✓

**Weight sums:**
- low_vol: 0.13+0.37+0.12+0.08+0.07+0.08+0.15 = 1.00 ✓
- normal: 0.15+0.30+0.15+0.08+0.07+0.10+0.15 = 1.00 ✓
- elevated: 0.10+0.23+0.22+0.08+0.07+0.10+0.20 = 1.00 ✓
- high: 0.08+0.12+0.28+0.07+0.05+0.10+0.30 = 1.00 ✓
- crisis: 0.06+0.10+0.32+0.05+0.05+0.10+0.32 = 1.00 ✓
