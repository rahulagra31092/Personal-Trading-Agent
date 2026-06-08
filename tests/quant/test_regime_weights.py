"""Tests for regime-adaptive weight system."""
import config
from quant.regime import get_regime_weights
from quant.signals import compute_signal


def test_all_regime_weights_sum_to_one():
    for regime_name, weights in config.REGIME_WEIGHTS.items():
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-9, f"{regime_name} weights sum to {total}"


def test_get_regime_weights_normal_returns_baseline():
    w = get_regime_weights("normal")
    assert w is config.SIGNAL_WEIGHTS


def test_get_regime_weights_low_vol_boosts_momentum():
    normal_w = get_regime_weights("normal")
    low_vol_w = get_regime_weights("low_vol")
    assert low_vol_w["momentum"] > normal_w["momentum"]


def test_get_regime_weights_crisis_boosts_quality():
    normal_w = get_regime_weights("normal")
    crisis_w = get_regime_weights("crisis")
    assert crisis_w["quality"] > normal_w["quality"]
    assert crisis_w["momentum"] < normal_w["momentum"]


def test_get_regime_weights_unknown_falls_back_to_baseline():
    w = get_regime_weights("nonexistent_regime")
    assert w is config.SIGNAL_WEIGHTS


def test_compute_signal_with_custom_weights():
    crisis_weights = config.REGIME_WEIGHTS["crisis"]
    result = compute_signal(
        technical_score=0.0, momentum_score=1.0, quality_score=0.0,
        congress_score=0.0, estimate_revisions_score=0.0,
        earnings_score=0.0,
        weights=crisis_weights,
    )
    expected = crisis_weights["momentum"]
    assert abs(result["composite_score"] - expected) < 0.001


def test_compute_signal_default_weights_unchanged():
    result = compute_signal(
        technical_score=0.0, momentum_score=1.0, quality_score=0.0,
        congress_score=0.0, estimate_revisions_score=0.0,
        earnings_score=0.0,
    )
    # Momentum weight in default = 0.30
    assert abs(result["composite_score"] - 0.30) < 0.001
