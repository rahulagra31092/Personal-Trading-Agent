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


def test_high_vol_widens_bands():
    low_vol = run_monte_carlo(100.0, 0.01, seed=42)
    high_vol = run_monte_carlo(100.0, 0.05, seed=42)
    assert (high_vol["upper_80"] - high_vol["lower_80"]) > (low_vol["upper_80"] - low_vol["lower_80"])


def test_zero_drift_prob_success_near_half():
    r = run_monte_carlo(100.0, 0.02, days=5, simulations=10_000, seed=42)
    assert 0.40 <= r["prob_success"] <= 0.60
