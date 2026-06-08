"""
Performance metrics calculation.

Converts raw trade data to performance stats.
"""
import numpy as np
from datetime import datetime


def calculate_cagr(start_value: float, end_value: float, years: float) -> float:
    """
    Calculate Compound Annual Growth Rate.

    CAGR = (End Value / Start Value) ^ (1 / Years) - 1
    """
    if start_value <= 0 or years <= 0:
        return 0.0

    return float((end_value / start_value) ** (1 / years) - 1)


def calculate_sharpe_ratio(returns: list[float], risk_free_rate: float = 0.04) -> float:
    """
    Calculate Sharpe ratio (annualized).

    Assumes returns are daily.
    """
    if not returns or len(returns) < 2:
        return 0.0

    ret_array = np.array(returns)
    excess_returns = ret_array - (risk_free_rate / 252)

    if np.std(excess_returns) == 0:
        return 0.0

    return float(np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252))


def calculate_max_drawdown(prices: list[float]) -> float:
    """
    Calculate maximum drawdown.

    Peak-to-trough decline.
    """
    if not prices or len(prices) < 2:
        return 0.0

    prices = np.array(prices)
    cummax = np.maximum.accumulate(prices)
    drawdown = (prices - cummax) / cummax

    return float(np.min(drawdown))


def calculate_sortino_ratio(returns: list[float], target_return: float = 0.0) -> float:
    """
    Calculate Sortino ratio (downside focus).
    """
    if not returns or len(returns) < 2:
        return 0.0

    ret_array = np.array(returns)
    excess = ret_array - target_return
    downside = np.where(excess < 0, excess, 0)

    downside_std = np.std(downside)
    if downside_std == 0:
        return 0.0

    return float(np.mean(excess) / downside_std * np.sqrt(252))


def compare_to_spy(strategy_returns: list[float], spy_returns: list[float]) -> dict:
    """
    Compare strategy returns to SPY benchmark.

    Returns:
    {
        "strategy_cagr": 0.15,
        "spy_cagr": 0.10,
        "outperformance": 0.05,
        "correlation": 0.65,
        "beta": 1.2,
        "alpha": 0.08,  # Annualized alpha vs SPY
    }
    """
    if not strategy_returns or not spy_returns:
        return {}

    strategy = np.array(strategy_returns)
    spy = np.array(spy_returns)

    # Ensure same length
    min_len = min(len(strategy), len(spy))
    strategy = strategy[:min_len]
    spy = spy[:min_len]

    # CAGR
    strategy_cagr = calculate_cagr(1.0, np.prod(1 + strategy), len(strategy) / 252)
    spy_cagr = calculate_cagr(1.0, np.prod(1 + spy), len(spy) / 252)

    # Correlation
    correlation = float(np.corrcoef(strategy, spy)[0, 1])

    # Beta
    covariance = np.cov(strategy, spy)[0, 1]
    spy_variance = np.var(spy)
    beta = float(covariance / spy_variance) if spy_variance > 0 else 0.0

    # Alpha (Jensen's)
    risk_free = 0.04 / 252
    strategy_excess = np.mean(strategy - risk_free)
    spy_excess = np.mean(spy - risk_free)
    alpha = float((strategy_excess - beta * spy_excess) * 252)

    return {
        "strategy_cagr": round(strategy_cagr, 4),
        "spy_cagr": round(spy_cagr, 4),
        "outperformance": round(strategy_cagr - spy_cagr, 4),
        "correlation": round(correlation, 4),
        "beta": round(beta, 4),
        "alpha": round(alpha, 4),
    }
