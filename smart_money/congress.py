import re
import logging
from datetime import datetime, timedelta, timezone

import requests
import yfinance as yf

from data.cache import get_cache, set_cache
from util.timeout import timeout
from util.data_health import record_fetch
import config

logger = logging.getLogger(__name__)

_QUIVER_API_KEY: str | None = config.QUIVER_API_KEY
_QUIVER_BASE = "https://api.quiverquant.com/beta"


@timeout(10, default=[])
def _get_edgar_insider_trades(ticker: str) -> list[dict]:
    """
    Fallback: fetch insider trades from SEC Form 4 filings via yfinance.
    Converts to Congress-trade-like format.
    """
    try:
        ticker = ticker.strip().upper()
        t = yf.Ticker(ticker)
        insider_txns = t.insider_transactions

        if insider_txns is None or insider_txns.empty:
            logger.debug("No SEC EDGAR insider transactions available for %s", ticker)
            return []

        trades = []
        for idx, row in insider_txns.iterrows():
            try:
                # Extract transaction type
                txn_type = row.get("Transaction", "")
                if "sale" in txn_type.lower():
                    txn_label = "Insider Sale"
                elif "purchase" in txn_type.lower():
                    txn_label = "Insider Purchase"
                else:
                    continue

                # Extract date
                date_val = row.get("Date")
                if date_val is None:
                    continue
                if hasattr(date_val, "isoformat"):
                    date_str = date_val.isoformat()
                else:
                    date_str = str(date_val)

                # Extract share count
                shares = float(row.get("Shares", 0) or 0)
                if shares <= 0:
                    continue

                # Extract insider name
                insider_name = row.get("Insider", "")
                if not insider_name:
                    insider_name = "Unknown Insider"

                # Infer dollar range: assume $100-300/share
                lower_est = int(shares * 100)
                upper_est = int(shares * 300)
                range_str = f"${lower_est:,}-${upper_est:,}"

                trade = {
                    "Date": date_str,
                    "Transaction": txn_label,
                    "Range": range_str,
                    "Representative": insider_name,
                    "Amount": shares,
                }
                trades.append(trade)

            except Exception as e:
                logger.debug("Failed to parse SEC EDGAR trade row for %s: %s", ticker, e)
                continue

        record_fetch("edgar_insider_trades", success=True)
        return trades

    except Exception as exc:
        logger.warning("SEC EDGAR insider trades fetch failed for %s: %s", ticker, exc)
        record_fetch("edgar_insider_trades", success=False)
        return []


def get_congress_trades(ticker: str) -> list[dict]:
    ticker = ticker.strip().upper()
    cache_key = f"congress:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    trades = []

    # Try Quiver Congress first (paid API, Congress-specific)
    if _QUIVER_API_KEY:
        try:
            resp = requests.get(
                f"{_QUIVER_BASE}/historical/congresstrading/{ticker}",
                headers={"Authorization": f"Token {_QUIVER_API_KEY}"},
                timeout=10,
            )
            resp.raise_for_status()
            trades = resp.json()
            record_fetch("quiver_congress", success=True)
        except Exception as exc:
            logger.warning("Congress trades fetch failed for %s: %s", ticker, exc)
            record_fetch("quiver_congress", success=False)
    else:
        logger.debug("Quiver API key not configured")
        record_fetch("quiver_congress", success=False)

    # Fall back to SEC EDGAR if Congress unavailable
    if not trades:
        logger.info("Falling back to SEC EDGAR insider trades for %s", ticker)
        trades = _get_edgar_insider_trades(ticker)

    set_cache(cache_key, trades, ttl_seconds=6 * 3600)
    return trades


def _recency_weight(trade_date: datetime, now: datetime) -> float:
    """Recent trades carry more signal: 0-30 days = 1.0, 30-90 = 0.7, 90+ = 0.3."""
    days_ago = (now - trade_date).days
    if days_ago <= 30:
        return 1.0
    if days_ago <= 90:
        return 0.7
    return 0.3


def _parse_trade_size(range_str: str) -> float:
    """
    Map Quiver's dollar range field to a size weight (1–30).
    Larger trades from Congress members signal stronger conviction.

    Quiver ranges: "$1,001-$15,000" | "$15,001-$50,000" | "$50,001-$100,000" |
                   "$100,001-$250,000" | "$250,001-$500,000" | "$500,001-$1,000,000" |
                   "Over $1,000,000"
    Uses strict upper-bound comparisons (+1) so each range maps to its own bucket.
    """
    if not range_str:
        return 1.0
    if re.search(r"\bover\b", range_str, re.IGNORECASE):
        return 30.0
    nums = [int(n.replace(",", "")) for n in re.findall(r"[\d,]+", range_str)]
    if not nums:
        return 1.0
    upper = max(nums)
    if upper >= 1_000_001:
        return 30.0
    if upper >= 500_001:
        return 15.0
    if upper >= 250_001:
        return 8.0
    if upper >= 100_001:
        return 5.0
    if upper >= 50_001:
        return 3.0
    if upper >= 15_001:
        return 2.0
    return 1.0


def _institutional_adjustment(ticker: str) -> float:
    """Return discrete adjustment in {-0.05, 0.0, +0.05}:
    +0.05 if institutional ownership >= 70%, -0.05 if <= 30%, else 0.0.
    """
    cache_key = f"inst_adj:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    try:
        holders = yf.Ticker(ticker).major_holders
        if holders is None or holders.empty:
            return 0.0

        pct: float
        if hasattr(holders.index, '__contains__') and "institutionsPercentHeld" in holders.index:
            pct = float(holders.loc["institutionsPercentHeld"].iloc[0])
        else:
            raw = holders.iloc[1, 0]
            pct = float(str(raw).replace("%", "").strip()) / 100.0

        if pct >= 0.70:
            result = 0.05
        elif pct <= 0.30:
            result = -0.05
        else:
            result = 0.0

        set_cache(cache_key, result, ttl_seconds=86400)
        return result

    except (IndexError, KeyError, ValueError, TypeError) as exc:
        logger.warning("institutional adjustment parse failed for %s: %s", ticker, exc)
        return 0.0
    except Exception as exc:
        logger.warning("institutional adjustment unexpected error for %s: %s", ticker, exc)
        return 0.0


def compute_congress_score(ticker: str, lookback_days: int = 180) -> float:
    """
    Congress trading signal: buy/sell ratio weighted by recency, trade size, and member consensus.
    Score [0.1, 0.9] — 0.5 = neutral, >0.5 = net buying, <0.5 = net selling.
    """
    trades = get_congress_trades(ticker)
    if not trades:
        return 0.5

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)
    buy_weight = 0.0
    sell_weight = 0.0
    members_buy: set[str] = set()
    members_sell: set[str] = set()

    for trade in trades:
        try:
            date_str = trade.get("Date") or trade.get("TransactionDate") or ""
            if not date_str:
                continue
            trade_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if trade_date.tzinfo is None:
                trade_date = trade_date.replace(tzinfo=timezone.utc)
            if trade_date < cutoff:
                continue

            txn = (trade.get("Transaction") or "").lower()
            is_buy = "purchase" in txn or "buy" in txn
            is_sell = "sale" in txn or "sell" in txn
            if not is_buy and not is_sell:
                continue

            recency = _recency_weight(trade_date, now)
            size = _parse_trade_size(trade.get("Range") or trade.get("Amount") or "")
            member = trade.get("Representative") or trade.get("Senator") or ""

            w = recency * size
            if is_buy:
                buy_weight += w
                members_buy.add(member)
            else:
                sell_weight += w
                members_sell.add(member)
        except Exception:
            continue

    total_weight = buy_weight + sell_weight
    if total_weight == 0:
        return 0.5

    buy_ratio = buy_weight / total_weight
    dominant_distinct = len(members_buy) if buy_ratio >= 0.5 else len(members_sell)
    # Consensus bonus: each additional member beyond the first adds 3% strength (max +15%)
    consensus_factor = 1.0 + min(0.15, (dominant_distinct - 1) * 0.03)

    raw = 0.5 + (buy_ratio - 0.5) * 0.70 * consensus_factor
    adjustment = _institutional_adjustment(ticker)
    return round(max(0.1, min(0.9, raw + adjustment)), 4)
