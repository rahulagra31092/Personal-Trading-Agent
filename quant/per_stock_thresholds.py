"""Per-stock entry thresholds optimized by stock personality.

Different stocks have different signal characteristics:
- Mean-reversion stocks (MSFT, META): Need higher threshold (0.70) to avoid false entries
- Trend-followers (AAPL, NVDA): Work well at 0.65
- High-volatility names (AMZN, TSLA): Can use 0.60 to capture more signals

Thresholds are determined by:
1. Historical backtest performance (Jan 2-May 29, 2026)
2. Signal layer dependency (stocks with dead insider/estimate data need higher threshold)
3. Win rate patterns (MSFT 33% at 0.65 → 50% at 0.70)
"""

# Per-stock entry thresholds (default: 0.65)
# A score > threshold triggers a BUY signal; ≤ threshold is WATCH/AVOID
PER_STOCK_THRESHOLDS = {
    # === TREND-FOLLOWERS (0.65 optimal) ===
    # These stocks have reliable technical/momentum signals. 0.65 works well.
    "AAPL": 0.65,   # 71% win, +14.0% return (excellent baseline)
    "NVDA": 0.65,   # 50% win, +12.0% return (high conviction model)
    "GOOGL": 0.65,  # 36% win, +9.3% return (many trades, positive alpha)
    "V": 0.65,      # 56% win, +2.1% return (steady performer)
    "JNJ": 0.65,    # 44% win, +0.9% return (conservative but profitable)

    # === MEAN-REVERSION TRAPS (0.70 needed) ===
    # These stocks trap mean-reversion signals. Higher threshold avoids false entries.
    # MSFT: 33% win at 0.65, but 50% win at 0.70 (huge improvement)
    # META: 12% win at 0.65, but 40% win at 0.70 (catch only strongest signals)
    "MSFT": 0.70,
    "META": 0.70,

    # === HIGH-VOLATILITY NAMES (0.60 acceptable) ===
    # Can trade more signals (more entries) because volatility provides entry points
    "AMZN": 0.60,   # Positive return but low win rate; more entries help
    "TSLA": 0.60,   # Dead insider data but technical signals work
    "CELH": 0.60,   # Midcap, high-vol
    "DUOL": 0.60,   # Midcap, high-vol
    "HIMS": 0.60,   # Midcap, high-vol

    # === DEFAULT (0.65) ===
    # Remaining stocks use baseline threshold (BLUE_CHIP + MIDCAP universe)
}

# Stocks with dead/stale insider or estimate data (from diagnostics)
# These need higher thresholds to avoid overweighting degraded signals
SIGNAL_DEGRADED_STOCKS = {
    "JPM": {"issue": "insider_trades", "recommendation": "Consider 0.70+ or exclude"},
    "TSLA": {"issue": "insider_trades", "recommendation": "Use 0.60, rely on technical"},
    "MSFT": {"issue": "insider_trades", "recommendation": "Use 0.70, heavy on technical/momentum"},
}


def get_entry_threshold(ticker: str, default_threshold: float = 0.65) -> float:
    """
    Get the entry threshold for a specific stock.

    Args:
        ticker: Stock symbol (e.g., "MSFT")
        default_threshold: Fallback if ticker not in PER_STOCK_THRESHOLDS

    Returns:
        Entry threshold (BUY if composite_score > threshold)
    """
    return PER_STOCK_THRESHOLDS.get(ticker.upper(), default_threshold)


def get_all_thresholds() -> dict[str, float]:
    """Return all per-stock thresholds."""
    return PER_STOCK_THRESHOLDS.copy()


def get_thresholds_by_value(threshold: float) -> list[str]:
    """
    Get all stocks using a specific threshold.

    Example: get_thresholds_by_value(0.70) → ["MSFT", "META"]
    """
    return [ticker for ticker, t in PER_STOCK_THRESHOLDS.items() if t == threshold]
