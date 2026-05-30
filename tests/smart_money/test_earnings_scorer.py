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
        assert abs(compute_earnings_score("AAPL") - 0.675) < 0.001


def test_pre_earnings_subtracts_modifier():
    from datetime import date, timedelta
    in_3_days = (date.today() + timedelta(days=3)).isoformat()
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=_cal(0.75, in_3_days)):
        assert abs(compute_earnings_score("AAPL") - 0.575) < 0.001


def test_far_earnings_no_modifier():
    from datetime import date, timedelta
    in_45_days = (date.today() + timedelta(days=45)).isoformat()
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=_cal(0.75, in_45_days)):
        assert abs(compute_earnings_score("AAPL") - 0.625) < 0.001


def test_score_bounded_high_end_clamp_required():
    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=_cal(1.0, yesterday)):
        assert compute_earnings_score("AAPL") == 0.80


def test_score_bounded_low_end_clamp_required():
    from datetime import date, timedelta
    in_3_days = (date.today() + timedelta(days=3)).isoformat()
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value=_cal(0.0, in_3_days)):
        assert compute_earnings_score("AAPL") == 0.20


def test_exception_returns_neutral():
    with patch("smart_money.earnings_scorer.get_earnings_calendar", side_effect=RuntimeError("api down")):
        assert compute_earnings_score("AAPL") == 0.5


def test_missing_beat_rate_key_returns_neutral():
    with patch("smart_money.earnings_scorer.get_earnings_calendar", return_value={"eps_estimate": 1.5}):
        assert compute_earnings_score("AAPL") == 0.5
