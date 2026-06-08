import logging
from datetime import datetime, timedelta, timezone

import yfinance as yf

from data.cache import get_cache, set_cache
from util.timeout import timeout
from util.data_health import record_fetch

logger = logging.getLogger(__name__)

_ET = timezone(timedelta(hours=-5))  # Eastern Time


@timeout(10, default=[])
def get_insider_trades(ticker: str) -> list[dict]:
    """
    Fetch insider trades (Form 4 filings) from yfinance.

    Unlike Congress trades (legislative intelligence), insider trades are
    direct evidence of company insiders (officers, directors) buying/selling.

    Signal: Heavy insider buying = confidence, insider selling = concern.
    """
    ticker = ticker.strip().upper()
    cache_key = f"insider_trades:{ticker}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    try:
        t = yf.Ticker(ticker)
        txns = t.insider_transactions

        if txns is None or txns.empty:
            logger.debug("No insider transactions for %s", ticker)
            return []

        trades = []
        for idx, row in txns.iterrows():
            try:
                txn_type = row.get("Transaction", "").lower()
                if "sale" in txn_type:
                    label = "Sale"
                    is_buy = False
                elif "purchase" in txn_type or "buy" in txn_type:
                    label = "Purchase"
                    is_buy = True
                else:
                    continue

                date_val = row.get("Date")
                if date_val is None:
                    continue
                date_str = date_val.isoformat() if hasattr(date_val, "isoformat") else str(date_val)

                shares = float(row.get("Shares", 0) or 0)
                if shares <= 0:
                    continue

                insider = row.get("Insider", "Unknown")

                trades.append({
                    "date": date_str,
                    "transaction": label,
                    "shares": shares,
                    "insider": insider,
                    "is_buy": is_buy,
                })
            except Exception as e:
                logger.debug("Failed to parse insider trade: %s", e)
                continue

        record_fetch("insider_trades", success=True)
        set_cache(cache_key, trades, ttl_seconds=86400)  # 24h cache
        return trades

    except Exception as exc:
        logger.warning("Insider trades fetch failed for %s: %s", ticker, exc)
        record_fetch("insider_trades", success=False)
        return []


def compute_insider_trades_score(ticker: str, lookback_days: int = 180) -> float:
    """
    Insider trading signal [0, 1].

    Score high when:
    - Multiple insiders buying (conviction signal)
    - Recent heavy buying volume

    Score low when:
    - Insider selling (exit signal)
    - Heavy sales by executives

    Returns 0.5 (neutral) when no recent activity.
    """
    trades = get_insider_trades(ticker)
    if not trades:
        return 0.5

    now = datetime.now(_ET)
    cutoff = now - timedelta(days=lookback_days)

    buy_shares = 0.0
    sell_shares = 0.0
    buy_count = 0
    sell_count = 0

    for trade in trades:
        try:
            date_str = trade.get("date", "")
            if not date_str:
                continue

            trade_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if trade_date.tzinfo is None:
                trade_date = trade_date.replace(tzinfo=_ET)

            if trade_date < cutoff:
                continue

            shares = trade.get("shares", 0)
            is_buy = trade.get("is_buy", False)

            if is_buy:
                buy_shares += shares
                buy_count += 1
            else:
                sell_shares += shares
                sell_count += 1

        except Exception:
            continue

    total_shares = buy_shares + sell_shares
    if total_shares == 0:
        return 0.5

    # Ratio of buys to total activity
    buy_ratio = buy_shares / total_shares

    # Consensus bonus: more insiders buying = stronger signal
    consensus_bonus = min(0.1, buy_count * 0.02)  # +2% per insider buyer, capped at 10%

    raw = 0.5 + (buy_ratio - 0.5) * 0.60 + consensus_bonus
    return round(min(1.0, max(0.0, raw)), 4)
