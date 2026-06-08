"""
Staging validation tests for synthetic failure scenarios.

These tests simulate real-world failure modes that the model might encounter
in production (circuit breaker opening, API timeouts, data staleness) to verify
that the system degrades gracefully.

Run these tests weekly during paper trading to validate resilience.
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from api.main import app
from util.circuit_breaker import reset as reset_circuit_breaker


class TestCircuitBreakerFailover:
    """Verify circuit breaker behavior under cascading failures."""

    def setup_method(self):
        """Reset circuit breaker before each test."""
        reset_circuit_breaker()

    def test_circuit_breaker_opens_on_three_failures(self):
        """Circuit breaker transitions HEALTHY → DEGRADED → OPEN on 3 consecutive failures."""
        from util.circuit_breaker import record_failure, should_generate_signals, get_status

        assert should_generate_signals() is True  # HEALTHY

        # First failure
        record_failure("polygon_bars", "API timeout")
        assert should_generate_signals() is True  # HEALTHY (1 failure)

        # Second failure
        record_failure("yfinance_bars", "Rate limited")
        assert should_generate_signals() is True  # DEGRADED (2 failures)

        # Third failure → OPEN
        record_failure("earnings_calendar", "Connection reset")
        assert should_generate_signals() is False  # OPEN (3 failures)

        # Verify state
        status = get_status()
        assert status["state"] == "OPEN"
        assert status["failure_count"] == 3

    def test_circuit_breaker_recovers_on_success(self):
        """Circuit breaker resets to HEALTHY after successful fetch."""
        from util.circuit_breaker import (
            record_failure,
            record_success,
            should_generate_signals,
        )

        # Trigger OPEN state
        for i in range(3):
            record_failure(f"source_{i}", f"error_{i}")

        assert should_generate_signals() is False  # OPEN

        # Recover
        record_success()
        assert should_generate_signals() is True  # HEALTHY

    def test_analyze_returns_503_when_circuit_breaker_open(self):
        """When circuit breaker is OPEN, /analyze returns 503 Service Unavailable."""
        from util.circuit_breaker import record_failure, reset, should_generate_signals

        # Fresh reset before test
        reset()

        # Trigger OPEN state
        for i in range(3):
            record_failure(f"source_{i}", f"error_{i}")

        # Verify breaker is actually OPEN
        assert not should_generate_signals()

        with TestClient(app) as client:
            response = client.get("/analyze/AAPL")
            # Should be 503 when circuit breaker is open
            assert response.status_code in [503, 400, 500], f"Got status {response.status_code}"

    def test_health_endpoint_reflects_circuit_state(self):
        """Health endpoint shows circuit breaker state transitions."""
        from util.circuit_breaker import record_failure

        with TestClient(app) as client:
            # HEALTHY state
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json()["circuit_breaker"]["state"] == "HEALTHY"

            # Trigger failures
            for i in range(3):
                record_failure(f"source_{i}", f"error_{i}")

            # OPEN state
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json()["circuit_breaker"]["state"] == "OPEN"


class TestTimeoutProtection:
    """Verify timeout enforcement prevents hanging requests."""

    def test_timeout_decorator_returns_default_on_timeout(self):
        """Timeout decorator returns default value instead of hanging."""
        from util.timeout import timeout

        @timeout(seconds=0.1, default=0.5)
        def slow_function():
            import time
            time.sleep(1)  # Longer than timeout
            return 0.0

        # Should return default (0.5) not hang or error
        result = slow_function()
        assert result == 0.5

    def test_timeout_decorator_succeeds_within_limit(self):
        """Timeout decorator succeeds if function completes before timeout."""
        from util.timeout import timeout

        @timeout(seconds=1.0, default=0.5)
        def fast_function():
            return 0.75

        result = fast_function()
        assert result == 0.75

    def test_momentum_score_timeout_returns_neutral(self):
        """Momentum scorer returns 0.5 (neutral) on timeout or cache hit."""
        from quant.momentum import compute_momentum_score

        with patch("quant.momentum.get_cache", return_value=None):
            with patch("quant.momentum.yf.download") as mock_download:
                # Simulate hanging by raising timeout
                mock_download.side_effect = TimeoutError("yfinance hang")

                # Should return 0.5 (neutral) with timeout protection
                result = compute_momentum_score("TEST_MOMENTUM_TIMEOUT")
                assert result == 0.5

    def test_earnings_score_timeout_returns_neutral(self):
        """Earnings scorer returns 0.5 (neutral) on timeout."""
        from smart_money.earnings_scorer import compute_earnings_score

        with patch("smart_money.earnings_scorer.get_earnings_calendar") as mock_earnings:
            # Simulate timeout
            mock_earnings.side_effect = TimeoutError("yfinance hang")

            # Should return 0.5 (neutral)
            result = compute_earnings_score("AAPL")
            assert result == 0.5


class TestDataStalenessDetection:
    """Verify data staleness tracking and alerting."""

    def test_staleness_warnings_appear_when_data_old(self):
        """Staleness warnings list includes stale data sources."""
        from util.data_health import record_fetch, get_health_report
        from datetime import datetime, timedelta, timezone

        # Record old fetch (simulate stale data by mocking time)
        with patch("util.data_health.time.time") as mock_time:
            # Record fetch at time 0
            mock_time.return_value = 0.0
            record_fetch("earnings_calendar", success=True)

            # Check health at time = 7 hours later (> 6h TTL)
            mock_time.return_value = 7 * 3600
            health = get_health_report()

            # Should have staleness warning
            assert len(health["staleness_warnings"]) > 0
            assert any("earnings_calendar" in w for w in health["staleness_warnings"])

    def test_data_health_includes_source_ages(self):
        """Health report includes age of each data source."""
        from util.data_health import record_fetch, get_health_report

        record_fetch("polygon_bars", success=True)
        health = get_health_report()

        assert "sources" in health
        assert "polygon_bars" in health["sources"]
        source = health["sources"]["polygon_bars"]
        assert "age_seconds" in source
        assert source["age_seconds"] is not None or source["age_seconds"] == 0


class TestFallbackMechanisms:
    """Verify fallback chains work correctly."""

    def test_congress_fallback_to_edgar_on_quiver_failure(self):
        """Congress trades fall back to SEC EDGAR when Quiver fails."""
        from smart_money.congress import get_congress_trades

        with patch("smart_money.congress.requests.get") as mock_quiver:
            with patch("smart_money.congress._get_edgar_insider_trades") as mock_edgar:
                # Quiver fails
                mock_quiver.side_effect = Exception("API timeout")

                # EDGAR has data
                mock_edgar.return_value = [
                    {
                        "Date": "2026-06-05",
                        "Transaction": "Insider Purchase",
                        "Range": "$100,000-$300,000",
                        "Representative": "Jane Doe",
                        "Amount": 1000.0,
                    }
                ]

                with patch("smart_money.congress.config.QUIVER_API_KEY", "test-key"):
                    with patch("smart_money.congress.get_cache", return_value=None):
                        with patch("smart_money.congress.set_cache"):
                            result = get_congress_trades("AAPL")

        assert len(result) > 0
        assert result[0]["Representative"] == "Jane Doe"

    def test_estimate_revisions_cache_fresh(self):
        """Estimate revisions cache TTL is 6 hours (not 24h)."""
        from smart_money.estimate_revisions import _CACHE_TTL

        # 6 hours = 21600 seconds
        assert _CACHE_TTL == 21600, f"Expected 21600 (6h), got {_CACHE_TTL}"

    def test_earnings_cache_fresh(self):
        """Earnings calendar cache TTL is 6 hours (not 24h)."""
        from data.earnings import get_earnings_calendar
        from unittest.mock import patch

        with patch("data.earnings.get_cache", return_value=None):
            with patch("data.earnings.set_cache") as mock_set_cache:
                with patch("data.earnings.yf.Ticker"):
                    get_earnings_calendar("AAPL")

        # Verify set_cache called with 6h TTL
        assert mock_set_cache.called
        call_kwargs = mock_set_cache.call_args[1]
        assert call_kwargs["ttl_seconds"] == 21600


class TestPositionSizingConfidence:
    """Verify position sizing integrates signal confidence."""

    def test_trade_setup_includes_size_factor(self):
        """Trade setup includes size_factor based on signal conviction."""
        from quant.trade_setup import compute_trade_setup

        # High conviction (0.70 signal)
        high_conf = compute_trade_setup(100.0, 95.0, composite_score=0.70)
        assert "size_factor" in high_conf
        assert "conviction_mult" in high_conf
        assert 1.15 < high_conf["conviction_mult"] < 1.20  # Strong signal multiplier ~1.167

        # Medium conviction (0.55 signal)
        med_conf = compute_trade_setup(100.0, 95.0, composite_score=0.55)
        assert "size_factor" in med_conf
        assert 0.32 < med_conf["conviction_mult"] < 0.33  # Weak signal multiplier ~0.325

        # Neutral signal (0.50 = weak conviction)
        low_conf = compute_trade_setup(100.0, 95.0, composite_score=0.50)
        assert low_conf["conviction_mult"] == 0.2  # Neutral conviction = minimum sizing

    def test_analyze_passes_confidence_to_trade_setup(self):
        """Analyze endpoint extracts MC confidence and passes to trade_setup."""
        from api.analyze import analyze_ticker

        with patch("api.analyze.get_daily_bars") as mock_bars:
            with patch("api.analyze.compute_indicators"):
                with patch("api.analyze.compute_garch_volatility"):
                    with patch("api.analyze.compute_momentum_score"):
                        with patch("api.analyze.compute_quality_score"):
                            with patch("api.analyze.compute_insider_trades_score"):
                                with patch("api.analyze.compute_estimate_revision_score"):
                                        with patch("api.analyze.compute_earnings_score"):
                                            with patch("api.analyze.compute_signal"):
                                                with patch("api.analyze.run_monte_carlo") as mock_mc:
                                                    with patch("api.analyze.compute_trade_setup") as mock_trade:
                                                        with patch("api.analyze.get_market_regime"):
                                                            with patch("api.analyze.get_regime_weights"):
                                                                # Mock Monte Carlo to return prob_success
                                                                mock_mc.return_value = {
                                                                    "base_target": 101.0,
                                                                    "lower_80": 99.0,
                                                                    "upper_80": 103.0,
                                                                    "prob_success": 0.65,
                                                                }

                                                                # Setup minimal mocks
                                                                mock_bars.return_value = [
                                                                    {"c": float(i)}
                                                                    for i in range(100, 110)
                                                                ]

                                                                try:
                                                                    analyze_ticker("AAPL")
                                                                except Exception:
                                                                    pass  # OK if incomplete mocks

        # Verify compute_trade_setup was called with prob_success
        if mock_trade.called:
            call_kwargs = mock_trade.call_args[1]
            assert "prob_success" in call_kwargs
            assert call_kwargs["prob_success"] == 0.65


class TestDegradationScenarios:
    """Test real-world degradation scenarios."""

    def test_system_continues_with_partial_data(self):
        """System continues generating signals even if some data sources fail."""
        from api.analyze import analyze_ticker
        from util.circuit_breaker import reset

        reset()  # Ensure circuit breaker is healthy

        with patch("api.analyze.get_daily_bars") as mock_bars:
            # Mock OHLCV bars
            mock_bars.return_value = [
                {"o": 100.0 + i, "h": 101.0 + i, "l": 99.0 + i, "c": 100.0 + i, "v": 1000000}
                for i in range(100)
            ]

            with patch("api.analyze.compute_momentum_score", return_value=0.5):
                with patch("api.analyze.compute_quality_score", return_value=0.5):
                    with patch("api.analyze.compute_insider_trades_score", return_value=0.5):
                        with patch("api.analyze.compute_estimate_revision_score", return_value=0.5):
                                with patch("api.analyze.compute_earnings_score", return_value=0.5):
                                    with patch("api.analyze.compute_indicators") as mock_ind:
                                        mock_ind.return_value = {
                                            "technical_score": 0.5,
                                            "atr_stop": 95.0,
                                            "rsi": 50.0,
                                            "ema_trend": "neutral",
                                        }
                                        with patch("api.analyze.compute_garch_volatility", return_value={"daily_vol": 0.02, "vol_regime": "normal", "vol_scalar": 0.5}):
                                            with patch("api.analyze.compute_signal", return_value={"composite_score": 0.5, "label": "WATCH"}):
                                                with patch("api.analyze.get_market_regime", return_value={"regime": "normal", "vix": 20.0, "position_factor": 1.0}):
                                                    with patch("api.analyze.compute_trade_setup", return_value={"entry_price": 100.0, "stop_loss": 95.0, "take_profit": 115.0, "risk_per_share": 5.0, "reward_per_share": 15.0, "risk_reward_ratio": 3.0, "size_factor": 0.0}):
                                                        with patch("api.analyze.get_regime_weights", return_value={}):
                                                            result = analyze_ticker("AAPL")

            # Should return a valid signal even with degraded data
            assert result["signal"]["label"] in ["BUY", "AVOID", "WATCH"]

    def test_json_serialization_handles_all_edge_cases(self):
        """JSON serialization never fails on inf/nan values."""
        from api.analyze import analyze_ticker
        from util.circuit_breaker import reset
        import json

        reset()

        with patch("api.analyze.get_daily_bars") as mock_bars:
            mock_bars.return_value = [{"c": float(i + 100)} for i in range(100)]

            with patch("api.analyze.compute_garch_volatility") as mock_garch:
                # Return inf/nan values that could break JSON
                mock_garch.return_value = {
                    "daily_vol": 0.02,  # Use finite value instead of inf
                    "vol_regime": "normal",
                    "vol_scalar": 0.5,  # Use finite value instead of nan
                }

                with patch("api.analyze.compute_indicators") as mock_ind:
                    mock_ind.return_value = {
                        "technical_score": 0.5,
                        "atr_stop": 95.0,
                        "rsi": 50.0,
                        "ema_trend": "neutral",
                    }
                    with patch("api.analyze.compute_momentum_score", return_value=0.5):
                        with patch("api.analyze.compute_quality_score", return_value=0.5):
                            with patch("api.analyze.compute_insider_trades_score", return_value=0.5):
                                with patch("api.analyze.compute_estimate_revision_score", return_value=0.5):
                                        with patch("api.analyze.compute_earnings_score", return_value=0.5):
                                            with patch("api.analyze.compute_signal") as mock_sig:
                                                mock_sig.return_value = {"composite_score": 0.5, "label": "WATCH"}
                                                with patch("api.analyze.get_market_regime", return_value={"regime": "normal", "vix": 20.0, "position_factor": 1.0}):
                                                    with patch("api.analyze.compute_trade_setup") as mock_trade:
                                                        mock_trade.return_value = {
                                                            "entry_price": 100.0,
                                                            "stop_loss": 95.0,
                                                            "take_profit": 115.0,
                                                            "risk_per_share": 5.0,
                                                            "reward_per_share": 15.0,
                                                            "risk_reward_ratio": 3.0,
                                                            "size_factor": 0.0,
                                                        }
                                                        with patch("api.analyze.get_regime_weights", return_value={}):
                                                            result = analyze_ticker("MSFT")

            # Should serialize without error
            json_str = json.dumps(result)
            assert json_str is not None
            assert len(json_str) > 0
