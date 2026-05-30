def compute_trade_setup(current_price: float, atr_stop: float) -> dict:
    """Return entry, stop, target, and risk metrics assuming a fixed 3:1 reward/risk ratio."""
    entry = round(current_price, 2)
    risk = round(max(current_price - atr_stop, 0.01), 2)
    reward = round(3.0 * risk, 2)
    return {
        "entry_price": entry,
        "stop_loss": round(atr_stop, 2),
        "take_profit": round(entry + reward, 2),
        "risk_per_share": risk,
        "reward_per_share": reward,
        "risk_reward_ratio": round(reward / risk, 2),
    }
