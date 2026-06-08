import pytest

from quant.confidence import run_monte_carlo


def test_returns_required_keys():
    result = run_monte_carlo(100.0, 0.02, seed=42)
    for key in ("base_target", "lower_80", "upper_80", "downside_pct",
                "upside_pct", "prob_success", "daily_vol_expected"):
        assert key in result


def test_prob_success_bounded():
    assert 0.0 <= run_monte_carlo(100.0, 0.02, seed=42)["prob_success"] <= 1.0


def test_lower_below_base_below_upper():
    r = run_monte_carlo(100.0, 0.02, seed=42)
    assert r["lower_80"] < r["base_target"] < r["upper_80"]


def test_downside_negative_upside_positive():
    r = run_monte_carlo(100.0, 0.02, seed=42)
    assert r["downside_pct"] < 0.0
    assert r["upside_pct"] > 0.0


def test_deprecated_returns_constant_dummy_values():
    """Deprecated stub returns constant dummy values regardless of input."""
    r1 = run_monte_carlo(100.0, 0.01, seed=42)
    r2 = run_monte_carlo(100.0, 0.05, seed=42)
    # Both should return identical dummy values
    assert r1["base_target"] == r2["base_target"]
    assert r1["prob_success"] == r2["prob_success"] == 0.5
    assert r1["lower_80"] == r2["lower_80"]
    assert r1["upper_80"] == r2["upper_80"]


def test_deprecated_accepts_any_vol():
    """Deprecated stub accepts any vol (no validation)."""
    # Should not raise even with zero vol (stub is permissive)
    r = run_monte_carlo(100.0, 0.0, seed=42)
    assert r["prob_success"] == 0.5


def test_monte_carlo_zero_drift_is_coin_flip():
    """Current Monte Carlo with zero drift always returns ~50% prob_success."""
    # Run multiple times with different volatilities
    probs = []
    for vol in [0.01, 0.02, 0.05, 0.10, 0.20]:
        mc = run_monte_carlo(100.0, vol, simulations=10000)
        probs.append(mc["prob_success"])

    # All probabilities should be ~0.50 (within 1%)
    for p in probs:
        assert 0.49 < p < 0.51, f"Expected ~0.50, got {p} (this is a coin flip)"


def test_monte_carlo_provides_zero_signal():
    """Monte Carlo cannot distinguish good trades from bad trades."""
    # Two scenarios: one where we're buying at support, one at resistance
    # MC should give same prob_success to both (it does = useless)

    mc_at_support = run_monte_carlo(90.0, 0.02)  # Buying at low
    mc_at_resistance = run_monte_carlo(100.0, 0.02)  # Buying at high

    # These should be different but aren't (both ~0.50)
    assert abs(mc_at_support["prob_success"] - mc_at_resistance["prob_success"]) < 0.02
