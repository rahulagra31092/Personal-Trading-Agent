"""
Backtesting engine for walk-forward validation.

Tests the 7-signal trading model on historical data:
- technical, momentum, quality, insider_trades, estimate_revisions, earnings

Walk-forward approach:
- Train period: 2 years (learn market regime)
- Test period: 1 year (validate signals)
- Rolling: step forward 3 months, repeat
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np

from data.market import get_daily_bars
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

logger = logging.getLogger(__name__)

_ET = timezone(timedelta(hours=-5))


class BacktestTrade:
    """Single trade in backtest."""

    def __init__(
        self,
        entry_date: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        signal_score: float,
        position_size: float,
    ):
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.signal_score = signal_score
        self.position_size = position_size

        self.exit_date: Optional[str] = None
        self.exit_price: Optional[float] = None
        self.exit_reason: Optional[str] = None  # "tp" (take profit), "sl" (stop loss), "timeout"
        self.pnl: Optional[float] = None
        self.return_pct: Optional[float] = None

    def close(self, exit_date: str, exit_price: float, reason: str):
        """Close the trade."""
        self.exit_date = exit_date
        self.exit_price = exit_price
        self.exit_reason = reason

        # Calculate return
        gross_return = (exit_price - self.entry_price) / self.entry_price
        self.return_pct = gross_return
        self.pnl = gross_return * self.position_size

    def is_open(self) -> bool:
        return self.exit_date is None

    def to_dict(self) -> dict:
        return {
            "entry_date": self.entry_date,
            "entry_price": self.entry_price,
            "exit_date": self.exit_date,
            "exit_price": self.exit_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "signal_score": round(self.signal_score, 4),
            "position_size": round(self.position_size, 4),
            "return_pct": round(self.return_pct, 4) if self.return_pct else None,
            "pnl": round(self.pnl, 4) if self.pnl else None,
            "exit_reason": self.exit_reason,
        }


class BacktestRun:
    """Single backtest run (train + test period)."""

    def __init__(self, ticker: str, start_date: str, end_date: str):
        self.ticker = ticker
        self.start_date = start_date
        self.end_date = end_date

        self.trades: list[BacktestTrade] = []
        self.daily_signals: list[dict] = []  # Signals for each date
        self.returns: list[float] = []  # Portfolio returns

        self.total_return: Optional[float] = None
        self.sharpe_ratio: Optional[float] = None
        self.max_drawdown: Optional[float] = None
        self.win_rate: Optional[float] = None
        self.avg_win: Optional[float] = None
        self.avg_loss: Optional[float] = None

    def add_trade(self, trade: BacktestTrade):
        self.trades.append(trade)

    def add_daily_signal(self, date: str, signal: dict):
        """Record signal for a date."""
        self.daily_signals.append({
            "date": date,
            "composite_score": signal.get("composite_score"),
            "label": signal.get("label"),
        })

    def compute_metrics(self):
        """Calculate backtest metrics."""
        if not self.trades:
            self.total_return = 0.0
            self.sharpe_ratio = 0.0
            self.max_drawdown = 0.0
            self.win_rate = 0.0
            return

        # Return calculation
        returns = [t.return_pct for t in self.trades if t.return_pct is not None]
        if returns:
            self.total_return = float(np.sum(returns))
            self.sharpe_ratio = (
                float(np.mean(returns)) / (np.std(returns) + 1e-6) * np.sqrt(252)
            )
            self.max_drawdown = float(np.min(returns)) if returns else 0.0

        # Win rate
        wins = [r for r in returns if r > 0]
        self.win_rate = len(wins) / len(returns) if returns else 0.0

        # Avg win/loss
        if wins:
            self.avg_win = float(np.mean(wins))
        losses = [r for r in returns if r <= 0]
        if losses:
            self.avg_loss = float(np.mean(losses))

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "num_trades": len(self.trades),
            "total_return": round(self.total_return, 4) if self.total_return else None,
            "sharpe_ratio": round(self.sharpe_ratio, 4) if self.sharpe_ratio else None,
            "max_drawdown": round(self.max_drawdown, 4) if self.max_drawdown else None,
            "win_rate": round(self.win_rate, 4) if self.win_rate else None,
            "avg_win": round(self.avg_win, 4) if self.avg_win else None,
            "avg_loss": round(self.avg_loss, 4) if self.avg_loss else None,
            "trades": [t.to_dict() for t in self.trades[:10]],  # First 10 trades
        }


def run_backtest(ticker: str, start_date: str, end_date: str) -> BacktestRun:
    """
    Run backtest on a ticker from start_date to end_date.

    Algorithm:
    1. Load all daily bars
    2. For each date:
       a. Compute all 7 signals
       b. Composite score
       c. Generate BUY/AVOID signal
       d. If BUY: Enter position, set stop/target
       e. If bar hits stop or target: Close position
    3. Calculate metrics
    """
    from datetime import datetime as dt

    ticker = ticker.strip().upper()
    backtest = BacktestRun(ticker, start_date, end_date)

    try:
        bars = get_daily_bars(ticker, days=1095)  # 3 years
    except Exception as e:
        logger.warning("Failed to load bars for %s: %s", ticker, e)
        return backtest

    if len(bars) < 60:
        logger.warning("Insufficient history for %s: %d bars", ticker, len(bars))
        return backtest

    # Convert start/end dates to comparable format
    start_dt = dt.strptime(start_date, "%Y-%m-%d")
    end_dt = dt.strptime(end_date, "%Y-%m-%d")

    # Filter to date range - handle both 't' (unix timestamp) and 'date' (string)
    filtered_bars = []
    for bar in bars:
        if "t" in bar:  # Unix timestamp in milliseconds
            bar_dt = dt.fromtimestamp(bar["t"] / 1000)
            bar_date_str = bar_dt.strftime("%Y-%m-%d")
        elif "date" in bar:
            bar_date_str = bar["date"][:10]
            bar_dt = dt.strptime(bar_date_str, "%Y-%m-%d")
        else:
            continue

        if start_dt <= bar_dt <= end_dt:
            filtered_bars.append((bar, bar_date_str))

    bars = filtered_bars

    if not bars:
        logger.warning("No bars in range %s-%s for %s", start_date, end_date, ticker)
        return backtest

    open_trades: list[BacktestTrade] = []

    for i, (bar, date_str) in enumerate(bars):
        # date_str is already extracted above
        close_price = float(bar.get("c", bar.get("close", 0)))

        # Check if open trades hit stop/target
        for trade in list(open_trades):
            high = float(bar.get("h", bar.get("high", close_price)))
            low = float(bar.get("l", bar.get("low", close_price)))

            # Take profit
            if high >= trade.take_profit:
                trade.close(date_str, trade.take_profit, "tp")
                backtest.add_trade(trade)
                open_trades.remove(trade)
                continue

            # Stop loss
            if low <= trade.stop_loss:
                trade.close(date_str, trade.stop_loss, "sl")
                backtest.add_trade(trade)
                open_trades.remove(trade)
                continue

            # Timeout (hold 20 days)
            if (datetime.fromisoformat(date_str) - datetime.fromisoformat(trade.entry_date)).days > 20:
                trade.close(date_str, close_price, "timeout")
                backtest.add_trade(trade)
                open_trades.remove(trade)

        # Compute signals for this date
        try:
            # Get indicators (extract actual bar dicts from tuples)
            recent_bars_tuples = bars[max(0, i-60):i+1]
            recent_bars = [b[0] for b in recent_bars_tuples]  # Extract bar dict from (bar, date_str) tuple
            if len(recent_bars) < 20:
                continue

            ind = compute_indicators(recent_bars)
            garch = compute_garch_volatility([float(b.get("c", b.get("close", 0))) for b in recent_bars])

            # Get smart money scores - use defaults if computation fails
            try:
                momentum_score = compute_momentum_score(ticker)
            except Exception as e:
                logger.debug("Failed to compute momentum score: %s", e)
                momentum_score = 0.5

            try:
                quality_score = compute_quality_score(ticker)
            except Exception as e:
                logger.debug("Failed to compute quality score: %s", e)
                quality_score = 0.5

            try:
                insider_score = compute_insider_trades_score(ticker)
            except Exception as e:
                logger.debug("Failed to compute insider trades score: %s", e)
                insider_score = 0.5

            try:
                estimate_score = compute_estimate_revision_score(ticker)
            except Exception as e:
                logger.debug("Failed to compute estimate revision score: %s", e)
                estimate_score = 0.5

            try:
                earnings_score = compute_earnings_score(ticker)
            except Exception as e:
                logger.debug("Failed to compute earnings score: %s", e)
                earnings_score = 0.5

            # Get regime weights
            try:
                regime = get_market_regime()
            except Exception as e:
                logger.debug("Failed to get market regime: %s", e)
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

            backtest.add_daily_signal(date_str, sig)

            # Entry logic: BUY only if no open trades and high conviction
            if not open_trades and sig["composite_score"] > 0.65:
                # Trade setup
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
    if bars:
        last_bar_tuple = bars[-1]
        last_bar = last_bar_tuple[0]  # Extract bar dict from tuple
        last_date = last_bar_tuple[1]  # Extract date string from tuple
        last_price = float(last_bar.get("c", last_bar.get("close", 0)))
        for trade in open_trades:
            trade.close(last_date, last_price, "timeout")
            backtest.add_trade(trade)

    # Calculate metrics
    backtest.compute_metrics()

    return backtest
