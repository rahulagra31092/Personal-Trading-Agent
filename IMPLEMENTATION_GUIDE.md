# Data Resilience Implementation Guide
## Quick-Reference for Phase 1 Critical Fixes

---

## Fix 1: Polygon → yfinance Fallback (2 hours)

**File:** `data/market.py`

**Current Code:**
```python
def get_daily_bars(ticker: str, days: int = 30) -> list[dict]:
    ticker = ticker.strip().upper()
    if config.is_excluded(ticker):
        raise ValueError(f"{ticker} is excluded from analysis")

    cache_key = f"bars:{ticker}:{days}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    client = RESTClient(config.POLYGON_API_KEY)
    end = date.today()
    start = end - timedelta(days=days * 2)

    bars = [
        {"t": b.timestamp, "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume}
        for b in client.list_aggs(ticker, 1, "day", str(start), str(end))
    ]
    if not bars:
        raise ValueError(f"No bars returned for {ticker}")

    result = bars[-days:] if len(bars) >= days else bars
    set_cache(cache_key, result, ttl_seconds=3600)
    return result
```

**Proposed Change:**
```python
import logging
import yfinance as yf
from polygon import RESTClient

logger = logging.getLogger(__name__)

def get_daily_bars(ticker: str, days: int = 30) -> list[dict]:
    """
    Fetch daily OHLCV bars.
    Primary: Polygon API (faster, more reliable)
    Fallback: yfinance (free, always available)
    """
    ticker = ticker.strip().upper()
    if config.is_excluded(ticker):
        raise ValueError(f"{ticker} is excluded from analysis")

    cache_key = f"bars:{ticker}:{days}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    # Try Polygon first
    if config.POLYGON_API_KEY:
        try:
            bars = _fetch_bars_polygon(ticker, days)
            if bars:
                set_cache(cache_key, bars, ttl_seconds=3600)
                logger.info(f"get_daily_bars({ticker}): Polygon primary source")
                return bars
        except Exception as exc:
            logger.warning(f"get_daily_bars({ticker}): Polygon failed, trying yfinance fallback: {exc}")
    
    # Fallback to yfinance
    try:
        bars = _fetch_bars_yfinance(ticker, days)
        if bars:
            set_cache(cache_key, bars, ttl_seconds=3600)
            logger.info(f"get_daily_bars({ticker}): yfinance fallback source")
            return bars
    except Exception as exc:
        logger.error(f"get_daily_bars({ticker}): yfinance fallback also failed: {exc}")
    
    raise ValueError(f"No bars available for {ticker} from any source")

def _fetch_bars_polygon(ticker: str, days: int) -> list[dict] | None:
    """Polygon API with timeout."""
    import signal
    
    def timeout_handler(signum, frame):
        raise TimeoutError("Polygon API timeout (>15s)")
    
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(15)  # 15-second timeout
    
    try:
        client = RESTClient(config.POLYGON_API_KEY)
        end = date.today()
        start = end - timedelta(days=days * 2)
        
        bars = [
            {"t": b.timestamp, "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume}
            for b in client.list_aggs(ticker, 1, "day", str(start), str(end))
        ]
        signal.alarm(0)
        
        if not bars:
            return None
        return bars[-days:] if len(bars) >= days else bars
    
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

def _fetch_bars_yfinance(ticker: str, days: int) -> list[dict] | None:
    """yfinance fallback with timeout."""
    import signal
    
    def timeout_handler(signum, frame):
        raise TimeoutError("yfinance timeout (>15s)")
    
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(15)
    
    try:
        # Fetch 2x the days to ensure we get enough history
        hist = yf.Ticker(ticker).history(period=f"{days * 2}d", auto_adjust=True)
        signal.alarm(0)
        
        if hist.empty:
            return None
        
        bars = [
            {
                "t": pd.Timestamp(idx).timestamp() * 1000,  # Convert to milliseconds like Polygon
                "o": row.Open,
                "h": row.High,
                "l": row.Low,
                "c": row.Close,
                "v": row.Volume,
            }
            for idx, row in hist.iterrows()
        ]
        
        return bars[-days:] if len(bars) >= days else bars
    
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
```

**Tests to Add:**
```python
# tests/data/test_market.py

def test_get_daily_bars_uses_polygon_when_available():
    """Verify Polygon is primary source."""
    with patch("data.market.config.POLYGON_API_KEY", "test_key"), \
         patch("data.market._fetch_bars_polygon", return_value=_FAKE_BARS) as mock_poly:
        bars = get_daily_bars("AAPL")
        assert mock_poly.called
        assert len(bars) == len(_FAKE_BARS)

def test_get_daily_bars_falls_back_to_yfinance_on_polygon_timeout():
    """Verify yfinance fallback when Polygon times out."""
    with patch("data.market._fetch_bars_polygon", side_effect=TimeoutError("timeout")), \
         patch("data.market._fetch_bars_yfinance", return_value=_FAKE_BARS) as mock_yf:
        bars = get_daily_bars("AAPL")
        assert mock_yf.called
        assert len(bars) == len(_FAKE_BARS)

def test_get_daily_bars_raises_when_both_fail():
    """Verify error when all sources fail."""
    with patch("data.market._fetch_bars_polygon", side_effect=Exception("failed")), \
         patch("data.market._fetch_bars_yfinance", side_effect=Exception("failed")):
        with pytest.raises(ValueError, match="No bars available"):
            get_daily_bars("AAPL")
```

---

## Fix 2: yfinance Timeout Enforcement (3 hours)

**File:** `quant/momentum.py` (and similar in quality.py, earnings.py, estimate_revisions.py)

**Current Code (problematic):**
```python
def _blended_score(closes: list[float]) -> float:
    """Multi-timeframe momentum..."""
    weights = [(_LOOKBACK_12M, 0.50), (_LOOKBACK_6M, 0.30), (_LOOKBACK_3M, 0.20)]
    # ...

def compute_momentum_score(ticker: str) -> float:
    """
    Multi-timeframe momentum with skip-adjusted returns.
    [...]
    """
    cache_key = f"momentum:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    try:
        bars = get_daily_bars(ticker, days=250)  # Already has timeout from market.py
        # ... compute score ...
        return score
    except Exception as exc:
        logger.warning("momentum score failed for %s: %s", ticker, exc)
        return 0.5
```

**Problem:** `get_daily_bars()` calls yfinance fallback which can still hang.

**Better Approach: Create timeout wrapper utility**

**File:** `util/timeout.py` (NEW)
```python
import signal
import logging
from typing import Callable, TypeVar, Optional

logger = logging.getLogger(__name__)

T = TypeVar('T')

class TimeoutError(Exception):
    pass

def call_with_timeout(
    fn: Callable[..., T],
    timeout_seconds: int = 15,
    component_name: str = "api_call",
) -> T:
    """
    Execute a function with a hard timeout.
    
    Args:
        fn: Function to call (no args; use lambda if needed)
        timeout_seconds: Timeout in seconds
        component_name: Name for logging/errors
    
    Returns:
        Result of fn()
    
    Raises:
        TimeoutError: If fn() exceeds timeout
    
    Example:
        hist = call_with_timeout(
            fn=lambda: yf.Ticker("AAPL").history(period="1y"),
            timeout_seconds=15,
            component_name="yfinance_1y_history"
        )
    """
    
    def timeout_handler(signum, frame):
        raise TimeoutError(f"{component_name} exceeded {timeout_seconds}s timeout")
    
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout_seconds)
    
    try:
        result = fn()
        signal.alarm(0)  # Cancel timeout
        logger.debug(f"{component_name}: completed within {timeout_seconds}s")
        return result
    except TimeoutError as e:
        signal.alarm(0)
        logger.error(f"{component_name}: {e}")
        raise
    finally:
        signal.signal(signal.SIGALRM, old_handler)
```

**Update momentum.py:**
```python
from util.timeout import call_with_timeout

def compute_momentum_score(ticker: str) -> float:
    """Multi-timeframe momentum with skip-adjusted returns."""
    cache_key = f"momentum:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    try:
        # Timeout-wrapped yfinance call
        bars = call_with_timeout(
            fn=lambda: get_daily_bars(ticker, days=250),
            timeout_seconds=15,
            component_name=f"momentum_bars_{ticker}"
        )
        
        closes = [b["c"] for b in bars]
        score = _blended_score(closes)
        set_cache(cache_key, score, ttl_seconds=86400)
        return score
    
    except TimeoutError:
        logger.error(f"momentum score timeout for {ticker}")
        return 0.5
    except Exception as exc:
        logger.warning(f"momentum score failed for {ticker}: {exc}")
        return 0.5
```

**Similarly update:**
- `quant/quality.py` → wrap `yf.Ticker(ticker).info` calls
- `data/earnings.py` → wrap `yf.Ticker(ticker).calendar` and `.earnings_history` calls
- `smart_money/estimate_revisions.py` → wrap `yf.Ticker(ticker).upgrades_downgrades` calls

---

## Fix 3: Congress Trades Fallback (4 hours)

**File:** `smart_money/congress.py`

**Current Code:**
```python
def get_congress_trades(ticker: str) -> list[dict]:
    ticker = ticker.strip().upper()
    cache_key = f"congress:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    if not _QUIVER_API_KEY:
        return []

    try:
        resp = requests.get(
            f"{_QUIVER_BASE}/historical/congresstrading/{ticker}",
            headers={"Authorization": f"Token {_QUIVER_API_KEY}"},
            timeout=10,
        )
        resp.raise_for_status()
        trades = resp.json()
    except Exception as exc:
        logger.warning("Congress trades fetch failed for %s: %s", ticker, exc)
        return []

    set_cache(cache_key, trades, ttl_seconds=6 * 3600)
    return trades
```

**Proposed Change (add SEC EDGAR fallback):**
```python
def get_congress_trades(ticker: str) -> list[dict]:
    """
    Fetch congressional trades.
    Primary: Quiver Quantum API (faster, pre-aggregated)
    Fallback: SEC EDGAR filings (slower, always available)
    """
    ticker = ticker.strip().upper()
    cache_key = f"congress:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    trades = []
    
    # Try Quiver first
    if _QUIVER_API_KEY:
        trades = _fetch_congress_trades_quiver(ticker)
        if trades:
            logger.info(f"Congress trades({ticker}): Quiver primary source")
            set_cache(cache_key, trades, ttl_seconds=6 * 3600)
            return trades
        logger.warning(f"Congress trades({ticker}): Quiver empty or failed; trying EDGAR fallback")
    
    # Fallback to SEC EDGAR
    try:
        trades = _fetch_congress_trades_edgar(ticker)
        if trades:
            logger.info(f"Congress trades({ticker}): SEC EDGAR fallback source")
            set_cache(cache_key, trades, ttl_seconds=6 * 3600)
            return trades
    except Exception as exc:
        logger.error(f"Congress trades({ticker}): EDGAR fallback failed: {exc}")
    
    logger.warning(f"Congress trades({ticker}): no trades found from any source")
    return []

def _fetch_congress_trades_quiver(ticker: str) -> list[dict]:
    """Quiver API with timeout."""
    if not _QUIVER_API_KEY:
        return []
    
    try:
        resp = requests.get(
            f"{_QUIVER_BASE}/historical/congresstrading/{ticker}",
            headers={"Authorization": f"Token {_QUIVER_API_KEY}"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.debug(f"_fetch_congress_trades_quiver({ticker}): {exc}")
        return []

def _fetch_congress_trades_edgar(ticker: str) -> list[dict]:
    """
    Fallback: SEC EDGAR Form 4 filings for insider trading.
    
    Returns normalized trades like Quiver format:
    [
        {
            "Date": "2026-06-03",
            "Representative": "John Smith",
            "Transaction": "Purchase",
            "Range": "$50,001-$100,000"
        },
        ...
    ]
    """
    try:
        # Simple approach: use sec-filings library or SEC Edgar API
        # For now, returns empty (requires external API or HTML scraping)
        # This is a placeholder for future implementation
        logger.debug(f"_fetch_congress_trades_edgar({ticker}): not yet implemented")
        return []
    except Exception as exc:
        logger.warning(f"_fetch_congress_trades_edgar({ticker}): {exc}")
        return []
```

**Note:** Full EDGAR implementation requires additional work:
- Option A: Use `sec-filings` library (needs pip install)
- Option B: Parse SEC Edgar HTML directly (fragile)
- Option C: Use paid SEC data API like Intrinio or Quiver for full fallback

For MVP, returning empty list is acceptable (score defaults to 0.5 neutral).

---

## Fix 4: Earnings Cache TTL Reduction (2 hours)

**File:** `data/earnings.py`

**Current Code:**
```python
def get_earnings_calendar(ticker: str) -> dict:
    cache_key = f"earnings:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    t = yf.Ticker(ticker)
    info = t.info or {}

    result: dict = {
        "next_earnings_date": None,
        "eps_estimate": info.get("forwardEps"),
        "earnings_quarterly_growth": info.get("earningsQuarterlyGrowth"),
        **_calculate_eps_stats(t),
    }

    try:
        cal = t.calendar
        if cal is not None and not cal.empty and "Earnings Date" in cal.index:
            raw = cal.loc["Earnings Date"].iloc[0]
            if pd.notna(raw):
                ts = pd.Timestamp(raw)
                result["next_earnings_date"] = str(
                    ts.tz_convert(_ET).date() if ts.tzinfo else ts.date()
                )
    except Exception:
        pass

    set_cache(cache_key, result, ttl_seconds=86400)  # 24 hours
    return result
```

**Proposed Change:**
```python
def get_earnings_calendar(ticker: str) -> dict:
    """
    Fetch earnings calendar (date, EPS, growth).
    
    TTL reduced from 24h to 6h because:
    - Earnings dates announced mid-day frequently
    - Pre-earnings modifiers need fresh dates
    - Backward-looking stats (history) change rarely
    """
    cache_key = f"earnings:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        # Validate cached data isn't stale for pre-earnings modifiers
        if not _is_earnings_data_stale(cached):
            return cached
        logger.info(f"earnings_calendar({ticker}): cached data is stale; refreshing")

    t = None
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        result: dict = {
            "next_earnings_date": None,
            "eps_estimate": info.get("forwardEps"),
            "earnings_quarterly_growth": info.get("earningsQuarterlyGrowth"),
            **_calculate_eps_stats(t),
            "_fetched_at": time.time(),  # Track when data was fetched
        }

        try:
            cal = t.calendar
            if cal is not None and not cal.empty and "Earnings Date" in cal.index:
                raw = cal.loc["Earnings Date"].iloc[0]
                if pd.notna(raw):
                    ts = pd.Timestamp(raw)
                    result["next_earnings_date"] = str(
                        ts.tz_convert(_ET).date() if ts.tzinfo else ts.date()
                    )
        except Exception:
            pass

        # Reduced from 86400 (24h) to 21600 (6h)
        set_cache(cache_key, result, ttl_seconds=21600)
        return result
    
    except Exception as exc:
        logger.error(f"earnings_calendar({ticker}): {exc}")
        # If yfinance fails, return cached even if stale
        if cached:
            logger.warning(f"earnings_calendar({ticker}): returning stale cache due to error")
            return cached
        raise

def _is_earnings_data_stale(cached: dict) -> bool:
    """Check if cached earnings date is stale for pre-earnings modifier."""
    try:
        fetched_at = cached.get("_fetched_at", 0)
        now = time.time()
        age_seconds = now - fetched_at
        
        # If fetched >3 hours ago, consider stale (might have been announced)
        return age_seconds > 10800
    except Exception:
        return False
```

**Also update `smart_money/earnings_scorer.py` to flag stale data:**
```python
def compute_earnings_score(ticker: str) -> float:
    """..."""
    try:
        cal = get_earnings_calendar(ticker)
    except Exception as exc:
        logger.warning("earnings calendar failed for %s: %s", ticker, exc)
        return 0.5

    # ... compute base score ...

    # NEW: Check if earnings date is stale for modifier
    if cal.get("next_earnings_date"):
        fetched_at = cal.get("_fetched_at", 0)
        if fetched_at > 0:
            age_seconds = time.time() - fetched_at
            if age_seconds > 10800:  # >3 hours
                logger.warning(f"earnings_score({ticker}): earnings date {age_seconds}s old; skipping modifier")
                return round(min(1.0, max(0.0, base)), 4)  # No modifier
    
    # ... apply modifier ...
    return round(min(1.0, max(0.0, base + modifier)), 4)
```

---

## Fix 5: Staleness Monitoring Foundation (4 hours)

**File:** `data/cache.py`

**Current Code:**
```python
import sqlite3
import json
import time
from decimal import Decimal
from pathlib import Path

DB_PATH = Path(__file__).parent / "cache.db"

def _json_default(o: object) -> object:
    if isinstance(o, Decimal):
        return str(o)
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if hasattr(o, "item"):  # numpy scalars
        return o.item()
    raise TypeError(f"Not JSON serializable: {type(o)}")

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                expires_at REAL NOT NULL
            )
        """)

def get_cache(key: str) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        value, expires_at = row
        if expires_at != 0 and expires_at < time.time():
            return None
        return json.loads(value)

def set_cache(key: str, value: dict, ttl_seconds: int = 3600) -> None:
    expires_at = time.time() + ttl_seconds if ttl_seconds > 0 else 0
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, default=_json_default), expires_at),
        )
```

**Proposed Change (add staleness tracking):**
```python
import sqlite3
import json
import time
import logging
from decimal import Decimal
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)
DB_PATH = Path(__file__).parent / "cache.db"

# Maximum acceptable data age by component type
MAX_DATA_AGE = {
    "bars": 14400,           # 4 hours
    "momentum": 7200,        # 2 hours
    "quality": 259200,       # 3 days
    "congress": 7200,        # 2 hours
    "news": 7200,            # 2 hours
    "earnings": 21600,       # 6 hours
    "regime": 1800,          # 30 minutes
    "estimate_revision": 14400,  # 4 hours
}

@dataclass
class CacheEntry:
    key: str
    value: dict
    cached_at: float
    expires_at: float
    data_published_at: float | None = None
    
    @property
    def age_seconds(self) -> float:
        """Age of the data itself (not the cache timestamp)."""
        return time.time() - (self.data_published_at or self.cached_at)
    
    @property
    def is_expired(self) -> bool:
        """Has the cache TTL expired?"""
        return self.expires_at > 0 and self.expires_at < time.time()
    
    def is_stale(self, max_age_seconds: int) -> bool:
        """Is the data older than acceptable?"""
        return self.age_seconds > max_age_seconds
    
    def to_json(self) -> str:
        """Serialize for storage."""
        return json.dumps({
            "value": self.value,
            "cached_at": self.cached_at,
            "expires_at": self.expires_at,
            "data_published_at": self.data_published_at,
        }, default=_json_default)
    
    @classmethod
    def from_json(cls, key: str, json_str: str):
        """Deserialize from storage."""
        data = json.loads(json_str)
        return cls(
            key=key,
            value=data["value"],
            cached_at=data["cached_at"],
            expires_at=data["expires_at"],
            data_published_at=data.get("data_published_at"),
        )

def _json_default(o: object) -> object:
    if isinstance(o, Decimal):
        return str(o)
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if hasattr(o, "item"):  # numpy scalars
        return o.item()
    raise TypeError(f"Not JSON serializable: {type(o)}")

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                expires_at REAL NOT NULL,
                cached_at REAL NOT NULL,
                data_published_at REAL
            )
        """)
        conn.commit()

def get_cache(key: str) -> dict | None:
    """Get cached value (ignores staleness)."""
    entry = _get_cache_entry(key)
    if entry is None or entry.is_expired:
        return None
    return entry.value

def get_cache_with_age(key: str, max_age_seconds: int | None = None) -> tuple[dict | None, float | None]:
    """
    Get cached value and its age.
    
    Returns:
        (value, age_seconds) or (None, None) if expired or missing
    
    Args:
        key: Cache key
        max_age_seconds: If provided, only return if data age <= max_age
    """
    entry = _get_cache_entry(key)
    if entry is None or entry.is_expired:
        return None, None
    
    if max_age_seconds is not None and entry.is_stale(max_age_seconds):
        logger.warning(
            f"Cache {key}: data is {entry.age_seconds:.0f}s old (max {max_age_seconds}s); "
            "returning None to force refresh"
        )
        return None, entry.age_seconds
    
    logger.debug(f"Cache {key}: serving {entry.age_seconds:.0f}s old data")
    return entry.value, entry.age_seconds

def set_cache(
    key: str,
    value: dict,
    ttl_seconds: int = 3600,
    data_published_at: float | None = None,
) -> None:
    """
    Store value in cache.
    
    Args:
        key: Cache key
        value: Data to store
        ttl_seconds: Time-to-live in seconds (0 = no expiry)
        data_published_at: When the data was published (default = now)
    """
    now = time.time()
    expires_at = now + ttl_seconds if ttl_seconds > 0 else 0
    data_published_at = data_published_at or now
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO cache 
               (key, value, expires_at, cached_at, data_published_at) 
               VALUES (?, ?, ?, ?, ?)""",
            (key, json.dumps(value, default=_json_default), expires_at, now, data_published_at),
        )
        conn.commit()
    
    logger.debug(f"Cache SET: {key} (TTL {ttl_seconds}s)")

def _get_cache_entry(key: str) -> CacheEntry | None:
    """Get cache entry with metadata."""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """SELECT value, cached_at, expires_at, data_published_at 
               FROM cache WHERE key = ?""",
            (key,)
        ).fetchone()
        
        if row is None:
            return None
        
        value_json, cached_at, expires_at, data_published_at = row
        try:
            value = json.loads(value_json)
        except json.JSONDecodeError:
            logger.error(f"Cache {key}: corrupted JSON data; clearing")
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            return None
        
        return CacheEntry(
            key=key,
            value=value,
            cached_at=cached_at,
            expires_at=expires_at,
            data_published_at=data_published_at,
        )

def get_cache_staleness_report() -> dict:
    """
    Return staleness report for monitoring.
    
    Example:
    {
        "bars:AAPL:30": {"age_seconds": 120, "max_age": 14400, "is_stale": false},
        "news:AAPL:3": {"age_seconds": 3600, "max_age": 7200, "is_stale": false},
        "earnings:AAPL": {"age_seconds": 86400, "max_age": 21600, "is_stale": true},
        ...
    }
    """
    report = {}
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT key, cached_at, data_published_at FROM cache WHERE expires_at = 0 OR expires_at > ?"
            " ORDER BY data_published_at DESC",
            (time.time(),)
        ).fetchall()
        
        for key, cached_at, data_published_at in rows:
            age = time.time() - (data_published_at or cached_at)
            
            # Determine max age from key prefix
            max_age = None
            for prefix, max_sec in MAX_DATA_AGE.items():
                if key.startswith(prefix):
                    max_age = max_sec
                    break
            
            report[key] = {
                "age_seconds": round(age, 1),
                "max_age_seconds": max_age,
                "is_stale": max_age is not None and age > max_age,
            }
    
    return report
```

---

## Fix 6: Data Quality Metadata (2 hours)

**File:** `api/analyze.py`

**Update the analyze_ticker response:**
```python
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
    trade_card = compute_trade_setup(current_price, ind["atr_stop"])

    # NEW: Compute data quality metrics
    data_quality = _compute_data_quality(ticker)

    return {
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
        "data_quality": data_quality,  # NEW
    }

def _compute_data_quality(ticker: str) -> dict:
    """
    Compute data quality report based on component freshness.
    
    Returns:
    {
        "freshness_score": 0.95,  # 0.0 (all stale) to 1.0 (all fresh)
        "components_fresh": 7,
        "components_stale": 0,
        "stale_components": [],
        "warnings": []
    }
    """
    from data.cache import get_cache_with_age, MAX_DATA_AGE
    
    components = {
        "technical": f"bars:{ticker}:250",
        "momentum": f"momentum:{ticker}",
        "quality": f"quality:{ticker}",
        "congress": f"congress:{ticker}",
        "estimate_revisions": f"est_revision:{ticker}",
        "news": f"news:{ticker}:3",
        "earnings": f"earnings:{ticker}",
    }
    
    fresh = []
    stale = []
    warnings = []
    
    for component, cache_key in components.items():
        _, age = get_cache_with_age(cache_key)
        if age is None:
            # Data not in cache; assume fresh (just fetched)
            fresh.append(component)
            continue
        
        max_age = MAX_DATA_AGE.get(component.split(':')[0], 3600)
        if age <= max_age:
            fresh.append(component)
        else:
            stale.append(component)
            hours_old = age / 3600
            max_hours = max_age / 3600
            warnings.append(
                f"{component}: {hours_old:.1f}h old (max {max_hours:.1f}h)"
            )
    
    freshness_score = len(fresh) / len(components) if components else 1.0
    
    return {
        "freshness_score": round(freshness_score, 2),
        "components_fresh": len(fresh),
        "components_stale": len(stale),
        "stale_components": stale,
        "warnings": warnings,
    }
```

---

## Summary Checklist

- [ ] `data/market.py` — Add Polygon → yfinance fallback
- [ ] `util/timeout.py` — Create timeout wrapper utility
- [ ] `quant/momentum.py` — Add timeout to yfinance call
- [ ] `quant/quality.py` — Add timeout to yfinance.info call
- [ ] `data/earnings.py` — Reduce TTL to 6h, add staleness check
- [ ] `smart_money/estimate_revisions.py` — Add timeout to yfinance calls
- [ ] `smart_money/congress.py` — Add SEC EDGAR fallback (placeholder)
- [ ] `data/cache.py` — Add staleness tracking, MAX_DATA_AGE dict
- [ ] `api/analyze.py` — Add data_quality to response
- [ ] Tests — Add test cases for each fallback path

**Estimated Time:** 16 hours total  
**Recommended Sequence:** Market data first (1-2), then earnings (3-4), then staleness foundation (5-6)

