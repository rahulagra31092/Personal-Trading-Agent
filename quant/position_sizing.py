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
    return round(max(total_capital * short_pct, min(total_capital * max_pct,
                                                     total_capital * short_pct)))
