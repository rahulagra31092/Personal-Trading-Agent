from unittest.mock import patch
from smart_money.earnings_scorer import compute_earnings_score


def test_none_days_returns_neutral():
    with patch("smart_money.earnings_scorer.days_to_earnings", return_value=None):
        assert compute_earnings_score("AAPL") == 0.5


def test_far_earnings_returns_neutral():
    with patch("smart_money.earnings_scorer.days_to_earnings", return_value=45):
        assert compute_earnings_score("AAPL") == 0.5


def test_approaching_earnings_returns_slight_positive():
    with patch("smart_money.earnings_scorer.days_to_earnings", return_value=15):
        assert compute_earnings_score("AAPL") == 0.55


def test_imminent_earnings_returns_low():
    with patch("smart_money.earnings_scorer.days_to_earnings", return_value=3):
        assert compute_earnings_score("AAPL") == 0.2


def test_post_earnings_returns_high():
    with patch("smart_money.earnings_scorer.days_to_earnings", return_value=-1):
        assert compute_earnings_score("AAPL") == 0.7


def test_stale_earnings_returns_neutral():
    with patch("smart_money.earnings_scorer.days_to_earnings", return_value=-10):
        assert compute_earnings_score("AAPL") == 0.5


def test_exception_returns_neutral():
    with patch(
        "smart_money.earnings_scorer.days_to_earnings",
        side_effect=Exception("network error"),
    ):
        assert compute_earnings_score("AAPL") == 0.5
