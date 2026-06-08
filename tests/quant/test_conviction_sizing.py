def test_conviction_multiplier_scales_with_distance_from_threshold():
    """Position size should scale with conviction (distance from 0.58 threshold)."""
    from quant.conviction_sizing import compute_conviction_multiplier

    # Barely at threshold
    assert compute_conviction_multiplier(0.58) == 0.4   # Clear BUY lower boundary
    assert compute_conviction_multiplier(0.42) == 0.2   # Just barely AVOID

    # Clear signal
    assert compute_conviction_multiplier(0.65) == 1.0   # Clear BUY upper boundary
    assert compute_conviction_multiplier(0.50) == 0.2   # Neutral/weak

    # Strong conviction
    assert compute_conviction_multiplier(0.80) == 1.5   # Strong BUY, cap at 1.5x
    assert compute_conviction_multiplier(0.85) == 1.5   # Very strong, still capped

def test_conviction_multiplier_bounds():
    """Position multiplier should be bounded [0.2x, 1.5x]."""
    from quant.conviction_sizing import compute_conviction_multiplier

    assert compute_conviction_multiplier(0.0) == 0.2     # Lowest = 0.2x
    assert compute_conviction_multiplier(1.0) == 1.5     # Highest = 1.5x
    assert compute_conviction_multiplier(0.5) >= 0.2     # Never below 0.2x
    assert compute_conviction_multiplier(0.5) <= 1.5     # Never above 1.5x

def test_conviction_multiplier_is_continuous():
    """Position size should scale smoothly, not jump at thresholds."""
    from quant.conviction_sizing import compute_conviction_multiplier

    # No discontinuous jumps
    m1 = compute_conviction_multiplier(0.57)
    m2 = compute_conviction_multiplier(0.59)
    assert abs(m1 - m2) < 0.15   # Should change smoothly, not jump
