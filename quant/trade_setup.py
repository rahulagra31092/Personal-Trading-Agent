def compute_trade_setup(current_price: float, atr_stop: float, prob_success: float = 0.5) -> dict:
    """
    Return entry, stop, target, and risk metrics with position confidence weighting.

    Position sizing formula:
    - base_size = 1.0 (100% position)
    - size_factor = (prob_success - 0.50) / 0.50
      - 52% win → size_factor = 0.04 (4% position)
      - 60% win → size_factor = 0.20 (20% position)
      - 70% win → size_factor = 0.40 (40% position)
      - 80% win → size_factor = 0.60 (60% position)

    This is then combined with VIX-based regime factor in api/analyze.py.

    Args:
        current_price: Entry price
        atr_stop: ATR-based stop loss price
        prob_success: Monte Carlo probability of success [0, 1]. Default 0.5 (no weighting)

    Returns:
        dict with entry, stop, target, risk metrics, and size_factor
    """
    entry = round(current_price, 2)
    risk = round(max(current_price - atr_stop, 0.01), 2)
    reward = round(3.0 * risk, 2)

    # Confidence-based position sizing
    # Only increase size if win probability > 50% (coin flip)
    size_factor = max(0.0, (prob_success - 0.50) / 0.50)

    return {
        "entry_price": entry,
        "stop_loss": round(atr_stop, 2),
        "take_profit": round(entry + reward, 2),
        "risk_per_share": risk,
        "reward_per_share": reward,
        "risk_reward_ratio": round(reward / risk, 2),
        "size_factor": round(size_factor, 4),  # Position size confidence adjustment
    }
