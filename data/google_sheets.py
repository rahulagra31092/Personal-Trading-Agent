"""
Read actual portfolio holdings from a publicly shared Google Sheet.

Required sheet format (Row 1 = headers):
  Ticker | Shares | Avg Cost | Entry Date

The sheet must be shared: File → Share → Anyone with the link → Viewer.
"""
import csv
import io
import logging
from typing import Optional

import requests

from data.cache import get_cache, set_cache
import config

logger = logging.getLogger(__name__)

_EXPORT_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"

# Accepted column name variants (case-insensitive)
_TICKER_COLS  = {"ticker", "tickr", "symbol", "stock"}
_SHARES_COLS  = {"shares", "qty", "quantity", "units"}
_COST_COLS    = {"avg cost", "avg_cost", "avgcost", "entry price", "entry_price", "cost", "price"}
_DATE_COLS    = {"entry date", "entry_date", "date", "purchase date"}


def _header_map(header_row: list[str]) -> dict[str, int]:
    """Map normalised column names → column index."""
    mapping: dict[str, int] = {}
    for i, col in enumerate(header_row):
        key = col.strip().lower()
        if key in _TICKER_COLS:
            mapping["ticker"] = i
        elif key in _SHARES_COLS:
            mapping["shares"] = i
        elif key in _COST_COLS:
            mapping["avg_cost"] = i
        elif key in _DATE_COLS:
            mapping["entry_date"] = i
    return mapping


def _safe_float(val: str) -> float:
    try:
        return float(val.replace(",", "").replace("$", "").strip())
    except (ValueError, AttributeError):
        return 0.0


def fetch_google_sheet_portfolio(
    sheet_id: Optional[str] = None,
    gid: int = 0,
    ttl_seconds: int = 1800,
) -> list[dict]:
    """
    Fetch portfolio from Google Sheets and return normalised position list.
    Returns [] if sheet_id not set, sheet not public, or malformed.
    """
    sid = sheet_id or config.GOOGLE_SHEET_ID
    if not sid:
        logger.info("GOOGLE_SHEET_ID not set — skipping real portfolio")
        return []

    cache_key = f"gsheets:portfolio:{sid}:{gid}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    url = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"
    try:
        resp = requests.get(url, timeout=15, allow_redirects=True)
        # Google redirects to login page if not public
        if "accounts.google.com" in resp.url or resp.status_code != 200:
            logger.warning(
                "Google Sheet not publicly accessible. "
                "Share it: File → Share → Anyone with the link → Viewer."
            )
            return []

        reader = csv.reader(io.StringIO(resp.text))
        rows = list(reader)
        if not rows:
            return []

        col_map = _header_map(rows[0])
        if "ticker" not in col_map:
            logger.warning("Google Sheet missing Ticker column — found headers: %s", rows[0])
            return []

        positions = []
        for row in rows[1:]:
            if not row or not any(row):
                continue
            ticker = row[col_map["ticker"]].strip().upper() if col_map.get("ticker") is not None else ""
            if not ticker or ticker.lower() in {"ticker", "symbol"}:
                continue
            shares = _safe_float(row[col_map["shares"]]) if col_map.get("shares") is not None else 0.0
            avg_cost = _safe_float(row[col_map["avg_cost"]]) if col_map.get("avg_cost") is not None else 0.0
            entry_date = row[col_map["entry_date"]].strip() if col_map.get("entry_date") is not None else ""
            if shares <= 0:
                continue
            positions.append(
                {
                    "ticker": ticker,
                    "shares": shares,
                    "avg_cost": avg_cost,
                    "entry_date": entry_date,
                    "source": "google_sheets",
                }
            )

        set_cache(cache_key, positions, ttl_seconds=ttl_seconds)
        logger.info("Google Sheet: loaded %d positions", len(positions))
        return positions

    except Exception as exc:
        logger.warning("Google Sheet fetch failed: %s", exc)
        return []


def score_real_portfolio(sheet_positions: list[dict]) -> list[dict]:
    """
    Enrich Google Sheet positions with live prices and model scores.
    Returns scored positions sorted by P&L%.
    """
    if not sheet_positions:
        return []

    from api.analyze import analyze_ticker
    from api.paper_portfolio import _fetch_prices
    import config as cfg

    tickers = [p["ticker"] for p in sheet_positions]
    prices = _fetch_prices(tickers)

    enriched = []
    for p in sheet_positions:
        current = prices.get(p["ticker"], p["avg_cost"])
        cost_basis = round(p["shares"] * p["avg_cost"], 2)
        market_value = round(p["shares"] * current, 2)
        pnl = round(market_value - cost_basis, 2)
        pnl_pct = round((current / p["avg_cost"] - 1) * 100, 2) if p["avg_cost"] else 0.0

        # Model score (best-effort — skip if fails)
        signal = {"label": "N/A", "composite_score": 0.5}
        try:
            result = analyze_ticker(p["ticker"])
            signal = result["signal"]
        except Exception:
            pass

        enriched.append(
            {
                **p,
                "current_price": round(current, 2),
                "cost_basis": cost_basis,
                "market_value": market_value,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "signal": signal,
            }
        )
    return sorted(enriched, key=lambda p: p["pnl_pct"], reverse=True)
