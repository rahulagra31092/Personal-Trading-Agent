import logging
import re

from fastapi import APIRouter, HTTPException

from data.market import get_daily_bars
from quant.indicators import compute_indicators
from quant.forecast import compute_arima_score, compute_garch_volatility
from quant.signals import compute_signal
from quant.confidence import run_monte_carlo
from quant.trade_setup import compute_trade_setup
from smart_money.congress import compute_congress_score
from smart_money.news_scorer import compute_news_score
from smart_money.earnings_scorer import compute_earnings_score
import config

logger = logging.getLogger(__name__)

router = APIRouter()

_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")


def analyze_ticker(ticker: str) -> dict:
    ticker = ticker.strip().upper()
    if not _TICKER_RE.match(ticker):
        raise ValueError(f"Invalid ticker format: {ticker!r}")
    if config.is_excluded(ticker):
        raise ValueError(f"{ticker} is excluded from analysis")

    bars = get_daily_bars(ticker, days=250)
    if len(bars) < 60:
        raise ValueError(f"Insufficient history for {ticker}: {len(bars)} bars (need 60)")

    prices = [b["c"] for b in bars]
    current_price = float(bars[-1]["c"])

    ind = compute_indicators(bars)
    fcast = compute_arima_score(prices)
    garch = compute_garch_volatility(prices)

    smart_money_score = compute_congress_score(ticker)
    news_score = compute_news_score(ticker)
    earnings_score = compute_earnings_score(ticker)

    sig = compute_signal(
        technical_score=ind["technical_score"],
        arima_score=fcast["arima_score"],
        smart_money_score=smart_money_score,
        news_score=news_score,
        earnings_score=earnings_score,
    )

    mc = run_monte_carlo(current_price, max(garch["daily_vol"], 0.001))
    trade_card = compute_trade_setup(current_price, ind["atr_stop"])

    return {
        "ticker": ticker,
        "signal": sig,
        "confidence": mc,
        "current_price": round(current_price, 2),
        "atr_stop": ind["atr_stop"],
        "vol_regime": garch["vol_regime"],
        "rsi": ind["rsi"],
        "trend_regime": ind["ema_trend"],
        "trade_card": trade_card,
    }


@router.get("/analyze/{ticker}")
def get_analyze(ticker: str):
    try:
        return analyze_ticker(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("Analysis failed for %s", ticker)
        raise HTTPException(status_code=500, detail="Internal analysis error. Check server logs.")
