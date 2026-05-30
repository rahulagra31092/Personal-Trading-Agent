def compute_trade_setup(current_price: float, atr_stop: float) -> dict:
    risk = max(current_price - atr_stop, 0.01)
    reward = 3.0 * risk
    return {
        "entry_price": round(current_price, 2),
        "stop_loss": round(atr_stop, 2),
        "take_profit": round(current_price + reward, 2),
        "risk_per_share": round(risk, 2),
        "reward_per_share": round(reward, 2),
        "risk_reward_ratio": round(reward / risk, 2),
    }
