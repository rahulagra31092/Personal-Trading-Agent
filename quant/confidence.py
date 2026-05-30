import numpy as np


def run_monte_carlo(
    current_price: float,
    daily_vol: float,
    days: int = 5,
    simulations: int = 1_000,
    seed: int | None = None,
) -> dict:
    if daily_vol <= 0:
        raise ValueError(f"daily_vol must be positive, got {daily_vol}")
    rng = np.random.default_rng(seed)
    # GBM with zero drift: log-returns ~ N(0, daily_vol)
    log_returns = rng.normal(0.0, daily_vol, size=(simulations, days))
    final_prices = current_price * np.exp(np.cumsum(log_returns, axis=1)[:, -1])

    base_target = float(np.median(final_prices))
    lower_80 = float(np.percentile(final_prices, 10))
    upper_80 = float(np.percentile(final_prices, 90))
    prob_success = float(np.mean(final_prices > current_price))

    return {
        "base_target": round(base_target, 2),
        "lower_80": round(lower_80, 2),
        "upper_80": round(upper_80, 2),
        "downside_pct": round((lower_80 - current_price) / current_price, 4),
        "upside_pct": round((upper_80 - current_price) / current_price, 4),
        "prob_success": round(prob_success, 4),
        "daily_vol_expected": round(daily_vol, 6),
    }
