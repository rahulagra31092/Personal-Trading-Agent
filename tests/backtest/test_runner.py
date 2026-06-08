import pytest
from backtest.runner import (
    run_walk_forward_backtest,
    _evaluate_backtest_run,
    _calculate_confidence,
    run_portfolio_backtest,
)
from backtest.engine import BacktestRun, BacktestTrade


def test_evaluate_backtest_run_passes():
    """Passing backtest run."""
    run = BacktestRun("AAPL", "2024-01-01", "2024-12-31")

    # Add passing trades
    t1 = BacktestTrade("2024-01-01", 100.0, 95.0, 110.0, 0.7, 1.0)
    t1.close("2024-01-15", 110.0, "tp")
    run.add_trade(t1)

    t2 = BacktestTrade("2024-02-01", 110.0, 105.0, 121.0, 0.75, 1.0)
    t2.close("2024-02-10", 121.0, "tp")
    run.add_trade(t2)

    t3 = BacktestTrade("2024-03-01", 121.0, 110.0, 133.1, 0.68, 1.0)
    t3.close("2024-03-20", 110.0, "sl")
    run.add_trade(t3)

    run.compute_metrics()

    # 2 wins, 1 loss = 67% win rate, passes
    assert _evaluate_backtest_run(run) is True


def test_evaluate_backtest_run_fails_low_win_rate():
    """Failing backtest: win rate too low."""
    run = BacktestRun("AAPL", "2024-01-01", "2024-12-31")

    # Add losing trades
    for i in range(3):
        t = BacktestTrade(f"2024-0{i+1}-01", 100.0, 95.0, 110.0, 0.6, 1.0)
        t.close(f"2024-0{i+1}-10", 95.0, "sl")
        run.add_trade(t)

    run.compute_metrics()

    # 0 wins = 0% win rate, fails
    assert _evaluate_backtest_run(run) is False


def test_evaluate_backtest_run_fails_insufficient_trades():
    """Failing backtest: not enough trades."""
    run = BacktestRun("AAPL", "2024-01-01", "2024-12-31")

    # Only 2 trades
    t1 = BacktestTrade("2024-01-01", 100.0, 95.0, 110.0, 0.7, 1.0)
    t1.close("2024-01-15", 110.0, "tp")
    run.add_trade(t1)

    run.compute_metrics()

    assert _evaluate_backtest_run(run) is False


def test_calculate_confidence():
    """Confidence score calculation."""
    run = BacktestRun("AAPL", "2024-01-01", "2024-12-31")

    # Add trades
    for i in range(10):
        t = BacktestTrade(f"2024-{i:02d}-01", 100.0 + i, 95.0 + i, 110.0 + i, 0.7, 1.0)
        if i % 2 == 0:
            t.close(f"2024-{i:02d}-15", 110.0 + i, "tp")  # Win
        else:
            t.close(f"2024-{i:02d}-10", 98.0 + i, "sl")   # Loss
        run.add_trade(t)

    run.compute_metrics()

    confidence = _calculate_confidence(run)
    assert 0.0 <= confidence <= 1.0
    # 50% win rate, 10 trades → should be moderate confidence
    assert 0.5 < confidence < 0.8


def test_run_walk_forward_backtest_returns_dict():
    """run_walk_forward_backtest returns proper structure."""
    result = run_walk_forward_backtest("AAPL")

    assert isinstance(result, dict)
    assert "ticker" in result
    assert "status" in result
    assert result["ticker"] == "AAPL"
    assert result["status"] in ["PASS", "FAIL", "ERROR"]


def test_run_portfolio_backtest_structure():
    """run_portfolio_backtest returns proper structure."""
    result = run_portfolio_backtest()

    assert "timestamp" in result
    assert "summary" in result
    assert "results" in result

    summary = result["summary"]
    assert "go_nogo" in summary
    assert summary["go_nogo"] in ["GO", "NO-GO"]
    assert "pass_rate" in summary
    assert "avg_confidence" in summary
