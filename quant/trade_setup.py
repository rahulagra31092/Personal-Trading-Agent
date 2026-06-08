from quant.conviction_sizing import compute_conviction_multiplier


def compute_trade_setup(current_price: float, atr_stop: float, composite_score: float = 0.5, regime_factor: float = 1.0, vol_scalar: float = 0.5) -> dict:
    """
    Return entry, stop, target, and size metrics using conviction-based position sizing.

    Args:
        current_price: Entry price
        atr_stop: ATR-based stop loss price
        composite_score: Signal composite [0, 1]. Used to scale position size.
        regime_factor: Market regime multiplier (VIX-based, from 0.5 to 1.0)
        vol_scalar: GARCH volatility state (from 0.2 to 0.8)

    Position size formula:
    - Base: 1.0 (100% standard position)
    - Conviction: multiplier from 0.2x (weak signal) to 1.5x (strong signal)
    - Regime: 0.5x-1.0x based on VIX
    - Volatility: 0.75x-1.25x based on realized volatility
    """
    entry = round(current_price, 2)
    risk = round(max(current_price - atr_stop, 0.01), 2)
    reward = round(3.0 * risk, 2)

    # Conviction-based sizing
    conviction_mult = compute_conviction_multiplier(composite_score)
    vol_mult = 0.75 + 0.50 * vol_scalar
    size_factor = conviction_mult * regime_factor * vol_mult

    return {
        "entry_price": entry,
        "stop_loss": round(atr_stop, 2),
        "take_profit": round(entry + reward, 2),
        "risk_per_share": risk,
        "reward_per_share": reward,
        "risk_reward_ratio": round(reward / risk, 2),
        "size_factor": round(size_factor, 4),  # Position size multiplier
        "conviction_mult": round(conviction_mult, 4),  # Debugging visibility
    }
