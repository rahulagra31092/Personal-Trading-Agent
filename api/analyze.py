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
from smart_money.estimate_revisions import compute_estimate_revision_score
from smart_money.news_scorer import compute_news_score
from smart_money.earnings_scorer import compute_earnings_score
from quant.regime import get_market_regime, get_regime_weights
from util.data_health import record_fetch, get_health_report, get_staleness_warnings
from util.circuit_breaker import record_failure, record_success, should_generate_signals
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
    # Check if circuit breaker is OPEN (halt signal generation)
    if not should_generate_signals():
        raise HTTPException(
            status_code=503,
            detail="Data quality degraded — circuit breaker is OPEN. Retry in 5 minutes."
        )

    ticker = ticker.strip().upper()
    if not _TICKER_RE.match(ticker):
        raise ValueError(f"Invalid ticker format: {ticker!r}")
    if config.is_excluded(ticker):
        raise ValueError(f"{ticker} is excluded from analysis")

    try:
        bars = get_daily_bars(ticker, days=250)
        record_fetch("polygon_bars", success=True)
    except Exception as e:
        record_fetch("polygon_bars", success=False)
        record_failure("polygon_bars", str(e))
        raise

    if len(bars) < 60:
        raise ValueError(f"Insufficient history for {ticker}: {len(bars)} bars (need 60)")

    prices = [b["c"] for b in bars]
    current_price = float(bars[-1]["c"])

    try:
        spy_return_3m = _spy_3m_return()
        record_fetch("spy_bars", success=True)
    except Exception:
        spy_return_3m = None
        record_fetch("spy_bars", success=False)

    ind = compute_indicators(bars, spy_return_3m=spy_return_3m)
    garch = compute_garch_volatility(prices)

    momentum_score = compute_momentum_score(ticker)
    quality_score = compute_quality_score(ticker)
    congress_score = compute_congress_score(ticker)
    estimate_revisions_score = compute_estimate_revision_score(ticker)
    news_score = compute_news_score(ticker)
    earnings_score = compute_earnings_score(ticker)

    regime = get_market_regime()
    regime_weights = get_regime_weights(regime.get("regime", "normal"))

    sig = compute_signal(
        technical_score=ind["technical_score"],
        momentum_score=momentum_score,
        quality_score=quality_score,
        congress_score=congress_score,
        estimate_revisions_score=estimate_revisions_score,
        news_score=news_score,
        earnings_score=earnings_score,
        weights=regime_weights,
    )

    mc = run_monte_carlo(current_price, max(garch["daily_vol"], 0.001))

    # Extract probability of success from Monte Carlo simulation
    prob_success = mc.get("prob_success", 0.5)

    # Pass confidence to position sizing (adjusted by regime factor in paper trading)
    trade_card = compute_trade_setup(current_price, ind["atr_stop"], prob_success=prob_success)

    # Sanitize for JSON: convert inf/nan to None
    def sanitize_for_json(obj):
        if isinstance(obj, float):
            if obj != obj or (obj == float('inf')) or (obj == float('-inf')):
                return None
            return obj
        elif isinstance(obj, dict):
            return {k: sanitize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [sanitize_for_json(x) for x in obj]
        return obj

    mc = sanitize_for_json(mc)
    trade_card = sanitize_for_json(trade_card)

    # Get health report
    health = get_health_report()

    # Record success if we got here
    record_success()

    # Sanitize health sources for JSON serialization (remove infinity values)
    sanitized_sources = {}
    for name, source_data in health["sources"].items():
        sanitized = dict(source_data)
        # Replace infinity age_seconds with None for JSON safety
        if sanitized.get("age_seconds") is None:
            sanitized["age_seconds"] = None
        sanitized_sources[name] = sanitized

    # Build response and sanitize all floats for JSON serialization
    response = {
        "ticker": ticker,
        "signal": sig,
        "confidence": mc,
        "current_price": round(current_price, 2),
        "atr_stop": ind["atr_stop"],
        "vol_regime": garch["vol_regime"],
        "garch_vol_scalar": garch["vol_scalar"],
        "rsi": ind["rsi"],
        "trend_regime": ind["ema_trend"],
        "trade_card": trade_card,
        "market_regime": regime.get("regime", "normal"),
        "vix": regime.get("vix", 0.0),
        "data_health": {
            "sources": sanitized_sources,
            "staleness_warnings": health["staleness_warnings"],
            "is_healthy": health["is_healthy"],
        },
    }

    # Recursively sanitize all float values
    def sanitize_floats(obj):
        if isinstance(obj, float):
            if obj != obj or (obj == float('inf')) or (obj == float('-inf')):
                return None
            return obj
        elif isinstance(obj, dict):
            return {k: sanitize_floats(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [sanitize_floats(x) for x in obj]
        return obj

    return sanitize_floats(response)


@router.get("/analyze/{ticker}")
def get_analyze(ticker: str):
    try:
        return analyze_ticker(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("Analysis failed for %s", ticker)
        raise HTTPException(status_code=500, detail="Internal analysis error. Check server logs.")
