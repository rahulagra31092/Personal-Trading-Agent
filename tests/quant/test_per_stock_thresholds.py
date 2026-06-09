"""Tests for per-stock entry thresholds."""
import pytest
from quant.per_stock_thresholds import (
    get_entry_threshold,
    get_all_thresholds,
    get_thresholds_by_value,
    PER_STOCK_THRESHOLDS,
)
from quant.signals import compute_signal


class TestPerStockThresholds:
    """Test per-stock threshold configuration."""

    def test_msft_has_0_70_threshold(self):
        """MSFT uses 0.70 threshold (mean-reversion correction)."""
        assert get_entry_threshold("MSFT") == 0.70

    def test_meta_has_0_70_threshold(self):
        """META uses 0.70 threshold (mean-reversion correction)."""
        assert get_entry_threshold("META") == 0.70

    def test_aapl_has_0_65_threshold(self):
        """AAPL uses 0.65 threshold (trend-follower baseline)."""
        assert get_entry_threshold("AAPL") == 0.65

    def test_nvda_has_0_65_threshold(self):
        """NVDA uses 0.65 threshold (trend-follower baseline)."""
        assert get_entry_threshold("NVDA") == 0.65

    def test_amzn_has_0_60_threshold(self):
        """AMZN uses 0.60 threshold (high-volatility name)."""
        assert get_entry_threshold("AMZN") == 0.60

    def test_case_insensitive_lookup(self):
        """Ticker lookup is case-insensitive."""
        assert get_entry_threshold("msft") == 0.70
        assert get_entry_threshold("MSFT") == 0.70
        assert get_entry_threshold("MsFt") == 0.70

    def test_unknown_ticker_uses_default(self):
        """Unknown tickers use 0.65 default."""
        assert get_entry_threshold("UNKNOWN") == 0.65
        assert get_entry_threshold("FAKE") == 0.65

    def test_custom_default_threshold(self):
        """Can override default threshold."""
        assert get_entry_threshold("UNKNOWN", default_threshold=0.60) == 0.60

    def test_get_all_thresholds_returns_dict(self):
        """get_all_thresholds returns a copy of the config."""
        thresholds = get_all_thresholds()
        assert isinstance(thresholds, dict)
        assert "MSFT" in thresholds
        assert thresholds["MSFT"] == 0.70

    def test_get_all_thresholds_is_copy(self):
        """get_all_thresholds returns a copy, not reference."""
        thresholds = get_all_thresholds()
        thresholds["FAKE"] = 0.99
        # Original should not be modified
        assert get_all_thresholds().get("FAKE") is None

    def test_get_thresholds_by_value_0_70(self):
        """Get all stocks using 0.70 threshold."""
        stocks_0_70 = get_thresholds_by_value(0.70)
        assert "MSFT" in stocks_0_70
        assert "META" in stocks_0_70
        assert "AAPL" not in stocks_0_70

    def test_get_thresholds_by_value_0_65(self):
        """Get all stocks using 0.65 threshold."""
        stocks_0_65 = get_thresholds_by_value(0.65)
        assert "AAPL" in stocks_0_65
        assert "NVDA" in stocks_0_65
        assert len(stocks_0_65) >= 5

    def test_get_thresholds_by_value_0_60(self):
        """Get all stocks using 0.60 threshold."""
        stocks_0_60 = get_thresholds_by_value(0.60)
        assert "AMZN" in stocks_0_60
        assert "TSLA" in stocks_0_60
        assert len(stocks_0_60) >= 3

    def test_all_thresholds_are_reasonable(self):
        """All thresholds should be between 0.5 and 0.8."""
        thresholds = get_all_thresholds()
        for ticker, threshold in thresholds.items():
            assert 0.5 <= threshold <= 0.8, f"{ticker} threshold {threshold} out of range"


class TestSignalWithPerStockThreshold:
    """Test signal computation with per-stock thresholds."""

    def test_signal_msft_at_0_68_is_watch_with_per_stock(self):
        """MSFT at 0.68 is WATCH (needs 0.70 for BUY)."""
        sig = compute_signal(
            technical_score=0.70,
            momentum_score=0.68,
            quality_score=0.65,
            insider_trades_score=0.60,
            estimate_revisions_score=0.60,
            earnings_score=0.68,
            ticker="MSFT",
        )
        # Composite ≈ 0.66, which is > 0.65 but NOT > 0.70 (MSFT threshold)
        # Expected: WATCH
        assert sig["label"] == "WATCH"
        assert sig["composite_score"] > 0.65

    def test_signal_msft_at_0_72_is_buy_with_per_stock(self):
        """MSFT at 0.72 is BUY (exceeds 0.70 threshold)."""
        sig = compute_signal(
            technical_score=0.75,
            momentum_score=0.72,
            quality_score=0.70,
            insider_trades_score=0.70,
            estimate_revisions_score=0.70,
            earnings_score=0.74,
            ticker="MSFT",
        )
        # Composite ≈ 0.72, which is > 0.70 (MSFT threshold)
        assert sig["label"] == "BUY"
        assert sig["composite_score"] >= 0.70

    def test_signal_aapl_at_0_67_is_buy_with_per_stock(self):
        """AAPL at 0.67 is BUY (exceeds 0.65 threshold)."""
        sig = compute_signal(
            technical_score=0.68,
            momentum_score=0.67,
            quality_score=0.66,
            insider_trades_score=0.66,
            estimate_revisions_score=0.66,
            earnings_score=0.68,
            ticker="AAPL",
        )
        # Composite ≈ 0.67, which is > 0.65 (AAPL threshold)
        assert sig["label"] == "BUY"

    def test_signal_amzn_at_0_61_is_buy_with_per_stock(self):
        """AMZN at 0.61 is BUY (exceeds 0.60 threshold)."""
        sig = compute_signal(
            technical_score=0.62,
            momentum_score=0.61,
            quality_score=0.60,
            insider_trades_score=0.60,
            estimate_revisions_score=0.60,
            earnings_score=0.62,
            ticker="AMZN",
        )
        # Composite ≈ 0.61, which is > 0.60 (AMZN threshold)
        assert sig["label"] == "BUY"

    def test_signal_with_explicit_threshold_override(self):
        """Explicit buy_threshold parameter overrides per-stock lookup."""
        sig = compute_signal(
            technical_score=0.65,
            momentum_score=0.65,
            quality_score=0.65,
            insider_trades_score=0.65,
            estimate_revisions_score=0.65,
            earnings_score=0.65,
            ticker="MSFT",  # Would normally use 0.70
            buy_threshold=0.60,  # Override to 0.60
        )
        # Composite ≈ 0.65, which is > 0.60 (explicit override)
        assert sig["label"] == "BUY"

    def test_signal_backward_compatible_without_ticker(self):
        """Signal computation still works without ticker (backward compat)."""
        sig = compute_signal(
            technical_score=0.67,
            momentum_score=0.67,
            quality_score=0.67,
            insider_trades_score=0.67,
            estimate_revisions_score=0.67,
            earnings_score=0.67,
        )
        # Should use default 0.65 threshold (no ticker provided)
        # Composite ≈ 0.67 > 0.65 → BUY
        assert sig["label"] == "BUY"

    def test_signal_unknown_ticker_uses_default(self):
        """Unknown ticker uses default 0.65 threshold."""
        sig = compute_signal(
            technical_score=0.67,
            momentum_score=0.67,
            quality_score=0.67,
            insider_trades_score=0.67,
            estimate_revisions_score=0.67,
            earnings_score=0.67,
            ticker="UNKNOWN",
        )
        # Composite ≈ 0.67 > 0.65 (default) → BUY
        assert sig["label"] == "BUY"

    def test_signal_msft_improvement_from_0_65_to_0_70(self):
        """
        Demonstrate MSFT improvement: at 0.68 composite,
        old 0.65 threshold gives BUY (false entry),
        new 0.70 threshold gives WATCH (correct).
        """
        # At 0.68 composite
        sig_old = compute_signal(
            technical_score=0.70,
            momentum_score=0.68,
            quality_score=0.66,
            insider_trades_score=0.65,
            estimate_revisions_score=0.65,
            earnings_score=0.68,
            buy_threshold=0.65,  # Old threshold
        )
        sig_new = compute_signal(
            technical_score=0.70,
            momentum_score=0.68,
            quality_score=0.66,
            insider_trades_score=0.65,
            estimate_revisions_score=0.65,
            earnings_score=0.68,
            ticker="MSFT",  # New per-stock (0.70)
        )
        assert sig_old["label"] == "BUY"  # False entry at old threshold
        assert sig_new["label"] == "WATCH"  # Correctly rejected at new threshold
        assert sig_old["composite_score"] == sig_new["composite_score"]  # Same composite


class TestThresholdConfiguration:
    """Test that configuration matches backtest analysis."""

    def test_trend_followers_use_0_65(self):
        """AAPL, NVDA, GOOGL, V, JNJ use 0.65 (trend-followers)."""
        trend_followers = ["AAPL", "NVDA", "GOOGL", "V", "JNJ"]
        for ticker in trend_followers:
            assert get_entry_threshold(ticker) == 0.65, f"{ticker} should use 0.65"

    def test_mean_reversion_traps_use_0_70(self):
        """MSFT, META use 0.70 (mean-reversion correction)."""
        mean_reversions = ["MSFT", "META"]
        for ticker in mean_reversions:
            assert get_entry_threshold(ticker) == 0.70, f"{ticker} should use 0.70"

    def test_high_volatility_use_0_60(self):
        """AMZN, TSLA, and other high-vol names use 0.60."""
        high_vol = ["AMZN", "TSLA"]
        for ticker in high_vol:
            assert get_entry_threshold(ticker) == 0.60, f"{ticker} should use 0.60"

    def test_no_threshold_below_0_55(self):
        """No thresholds below 0.55 (maintains entry quality)."""
        thresholds = get_all_thresholds()
        for ticker, threshold in thresholds.items():
            assert threshold >= 0.55, f"{ticker} threshold {threshold} too low"

    def test_no_threshold_above_0_75(self):
        """No thresholds above 0.75 (avoids too-conservative gate)."""
        thresholds = get_all_thresholds()
        for ticker, threshold in thresholds.items():
            assert threshold <= 0.75, f"{ticker} threshold {threshold} too high"
