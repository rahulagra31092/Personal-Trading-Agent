import yfinance as yf
from polygon import RESTClient
from datetime import date, timedelta
from data.cache import get_cache, set_cache
import config


def get_daily_bars(ticker: str, days: int = 30) -> list[dict]:
    if config.is_excluded(ticker):
        raise ValueError(f"{ticker} is excluded from analysis")

    cache_key = f"bars:{ticker}:{days}"
    cached = get_cache(cache_key)
    if cached:
        return cached

    client = RESTClient(config.POLYGON_API_KEY)
    end = date.today()
    start = end - timedelta(days=days * 2)

    bars = [
        {"t": b.timestamp, "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume}
        for b in client.list_aggs(ticker, 1, "day", str(start), str(end))
    ]

    result = bars[-days:] if len(bars) >= days else bars
    set_cache(cache_key, result, ttl_seconds=3600)
    return result


def get_historical_prices(ticker: str, years: int = 2) -> list[dict]:
    if config.is_excluded(ticker):
        raise ValueError(f"{ticker} is excluded from analysis")

    cache_key = f"hist:{ticker}:{years}"
    cached = get_cache(cache_key)
    if cached:
        return cached

    hist = yf.Ticker(ticker).history(period=f"{years}y", auto_adjust=True)
    result = [
        {"date": str(idx.date()), "open": row.Open, "high": row.High,
         "low": row.Low, "close": row.Close, "volume": row.Volume}
        for idx, row in hist.iterrows()
    ]
    set_cache(cache_key, result, ttl_seconds=86400)
    return result


def get_crypto_price(symbol: str) -> float:
    cache_key = f"crypto:{symbol}"
    cached = get_cache(cache_key)
    if cached:
        return cached["price"]

    hist = yf.Ticker(f"{symbol}-USD").history(period="1d")
    if hist.empty:
        raise ValueError(f"No price data for {symbol}")

    price = float(hist["Close"].iloc[-1])
    set_cache(cache_key, {"price": price}, ttl_seconds=300)
    return price
