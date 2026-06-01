"""SQLite-backed $10K paper trading portfolio tracker."""
import json
import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"
PAPER_DB_PATH = _DATA_DIR / "paper_portfolio.db"

STARTING_CAPITAL = 10_000.0
POSITION_SIZE = 500.0  # $500 per position = 20 positions


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_paper_db() -> None:
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS paper_account (
                id        INTEGER PRIMARY KEY CHECK (id = 1),
                starting_capital REAL NOT NULL,
                cash      REAL NOT NULL,
                created_date TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_positions (
                ticker      TEXT PRIMARY KEY,
                shares      REAL NOT NULL,
                avg_cost    REAL NOT NULL,
                entry_date  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date  TEXT NOT NULL,
                ticker      TEXT NOT NULL,
                action      TEXT NOT NULL,
                shares      REAL NOT NULL,
                price       REAL NOT NULL,
                value       REAL NOT NULL,
                note        TEXT DEFAULT ''
            );
        """)


def _conn() -> sqlite3.Connection:
    PAPER_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(PAPER_DB_PATH)
    con.row_factory = sqlite3.Row
    return con


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def is_initialized() -> bool:
    try:
        init_paper_db()
        with _conn() as con:
            row = con.execute(
                "SELECT id FROM paper_account WHERE id = 1"
            ).fetchone()
            return row is not None
    except Exception:
        return False


def initialize_portfolio(
    buys: list[dict],
    capital: float = STARTING_CAPITAL,
    trade_date: Optional[str] = None,
) -> None:
    """
    Create fresh portfolio from scratch.
    buys = [{"ticker": "NVDA", "shares": 3.81, "price": 131.20}, ...]
    Idempotent — replaces any existing data.
    """
    if trade_date is None:
        trade_date = date.today().isoformat()

    init_paper_db()
    spent = sum(b["shares"] * b["price"] for b in buys)
    cash = capital - spent

    with _conn() as con:
        con.execute("DELETE FROM paper_positions")
        con.execute("DELETE FROM paper_trades")
        con.execute(
            "INSERT OR REPLACE INTO paper_account (id, starting_capital, cash, created_date)"
            " VALUES (1, ?, ?, ?)",
            (capital, cash, trade_date),
        )
        for b in buys:
            shares = round(b["shares"], 6)
            price = round(b["price"], 4)
            value = round(shares * price, 2)
            con.execute(
                "INSERT OR REPLACE INTO paper_positions (ticker, shares, avg_cost, entry_date)"
                " VALUES (?, ?, ?, ?)",
                (b["ticker"], shares, price, trade_date),
            )
            con.execute(
                "INSERT INTO paper_trades (trade_date, ticker, action, shares, price, value, note)"
                " VALUES (?, ?, 'BUY', ?, ?, ?, 'Initial portfolio')",
                (trade_date, b["ticker"], shares, price, value),
            )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def get_account() -> dict:
    with _conn() as con:
        row = con.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
    return dict(row) if row else {}


def get_raw_positions() -> list[dict]:
    """Positions without live prices (fast)."""
    with _conn() as con:
        rows = con.execute("SELECT * FROM paper_positions").fetchall()
    return [dict(r) for r in rows]


def _fetch_prices(tickers: list[str]) -> dict[str, float]:
    """Returns {ticker: latest_close}. Tolerates partial failures."""
    if not tickers:
        return {}
    prices: dict[str, float] = {}
    try:
        hist = yf.download(
            tickers if len(tickers) > 1 else tickers[0],
            period="2d",
            progress=False,
            auto_adjust=True,
        )
        if hist is None or hist.empty:
            return prices

        if isinstance(hist.columns, pd.MultiIndex):
            close_df = hist["Close"]
            for t in tickers:
                try:
                    col = close_df[t].dropna()
                    if not col.empty:
                        prices[t] = float(col.iloc[-1])
                except Exception:
                    pass
        else:
            col = hist["Close"].dropna()
            if not col.empty and len(tickers) == 1:
                prices[tickers[0]] = float(col.iloc[-1])
    except Exception as exc:
        logger.warning("Price fetch failed: %s", exc)
    return prices


def get_positions() -> list[dict]:
    """Positions enriched with live prices and P&L, sorted best-to-worst."""
    raw = get_raw_positions()
    if not raw:
        return []

    prices = _fetch_prices([p["ticker"] for p in raw])

    enriched = []
    for p in raw:
        current = prices.get(p["ticker"], p["avg_cost"])
        cost_basis = round(p["shares"] * p["avg_cost"], 2)
        market_value = round(p["shares"] * current, 2)
        pnl = round(market_value - cost_basis, 2)
        pnl_pct = round((current / p["avg_cost"] - 1) * 100, 2) if p["avg_cost"] else 0.0
        enriched.append(
            {
                **p,
                "current_price": round(current, 2),
                "cost_basis": cost_basis,
                "market_value": market_value,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
            }
        )
    return sorted(enriched, key=lambda p: p["pnl_pct"], reverse=True)


def get_portfolio_value() -> dict:
    """Full snapshot: cash + invested + total P&L vs SPY."""
    account = get_account()
    positions = get_positions()

    starting = account.get("starting_capital", STARTING_CAPITAL)
    cash = account.get("cash", 0.0)
    invested = sum(p["market_value"] for p in positions)
    total = round(cash + invested, 2)
    total_pnl = round(total - starting, 2)
    total_pnl_pct = round((total / starting - 1) * 100, 2) if starting else 0.0

    # SPY return since portfolio creation
    spy_return_pct = _spy_return_since(account.get("created_date"))

    return {
        "starting_capital": starting,
        "cash": round(cash, 2),
        "invested": round(invested, 2),
        "total_value": total,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "spy_return_pct": spy_return_pct,
        "alpha_pct": round(total_pnl_pct - spy_return_pct, 2),
        "created_date": account.get("created_date", ""),
        "positions": positions,
    }


def _spy_return_since(start_date: Optional[str]) -> float:
    if not start_date:
        return 0.0
    try:
        hist = yf.download("SPY", start=start_date, progress=False, auto_adjust=True)
        if hist is None or hist.empty:
            return 0.0
        if isinstance(hist.columns, pd.MultiIndex):
            closes = hist["Close"].iloc[:, 0].dropna()
        else:
            closes = hist["Close"].dropna()
        if len(closes) < 2:
            return 0.0
        return round((float(closes.iloc[-1]) / float(closes.iloc[0]) - 1) * 100, 2)
    except Exception as exc:
        logger.warning("SPY benchmark fetch failed: %s", exc)
        return 0.0


# ---------------------------------------------------------------------------
# Rebalance (monthly)
# ---------------------------------------------------------------------------

def rebalance(
    sells: list[dict],
    buys: list[dict],
    trade_date: Optional[str] = None,
) -> None:
    """
    Monthly rebalance.
    sells = [{"ticker": "ZS", "price": 205.0, "reason": "score < 0.45"}]
    buys  = [{"ticker": "ARM", "shares": 5.0, "price": 98.0}]
    """
    if trade_date is None:
        trade_date = date.today().isoformat()

    with _conn() as con:
        for s in sells:
            row = con.execute(
                "SELECT * FROM paper_positions WHERE ticker = ?", (s["ticker"],)
            ).fetchone()
            if not row:
                continue
            price = s.get("price", row["avg_cost"])
            value = round(row["shares"] * price, 2)
            con.execute(
                "DELETE FROM paper_positions WHERE ticker = ?", (s["ticker"],)
            )
            con.execute(
                "INSERT INTO paper_trades (trade_date, ticker, action, shares, price, value, note)"
                " VALUES (?, ?, 'SELL', ?, ?, ?, ?)",
                (
                    trade_date, s["ticker"], row["shares"],
                    price, value, s.get("reason", "Monthly rebalance"),
                ),
            )
            con.execute(
                "UPDATE paper_account SET cash = cash + ? WHERE id = 1", (value,)
            )

        for b in buys:
            shares = round(b["shares"], 6)
            price = round(b["price"], 4)
            value = round(shares * price, 2)
            existing = con.execute(
                "SELECT * FROM paper_positions WHERE ticker = ?", (b["ticker"],)
            ).fetchone()
            if existing:
                total_shares = existing["shares"] + shares
                avg = (existing["shares"] * existing["avg_cost"] + value) / total_shares
                con.execute(
                    "UPDATE paper_positions SET shares = ?, avg_cost = ? WHERE ticker = ?",
                    (round(total_shares, 6), round(avg, 4), b["ticker"]),
                )
            else:
                con.execute(
                    "INSERT INTO paper_positions (ticker, shares, avg_cost, entry_date)"
                    " VALUES (?, ?, ?, ?)",
                    (b["ticker"], shares, price, trade_date),
                )
            con.execute(
                "INSERT INTO paper_trades (trade_date, ticker, action, shares, price, value, note)"
                " VALUES (?, ?, 'BUY', ?, ?, ?, 'Monthly rebalance')",
                (trade_date, b["ticker"], shares, price, value),
            )
            con.execute(
                "UPDATE paper_account SET cash = cash - ? WHERE id = 1", (value,)
            )


# ---------------------------------------------------------------------------
# Summaries for Slack
# ---------------------------------------------------------------------------

def get_recent_trades(n: int = 10) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM paper_trades ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_monthly_trade_summary(year: int, month: int) -> dict:
    """All trades in a given month plus start/end value comparison."""
    start = f"{year}-{month:02d}-01"
    end = f"{year}-{month:02d}-31"
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM paper_trades WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date",
            (start, end),
        ).fetchall()
    trades = [dict(r) for r in rows]
    buys = [t for t in trades if t["action"] == "BUY"]
    sells = [t for t in trades if t["action"] == "SELL"]
    return {
        "buys": buys,
        "sells": sells,
        "total_bought": round(sum(t["value"] for t in buys), 2),
        "total_sold": round(sum(t["value"] for t in sells), 2),
        "trade_count": len(trades),
    }
