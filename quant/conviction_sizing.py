def compute_conviction_multiplier(composite_score: float) -> float:
    """
    Map signal strength (composite_score) to position size multiplier.

    Uses distance from neutral (0.5) to scale position size:
    - 0.42-0.58 (near neutral) = 0.2x - 0.4x (skeptical)
    - 0.58-0.65 (clear BUY) = 0.4x - 1.0x (normal)
    - 0.65-0.80 (strong BUY) = 1.0x - 1.5x (confident)
    - 0.80+ (very strong) = 1.5x (max conviction)

    Ensures we size DOWN on weak signals, not up on everything.
    """
    # Clamp to [0, 1]
    score = max(0.0, min(1.0, composite_score))

    if score < 0.42:
        # Strong AVOID - shouldn't get here (no short logic yet)
        return 0.2

    if score < 0.50:
        # Weak BUY/AVOID boundary - very skeptical
        return 0.2

    if score < 0.58:
        # Barely BUY threshold - still skeptical
        t = (score - 0.50) / 0.08
        return 0.2 + t * 0.2  # Interpolate 0.2 → 0.4

    if score < 0.65:
        # Clear BUY - normal position
        t = (score - 0.58) / 0.07
        return 0.4 + t * 0.6  # Interpolate 0.4 → 1.0

    if score < 0.80:
        # Strong BUY - confident
        t = (score - 0.65) / 0.15
        return 1.0 + t * 0.5  # Interpolate 1.0 → 1.5

    # Very strong BUY - max conviction (cap at 1.5x)
    return 1.5


def compute_position_size_with_conviction(
    base_size: float,
    composite_score: float,
    regime_factor: float = 1.0,
    vol_scalar: float = 0.5,
) -> float:
    """
    Calculate final position size combining:
    - Base volatility-adjusted size
    - Signal conviction (composite_score distance from neutral)
    - Market regime factor (VIX-based)
    - Volatility state (GARCH scalar)

    Example:
    - base_size=$1000, composite=0.70, regime=0.8, vol_scalar=0.5
    - conviction_mult = 1.2 (strong signal)
    - vol_mult = 0.75 + 0.5*0.5 = 1.0
    - final = $1000 * 1.2 * 0.8 * 1.0 = $960
    """
    conviction_mult = compute_conviction_multiplier(composite_score)
    vol_mult = 0.75 + 0.50 * vol_scalar  # 0.75-1.25 range

    final_size = base_size * conviction_mult * regime_factor * vol_mult
    return round(final_size, 2)
