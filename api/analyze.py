import logging
import re

from fastapi import APIRouter, HTTPException

from data.market import get_daily_bars
from quant.indicators import compute_indicators
from quant.forecast import compute_garch_volatility
from quant.momentum import compute_momentum_score
from quant.quality import compute_quality_score
from quant.signals import compute_signal
from quant.confidence import run_monte_carlo
from quant.trade_setup import compute_trade_setup
from smart_money.congress import compute_congress_score
from smart_money.trump_scorer import compute_trump_policy_score
from smart_money.news_scorer import compute_news_score
from smart_money.earnings_scorer import compute_earnings_score
from quant.regime import get_market_regime, get_regime_weights
import config

logger = logging.getLogger(__name__)

router = APIRouter()


def _spy_3m_return() -> float | None:
    try:
        spy_bars = get_daily_bars("SPY", days=250)
        if len(spy_bars) < 64:
            return None
        start = float(spy_bars[-64]["c"])
        end = float(spy_bars[-1]["c"])
        return (end - start) / start if start > 0 else None
    except Exception:
        return None

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

    spy_return_3m = _spy_3m_return()
    ind = compute_indicators(bars, spy_return_3m=spy_return_3m)
    garch = compute_garch_volatility(prices)

    momentum_score = compute_momentum_score(ticker)
    quality_score = compute_quality_score(ticker)
    congress_score = compute_congress_score(ticker)
    trump_policy_score = compute_trump_policy_score(ticker)
    news_score = compute_news_score(ticker)
    earnings_score = compute_earnings_score(ticker)

    regime = get_market_regime()
    regime_weights = get_regime_weights(regime.get("regime", "normal"))

    sig = compute_signal(
        technical_score=ind["technical_score"],
        momentum_score=momentum_score,
        quality_score=quality_score,
        congress_score=congress_score,
        trump_policy_score=trump_policy_score,
        news_score=news_score,
        earnings_score=earnings_score,
        weights=regime_weights,
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
        "market_regime": regime.get("regime", "normal"),
        "vix": regime.get("vix", 0.0),
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
