"""Tests for quarterly regression engine."""
import pytest
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo

from api.quarterly_review import (
    _spearman,
    _significance,
    _recommend_weights,
    run_quarterly_review,
    build_quarterly_slack_blocks,
    is_quarter_start,
    FACTORS,
)
import config

_ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Spearman tests
# ---------------------------------------------------------------------------

def test_spearman_perfect_positive():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert abs(_spearman(xs, ys) - 1.0) < 0.001


def test_spearman_perfect_negative():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [50.0, 40.0, 30.0, 20.0, 10.0]
    assert abs(_spearman(xs, ys) - (-1.0)) < 0.001


def test_spearman_too_few_returns_zero():
    assert _spearman([1.0, 2.0], [3.0, 4.0]) == 0.0


def test_spearman_bounded():
    xs = [0.1, 0.9, 0.5, 0.3, 0.7, 0.2, 0.8, 0.4]
    ys = [5.0, 1.0, 3.0, 7.0, 2.0, 8.0, 4.0, 6.0]
    r = _spearman(xs, ys)
    assert -1.0 <= r <= 1.0


def test_spearman_handles_ties_correctly():
    from api.quarterly_review import _spearman
    # All xs are tied at the same value → correlation should be 0.0 (undefined → 0)
    xs = [0.5, 0.5, 0.5, 0.5, 0.5]
    ys = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = _spearman(xs, ys)
    assert result == 0.0  # perfectly tied predictor → no correlation


def test_spearman_tied_ranks_stays_in_bounds():
    from api.quarterly_review import _spearman
    # Heavy ties — many 0.5 defaults like real factor scores
    xs = [0.5, 0.5, 0.5, 0.6, 0.5, 0.7, 0.5, 0.5, 0.6, 0.5]
    ys = [5.0, -3.0, 8.0, 2.0, 1.0, 9.0, -1.0, 4.0, 3.0, 7.0]
    result = _spearman(xs, ys)
    assert -1.0 <= result <= 1.0  # biased formula can violate this


def test_spearman_perfect_correlation_still_works():
    from api.quarterly_review import _spearman
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [2.0, 4.0, 6.0, 8.0, 10.0]
    assert _spearman(xs, ys) == pytest.approx(1.0, abs=0.001)


def test_spearman_perfect_anticorrelation():
    from api.quarterly_review import _spearman
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [5.0, 4.0, 3.0, 2.0, 1.0]
    assert _spearman(xs, ys) == pytest.approx(-1.0, abs=0.001)


# ---------------------------------------------------------------------------
# Significance tests
# ---------------------------------------------------------------------------

def test_significance_strong():
    assert _significance(0.7, 30) in ("***", "**")


def test_significance_none():
    assert _significance(0.05, 10) == "ns"


# ---------------------------------------------------------------------------
# Weight recommendation tests
# ---------------------------------------------------------------------------

def test_recommend_weights_sums_to_one():
    corrs = {col: 0.3 for col, _ in FACTORS}
    rw = _recommend_weights(corrs)
    assert abs(sum(rw.values()) - 1.0) < 0.01


def test_recommend_weights_bounded():
    corrs = {col: 1.0 for col, _ in FACTORS}
    rw = _recommend_weights(corrs)
    for w in rw.values():
        assert 0.03 <= w <= 0.36


def test_recommend_weights_no_change_on_neutral():
    corrs = {col: 0.0 for col, _ in FACTORS}
    rw = _recommend_weights(corrs)
    for k, v in rw.items():
        baseline = config.SIGNAL_WEIGHTS.get(k, v)
        assert abs(v - baseline) < 0.06


# ---------------------------------------------------------------------------
# run_quarterly_review tests
# ---------------------------------------------------------------------------

def _make_closed(n: int, avg_ret: float = 5.0) -> list[dict]:
    base = {col: 0.6 for col, _ in FACTORS}
    base["score_composite"] = 0.65
    base["vix_at_entry"] = 18.0
    base["regime_at_entry"] = "normal"
    base["sector"] = "Tech"
    base["entry_date"] = "2026-01-01"
    base["exit_date"]  = "2026-02-15"
    base["entry_price"] = 100.0
    base["exit_price"]  = 100.0 * (1 + avg_ret / 100)
    base["days_held"]   = 45
    base["exit_reason"] = "rank_drop"
    return [{**base, "ticker": f"T{i}", "realized_return_pct": avg_ret} for i in range(n)]


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


def test_run_quarterly_review_skipped_when_too_few():
    with patch("api.quarterly_review.get_closed_outcomes", return_value=_make_closed(5)):
        result = run_quarterly_review(min_closed=15)
    assert result["skipped"] is True


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


def test_run_quarterly_review_returns_report():
    with patch("api.quarterly_review.get_closed_outcomes", return_value=_make_closed(20)):
        result = run_quarterly_review(min_closed=15)
    assert result["skipped"] is False
    assert result["n"] == 20
    assert 0.0 <= result["win_rate"] <= 100.0
    assert "recommended_weights" in result
    assert abs(sum(result["recommended_weights"].values()) - 1.0) < 0.01


def test_run_quarterly_review_on_track_flag():
    positions = _make_closed(20, avg_ret=8.0)   # ~60% annualised
    with patch("api.quarterly_review.get_closed_outcomes", return_value=positions):
        result = run_quarterly_review(min_closed=15)
    assert result["on_track_18pct"] is True


# ---------------------------------------------------------------------------
# Slack block builder tests
# ---------------------------------------------------------------------------

def test_build_blocks_skipped_returns_single_block():
    now = datetime(2026, 10, 1, 9, 0, tzinfo=_ET)
    report = {"skipped": True, "n": 5, "reason": "Not enough data."}
    blocks = build_quarterly_slack_blocks(report, now)
    assert len(blocks) == 1
    assert "Not enough data" in blocks[0]["text"]["text"]


def test_build_blocks_full_report_has_multiple_sections():
    now = datetime(2026, 10, 1, 9, 0, tzinfo=_ET)
    with patch("api.quarterly_review.get_closed_outcomes", return_value=_make_closed(20)):
        report = run_quarterly_review(min_closed=15)
    blocks = build_quarterly_slack_blocks(report, now)
    assert len(blocks) >= 4


# ---------------------------------------------------------------------------
# is_quarter_start tests
# ---------------------------------------------------------------------------

def test_is_quarter_start_jan1():
    assert is_quarter_start(datetime(2026, 1, 1, tzinfo=_ET))


def test_is_quarter_start_jul1():
    assert is_quarter_start(datetime(2026, 7, 1, tzinfo=_ET))


def test_is_quarter_start_not_feb1():
    assert not is_quarter_start(datetime(2026, 2, 1, tzinfo=_ET))


def test_is_quarter_start_not_jan2():
    assert not is_quarter_start(datetime(2026, 1, 2, tzinfo=_ET))


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
