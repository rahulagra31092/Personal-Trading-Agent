"""
Diagnostic tools for data quality verification.

Analyzes signal flows to detect stale data and dead data sources.
"""
import logging
from typing import Optional
from collections import Counter

from data.market import get_daily_bars
from quant.indicators import compute_indicators
from quant.momentum import compute_momentum_score
from quant.quality import compute_quality_score
from smart_money.insider_trades import compute_insider_trades_score
from smart_money.estimate_revisions import compute_estimate_revision_score
from smart_money.earnings_scorer import compute_earnings_score

logger = logging.getLogger(__name__)


def analyze_data_quality(ticker: str) -> dict:
    """
    Analyze data quality for a ticker.

    Returns:
    {
        "ticker": "MSFT",
        "insider_trades_score_values": [0.5, 0.5, 0.48, ...],
        "insider_trades_stuck_at_neutral": True/False,
        "earnings_score_values": [0.5, 0.51, 0.49, ...],
        "earnings_score_stuck": True/False,
        "estimate_revisions_score_values": [...],
        "estimate_revisions_stuck": True/False,
        "momentum_score_values": [...],
        "momentum_score_stuck": True/False,
        "quality_score_values": [...],
        "quality_score_stuck": True/False,
        "num_dates_analyzed": 158,
        "recommendation": "insider_trades data is stale or unavailable"
    }
    """
    ticker = ticker.strip().upper()

    try:
        bars = get_daily_bars(ticker, days=1095)  # 3 years
    except Exception as e:
        logger.warning("Failed to load bars for %s: %s", ticker, e)
        return {
            "ticker": ticker,
            "error": str(e),
            "recommendation": "Failed to load market data"
        }

    if len(bars) < 60:
        logger.warning("Insufficient history for %s: %d bars", ticker, len(bars))
        return {
            "ticker": ticker,
            "num_bars": len(bars),
            "recommendation": "Insufficient historical data"
        }

    # Analyze recent dates (last 158 trading days ≈ 6 months)
    recent_bars = bars[-158:] if len(bars) >= 158 else bars

    insider_scores = []
    estimate_scores = []
    earnings_scores = []
    momentum_scores = []
    quality_scores = []

    for bar in recent_bars:
        try:
            insider_score = compute_insider_trades_score(ticker)
            insider_scores.append(insider_score)
        except Exception as e:
            logger.debug("Failed to compute insider score: %s", e)
            insider_scores.append(0.5)

        try:
            estimate_score = compute_estimate_revision_score(ticker)
            estimate_scores.append(estimate_score)
        except Exception as e:
            logger.debug("Failed to compute estimate score: %s", e)
            estimate_scores.append(0.5)

        try:
            earnings_score = compute_earnings_score(ticker)
            earnings_scores.append(earnings_score)
        except Exception as e:
            logger.debug("Failed to compute earnings score: %s", e)
            earnings_scores.append(0.5)

        try:
            momentum_score = compute_momentum_score(ticker)
            momentum_scores.append(momentum_score)
        except Exception as e:
            logger.debug("Failed to compute momentum score: %s", e)
            momentum_scores.append(0.5)

        try:
            quality_score = compute_quality_score(ticker)
            quality_scores.append(quality_score)
        except Exception as e:
            logger.debug("Failed to compute quality score: %s", e)
            quality_scores.append(0.5)

    # Count how many are stuck at 0.5 (neutral)
    def is_stuck_at_neutral(scores: list[float], threshold=0.80) -> bool:
        """Returns True if >80% of scores are exactly 0.5"""
        if not scores:
            return False
        count_neutral = sum(1 for s in scores if abs(s - 0.5) < 1e-6)
        return (count_neutral / len(scores)) >= threshold

    insider_stuck = is_stuck_at_neutral(insider_scores)
    estimate_stuck = is_stuck_at_neutral(estimate_scores)
    earnings_stuck = is_stuck_at_neutral(earnings_scores)
    momentum_stuck = is_stuck_at_neutral(momentum_scores)
    quality_stuck = is_stuck_at_neutral(quality_scores)

    # Count unique values
    insider_unique = len(set(round(s, 6) for s in insider_scores))
    estimate_unique = len(set(round(s, 6) for s in estimate_scores))
    earnings_unique = len(set(round(s, 6) for s in earnings_scores))
    momentum_unique = len(set(round(s, 6) for s in momentum_scores))
    quality_unique = len(set(round(s, 6) for s in quality_scores))

    # Build recommendation
    issues = []
    if insider_stuck:
        issues.append("insider_trades data is stale or unavailable")
    if estimate_stuck:
        issues.append("estimate_revisions data is stale or unavailable")
    if earnings_stuck:
        issues.append("earnings data is stale or unavailable")
    if momentum_stuck:
        issues.append("momentum data is stale or unavailable")
    if quality_stuck:
        issues.append("quality data is stale or unavailable")

    recommendation = "; ".join(issues) if issues else "Data quality is healthy"

    return {
        "ticker": ticker,
        "insider_trades_score_values": insider_scores[:10],  # First 10 for brevity
        "insider_trades_stuck_at_neutral": insider_stuck,
        "insider_trades_unique_values": insider_unique,
        "estimate_revisions_score_values": estimate_scores[:10],
        "estimate_revisions_stuck": estimate_stuck,
        "estimate_revisions_unique_values": estimate_unique,
        "earnings_score_values": earnings_scores[:10],
        "earnings_score_stuck": earnings_stuck,
        "earnings_score_unique_values": earnings_unique,
        "momentum_score_values": momentum_scores[:10],
        "momentum_score_stuck": momentum_stuck,
        "momentum_score_unique_values": momentum_unique,
        "quality_score_values": quality_scores[:10],
        "quality_score_stuck": quality_stuck,
        "quality_score_unique_values": quality_unique,
        "num_dates_analyzed": len(recent_bars),
        "recommendation": recommendation,
    }
