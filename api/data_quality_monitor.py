"""Real-time data quality monitoring for the trading system.

Detects stale/dead signal flows and alerts when >30% of holdings have degraded data.
Used by daily briefing to warn about data quality issues before trading.
"""
import logging
from typing import Optional
from datetime import date

from api.briefing import BLUE_CHIP_UNIVERSE, MIDCAP_UNIVERSE
from backtest.diagnostics import analyze_data_quality
from api.paper_portfolio import log_warren_decision

logger = logging.getLogger(__name__)

# All 77 stocks that system trades on
TRADING_UNIVERSE = list(set(BLUE_CHIP_UNIVERSE + MIDCAP_UNIVERSE))

# Data quality thresholds
STUCK_THRESHOLD = 0.80  # >80% stuck at 0.5 = stale/dead
PORTFOLIO_HEALTH_THRESHOLD = 0.70  # Need >70% healthy signals


def check_universe_data_quality() -> dict:
    """
    Analyze data quality for all 77 stocks in the trading universe.

    Returns:
    {
        "timestamp": "2026-06-09",
        "total_stocks": 77,
        "healthy_stocks": 60,
        "degraded_stocks": 15,
        "dead_stocks": 2,
        "portfolio_health_pct": 77.9,
        "is_healthy": True/False,
        "alert_required": True/False,
        "degraded_list": [
            {"ticker": "JPM", "issues": ["insider_trades_stuck", "earnings_stuck"]},
            ...
        ],
        "dead_list": [
            {"ticker": "TSLA", "reason": "only 1 unique signal value across all layers"},
            ...
        ],
        "recommendation": "...",
    }
    """
    results = {
        "timestamp": date.today().isoformat(),
        "total_stocks": len(TRADING_UNIVERSE),
        "healthy_stocks": 0,
        "degraded_stocks": 0,
        "dead_stocks": 0,
        "degraded_list": [],
        "dead_list": [],
    }

    if not TRADING_UNIVERSE:
        logger.error("Trading universe is empty")
        results["is_healthy"] = False
        results["alert_required"] = True
        results["recommendation"] = "ERROR: Trading universe empty"
        return results

    # Analyze each stock
    analysis_by_ticker = {}
    for ticker in TRADING_UNIVERSE:
        try:
            analysis = analyze_data_quality(ticker)
            analysis_by_ticker[ticker] = analysis

            # Determine health status for this stock
            issues = []
            stuck_count = 0

            # Check each signal layer
            if analysis.get("insider_trades_stuck"):
                issues.append("insider_trades_stuck")
                stuck_count += 1
            if analysis.get("estimate_revisions_stuck"):
                issues.append("estimate_revisions_stuck")
                stuck_count += 1
            if analysis.get("earnings_score_stuck"):
                issues.append("earnings_stuck")
                stuck_count += 1
            if analysis.get("momentum_score_stuck"):
                issues.append("momentum_stuck")
                stuck_count += 1
            if analysis.get("quality_score_stuck"):
                issues.append("quality_stuck")
                stuck_count += 1

            # Classify stock health
            if stuck_count >= 4:
                # Dead: 4+ layers stuck at neutral
                results["dead_stocks"] += 1
                results["dead_list"].append({
                    "ticker": ticker,
                    "stuck_layers": stuck_count,
                    "reason": f"{stuck_count}/5 signal layers stuck at neutral",
                })
            elif stuck_count >= 2:
                # Degraded: 2-3 layers stuck at neutral
                results["degraded_stocks"] += 1
                results["degraded_list"].append({
                    "ticker": ticker,
                    "stuck_layers": stuck_count,
                    "issues": issues,
                })
            else:
                # Healthy: 0-1 layers stuck (at least 4 good signals)
                results["healthy_stocks"] += 1

        except Exception as exc:
            logger.warning("Failed to analyze data quality for %s: %s", ticker, exc)
            results["degraded_stocks"] += 1
            results["degraded_list"].append({
                "ticker": ticker,
                "error": str(exc),
                "issues": ["analysis_failed"],
            })

    # Calculate portfolio health percentage
    results["portfolio_health_pct"] = round(
        (results["healthy_stocks"] / results["total_stocks"]) * 100, 1
    )

    # Determine overall health and alert requirement
    results["is_healthy"] = results["portfolio_health_pct"] >= (PORTFOLIO_HEALTH_THRESHOLD * 100)
    results["alert_required"] = not results["is_healthy"]

    # Build recommendation
    if results["is_healthy"]:
        results["recommendation"] = (
            f"Data quality is healthy ({results['portfolio_health_pct']}% of universe "
            f"has reliable signals). Proceed with normal trading."
        )
    elif results["portfolio_health_pct"] >= 50:
        results["recommendation"] = (
            f"⚠️ DEGRADED DATA QUALITY: {results['degraded_stocks']} stocks have stale signals, "
            f"{results['dead_stocks']} are completely dead. "
            f"Portfolio health: {results['portfolio_health_pct']}%. "
            f"Recommendation: Reduce position sizing on affected stocks. "
            f"See degraded_list and dead_list for details."
        )
    else:
        results["recommendation"] = (
            f"🚨 CRITICAL DATA QUALITY: {results['degraded_stocks']} stocks degraded, "
            f"{results['dead_stocks']} dead. "
            f"Portfolio health: {results['portfolio_health_pct']}% — below 50% threshold. "
            f"DO NOT TRADE until data pipeline recovers."
        )

    return results


def get_degraded_stocks_for_sizing_adjustment() -> dict[str, float]:
    """
    Return position sizing multipliers for each stock based on data quality.

    For stocks with degraded signals, return a sizing multiplier (0.5 to 1.0).
    Healthy stocks get 1.0x (no adjustment).

    Returns: {ticker: sizing_multiplier}
    """
    quality_check = check_universe_data_quality()
    multipliers = {}

    # Healthy stocks: no adjustment
    for ticker in TRADING_UNIVERSE:
        multipliers[ticker] = 1.0

    # Degraded stocks: reduce sizing
    # Formula: 2 stuck -> 0.8x, 3 stuck -> 0.6x (cap at 0.5x minimum)
    for degraded in quality_check["degraded_list"]:
        ticker = degraded["ticker"]
        stuck_layers = degraded.get("stuck_layers", 2)
        multiplier = max(0.5, 1.0 - stuck_layers * 0.1)
        multipliers[ticker] = multiplier

    # Dead stocks: no trading
    for dead in quality_check["dead_list"]:
        ticker = dead["ticker"]
        multipliers[ticker] = 0.0  # Block all sizing for dead stocks

    return multipliers


def log_data_quality_check(quality_check: dict, session_id: str = "") -> None:
    """Log the data quality check to decision log."""
    try:
        recommendation = quality_check.get("recommendation", "Unknown")
        healthy_pct = quality_check.get("portfolio_health_pct", 0)

        log_warren_decision(
            decision_type="data_quality_check",
            recommendation=f"Portfolio health: {healthy_pct}%",
            rationale=recommendation,
            ticker=None,
            session_id=session_id,
        )
    except Exception as exc:
        logger.warning("Failed to log data quality check: %s", exc)


# ============================================================================
# Slack Alert Helper
# ============================================================================

def format_quality_alert_for_slack(quality_check: dict) -> str:
    """Format data quality check results for Slack notification."""
    health_pct = quality_check.get("portfolio_health_pct", 0)
    is_healthy = quality_check.get("is_healthy", False)

    status_emoji = "✅" if is_healthy else "⚠️"
    header = f"{status_emoji} *Data Quality Check — {quality_check['timestamp']}*"

    summary = (
        f"Portfolio Health: *{health_pct}%*\n"
        f"Healthy: {quality_check['healthy_stocks']}/{quality_check['total_stocks']}\n"
        f"Degraded: {quality_check['degraded_stocks']}\n"
        f"Dead: {quality_check['dead_stocks']}"
    )

    if quality_check["dead_list"]:
        dead_tickers = ", ".join(d["ticker"] for d in quality_check["dead_list"])
        dead_section = f"\n\n*Dead Stocks (BLOCK TRADING):* {dead_tickers}"
    else:
        dead_section = ""

    if quality_check["degraded_list"][:3]:  # Show first 3
        degraded_section = "\n\n*Degraded (>80% stale):*"
        for item in quality_check["degraded_list"][:3]:
            degraded_section += f"\n  • {item['ticker']}: {item.get('stuck_layers', '?')}/5 layers stuck"
        if len(quality_check["degraded_list"]) > 3:
            degraded_section += f"\n  ... and {len(quality_check['degraded_list']) - 3} more"
    else:
        degraded_section = ""

    recommendation = quality_check.get("recommendation", "See above")
    rec_section = f"\n\n*Action:* {recommendation}"

    return f"{header}\n{summary}{dead_section}{degraded_section}{rec_section}"
