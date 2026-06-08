"""
Historical data pipeline for backtesting.

Provides bulk loading and caching of historical:
- Earnings dates
- Analyst revisions
- Price data (via get_daily_bars)
"""
import logging
from datetime import datetime, timedelta, timezone
import sqlite3
import os

from data.earnings import get_earnings_calendar_history
from smart_money.analyst_revisions import get_analyst_revisions_history

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(os.path.dirname(__file__), "historical.db")

_ET = timezone(timedelta(hours=-5))


def _init_db():
    """Initialize SQLite schema for historical data."""
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)

    conn = sqlite3.connect(_DB_PATH)
    c = conn.cursor()

    # Earnings table
    c.execute("""
        CREATE TABLE IF NOT EXISTS earnings (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            eps_estimate REAL,
            eps_actual REAL,
            surprise_pct REAL,
            PRIMARY KEY (ticker, date)
        )
    """)

    # Analyst revisions table
    c.execute("""
        CREATE TABLE IF NOT EXISTS analyst_revisions (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            num_analysts INTEGER,
            target_mean REAL,
            recommendation TEXT,
            PRIMARY KEY (ticker, date)
        )
    """)

    # Metadata: track when we last loaded data for each ticker
    c.execute("""
        CREATE TABLE IF NOT EXISTS load_metadata (
            ticker TEXT PRIMARY KEY,
            earnings_loaded_at TEXT,
            analyst_loaded_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def load_ticker_history(ticker: str, force: bool = False) -> dict:
    """
    Load all historical data for a ticker into SQLite.

    Returns:
    {
        "ticker": "AAPL",
        "earnings_loaded": 30,  # count of earnings dates loaded
        "analyst_loaded": 1,    # count of analyst snapshots loaded
        "last_updated": "2026-06-03T14:30:00"
    }
    """
    _init_db()

    ticker = ticker.strip().upper()
    conn = sqlite3.connect(_DB_PATH)
    c = conn.cursor()

    try:
        # Check if already loaded recently (unless forced)
        c.execute(
            "SELECT earnings_loaded_at, analyst_loaded_at FROM load_metadata WHERE ticker = ?",
            (ticker,)
        )
        row = c.fetchone()

        if row and not force:
            last_earnings = row[0]
            last_analyst = row[1]
            if last_earnings and last_analyst:
                # Already loaded today, skip
                logger.debug("%s already loaded, skipping", ticker)
                return {
                    "ticker": ticker,
                    "already_loaded": True,
                    "last_updated": last_earnings,
                }

        # Load earnings
        earnings = get_earnings_calendar_history(ticker, years=3)
        for e in earnings:
            c.execute(
                """
                INSERT OR REPLACE INTO earnings
                (ticker, date, eps_estimate, eps_actual, surprise_pct)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ticker, e["date"], e.get("eps_estimate"), e.get("eps_actual"), e.get("surprise_pct"))
            )

        # Load analyst revisions
        analyst = get_analyst_revisions_history(ticker)
        for a in analyst:
            c.execute(
                """
                INSERT OR REPLACE INTO analyst_revisions
                (ticker, date, num_analysts, target_mean, recommendation)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ticker, a["date"], a.get("num_analysts"), a.get("target_mean"), a.get("recommendation"))
            )

        # Update metadata
        now = datetime.now(_ET).isoformat()
        c.execute(
            """
            INSERT OR REPLACE INTO load_metadata
            (ticker, earnings_loaded_at, analyst_loaded_at)
            VALUES (?, ?, ?)
            """,
            (ticker, now, now)
        )

        conn.commit()

        return {
            "ticker": ticker,
            "earnings_loaded": len(earnings),
            "analyst_loaded": len(analyst),
            "last_updated": now,
        }

    finally:
        conn.close()


def get_earnings_on_date(ticker: str, date: str) -> dict | None:
    """
    Retrieve historical earnings for a specific date.

    Used in backtesting: what were the earnings announcement dates
    and EPS surprises on this date?
    """
    _init_db()

    conn = sqlite3.connect(_DB_PATH)
    c = conn.cursor()

    try:
        c.execute(
            "SELECT date, eps_estimate, eps_actual, surprise_pct FROM earnings WHERE ticker = ? AND date = ?",
            (ticker.upper(), date)
        )
        row = c.fetchone()

        if not row:
            return None

        return {
            "date": row[0],
            "eps_estimate": row[1],
            "eps_actual": row[2],
            "surprise_pct": row[3],
        }

    finally:
        conn.close()


def get_earnings_in_range(ticker: str, start_date: str, end_date: str) -> list[dict]:
    """
    Retrieve earnings announcements within a date range.

    Used in backtesting: find all earnings in the backtest period.
    """
    _init_db()

    conn = sqlite3.connect(_DB_PATH)
    c = conn.cursor()

    try:
        c.execute(
            """
            SELECT date, eps_estimate, eps_actual, surprise_pct
            FROM earnings
            WHERE ticker = ? AND date >= ? AND date <= ?
            ORDER BY date
            """,
            (ticker.upper(), start_date, end_date)
        )
        rows = c.fetchall()

        return [
            {
                "date": row[0],
                "eps_estimate": row[1],
                "eps_actual": row[2],
                "surprise_pct": row[3],
            }
            for row in rows
        ]

    finally:
        conn.close()
