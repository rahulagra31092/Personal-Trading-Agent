import math
import logging

from quant.indicators import compute_indicators
from quant.signals import compute_signal

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252  # US equity market convention


def run_backtest(
    ticker: str,
    bars: list[dict],
    min_bars: int = 30,
    hold_days: int = 5,
) -> dict:
    signals_log = []

    for i in range(min_bars, len(bars) - hold_days):
        history = bars[:i]  # lookahead-safe: only data available at bar i
        prices = [b["c"] for b in history]
        try:
            ind = compute_indicators(history)
            sig = compute_signal(technical_score=ind["technical_score"])
        except Exception as exc:
            logger.debug("Skipping bar %d: %s", i, exc)
            continue

        if sig["label"] == "WATCH":
            continue

        signal_price = float(bars[i]["c"])
        future_price = float(bars[i + hold_days]["c"])
        if sig["label"] == "BUY":
            strategy_return = (future_price - signal_price) / signal_price
        else:  # AVOID
            strategy_return = (signal_price - future_price) / signal_price

        signals_log.append({
            "label": sig["label"],
            "signal_price": signal_price,
            "future_price": future_price,
            "return_pct": round(strategy_return, 6),
            "correct": strategy_return > 0,
            "bar_i": i,
        })

    if not signals_log:
        return {
            "ticker": ticker,
            "total_signals": 0,
            "win_rate": 0.0,
            "correct_signals": 0,
            "avg_return_pct": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "cagr": 0.0,
        }

    rets = [s["return_pct"] for s in signals_log]
    total = len(signals_log)
    correct_count = sum(1 for s in signals_log if s["correct"])
    avg_ret = sum(rets) / total

    # Annualised Sharpe: scale per-trade returns to 252-day year
    periods_per_year = TRADING_DAYS_PER_YEAR / hold_days
    if total > 1:
        variance = sum((r - avg_ret) ** 2 for r in rets) / (total - 1)
        std_ret = math.sqrt(variance)
        # Rf=0 assumed; adjust TRADING_DAYS_PER_YEAR constant if comparing against benchmarks
        sharpe = round(avg_ret / std_ret * math.sqrt(periods_per_year), 4) if std_ret > 0 else 0.0
    else:
        sharpe = 0.0

    # Build equity curve → max drawdown and CAGR
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in rets:
        equity *= (1.0 + r)
        if equity > peak:
            peak = equity
        dd = min((peak - equity) / peak, 1.0) if equity > 0 else 1.0
        if dd > max_dd:
            max_dd = dd

    # Use actual bar span (first to last) not overlapping windows
    first_bar = signals_log[0]["bar_i"]
    last_bar = signals_log[-1]["bar_i"]
    elapsed_trading_days = (last_bar - first_bar) + hold_days
    if equity > 0 and elapsed_trading_days > 0:
        cagr = round((equity ** (TRADING_DAYS_PER_YEAR / elapsed_trading_days)) - 1.0, 4)
    else:
        cagr = 0.0

    return {
        "ticker": ticker,
        "total_signals": total,
        "win_rate": round(correct_count / total, 4),
        "correct_signals": correct_count,
        "avg_return_pct": round(avg_ret, 4),
        "sharpe_ratio": sharpe,
        "max_drawdown": round(max_dd, 4),
        "cagr": cagr,
    }
