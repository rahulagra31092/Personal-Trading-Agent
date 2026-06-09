"""Tests for real-time data quality monitoring."""
import pytest
from unittest.mock import patch, MagicMock
from api.data_quality_monitor import (
    check_universe_data_quality,
    get_degraded_stocks_for_sizing_adjustment,
    format_quality_alert_for_slack,
    PORTFOLIO_HEALTH_THRESHOLD,
)


@patch("api.data_quality_monitor.TRADING_UNIVERSE", ["AAPL", "MSFT", "NVDA", "JPM"])
@patch("api.data_quality_monitor.analyze_data_quality")
def test_check_universe_all_healthy(mock_analyze):
    """When all stocks are healthy, portfolio_health_pct should be 100%."""
    # All stocks return no stuck signals
    mock_analyze.return_value = {
        "ticker": "MOCK",
        "insider_trades_stuck": False,
        "estimate_revisions_stuck": False,
        "earnings_score_stuck": False,
        "momentum_score_stuck": False,
        "quality_score_stuck": False,
    }

    result = check_universe_data_quality()

    assert result["total_stocks"] == 4
    assert result["healthy_stocks"] == 4
    assert result["degraded_stocks"] == 0
    assert result["dead_stocks"] == 0
    assert result["portfolio_health_pct"] == 100.0
    assert result["is_healthy"] is True
    assert result["alert_required"] is False


@patch("api.data_quality_monitor.TRADING_UNIVERSE", ["AAPL", "MSFT", "NVDA", "JPM"])
@patch("api.data_quality_monitor.analyze_data_quality")
def test_check_universe_mixed_health(mock_analyze):
    """Test with mix of healthy, degraded, and dead stocks."""
    def mock_quality_analysis(ticker):
        if ticker == "AAPL":
            # Healthy
            return {
                "ticker": ticker,
                "insider_trades_stuck": False,
                "estimate_revisions_stuck": False,
                "earnings_score_stuck": False,
                "momentum_score_stuck": False,
                "quality_score_stuck": False,
            }
        elif ticker == "MSFT":
            # Degraded (2 stuck layers)
            return {
                "ticker": ticker,
                "insider_trades_stuck": True,
                "estimate_revisions_stuck": True,
                "earnings_score_stuck": False,
                "momentum_score_stuck": False,
                "quality_score_stuck": False,
            }
        elif ticker == "NVDA":
            # Degraded (1 stuck layer)
            return {
                "ticker": ticker,
                "insider_trades_stuck": True,
                "estimate_revisions_stuck": False,
                "earnings_score_stuck": False,
                "momentum_score_stuck": False,
                "quality_score_stuck": False,
            }
        else:  # JPM
            # Dead (4+ stuck layers)
            return {
                "ticker": ticker,
                "insider_trades_stuck": True,
                "estimate_revisions_stuck": True,
                "earnings_score_stuck": True,
                "momentum_score_stuck": True,
                "quality_score_stuck": False,
            }

    mock_analyze.side_effect = mock_quality_analysis

    result = check_universe_data_quality()

    assert result["total_stocks"] == 4
    assert result["healthy_stocks"] == 2  # AAPL (0 stuck), NVDA (1 stuck)
    assert result["degraded_stocks"] == 1  # MSFT (2 stuck)
    assert result["dead_stocks"] == 1  # JPM (4 stuck)
    assert result["portfolio_health_pct"] == 50.0  # 2/4 = 50%
    assert result["is_healthy"] is False  # 50% < 70% threshold
    assert result["alert_required"] is True

    # Check degraded list
    assert len(result["degraded_list"]) == 1
    msft_entry = next((d for d in result["degraded_list"] if d["ticker"] == "MSFT"), None)
    assert msft_entry is not None
    assert msft_entry["stuck_layers"] == 2

    # Check dead list
    assert len(result["dead_list"]) == 1
    assert result["dead_list"][0]["ticker"] == "JPM"


def test_get_degraded_stocks_for_sizing():
    """Test position sizing multipliers based on data quality."""
    # Directly construct a quality_check result instead of calling check_universe_data_quality
    quality_check = {
        "timestamp": "2026-06-09",
        "total_stocks": 3,
        "healthy_stocks": 1,
        "degraded_stocks": 1,
        "dead_stocks": 1,
        "portfolio_health_pct": 33.3,
        "is_healthy": False,
        "alert_required": True,
        "degraded_list": [
            {"ticker": "MSFT", "stuck_layers": 2, "issues": ["insider_trades_stuck", "estimate_revisions_stuck"]},
        ],
        "dead_list": [
            {"ticker": "JPM", "stuck_layers": 4, "reason": "4/5 signal layers stuck"},
        ],
        "recommendation": "Some stocks degraded",
    }

    # Mock the function to return our hardcoded check
    with patch("api.data_quality_monitor.check_universe_data_quality", return_value=quality_check):
        with patch("api.data_quality_monitor.TRADING_UNIVERSE", ["AAPL", "MSFT", "JPM"]):
            multipliers = get_degraded_stocks_for_sizing_adjustment()

    assert multipliers["AAPL"] == 1.0  # Healthy: no reduction
    assert multipliers["MSFT"] == 0.8  # Degraded: 2 stuck -> 0.8x (1.0 - 2*0.1)
    assert multipliers["JPM"] == 0.0  # Dead: block trading


@patch("api.data_quality_monitor.TRADING_UNIVERSE", ["AAPL", "MSFT"])
@patch("api.data_quality_monitor.analyze_data_quality")
def test_check_universe_handles_analysis_errors(mock_analyze):
    """Test resilience when analyze_data_quality raises errors."""
    def mock_quality_analysis(ticker):
        if ticker == "AAPL":
            # Healthy
            return {
                "ticker": ticker,
                "insider_trades_stuck": False,
                "estimate_revisions_stuck": False,
                "earnings_score_stuck": False,
                "momentum_score_stuck": False,
                "quality_score_stuck": False,
            }
        else:
            # Simulate analysis failure
            raise Exception("Data fetch failed")

    mock_analyze.side_effect = mock_quality_analysis

    result = check_universe_data_quality()

    # Should still return results, with MSFT marked as degraded (error)
    assert result["total_stocks"] == 2
    assert result["healthy_stocks"] == 1
    assert result["degraded_stocks"] == 1  # MSFT (error)
    assert result["dead_stocks"] == 0

    # Error entry should be in degraded_list
    msft_entry = next((d for d in result["degraded_list"] if d["ticker"] == "MSFT"), None)
    assert msft_entry is not None
    assert "error" in msft_entry


def test_format_quality_alert_healthy():
    """Test Slack alert formatting for healthy portfolio."""
    quality_check = {
        "timestamp": "2026-06-09",
        "total_stocks": 77,
        "healthy_stocks": 70,
        "degraded_stocks": 5,
        "dead_stocks": 2,
        "portfolio_health_pct": 90.9,
        "is_healthy": True,
        "recommendation": "Data quality is healthy. Proceed with normal trading.",
        "degraded_list": [],
        "dead_list": [],
    }

    alert = format_quality_alert_for_slack(quality_check)

    assert "✅" in alert
    assert "90.9%" in alert
    assert "Data quality is healthy" in alert


def test_format_quality_alert_degraded():
    """Test Slack alert formatting for degraded portfolio."""
    quality_check = {
        "timestamp": "2026-06-09",
        "total_stocks": 77,
        "healthy_stocks": 50,
        "degraded_stocks": 20,
        "dead_stocks": 7,
        "portfolio_health_pct": 64.9,
        "is_healthy": False,
        "recommendation": "Reduce position sizing on affected stocks.",
        "degraded_list": [
            {"ticker": "MSFT", "stuck_layers": 2, "issues": ["insider_trades_stuck"]},
            {"ticker": "META", "stuck_layers": 2, "issues": ["insider_trades_stuck"]},
            {"ticker": "AMZN", "stuck_layers": 1, "issues": ["estimate_revisions_stuck"]},
        ],
        "dead_list": [
            {"ticker": "JPM", "reason": "4/5 signal layers stuck at neutral"},
            {"ticker": "TSLA", "reason": "4/5 signal layers stuck at neutral"},
        ],
    }

    alert = format_quality_alert_for_slack(quality_check)

    assert "⚠️" in alert
    assert "64.9%" in alert
    assert "JPM" in alert
    assert "TSLA" in alert
    assert "Reduce position sizing" in alert


@patch("api.data_quality_monitor.TRADING_UNIVERSE", ["AAPL", "MSFT", "NVDA"])
@patch("api.data_quality_monitor.analyze_data_quality")
def test_portfolio_health_threshold_boundary(mock_analyze):
    """Test behavior at the 70% health threshold boundary."""
    # Setup: 2 healthy, 1 degraded = 66.7% health
    def mock_quality_analysis(ticker):
        if ticker in ["AAPL", "MSFT"]:
            return {
                "ticker": ticker,
                "insider_trades_stuck": False,
                "estimate_revisions_stuck": False,
                "earnings_score_stuck": False,
                "momentum_score_stuck": False,
                "quality_score_stuck": False,
            }
        else:  # NVDA
            return {
                "ticker": ticker,
                "insider_trades_stuck": True,
                "estimate_revisions_stuck": True,
                "earnings_score_stuck": False,
                "momentum_score_stuck": False,
                "quality_score_stuck": False,
            }

    mock_analyze.side_effect = mock_quality_analysis

    result = check_universe_data_quality()

    # 2/3 = 66.7%, which is below 70% threshold
    assert result["portfolio_health_pct"] < (PORTFOLIO_HEALTH_THRESHOLD * 100)
    assert result["is_healthy"] is False
    assert result["alert_required"] is True
