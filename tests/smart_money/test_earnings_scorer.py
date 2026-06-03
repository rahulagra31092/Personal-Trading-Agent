import math
import pytest
from unittest.mock import patch
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo

from smart_money.earnings_scorer import (
    compute_earnings_score,
    _beat_rate_score,
    _surprise_score,
    _growth_score,
)

_ET = ZoneInfo("America/New_York")


def _cal(beat_rate=None, avg_surprise=None, last_beat=None,
         growth=None, next_date=None):
    return {
        "eps_beat_rate": beat_rate,
        "avg_surprise_pct": avg_surprise,
        "last_beat": last_beat,
        "earnings_quarterly_growth": growth,
        "next_earnings_date": next_date,
        "eps_estimate": 1.0,
    }


# ---------------------------------------------------------------------------
# _beat_rate_score
# ---------------------------------------------------------------------------

def test_beat_rate_score_zero():
    assert _beat_rate_score(0.0) == pytest.approx(0.0)


def test_beat_rate_score_half():
    assert _beat_rate_score(0.5) == pytest.approx(0.5)


def test_beat_rate_score_seventy_five():
    assert _beat_rate_score(0.75) == pytest.approx(1.0)


def test_beat_rate_score_full():
    assert _beat_rate_score(1.0) == pytest.approx(1.0)


def test_beat_rate_score_sixty():
    assert _beat_rate_score(0.6) == pytest.approx(0.7)


def test_beat_rate_score_bounded():
    assert 0.0 <= _beat_rate_score(0.0) <= 1.0
    assert 0.0 <= _beat_rate_score(1.0) <= 1.0


# ---------------------------------------------------------------------------
# _surprise_score
# ---------------------------------------------------------------------------

def test_surprise_score_zero_avg():
    assert _surprise_score(0.0) == pytest.approx(0.5, abs=0.001)


def test_surprise_score_positive_25pct():
    # tanh(1) ≈ 0.7616 → 0.5 + 0.5 * 0.7616 ≈ 0.881
    assert _surprise_score(25.0) == pytest.approx(0.5 + 0.5 * math.tanh(1.0), abs=0.001)


def test_surprise_score_negative_25pct():
    assert _surprise_score(-25.0) == pytest.approx(0.5 - 0.5 * math.tanh(1.0), abs=0.001)


def test_surprise_score_bounded():
    assert 0.0 <= _surprise_score(1000.0) <= 1.0
    assert 0.0 <= _surprise_score(-1000.0) <= 1.0


def test_surprise_score_symmetric():
    assert _surprise_score(10.0) == pytest.approx(1.0 - _surprise_score(-10.0), abs=0.001)


# ---------------------------------------------------------------------------
# _growth_score
# ---------------------------------------------------------------------------

def test_growth_score_zero():
    assert _growth_score(0.0) == pytest.approx(0.5)


def test_growth_score_positive_twenty_pct():
    assert _growth_score(0.20) == pytest.approx(0.90)


def test_growth_score_negative_twenty_pct():
    assert _growth_score(-0.20) == pytest.approx(0.10)


def test_growth_score_bounded():
    assert _growth_score(5.0) == pytest.approx(1.0)
    assert _growth_score(-5.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# compute_earnings_score — base cases
# ---------------------------------------------------------------------------

def test_full_beat_rate_returns_one():
    with patch("smart_money.earnings_scorer.get_earnings_calendar",
               return_value=_cal(beat_rate=1.0)):
        assert compute_earnings_score("AAPL") == pytest.approx(1.0)


def test_zero_beat_rate_returns_zero():
    with patch("smart_money.earnings_scorer.get_earnings_calendar",
               return_value=_cal(beat_rate=0.0)):
        assert compute_earnings_score("AAPL") == pytest.approx(0.0)


def test_half_beat_rate_returns_neutral():
    with patch("smart_money.earnings_scorer.get_earnings_calendar",
               return_value=_cal(beat_rate=0.5)):
        assert compute_earnings_score("AAPL") == pytest.approx(0.5)


def test_none_beat_rate_returns_neutral():
    with patch("smart_money.earnings_scorer.get_earnings_calendar",
               return_value=_cal()):
        assert compute_earnings_score("AAPL") == 0.5


def test_exception_returns_neutral():
    with patch("smart_money.earnings_scorer.get_earnings_calendar",
               side_effect=RuntimeError("api down")):
        assert compute_earnings_score("AAPL") == 0.5


def test_score_bounded():
    with patch("smart_money.earnings_scorer.get_earnings_calendar",
               return_value=_cal(beat_rate=1.0, avg_surprise=100.0, growth=5.0)):
        assert 0.0 <= compute_earnings_score("AAPL") <= 1.0


# ---------------------------------------------------------------------------
# Composite weighting
# ---------------------------------------------------------------------------

def test_composite_all_factors_high_quality():
    with patch("smart_money.earnings_scorer.get_earnings_calendar",
               return_value=_cal(beat_rate=1.0, avg_surprise=30.0, growth=0.25)):
        assert compute_earnings_score("AAPL") > 0.85


def test_composite_all_factors_low_quality():
    with patch("smart_money.earnings_scorer.get_earnings_calendar",
               return_value=_cal(beat_rate=0.2, avg_surprise=-20.0, growth=-0.30)):
        assert compute_earnings_score("AAPL") < 0.20


def test_missing_growth_renormalizes_weights():
    # beat_rate=0.5, surprise=0.0 → both score 0.5; renormalized composite = 0.5
    with patch("smart_money.earnings_scorer.get_earnings_calendar",
               return_value=_cal(beat_rate=0.5, avg_surprise=0.0)):
        assert compute_earnings_score("AAPL") == pytest.approx(0.5, abs=0.01)


def test_only_beat_rate_present():
    with patch("smart_money.earnings_scorer.get_earnings_calendar",
               return_value=_cal(beat_rate=0.75)):
        assert compute_earnings_score("AAPL") == pytest.approx(1.0)


def test_surprise_magnitude_differentiates_companies():
    low_surprise = _cal(beat_rate=0.7, avg_surprise=2.0)
    high_surprise = _cal(beat_rate=0.7, avg_surprise=20.0)
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=low_surprise):
        score_low = compute_earnings_score("A")
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=high_surprise):
        score_high = compute_earnings_score("B")
    assert score_high > score_low


def test_earnings_growth_boosts_score():
    no_growth = _cal(beat_rate=0.6, growth=0.0)
    strong_growth = _cal(beat_rate=0.6, growth=0.25)
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=no_growth):
        score_flat = compute_earnings_score("A")
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=strong_growth):
        score_growing = compute_earnings_score("B")
    assert score_growing > score_flat


# ---------------------------------------------------------------------------
# Modifiers
# ---------------------------------------------------------------------------

def test_post_earnings_beat_adds_modifier():
    # beat_rate=0.6 → base=0.7, +0.07 PEAD modifier
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    cal = _cal(beat_rate=0.6, last_beat=True, next_date=yesterday)
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=cal):
        assert compute_earnings_score("AAPL") == pytest.approx(0.77, abs=0.01)


def test_post_earnings_miss_subtracts_modifier():
    # beat_rate=0.6 → base=0.7, -0.05 post-miss modifier
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    cal = _cal(beat_rate=0.6, last_beat=False, next_date=yesterday)
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=cal):
        assert compute_earnings_score("AAPL") == pytest.approx(0.65, abs=0.01)


def test_pre_earnings_imminent_deep_discount():
    # beat_rate=0.6 → base=0.7, -0.07 for days 1-3
    in_2_days = (date.today() + timedelta(days=2)).isoformat()
    cal = _cal(beat_rate=0.6, next_date=in_2_days)
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=cal):
        assert compute_earnings_score("AAPL") == pytest.approx(0.63, abs=0.01)


def test_pre_earnings_near_term_small_discount():
    # beat_rate=0.6 → base=0.7, -0.05 for days 4-7
    in_5_days = (date.today() + timedelta(days=5)).isoformat()
    cal = _cal(beat_rate=0.6, next_date=in_5_days)
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=cal):
        assert compute_earnings_score("AAPL") == pytest.approx(0.65, abs=0.01)


def test_far_earnings_no_modifier():
    in_45_days = (date.today() + timedelta(days=45)).isoformat()
    cal = _cal(beat_rate=0.6, next_date=in_45_days)
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=cal):
        assert compute_earnings_score("AAPL") == pytest.approx(0.70, abs=0.01)


def test_post_earnings_no_last_beat_info_no_modifier():
    # last_beat=None means we don't know → no PEAD modifier
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    cal = _cal(beat_rate=0.6, last_beat=None, next_date=yesterday)
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=cal):
        assert compute_earnings_score("AAPL") == pytest.approx(0.70, abs=0.01)


def test_pead_capped_at_one():
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    cal = _cal(beat_rate=1.0, last_beat=True, next_date=yesterday)
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=cal):
        assert compute_earnings_score("AAPL") == pytest.approx(1.0)


def test_floor_clamped_at_zero():
    in_2_days = (date.today() + timedelta(days=2)).isoformat()
    cal = _cal(beat_rate=0.0, next_date=in_2_days)
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=cal):
        assert compute_earnings_score("AAPL") == pytest.approx(0.0)
