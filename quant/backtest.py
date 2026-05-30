import logging

from quant.indicators import compute_indicators
from quant.forecast import compute_arima_score
from quant.signals import compute_signal

logger = logging.getLogger(__name__)


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
            fcast = compute_arima_score(prices)
            sig = compute_signal(
                technical_score=ind["technical_score"],
                arima_score=fcast["arima_score"],
            )
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
        })

    if not signals_log:
        return {"ticker": ticker, "total_signals": 0, "win_rate": 0.0,
                "correct_signals": 0, "avg_return_pct": 0.0}

    total = len(signals_log)
    correct_count = sum(1 for s in signals_log if s["correct"])
    return {
        "ticker": ticker,
        "total_signals": total,
        "win_rate": round(correct_count / total, 4),
        "correct_signals": correct_count,
        "avg_return_pct": round(sum(s["return_pct"] for s in signals_log) / total, 4),
    }
