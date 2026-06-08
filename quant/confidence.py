"""
DEPRECATED: Monte Carlo confidence removed.

Previous implementation (zero-drift GBM) always returned ~50% prob_success.
This was a coin flip and provided zero signal for position sizing.

Position sizing now uses signal conviction (composite_score distance from threshold)
instead. See quant/conviction_sizing.py for details.

Keeping this module for backwards compatibility but run_monte_carlo() now
returns a warning and dummy data.
"""
import logging

logger = logging.getLogger(__name__)


def run_monte_carlo(
    current_price: float,
    daily_vol: float,
    days: int = 5,
    simulations: int = 1_000,
    seed: int | None = None,
) -> dict:
    """
    DEPRECATED: Use quant/conviction_sizing.py instead.

    This function is kept for backwards compatibility but no longer used
    in position sizing. The previous implementation used zero-drift GBM
    which always returned ~50% prob_success (a coin flip with no signal).

    Now returns dummy values. Position sizing uses signal conviction instead.
    """
    logger.warning(
        "run_monte_carlo() called but is deprecated. "
        "Position sizing now uses signal conviction from quant/conviction_sizing.py"
    )

    # Dummy return for backwards compatibility
    return {
        "base_target": round(current_price * 1.01, 2),
        "lower_80": round(current_price * 0.98, 2),
        "upper_80": round(current_price * 1.04, 2),
        "downside_pct": -0.02,
        "upside_pct": 0.04,
        "prob_success": 0.5,  # Dummy coin flip
        "daily_vol_expected": round(daily_vol, 6),
    }
