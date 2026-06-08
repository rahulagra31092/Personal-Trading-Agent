import pytest
from backtest.engine import BacktestTrade, BacktestRun, run_backtest


def test_backtest_trade_lifecycle():
    """BacktestTrade tracks entry and exit."""
    trade = BacktestTrade(
        entry_date="2026-01-01",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        signal_score=0.7,
        position_size=1.0,
    )

    assert trade.is_open()
    assert trade.return_pct is None

    trade.close("2026-01-15", 110.0, "tp")

    assert not trade.is_open()
    assert trade.exit_price == 110.0
    assert abs(trade.return_pct - 0.10) < 0.001  # 10% gain


def test_backtest_trade_loss():
    """BacktestTrade correctly calculates losses."""
    trade = BacktestTrade(
        entry_date="2026-01-01",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        signal_score=0.6,
        position_size=1.0,
    )

    trade.close("2026-01-10", 95.0, "sl")

    assert abs(trade.return_pct - (-0.05)) < 0.001  # -5% loss


def test_backtest_run_metrics():
    """BacktestRun computes metrics correctly."""
    run = BacktestRun("AAPL", "2024-01-01", "2025-01-01")

    # Add some trades
    t1 = BacktestTrade("2024-01-01", 100.0, 95.0, 110.0, 0.7, 1.0)
    t1.close("2024-01-15", 110.0, "tp")
    run.add_trade(t1)

    t2 = BacktestTrade("2024-02-01", 110.0, 105.0, 121.0, 0.65, 1.0)
    t2.close("2024-02-10", 105.0, "sl")
    run.add_trade(t2)

    run.compute_metrics()

    assert run.total_return is not None
    assert run.win_rate is not None
    assert run.win_rate == 0.5  # 1 win, 1 loss


def test_run_backtest_returns_backtest_run():
    """run_backtest returns BacktestRun object."""
    result = run_backtest("AAPL", "2024-01-01", "2024-06-30")

    assert isinstance(result, BacktestRun)
    assert result.ticker == "AAPL"
    assert result.start_date == "2024-01-01"


def test_backtest_trade_to_dict():
    """BacktestTrade serializes correctly."""
    trade = BacktestTrade(
        entry_date="2026-01-01",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        signal_score=0.7,
        position_size=1.0,
    )

    trade.close("2026-01-15", 110.0, "tp")
    trade_dict = trade.to_dict()

    assert trade_dict["entry_date"] == "2026-01-01"
    assert trade_dict["entry_price"] == 100.0
    assert trade_dict["exit_price"] == 110.0
    assert trade_dict["exit_reason"] == "tp"
    assert "return_pct" in trade_dict


def test_backtest_run_to_dict():
    """BacktestRun serializes correctly."""
    run = BacktestRun("AAPL", "2024-01-01", "2025-01-01")

    t1 = BacktestTrade("2024-01-01", 100.0, 95.0, 110.0, 0.7, 1.0)
    t1.close("2024-01-15", 110.0, "tp")
    run.add_trade(t1)

    run.compute_metrics()
    run_dict = run.to_dict()

    assert run_dict["ticker"] == "AAPL"
    assert run_dict["start_date"] == "2024-01-01"
    assert run_dict["num_trades"] == 1
    assert "total_return" in run_dict


def test_backtest_trade_multiple_returns():
    """BacktestTrade calculates PnL correctly."""
    trade = BacktestTrade(
        entry_date="2026-01-01",
        entry_price=100.0,
        stop_loss=90.0,
        take_profit=120.0,
        signal_score=0.75,
        position_size=2.5,
    )

    trade.close("2026-01-20", 120.0, "tp")

    assert abs(trade.return_pct - 0.20) < 0.001  # 20% return
    assert abs(trade.pnl - 0.5) < 0.001  # 2.5 * 0.20 = 0.5
