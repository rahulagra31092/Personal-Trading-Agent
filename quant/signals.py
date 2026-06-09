import config
from quant.per_stock_thresholds import get_entry_threshold


def compute_signal(
    technical_score: float,
    momentum_score: float = 0.5,
    quality_score: float = 0.5,
    insider_trades_score: float = 0.5,
    estimate_revisions_score: float = 0.5,
    earnings_score: float = 0.5,
    weights: dict[str, float] | None = None,
    ticker: str | None = None,
    buy_threshold: float | None = None,
) -> dict:
    """
    Compute signal with optional per-stock threshold.

    Args:
        ticker: Stock symbol for per-stock threshold lookup (e.g., "MSFT")
        buy_threshold: Override threshold (if not None, use this instead of per-stock)
    """
    w = weights if weights is not None else config.SIGNAL_WEIGHTS
    composite = round(
        w["technical"] * technical_score
        + w["momentum"] * momentum_score
        + w["quality"] * quality_score
        + w["insider_trades"] * insider_trades_score
        + w["estimate_revisions"] * estimate_revisions_score
        + w["earnings"] * earnings_score,
        4,
    )

    # Interaction gate: quality < 0.35 with high composite = momentum trap.
    # Cap below BUY threshold to force WATCH.
    if quality_score < 0.35 and composite > 0.57:
        composite = 0.57

    # Determine entry threshold
    if buy_threshold is not None:
        # Explicit override (for testing)
        threshold = buy_threshold
    elif ticker:
        # Use per-stock threshold
        threshold = get_entry_threshold(ticker)
    else:
        # Default (backward compatible)
        threshold = 0.65

    label = "BUY" if composite > threshold else ("AVOID" if composite < 0.42 else "WATCH")

    return {
        "composite_score": composite,
        "label": label,
        "layer_scores": {
            "technical": technical_score,
            "momentum": momentum_score,
            "quality": quality_score,
            "insider_trades": insider_trades_score,
            "estimate_revisions": estimate_revisions_score,
            "earnings": earnings_score,
        },
    }
