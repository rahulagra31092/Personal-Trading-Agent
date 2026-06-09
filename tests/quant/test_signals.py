import pytest
import config
from quant.signals import compute_signal


# ---------------------------------------------------------------------------
# Label thresholds
# ---------------------------------------------------------------------------

def test_buy_signal_above_threshold():
    result = compute_signal(technical_score=0.9, momentum_score=0.9, quality_score=0.9,
                            insider_trades_score=0.9, estimate_revisions_score=0.9,
                            earnings_score=0.9)
    assert result["label"] == "BUY"
    assert result["composite_score"] > 0.65


def test_avoid_signal_below_threshold():
    result = compute_signal(technical_score=0.1, momentum_score=0.1, quality_score=0.1,
                            insider_trades_score=0.1, estimate_revisions_score=0.1,
                            earnings_score=0.1)
    assert result["label"] == "AVOID"
    assert result["composite_score"] < 0.40


def test_watch_signal_at_midpoint():
    result = compute_signal(technical_score=0.5, momentum_score=0.5, quality_score=0.5,
                            insider_trades_score=0.5, estimate_revisions_score=0.5,
                            earnings_score=0.5)
    assert result["label"] == "WATCH"


def test_exact_buy_boundary():
    # composite just above 0.65 (new default) -> BUY
    # (old threshold was 0.58, now default is 0.65)
    result = compute_signal(technical_score=0.66, momentum_score=0.66, quality_score=0.66,
                            insider_trades_score=0.66, estimate_revisions_score=0.66,
                            earnings_score=0.66)
    assert result["label"] == "BUY"
    assert result["composite_score"] > 0.65


def test_exact_avoid_boundary():
    # composite just below 0.42 → AVOID
    result = compute_signal(technical_score=0.41, momentum_score=0.41, quality_score=0.41,
                            insider_trades_score=0.41, estimate_revisions_score=0.41,
                            earnings_score=0.41)
    assert result["label"] == "AVOID"


# ---------------------------------------------------------------------------
# Individual layer weight verification
# ---------------------------------------------------------------------------

def test_technical_only_weight_is_015():
    result = compute_signal(technical_score=1.0, momentum_score=0.0, quality_score=0.0,
                            insider_trades_score=0.0, estimate_revisions_score=0.0,
                            earnings_score=0.0)
    assert result["composite_score"] == pytest.approx(0.15, abs=0.0001)


def test_momentum_only_weight_is_030():
    result = compute_signal(technical_score=0.0, momentum_score=1.0, quality_score=0.0,
                            insider_trades_score=0.0, estimate_revisions_score=0.0,
                            earnings_score=0.0)
    assert result["composite_score"] == pytest.approx(0.30, abs=0.0001)


def test_quality_only_weight_is_018():
    result = compute_signal(technical_score=0.0, momentum_score=0.0, quality_score=1.0,
                            insider_trades_score=0.0, estimate_revisions_score=0.0,
                            earnings_score=0.0)
    assert result["composite_score"] == pytest.approx(0.18, abs=0.0001)


def test_insider_trades_only_weight_is_007():
    result = compute_signal(technical_score=0.0, momentum_score=0.0, quality_score=0.0,
                            insider_trades_score=1.0, estimate_revisions_score=0.0,
                            earnings_score=0.0)
    assert result["composite_score"] == pytest.approx(0.07, abs=0.0001)


def test_estimate_revisions_only_weight_is_007():
    result = compute_signal(technical_score=0.0, momentum_score=0.0, quality_score=0.0,
                            insider_trades_score=0.0, estimate_revisions_score=1.0,
                            earnings_score=0.0)
    assert result["composite_score"] == pytest.approx(0.07, abs=0.0001)


def test_earnings_only_weight_is_023():
    result = compute_signal(technical_score=0.0, momentum_score=0.0, quality_score=0.0,
                            insider_trades_score=0.0, estimate_revisions_score=0.0,
                            earnings_score=1.0)
    assert result["composite_score"] == pytest.approx(0.23, abs=0.0001)


def test_all_weights_sum_to_one():
    # Verified by the assertion in config.py at module load, but also test via compute_signal
    result = compute_signal(technical_score=1.0, momentum_score=1.0, quality_score=1.0,
                            insider_trades_score=1.0, estimate_revisions_score=1.0,
                            earnings_score=1.0)
    assert result["composite_score"] == pytest.approx(1.0, abs=0.0001)


# ---------------------------------------------------------------------------
# Layer scores in response
# ---------------------------------------------------------------------------

def test_returns_layer_scores_dict():
    result = compute_signal(technical_score=0.7, momentum_score=0.8, quality_score=0.6)
    assert result["layer_scores"]["technical"] == 0.7
    assert result["layer_scores"]["momentum"] == 0.8
    assert result["layer_scores"]["quality"] == 0.6
    assert result["layer_scores"]["insider_trades"] == 0.5   # default
    assert result["layer_scores"]["estimate_revisions"] == 0.5
    assert result["layer_scores"]["earnings"] == 0.5


# ---------------------------------------------------------------------------
# Composite score bounded
# ---------------------------------------------------------------------------

def test_composite_score_bounded_all_zeros():
    result = compute_signal(technical_score=0.0, momentum_score=0.0, quality_score=0.0,
                            insider_trades_score=0.0, estimate_revisions_score=0.0,
                            earnings_score=0.0)
    assert result["composite_score"] == pytest.approx(0.0, abs=0.0001)


def test_composite_score_bounded_all_ones():
    result = compute_signal(technical_score=1.0, momentum_score=1.0, quality_score=1.0,
                            insider_trades_score=1.0, estimate_revisions_score=1.0,
                            earnings_score=1.0)
    assert result["composite_score"] == pytest.approx(1.0, abs=0.0001)


# ---------------------------------------------------------------------------
# Interaction gate: low quality blocks BUY regardless of other scores
# ---------------------------------------------------------------------------

def test_low_quality_gate_forces_watch():
    # quality=0.30 < 0.35 gate threshold; all others very high → would be BUY without gate
    result = compute_signal(
        technical_score=0.95, momentum_score=0.95, quality_score=0.30,
        insider_trades_score=0.90, estimate_revisions_score=0.90,
        earnings_score=0.90,
    )
    assert result["label"] == "WATCH"
    assert result["composite_score"] <= 0.57


def test_quality_above_gate_threshold_allows_buy():
    # quality=0.36 >= 0.35; gate does not fire
    result = compute_signal(
        technical_score=0.95, momentum_score=0.95, quality_score=0.36,
        insider_trades_score=0.90, estimate_revisions_score=0.90,
        earnings_score=0.90,
    )
    assert result["label"] == "BUY"


def test_gate_does_not_affect_avoid_signals():
    # Low quality AND low composite → AVOID (gate condition composite > 0.57 is False)
    result = compute_signal(
        technical_score=0.20, momentum_score=0.20, quality_score=0.20,
        insider_trades_score=0.20, estimate_revisions_score=0.20,
        earnings_score=0.20,
    )
    assert result["label"] == "AVOID"


def test_gate_exact_quality_boundary():
    # quality exactly 0.35 — strict < means gate does NOT fire
    result = compute_signal(
        technical_score=0.95, momentum_score=0.95, quality_score=0.35,
        insider_trades_score=0.90, estimate_revisions_score=0.90,
        earnings_score=0.90,
    )
    assert result["label"] == "BUY"


# ---------------------------------------------------------------------------
# Regression: estimate_revisions slot naming
# ---------------------------------------------------------------------------

def test_analyze_signal_has_estimate_revisions_key_not_trump_policy():
    """The composite signal dict must use estimate_revisions, not trump_policy."""
    from quant.signals import compute_signal
    result = compute_signal(
        technical_score=0.6, momentum_score=0.6, quality_score=0.6,
        insider_trades_score=0.6, estimate_revisions_score=0.8,
        earnings_score=0.6,
    )
    assert "composite_score" in result
    # Verify the weight slot is named correctly — calling with estimate_revisions works
    # and the old name raises TypeError
    with pytest.raises(TypeError):
        compute_signal(
            technical_score=0.6, momentum_score=0.6, quality_score=0.6,
            insider_trades_score=0.6, trump_policy_score=0.8,
            earnings_score=0.6,
        )
