"""
Backtest execution and reporting.

Runs walk-forward backtests on a list of stocks and generates
performance summaries.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from backtest.engine import run_backtest
from backtest.metrics import compare_to_spy

logger = logging.getLogger(__name__)

_ET = timezone(timedelta(hours=-5))

# High-confidence stocks from the portfolio (used for backtest)
BACKTEST_PORTFOLIO = [
    "AAPL", "MSFT", "NVDA", "TSLA", "META",
    "GOOGL", "AMZN", "JPM", "V", "JNJ",
]


def run_walk_forward_backtest(
    ticker: str,
    train_years: int = 2,
    test_years: int = 1,
) -> dict:
    """
    Run walk-forward backtest: train on N years, test on next year.

    Example: 2024 (train) → 2025 (test)

    Returns:
    {
        "ticker": "AAPL",
        "train_period": "2024-01-01:2024-12-31",
        "test_period": "2025-01-01:2025-12-31",
        "test_metrics": {...backtest run metrics...},
        "status": "PASS" or "FAIL",
        "confidence": 0.75,
        "notes": "Outperformed SPY by 8% with 0.65 Sharpe",
    }
    """
    try:
        # Calculate date ranges (going back from today)
        today = datetime.now(_ET)
        test_end = today - timedelta(days=30)  # 30 days ago (use historical data)
        test_start = test_end - timedelta(days=365 * test_years)
        train_end = test_start - timedelta(days=1)
        train_start = train_end - timedelta(days=365 * train_years)

        train_start_str = train_start.strftime("%Y-%m-%d")
        train_end_str = train_end.strftime("%Y-%m-%d")
        test_start_str = test_start.strftime("%Y-%m-%d")
        test_end_str = test_end.strftime("%Y-%m-%d")

        logger.info(
            "Walk-forward backtest for %s: train %s→%s, test %s→%s",
            ticker, train_start_str, train_end_str, test_start_str, test_end_str
        )

        # Run backtest on TEST period (validation period)
        test_run = run_backtest(ticker, test_start_str, test_end_str)

        # Evaluate results
        passed = _evaluate_backtest_run(test_run)
        confidence = _calculate_confidence(test_run)

        return {
            "ticker": ticker,
            "train_period": f"{train_start_str}:{train_end_str}",
            "test_period": f"{test_start_str}:{test_end_str}",
            "test_metrics": test_run.to_dict(),
            "status": "PASS" if passed else "FAIL",
            "confidence": round(confidence, 2),
            "notes": _generate_notes(test_run, passed),
        }

    except Exception as e:
        logger.exception("Backtest failed for %s: %s", ticker, e)
        return {
            "ticker": ticker,
            "status": "ERROR",
            "notes": str(e),
        }


def _evaluate_backtest_run(run) -> bool:
    """
    Validate backtest run meets minimum standards for paper trading.

    PASS criteria:
    - At least 3 trades
    - Win rate >= 35%
    - Positive total return
    - Sharpe ratio >= 0.3 (minimal)
    """
    if not run.trades or len(run.trades) < 3:
        logger.warning("Insufficient trades: %d", len(run.trades))
        return False

    if run.win_rate is None or run.win_rate < 0.35:
        logger.warning("Win rate too low: %.2f%%", (run.win_rate or 0) * 100)
        return False

    if run.total_return is None or run.total_return < 0:
        logger.warning("Negative return: %.2f%%", (run.total_return or 0) * 100)
        return False

    if run.sharpe_ratio is None or run.sharpe_ratio < 0.3:
        logger.warning("Sharpe too low: %.2f", run.sharpe_ratio or 0)
        return False

    logger.info(
        "PASS: %d trades, %.0f%% win rate, %.1f%% return, %.2f Sharpe",
        len(run.trades),
        (run.win_rate or 0) * 100,
        (run.total_return or 0) * 100,
        run.sharpe_ratio or 0,
    )
    return True


def _calculate_confidence(run) -> float:
    """
    Calculate confidence score [0, 1] based on backtest quality.

    Factors:
    - Win rate (35% = 0.5, 50% = 0.7, 65%+ = 0.9)
    - Sharpe ratio (0.3 = 0.5, 0.8 = 0.8, 1.5+ = 1.0)
    - Number of trades (3 = 0.5, 10 = 0.8, 20+ = 1.0)
    """
    if not run.trades:
        return 0.0

    score = 0.0

    # Win rate factor
    if run.win_rate:
        win_factor = min(1.0, (run.win_rate - 0.35) / 0.30)  # 35% = 0, 65% = 1.0
        score += win_factor * 0.4

    # Sharpe factor
    if run.sharpe_ratio:
        sharpe_factor = min(1.0, run.sharpe_ratio / 1.5)  # 1.5 = 1.0
        score += sharpe_factor * 0.4

    # Trade count factor
    trade_factor = min(1.0, len(run.trades) / 20)  # 20 trades = 1.0
    score += trade_factor * 0.2

    return score


def _generate_notes(run, passed: bool) -> str:
    """Generate human-readable summary of backtest results."""
    if not run.trades:
        return "No trades generated"

    notes = (
        f"{len(run.trades)} trades | "
        f"{(run.win_rate or 0)*100:.0f}% win | "
        f"{(run.total_return or 0)*100:.1f}% return | "
        f"Sharpe {run.sharpe_ratio or 0:.2f}"
    )

    if run.avg_win and run.avg_loss:
        ratio = abs(run.avg_win / run.avg_loss) if run.avg_loss != 0 else 0
        notes += f" | {ratio:.1f}:1 RR"

    if passed:
        notes += " ✓"
    else:
        notes += " ✗"

    return notes


def run_portfolio_backtest() -> dict:
    """
    Run backtest on entire portfolio.

    Returns:
    {
        "timestamp": "2026-06-08T14:30:00-05:00",
        "portfolio": ["AAPL", "MSFT", ...],
        "results": [
            {"ticker": "AAPL", "status": "PASS", ...},
            ...
        ],
        "summary": {
            "passed": 7,
            "failed": 2,
            "errored": 1,
            "confidence": 0.72,
            "go_nogo": "GO",
        },
    }
    """
    timestamp = datetime.now(_ET).isoformat()

    results = []
    for ticker in BACKTEST_PORTFOLIO:
        logger.info("Running backtest for %s...", ticker)
        result = run_walk_forward_backtest(ticker)
        results.append(result)

    # Calculate summary
    passed = len([r for r in results if r.get("status") == "PASS"])
    failed = len([r for r in results if r.get("status") == "FAIL"])
    errored = len([r for r in results if r.get("status") == "ERROR"])

    # Go/no-go decision
    pass_rate = passed / len(results) if results else 0.0
    avg_confidence = (
        sum(r.get("confidence", 0) for r in results if r.get("status") == "PASS")
        / max(1, passed)
    )

    # DECISION: Go if 50%+ stocks pass and avg confidence >= 0.60
    go_nogo = "GO" if pass_rate >= 0.50 and avg_confidence >= 0.60 else "NO-GO"

    return {
        "timestamp": timestamp,
        "portfolio": BACKTEST_PORTFOLIO,
        "results": results,
        "summary": {
            "passed": passed,
            "failed": failed,
            "errored": errored,
            "pass_rate": round(pass_rate, 2),
            "avg_confidence": round(avg_confidence, 2),
            "go_nogo": go_nogo,
        },
    }
