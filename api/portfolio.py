import logging

from fastapi import APIRouter

from data.holdings import load_holdings
from data.market import get_daily_bars
from quant.indicators import compute_indicators

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/portfolio/pnl")
def get_portfolio_pnl():
    holdings = load_holdings()
    if not holdings:
        return {
            "positions": [],
            "total_value": 0.0,
            "total_cost": 0.0,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
        }

    positions = []
    total_value = 0.0
    total_cost = 0.0

    for h in holdings:
        ticker = h["ticker"]
        shares = h["shares"]
        cost_basis = h["cost_basis"]

        current_price = None
        atr_stop = None
        below_stop = None

        try:
            bars = get_daily_bars(ticker, days=30)
            current_price = float(bars[-1]["c"])
            ind = compute_indicators(bars)
            atr_stop = ind["atr_stop"]
            below_stop = current_price < atr_stop
        except Exception as exc:
            logger.warning("Could not fetch live data for %s: %s", ticker, exc)

        position_cost = cost_basis * shares
        position_value = (current_price or 0.0) * shares
        pnl = position_value - position_cost
        pnl_pct = round(pnl / position_cost * 100, 2) if position_cost > 0 else 0.0

        total_value += position_value
        total_cost += position_cost

        positions.append({
            "ticker": ticker,
            "shares": shares,
            "cost_basis": cost_basis,
            "current_price": round(current_price, 2) if current_price is not None else None,
            "value": round(position_value, 2),
            "cost": round(position_cost, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": pnl_pct,
            "atr_stop": round(atr_stop, 2) if atr_stop is not None else None,
            "below_stop": below_stop,
        })

    total_pnl = total_value - total_cost
    total_pnl_pct = round(total_pnl / total_cost * 100, 2) if total_cost > 0 else 0.0

    return {
        "positions": positions,
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": total_pnl_pct,
    }
