"""
Test cases for data resilience fixes.
Add these to the appropriate test files during Phase 1 implementation.

Run with: pytest tests/test_resilience.py -v
"""

import pytest
from unittest.mock import patch, MagicMock
import time


# ============================================================================
# FIX 1: Polygon → yfinance Fallback Tests
# ============================================================================

class TestPolygonFallback:
    """Tests for data/market.py fallback logic."""

    FAKE_BARS = [
        {"t": 1717200000000, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 1_000_000},
        {"t": 1717286400000, "o": 100.5, "h": 102.0, "l": 100.0, "c": 101.0, "v": 1_100_000},
    ]

    def test_polygon_primary_succeeds(self):
        """Verify Polygon is used when available."""
        with patch("data.market._fetch_bars_polygon", return_value=self.FAKE_BARS) as mock_poly, \
             patch("data.market._fetch_bars_yfinance") as mock_yf:

            from data.market import get_daily_bars
            bars = get_daily_bars("AAPL", days=2)

            assert mock_poly.called
            assert not mock_yf.called
            assert len(bars) == 2

    def test_polygon_timeout_triggers_yfinance_fallback(self):
        """Verify yfinance fallback when Polygon times out."""
        with patch("data.market._fetch_bars_polygon", side_effect=TimeoutError("timeout")), \
             patch("data.market._fetch_bars_yfinance", return_value=self.FAKE_BARS) as mock_yf:

            from data.market import get_daily_bars
            bars = get_daily_bars("AAPL", days=2)

            assert mock_yf.called
            assert len(bars) == 2

    def test_polygon_connection_error_triggers_yfinance_fallback(self):
        """Verify yfinance fallback on connection error."""
        from requests.exceptions import ConnectionError

        with patch("data.market._fetch_bars_polygon", side_effect=ConnectionError("failed")), \
             patch("data.market._fetch_bars_yfinance", return_value=self.FAKE_BARS) as mock_yf:

            from data.market import get_daily_bars
            bars = get_daily_bars("AAPL", days=2)

            assert mock_yf.called
            assert len(bars) == 2

    def test_both_sources_fail_raises_error(self):
        """Verify proper error when all sources fail."""
        with patch("data.market._fetch_bars_polygon", side_effect=Exception("failed")), \
             patch("data.market._fetch_bars_yfinance", side_effect=Exception("failed")):

            from data.market import get_daily_bars

            with pytest.raises(ValueError, match="No bars available"):
                get_daily_bars("AAPL", days=2)

    def test_cache_used_before_fallback_logic(self):
        """Verify cached data doesn't trigger fallback."""
        from data.cache import set_cache

        set_cache("bars:AAPL:2", self.FAKE_BARS, ttl_seconds=3600)

        with patch("data.market._fetch_bars_polygon") as mock_poly, \
             patch("data.market._fetch_bars_yfinance") as mock_yf:

            from data.market import get_daily_bars
            bars = get_daily_bars("AAPL", days=2)

            assert not mock_poly.called
            assert not mock_yf.called
            assert len(bars) == 2


# ============================================================================
# FIX 2: yfinance Timeout Enforcement Tests
# ============================================================================

class TestYfinanceTimeout:
    """Tests for util/timeout.py wrapper."""

    def test_timeout_fires_on_long_operation(self):
        """Verify timeout stops hanging operations."""
        from util.timeout import call_with_timeout, TimeoutError

        def slow_fn():
            time.sleep(20)  # Slower than timeout
            return {"data": "result"}

        with pytest.raises(TimeoutError, match="exceeded 5s timeout"):
            call_with_timeout(slow_fn, timeout_seconds=5, component_name="slow_test")

    def test_timeout_completes_fast_operation(self):
        """Verify timeout allows fast operations through."""
        from util.timeout import call_with_timeout

        def fast_fn():
            return {"data": "result"}

        result = call_with_timeout(fast_fn, timeout_seconds=15, component_name="fast_test")
        assert result["data"] == "result"

    def test_momentum_score_uses_timeout(self):
        """Verify momentum scorer uses timeout wrapper."""
        from quant.momentum import compute_momentum_score

        with patch("quant.momentum.call_with_timeout") as mock_timeout:
            mock_timeout.return_value = [100.0, 101.0, 102.0]  # Fake closes

            # This test assumes compute_momentum_score calls call_with_timeout
            # (after implementation)
            # score = compute_momentum_score("AAPL")
            # assert mock_timeout.called
            # assert mock_timeout.call_args[1]["timeout_seconds"] == 15
            pass  # Placeholder

    def test_quality_score_uses_timeout(self):
        """Verify quality scorer uses timeout wrapper."""
        from quant.quality import compute_quality_score

        with patch("quant.quality.call_with_timeout") as mock_timeout:
            mock_timeout.return_value = 0.75  # Fake quality score

            # score = compute_quality_score("AAPL")
            # assert mock_timeout.called
            pass  # Placeholder


# ============================================================================
# FIX 3: Congress Trades Fallback Tests
# ============================================================================

class TestCongressTradesFallback:
    """Tests for smart_money/congress.py fallback logic."""

    FAKE_TRADES_QUIVER = [
        {
            "Date": "2026-06-01",
            "Representative": "John Smith",
            "Transaction": "Purchase",
            "Range": "$50,001-$100,000"
        }
    ]

    FAKE_TRADES_EDGAR = [
        {
            "Date": "2026-05-30",
            "Representative": "Jane Doe",
            "Transaction": "Sale",
            "Range": "$100,001-$250,000"
        }
    ]

    def test_quiver_primary_succeeds(self):
        """Verify Quiver is used when available."""
        with patch("smart_money.congress._fetch_congress_trades_quiver", return_value=self.FAKE_TRADES_QUIVER) as mock_quiver, \
             patch("smart_money.congress._fetch_congress_trades_edgar") as mock_edgar:

            from smart_money.congress import get_congress_trades
            trades = get_congress_trades("AAPL")

            assert mock_quiver.called
            assert not mock_edgar.called
            assert len(trades) == 1

    def test_quiver_failure_triggers_edgar_fallback(self):
        """Verify EDGAR fallback when Quiver fails."""
        with patch("smart_money.congress._fetch_congress_trades_quiver", return_value=[]), \
             patch("smart_money.congress._fetch_congress_trades_edgar", return_value=self.FAKE_TRADES_EDGAR) as mock_edgar:

            from smart_money.congress import get_congress_trades
            trades = get_congress_trades("AAPL")

            assert mock_edgar.called
            assert len(trades) == 1

    def test_both_sources_fail_returns_empty(self):
        """Verify graceful degradation when all sources fail."""
        with patch("smart_money.congress._fetch_congress_trades_quiver", return_value=[]), \
             patch("smart_money.congress._fetch_congress_trades_edgar", return_value=[]):

            from smart_money.congress import get_congress_trades
            trades = get_congress_trades("AAPL")

            assert trades == []

    def test_congress_score_neutral_when_trades_unavailable(self):
        """Verify score defaults to 0.5 (neutral) when trades unavailable."""
        with patch("smart_money.congress.get_congress_trades", return_value=[]):

            from smart_money.congress import compute_congress_score
            score = compute_congress_score("AAPL")

            assert score == 0.5


# ============================================================================
# FIX 4: Earnings Cache TTL Reduction Tests
# ============================================================================

class TestEarningsCacheTTL:
    """Tests for data/earnings.py cache TTL and staleness."""

    def test_earnings_cache_ttl_is_6_hours(self):
        """Verify earnings cache uses 6-hour TTL (not 24h)."""
        from data.earnings import get_earnings_calendar

        with patch("data.earnings.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.info = {"forwardEps": 4.50}
            mock_ticker.return_value.earnings_history = None
            mock_ticker.return_value.calendar = None

            with patch("data.cache.set_cache") as mock_cache:
                get_earnings_calendar("AAPL")

                # Verify TTL is 21600 (6 hours), not 86400 (24 hours)
                mock_cache.assert_called_once()
                call_args = mock_cache.call_args
                assert call_args[1]["ttl_seconds"] == 21600

    def test_stale_earnings_date_is_detected(self):
        """Verify cached earnings data marked as stale if >3h old."""
        from data.earnings import _is_earnings_data_stale

        # Cached 4 hours ago
        stale_cache = {
            "_fetched_at": time.time() - 14400,  # 4 hours ago
            "next_earnings_date": "2026-06-10"
        }

        assert _is_earnings_data_stale(stale_cache) is True

    def test_fresh_earnings_date_not_marked_stale(self):
        """Verify recently cached earnings data not marked stale."""
        from data.earnings import _is_earnings_data_stale

        # Cached 2 hours ago
        fresh_cache = {
            "_fetched_at": time.time() - 7200,  # 2 hours ago
            "next_earnings_date": "2026-06-10"
        }

        assert _is_earnings_data_stale(fresh_cache) is False


# ============================================================================
# FIX 5: Staleness Monitoring Foundation Tests
# ============================================================================

class TestStalenessMonitoring:
    """Tests for data/cache.py staleness tracking."""

    def test_cache_entry_tracks_data_published_at(self):
        """Verify CacheEntry tracks when data was published."""
        from data.cache import CacheEntry

        now = time.time()
        entry = CacheEntry(
            key="test:key",
            value={"data": "value"},
            cached_at=now,
            expires_at=now + 3600,
            data_published_at=now - 1800,  # Data is 30 min old
        )

        assert entry.age_seconds >= 1799
        assert entry.age_seconds <= 1801

    def test_get_cache_with_age_returns_tuple(self):
        """Verify get_cache_with_age returns (value, age_seconds)."""
        from data.cache import set_cache, get_cache_with_age

        set_cache("test:key", {"data": "value"}, ttl_seconds=3600)

        value, age = get_cache_with_age("test:key")
        assert value == {"data": "value"}
        assert age is not None
        assert age <= 1  # Should be ~0 seconds

    def test_max_age_exceeded_returns_none(self):
        """Verify cache returns None if data exceeds max age."""
        from data.cache import CacheEntry

        # Create entry with data 10 hours old
        old_time = time.time() - 36000
        entry = CacheEntry(
            key="test:key",
            value={"data": "value"},
            cached_at=old_time,
            expires_at=time.time() + 3600,
            data_published_at=old_time,
        )

        # Max age is 6 hours (21600 seconds)
        assert entry.is_stale(21600) is True

    def test_get_cache_staleness_report_works(self):
        """Verify staleness reporting function."""
        from data.cache import set_cache, get_cache_staleness_report

        set_cache("bars:AAPL:30", {"data": "bars"}, ttl_seconds=3600)
        set_cache("news:AAPL:3", {"data": "articles"}, ttl_seconds=3600)

        report = get_cache_staleness_report()

        assert "bars:AAPL:30" in report
        assert "news:AAPL:3" in report
        assert report["bars:AAPL:30"]["age_seconds"] <= 1
        assert report["bars:AAPL:30"]["max_age_seconds"] == 14400


# ============================================================================
# FIX 6: Data Quality Metadata Tests
# ============================================================================

class TestDataQualityMetadata:
    """Tests for api/analyze.py data quality reporting."""

    def test_analyze_response_includes_data_quality(self):
        """Verify /analyze response includes data_quality."""
        from api.analyze import analyze_ticker

        with patch("api.analyze.get_daily_bars") as mock_bars, \
             patch("api.analyze.compute_indicators") as mock_ind, \
             patch("api.analyze.compute_garch_volatility") as mock_garch, \
             patch("api.analyze.compute_momentum_score") as mock_mom, \
             patch("api.analyze.compute_quality_score") as mock_qual, \
             patch("api.analyze.compute_congress_score") as mock_congress, \
             patch("api.analyze.compute_estimate_revision_score") as mock_est, \
             patch("api.analyze.compute_news_score") as mock_news, \
             patch("api.analyze.compute_earnings_score") as mock_earn, \
             patch("api.analyze.get_market_regime") as mock_regime, \
             patch("api.analyze.run_monte_carlo") as mock_mc, \
             patch("api.analyze.compute_trade_setup") as mock_trade:

            mock_bars.return_value = [{"c": 100.0} for _ in range(100)]
            mock_ind.return_value = {"technical_score": 0.6, "atr_stop": 95.0}
            mock_garch.return_value = {"daily_vol": 0.02, "vol_regime": "normal", "vol_scalar": 1.0}
            mock_mom.return_value = 0.5
            mock_qual.return_value = 0.5
            mock_congress.return_value = 0.5
            mock_est.return_value = 0.5
            mock_news.return_value = 0.5
            mock_earn.return_value = 0.5
            mock_regime.return_value = {"regime": "normal", "vix": 20.0}
            mock_mc.return_value = {"base_target": 105.0}
            mock_trade.return_value = {"entry_price": 100.0}

            result = analyze_ticker("AAPL")

            assert "data_quality" in result
            assert "freshness_score" in result["data_quality"]
            assert "components_fresh" in result["data_quality"]
            assert "stale_components" in result["data_quality"]
            assert "warnings" in result["data_quality"]

    def test_data_quality_freshness_score_ranges_0_to_1(self):
        """Verify freshness_score is between 0.0 and 1.0."""
        from api.analyze import _compute_data_quality

        quality = _compute_data_quality("AAPL")

        assert 0.0 <= quality["freshness_score"] <= 1.0

    def test_data_quality_warns_on_stale_components(self):
        """Verify warnings generated for stale components."""
        from api.analyze import _compute_data_quality

        with patch("data.cache.get_cache_with_age") as mock_cache:
            # Simulate stale earnings data (18 hours old, max 6 hours)
            def mock_age(key):
                if "earnings" in key:
                    return {"value": {}}, 64800  # 18 hours
                return {"value": {}}, 1800  # 30 min

            mock_cache.side_effect = mock_age

            quality = _compute_data_quality("AAPL")

            assert any("earnings" in warning.lower() for warning in quality["warnings"])


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """End-to-end tests for resilience features."""

    def test_signal_generation_succeeds_with_all_fallbacks(self):
        """Verify signal generation works with all fallbacks active."""
        # This would require extensive mocking; placeholder for future
        pass

    def test_circuit_breaker_halts_on_multiple_failures(self):
        """Verify trading halts when 3+ sources fail in 5 minutes."""
        # Placeholder for Phase 2 testing
        pass

    def test_load_test_1000_concurrent_analyze_requests(self):
        """Verify system handles high load without degradation."""
        # Placeholder for Phase 2 load testing
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
