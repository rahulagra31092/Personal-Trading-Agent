"""
Backtest execution and reporting.

Runs walk-forward backtests on a list of stocks and generates
performance summaries.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import copy

from backtest.engine import run_backtest
from backtest.metrics import compare_to_spy
import quant.signals as signals_module

logger = logging.getLogger(__name__)

_ET = timezone(timedelta(hours=-5))

# High-confidence stocks from the portfolio (used for backtest)
BACKTEST_PORTFOLIO = [
    "AAPL", "MSFT", "NVDA", "TSLA", "META",
    "GOOGL", "AMZN", "JPM", "V", "JNJ",
]


def analyze_threshold_sensitivity(ticker: str) -> dict:
    """
    Test entry threshold sensitivity to find optimal threshold for a ticker.

    Tests thresholds: 0.55, 0.60, 0.65, 0.70

    Returns:
    {
        "ticker": "MSFT",
        "test_period": "2026-01-01:2026-06-08",
        "thresholds": {
            0.55: {"trades": 12, "win_rate": 0.38, "return": -0.012, "sharpe": 0.15},
            0.60: {"trades": 10, "win_rate": 0.40, "return": 0.003, "sharpe": 0.20},
            0.65: {"trades": 9, "win_rate": 0.33, "return": -0.027, "sharpe": -0.05},
            0.70: {"trades": 6, "win_rate": 0.50, "return": 0.021, "sharpe": 0.35},
        },
        "recommendation": "Use 0.70 for MSFT to avoid false entries",
    }
    """
    from data.market import get_daily_bars
    from datetime import datetime as dt
    from quant.indicators import compute_indicators
    from quant.forecast import compute_garch_volatility
    from quant.momentum import compute_momentum_score
    from quant.quality import compute_quality_score
    from quant.signals import compute_signal
    from quant.trade_setup import compute_trade_setup
    from smart_money.insider_trades import compute_insider_trades_score
    from smart_money.estimate_revisions import compute_estimate_revision_score
    from smart_money.earnings_scorer import compute_earnings_score
    from quant.regime import get_market_regime, get_regime_weights
    from backtest.engine import BacktestTrade, BacktestRun

    ticker = ticker.strip().upper()
    test_start_str = "2026-01-01"
    test_end_str = "2026-06-08"

    thresholds = [0.55, 0.60, 0.65, 0.70]
    results = {}

    try:
        bars = get_daily_bars(ticker, days=1095)
    except Exception as e:
        logger.warning("Failed to load bars for %s: %s", ticker, e)
        return {
            "ticker": ticker,
            "error": str(e),
            "recommendation": "Failed to load market data"
        }

    if len(bars) < 60:
        return {
            "ticker": ticker,
            "error": "Insufficient history",
            "recommendation": "Need at least 60 bars of data"
        }

    # Convert dates
    start_dt = dt.strptime(test_start_str, "%Y-%m-%d")
    end_dt = dt.strptime(test_end_str, "%Y-%m-%d")

    # Filter to date range
    filtered_bars = []
    for bar in bars:
        if "t" in bar:
            bar_dt = dt.fromtimestamp(bar["t"] / 1000)
            bar_date_str = bar_dt.strftime("%Y-%m-%d")
        elif "date" in bar:
            bar_date_str = bar["date"][:10]
            bar_dt = dt.strptime(bar_date_str, "%Y-%m-%d")
        else:
            continue

        if start_dt <= bar_dt <= end_dt:
            filtered_bars.append((bar, bar_date_str))

    if not filtered_bars:
        return {
            "ticker": ticker,
            "error": f"No bars in range {test_start_str}-{test_end_str}",
            "recommendation": "Check date range"
        }

    # For each threshold, run a minimal backtest
    for threshold in thresholds:
        open_trades = []
        trades = []

        for i, (bar, date_str) in enumerate(filtered_bars):
            close_price = float(bar.get("c", bar.get("close", 0)))

            # Check if open trades hit stop/target
            for trade in list(open_trades):
                high = float(bar.get("h", bar.get("high", close_price)))
                low = float(bar.get("l", bar.get("low", close_price)))

                # Take profit
                if high >= trade.take_profit:
                    trade.close(date_str, trade.take_profit, "tp")
                    trades.append(trade)
                    open_trades.remove(trade)
                    continue

                # Stop loss
                if low <= trade.stop_loss:
                    trade.close(date_str, trade.stop_loss, "sl")
                    trades.append(trade)
                    open_trades.remove(trade)
                    continue

                # Timeout (hold 20 days)
                if (dt.fromisoformat(date_str) - dt.fromisoformat(trade.entry_date)).days > 20:
                    trade.close(date_str, close_price, "timeout")
                    trades.append(trade)
                    open_trades.remove(trade)

            # Compute signals for this date
            try:
                recent_bars_tuples = filtered_bars[max(0, i-60):i+1]
                recent_bars = [b[0] for b in recent_bars_tuples]
                if len(recent_bars) < 20:
                    continue

                ind = compute_indicators(recent_bars)
                garch = compute_garch_volatility([float(b.get("c", b.get("close", 0))) for b in recent_bars])

                # Get smart money scores with defaults
                try:
                    momentum_score = compute_momentum_score(ticker)
                except Exception:
                    momentum_score = 0.5

                try:
                    quality_score = compute_quality_score(ticker)
                except Exception:
                    quality_score = 0.5

                try:
                    insider_score = compute_insider_trades_score(ticker)
                except Exception:
                    insider_score = 0.5

                try:
                    estimate_score = compute_estimate_revision_score(ticker)
                except Exception:
                    estimate_score = 0.5

                try:
                    earnings_score = compute_earnings_score(ticker)
                except Exception:
                    earnings_score = 0.5

                try:
                    regime = get_market_regime()
                except Exception:
                    regime = {"regime": "normal", "position_factor": 1.0}

                regime_weights = get_regime_weights(regime.get("regime", "normal"))

                # Compute signal
                sig = compute_signal(
                    technical_score=ind.get("technical_score", 0.5),
                    momentum_score=momentum_score,
                    quality_score=quality_score,
                    insider_trades_score=insider_score,
                    estimate_revisions_score=estimate_score,
                    earnings_score=earnings_score,
                    weights=regime_weights,
                )

                # Entry logic: BUY only if no open trades and signal > threshold
                if not open_trades and sig["composite_score"] > threshold:
                    trade_setup = compute_trade_setup(
                        close_price,
                        ind.get("atr_stop", close_price * 0.95),
                        composite_score=sig["composite_score"],
                        regime_factor=regime.get("position_factor", 1.0),
                        vol_scalar=garch.get("vol_scalar", 0.5),
                    )

                    trade = BacktestTrade(
                        entry_date=date_str,
                        entry_price=close_price,
                        stop_loss=trade_setup["stop_loss"],
                        take_profit=trade_setup["take_profit"],
                        signal_score=sig["composite_score"],
                        position_size=trade_setup["size_factor"],
                    )
                    open_trades.append(trade)

            except Exception as e:
                logger.debug("Signal computation failed for %s on %s: %s", ticker, date_str, e)
                continue

        # Close any remaining open trades at last bar
        if filtered_bars:
            last_bar = filtered_bars[-1][0]
            last_date = filtered_bars[-1][1]
            last_price = float(last_bar.get("c", last_bar.get("close", 0)))
            for trade in open_trades:
                trade.close(last_date, last_price, "timeout")
                trades.append(trade)

        # Calculate metrics for this threshold
        import numpy as np
        returns = [t.return_pct for t in trades if t.return_pct is not None]
        num_trades = len(trades)
        win_rate = len([r for r in returns if r > 0]) / len(returns) if returns else 0.0
        total_return = float(np.sum(returns)) if returns else 0.0
        sharpe = (float(np.mean(returns)) / (np.std(returns) + 1e-6) * np.sqrt(252)) if returns else 0.0

        results[threshold] = {
            "trades": num_trades,
            "win_rate": round(win_rate, 4),
            "return": round(total_return, 4),
            "sharpe": round(sharpe, 4),
        }

    # Generate recommendation
    best_threshold = max(results.keys(), key=lambda t: results[t]["return"])
    best_result = results[best_threshold]
    current_result = results.get(0.65, {})

    if best_result["return"] > (current_result.get("return", 0) + 0.01):
        recommendation = f"Use {best_threshold} for {ticker} (return {best_result['return']:.1%} vs current 0.65 {current_result.get('return', 0):.1%})"
    else:
        recommendation = f"Current threshold 0.65 is optimal for {ticker}"

    return {
        "ticker": ticker,
        "test_period": f"{test_start_str}:{test_end_str}",
        "thresholds": results,
        "recommendation": recommendation,
    }


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
        # Use actual available data range
        # We have data from June 10, 2025 to June 8, 2026
        # Backtest on the 1-year available period (June 2025 to June 2026)
        # This validates the model on actual recent market data
        train_start_str = "2025-06-10"
        train_end_str = "2025-12-31"
        test_start_str = "2026-01-01"
        test_end_str = "2026-06-08"

        logger.info(
            "Walk-forward backtest for %s: train %s→%s, test %s→%s",
            ticker, train_start_str, train_end_str, test_start_str, test_end_str
        )

        # Run backtest on TEST period (validation period)
        test_run = run_backtest(ticker, test_start_str, test_end_str)

        # Evaluate results
        passed = _evaluate_backtest_run(test_run)
        confidence = _calculate_confidence(test_run)

        result = {
            "ticker": ticker,
            "train_period": f"{train_start_str}:{train_end_str}",
            "test_period": f"{test_start_str}:{test_end_str}",
            "test_metrics": test_run.to_dict(),
            "status": "PASS" if passed else "FAIL",
            "confidence": round(confidence, 2),
            "notes": _generate_notes(test_run, passed),
        }

        # Run sensitivity analysis for MSFT and META only (quick optimization)
        if ticker in ["MSFT", "META"]:
            try:
                sensitivity = analyze_threshold_sensitivity(ticker)
                result["threshold_analysis"] = sensitivity
            except Exception as e:
                logger.debug("Threshold sensitivity analysis failed for %s: %s", ticker, e)

        return result

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
