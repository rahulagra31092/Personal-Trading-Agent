_REFERENCE_VOL = 0.02  # 2% daily vol baseline


def compute_position_size(
    daily_vol: float,
    total_capital: float,
    n_positions: int,
    position_factor: float = 1.0,
    min_pct: float = 0.005,
    max_pct: float = 0.03,
) -> float:
    """Volatility-targeted position size in dollars, clamped to [min_pct, max_pct] of capital."""
    effective_vol = daily_vol if daily_vol > 0 else _REFERENCE_VOL
    vol_scale = max(0.5, min(2.0, _REFERENCE_VOL / effective_vol))
    base = (total_capital / n_positions) * vol_scale * position_factor
    return round(max(total_capital * min_pct, min(total_capital * max_pct, base)))


def compute_short_position_size(
    total_capital: float,
    short_pct: float = 0.005,
    max_pct: float = 0.01,
) -> float:
    """Short position size in dollars, smaller than longs to cap upside risk."""
    return round(min(total_capital * max_pct, total_capital * short_pct))


def compute_conviction_position_size(
    base_size: float,
    composite_score: float,
    regime_factor: float = 1.0,
    garch_vol_scalar: float = 0.5,
    total_capital: float = 10_000.0,
    max_capital_pct: float = 0.08,
) -> float:
    """
    Conviction-adjusted position size in dollars.

    conviction_mult:
      composite >= 0.75 → 1.40×  (high conviction)
      composite >= 0.65 → 1.00×  (moderate conviction)
      composite <  0.65 → 0.65×  (entry-level conviction)

    vol_mult: 0.75 + 0.50 * garch_vol_scalar
      scalar=0.2 (high vol) → 0.85×; scalar=0.5 → 1.00×; scalar=0.8 (low vol) → 1.15×

    Hard cap: min(size, total_capital * max_capital_pct)
    """
    if composite_score >= 0.75:
        conviction_mult = 1.40
    elif composite_score >= 0.65:
        conviction_mult = 1.00
    else:
        conviction_mult = 0.65

    vol_mult = 0.75 + 0.50 * garch_vol_scalar
    size = base_size * conviction_mult * regime_factor * vol_mult
    max_size = total_capital * max_capital_pct
    return round(min(size, max_size))
