import logging
import yfinance as yf

from data.cache import get_cache, set_cache

logger = logging.getLogger(__name__)

_BETA_CACHE_TTL = 86400  # 24h — beta changes slowly


def get_ticker_beta(ticker: str) -> float:
    """Return market beta from yfinance info. Defaults to 1.0 on failure. Cached 24h."""
    cache_key = f"beta:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return float(cached.get("value", 1.0))
    try:
        beta = yf.Ticker(ticker).info.get("beta")
        result = float(beta) if beta is not None else 1.0
        result = max(0.0, min(5.0, result))  # sanity clamp
        set_cache(cache_key, {"value": result}, ttl_seconds=_BETA_CACHE_TTL)
        return result
    except Exception as exc:
        logger.warning("Beta fetch failed for %s: %s", ticker, exc)
        return 1.0


def compute_portfolio_beta(tickers: list[str]) -> float:
    """Equal-weighted average market beta for the given tickers. Returns 1.0 for empty list."""
    if not tickers:
        return 1.0
    betas = [get_ticker_beta(t) for t in tickers]
    return round(sum(betas) / len(betas), 3)
