import pytest
import config
from quant.signals import compute_signal


# ---------------------------------------------------------------------------
# Label thresholds
# ---------------------------------------------------------------------------

def test_buy_signal_above_threshold():
    result = compute_signal(technical_score=0.9, momentum_score=0.9, quality_score=0.9,
                            congress_score=0.9, trump_policy_score=0.9,
                            news_score=0.9, earnings_score=0.9)
    assert result["label"] == "BUY"
    assert result["composite_score"] > 0.65


def test_avoid_signal_below_threshold():
    result = compute_signal(technical_score=0.1, momentum_score=0.1, quality_score=0.1,
                            congress_score=0.1, trump_policy_score=0.1,
                            news_score=0.1, earnings_score=0.1)
    assert result["label"] == "AVOID"
    assert result["composite_score"] < 0.40


def test_watch_signal_at_midpoint():
    result = compute_signal(technical_score=0.5, momentum_score=0.5, quality_score=0.5,
                            congress_score=0.5, trump_policy_score=0.5,
                            news_score=0.5, earnings_score=0.5)
    assert result["label"] == "WATCH"


def test_exact_buy_boundary():
    # composite just above 0.58 → BUY
    result = compute_signal(technical_score=0.59, momentum_score=0.59, quality_score=0.59,
                            congress_score=0.59, trump_policy_score=0.59,
                            news_score=0.59, earnings_score=0.59)
    assert result["label"] == "BUY"


def test_exact_avoid_boundary():
    # composite just below 0.42 → AVOID
    result = compute_signal(technical_score=0.41, momentum_score=0.41, quality_score=0.41,
                            congress_score=0.41, trump_policy_score=0.41,
                            news_score=0.41, earnings_score=0.41)
    assert result["label"] == "AVOID"


# ---------------------------------------------------------------------------
# Individual layer weight verification
# ---------------------------------------------------------------------------

def test_technical_only_weight_is_020():
    result = compute_signal(technical_score=1.0, momentum_score=0.0, quality_score=0.0,
                            congress_score=0.0, trump_policy_score=0.0,
                            news_score=0.0, earnings_score=0.0)
    assert result["composite_score"] == pytest.approx(0.20, abs=0.0001)


def test_momentum_only_weight_is_025():
    result = compute_signal(technical_score=0.0, momentum_score=1.0, quality_score=0.0,
                            congress_score=0.0, trump_policy_score=0.0,
                            news_score=0.0, earnings_score=0.0)
    assert result["composite_score"] == pytest.approx(0.25, abs=0.0001)


def test_quality_only_weight_is_015():
    result = compute_signal(technical_score=0.0, momentum_score=0.0, quality_score=1.0,
                            congress_score=0.0, trump_policy_score=0.0,
                            news_score=0.0, earnings_score=0.0)
    assert result["composite_score"] == pytest.approx(0.15, abs=0.0001)


def test_congress_only_weight_is_008():
    result = compute_signal(technical_score=0.0, momentum_score=0.0, quality_score=0.0,
                            congress_score=1.0, trump_policy_score=0.0,
                            news_score=0.0, earnings_score=0.0)
    assert result["composite_score"] == pytest.approx(0.08, abs=0.0001)


def test_trump_policy_only_weight_is_007():
    result = compute_signal(technical_score=0.0, momentum_score=0.0, quality_score=0.0,
                            congress_score=0.0, trump_policy_score=1.0,
                            news_score=0.0, earnings_score=0.0)
    assert result["composite_score"] == pytest.approx(0.07, abs=0.0001)


def test_news_only_weight_is_010():
    result = compute_signal(technical_score=0.0, momentum_score=0.0, quality_score=0.0,
                            congress_score=0.0, trump_policy_score=0.0,
                            news_score=1.0, earnings_score=0.0)
    assert result["composite_score"] == pytest.approx(0.10, abs=0.0001)


def test_earnings_only_weight_is_015():
    result = compute_signal(technical_score=0.0, momentum_score=0.0, quality_score=0.0,
                            congress_score=0.0, trump_policy_score=0.0,
                            news_score=0.0, earnings_score=1.0)
    assert result["composite_score"] == pytest.approx(0.15, abs=0.0001)


def test_all_weights_sum_to_one():
    # Verified by the assertion in config.py at module load, but also test via compute_signal
    result = compute_signal(technical_score=1.0, momentum_score=1.0, quality_score=1.0,
                            congress_score=1.0, trump_policy_score=1.0,
                            news_score=1.0, earnings_score=1.0)
    assert result["composite_score"] == pytest.approx(1.0, abs=0.0001)


# ---------------------------------------------------------------------------
# Layer scores in response
# ---------------------------------------------------------------------------

def test_returns_layer_scores_dict():
    result = compute_signal(technical_score=0.7, momentum_score=0.8, quality_score=0.6)
    assert result["layer_scores"]["technical"] == 0.7
    assert result["layer_scores"]["momentum"] == 0.8
    assert result["layer_scores"]["congress"] == 0.5   # default
    assert result["layer_scores"]["trump_policy"] == 0.5
    assert result["layer_scores"]["news_reaction"] == 0.5
    assert result["layer_scores"]["earnings"] == 0.5


# ---------------------------------------------------------------------------
# Composite score bounded
# ---------------------------------------------------------------------------

def test_composite_score_bounded_all_zeros():
    result = compute_signal(technical_score=0.0, momentum_score=0.0, quality_score=0.0,
                            congress_score=0.0, trump_policy_score=0.0,
                            news_score=0.0, earnings_score=0.0)
    assert result["composite_score"] == pytest.approx(0.0, abs=0.0001)


def test_composite_score_bounded_all_ones():
    result = compute_signal(technical_score=1.0, momentum_score=1.0, quality_score=1.0,
                            congress_score=1.0, trump_policy_score=1.0,
                            news_score=1.0, earnings_score=1.0)
    assert result["composite_score"] == pytest.approx(1.0, abs=0.0001)
