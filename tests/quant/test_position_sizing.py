import pytest
from quant.position_sizing import compute_position_size, compute_short_position_size


CAPITAL = 100_000


def test_normal_vol_gives_base_size():
    # 2% daily vol (= reference_vol) → vol_scale = 1.0 → base = 100K/70 ≈ $1,429
    size = compute_position_size(daily_vol=0.02, total_capital=CAPITAL, n_positions=70)
    expected_base = CAPITAL / 70
    assert abs(size - expected_base) < 50  # within $50 of exact


def test_high_vol_gives_smaller_position():
    low_vol_size = compute_position_size(0.01, CAPITAL, 70)
    high_vol_size = compute_position_size(0.04, CAPITAL, 70)
    assert high_vol_size < low_vol_size


def test_low_vol_gives_larger_position():
    normal_size = compute_position_size(0.02, CAPITAL, 70)
    low_vol_size = compute_position_size(0.01, CAPITAL, 70)
    assert low_vol_size > normal_size


def test_size_bounded_by_max_pct():
    # Extremely low vol would give massive size → capped at 3%
    size = compute_position_size(0.001, CAPITAL, 70)
    assert size <= CAPITAL * 0.03


def test_size_bounded_by_min_pct():
    # Extremely high vol → capped at 0.5%
    size = compute_position_size(10.0, CAPITAL, 70)
    assert size >= CAPITAL * 0.005


def test_position_factor_scales_size():
    full_size = compute_position_size(0.02, CAPITAL, 70, position_factor=1.0)
    reduced_size = compute_position_size(0.02, CAPITAL, 70, position_factor=0.70)
    assert reduced_size < full_size
    assert abs(reduced_size / full_size - 0.70) < 0.05


def test_zero_vol_uses_reference_vol():
    # Daily vol = 0 → should not crash → uses reference vol = 0.02
    size_zero = compute_position_size(0.0, CAPITAL, 70)
    size_ref = compute_position_size(0.02, CAPITAL, 70)
    assert abs(size_zero - size_ref) < 50


def test_short_position_size_smaller_than_long():
    long_size = compute_position_size(0.02, CAPITAL, 70)
    short_size = compute_short_position_size(CAPITAL)
    assert short_size < long_size


def test_short_position_size_bounded():
    short_size = compute_short_position_size(CAPITAL)
    assert CAPITAL * 0.005 <= short_size <= CAPITAL * 0.01
