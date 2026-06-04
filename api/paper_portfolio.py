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
            CREATE TABLE IF NOT EXISTS signal_outcomes (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker              TEXT NOT NULL,
                entry_date          TEXT NOT NULL,
                exit_date           TEXT,
                entry_price         REAL NOT NULL,
                exit_price          REAL,
                realized_return_pct REAL,
                days_held           INTEGER,
                exit_reason         TEXT,
                score_technical     REAL,
                score_momentum      REAL,
                score_quality       REAL,
                score_congress      REAL,
                score_estimate_revisions  REAL,
                score_news          REAL,
                score_earnings      REAL,
                score_composite     REAL,
                vix_at_entry        REAL,
                regime_at_entry     TEXT,
                sector              TEXT
            );
            CREATE TABLE IF NOT EXISTS score_history (
                ticker          TEXT NOT NULL,
                score_date      TEXT NOT NULL,
                composite_score REAL NOT NULL,
                PRIMARY KEY (ticker, score_date)
            );
            CREATE TABLE IF NOT EXISTS weight_changes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                factor      TEXT NOT NULL,
                changed_at  TEXT NOT NULL,
                old_weight  REAL NOT NULL,
                new_weight  REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS warren_b_decisions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_date   TEXT NOT NULL,
                ticker          TEXT,
                decision_type   TEXT NOT NULL,
                recommendation  TEXT NOT NULL,
                rationale       TEXT NOT NULL,
                model_score     REAL,
                regime          TEXT,
                outcome         TEXT DEFAULT 'pending',
                outcome_note    TEXT DEFAULT '',
                session_id      TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS warren_b_conversations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                interface   TEXT NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                timestamp   TEXT NOT NULL
            );
        """)
    # Idempotent schema migrations
    with _conn() as con:
        try:
            con.execute("ALTER TABLE paper_positions ADD COLUMN peak_price REAL")
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc):
                raise
    try:
        with _conn() as con:
            con.execute(
                "ALTER TABLE signal_outcomes RENAME COLUMN score_trump_policy TO score_estimate_revisions"
            )
    except Exception:
        pass  # column already renamed or doesn't exist


def _conn() -> sqlite3.Connection:
    PAPER_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(PAPER_DB_PATH)
    con.row_factory = sqlite3.Row
    return con


# ---------------------------------------------------------------------------
# Outcome tracking — feeds the quarterly regression
# ---------------------------------------------------------------------------

def log_trade_entry(
    ticker: str,
    entry_date: str,
    entry_price: float,
    layer_scores: dict,
    composite_score: float,
    vix: float = 0.0,
    regime: str = "unknown",
    sector: str = "Other",
) -> None:
    """Record a new paper position entry with all 7 factor scores."""
    init_paper_db()
    ls = layer_scores or {}
    try:
        with _conn() as con:
            con.execute(
                """INSERT INTO signal_outcomes
                   (ticker, entry_date, entry_price,
                    score_technical, score_momentum, score_quality,
                    score_congress, score_estimate_revisions, score_news, score_earnings,
                    score_composite, vix_at_entry, regime_at_entry, sector)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ticker.upper(), entry_date, entry_price,
                    ls.get("technical"), ls.get("momentum"), ls.get("quality"),
                    ls.get("congress"), ls.get("estimate_revisions"), ls.get("news_reaction"),
                    ls.get("earnings"), composite_score,
                    vix, regime, sector,
                ),
            )
    except Exception as exc:
        logger.warning("log_trade_entry failed for %s: %s", ticker, exc)


def log_trade_exit(
    ticker: str,
    exit_date: str,
    exit_price: float,
    exit_reason: str,
) -> None:
    """Close the most recent open outcome record for ticker, computing realized return."""
    init_paper_db()
    try:
        with _conn() as con:
            row = con.execute(
                """SELECT id, entry_price, entry_date FROM signal_outcomes
                   WHERE ticker = ? AND exit_date IS NULL
                   ORDER BY entry_date DESC LIMIT 1""",
                (ticker.upper(),),
            ).fetchone()
            if not row:
                return
            entry_price = row["entry_price"]
            entry_date = row["entry_date"]
            realized = round((exit_price / entry_price - 1) * 100, 4) if entry_price else 0.0
            try:
                days = (date.fromisoformat(exit_date) - date.fromisoformat(entry_date)).days
            except Exception:
                days = None
            con.execute(
                """UPDATE signal_outcomes
                   SET exit_date=?, exit_price=?, realized_return_pct=?,
                       days_held=?, exit_reason=?
                   WHERE id=?""",
                (exit_date, exit_price, realized, days, exit_reason, row["id"]),
            )
    except Exception as exc:
        logger.warning("log_trade_exit failed for %s: %s", ticker, exc)


def get_closed_outcomes(min_closed: int = 0) -> list[dict]:
    """Return all closed positions for regression. Requires exit_date IS NOT NULL."""
    init_paper_db()
    try:
        with _conn() as con:
            rows = con.execute(
                """SELECT * FROM signal_outcomes
                   WHERE exit_date IS NOT NULL AND realized_return_pct IS NOT NULL
                   ORDER BY exit_date DESC"""
            ).fetchall()
        result = [dict(r) for r in rows]
        return result if len(result) >= min_closed else []
    except Exception as exc:
        logger.warning("get_closed_outcomes failed: %s", exc)
        return []


def get_open_outcome_tickers() -> set[str]:
    """Return tickers that have an open (not yet closed) outcome record."""
    init_paper_db()
    try:
        with _conn() as con:
            rows = con.execute(
                "SELECT ticker FROM signal_outcomes WHERE exit_date IS NULL"
            ).fetchall()
        return {r["ticker"] for r in rows}
    except Exception:
        return set()


def log_weight_change(
    factor: str,
    old_weight: float,
    new_weight: float,
    as_of: str | None = None,
) -> None:
    """Record a quarterly weight update. as_of: ISO date, defaults to today."""
    if as_of is None:
        as_of = date.today().isoformat()
    init_paper_db()
    try:
        with _conn() as con:
            con.execute(
                """INSERT INTO weight_changes (factor, changed_at, old_weight, new_weight)
                   VALUES (?, ?, ?, ?)""",
                (factor, as_of, round(float(old_weight), 4), round(float(new_weight), 4)),
            )
    except Exception as exc:
        logger.warning("log_weight_change failed for %s: %s", factor, exc)


def get_annual_weight_delta(factor: str, as_of: str | None = None) -> float:
    """
    Net signed weight drift for factor over the past 365 days from as_of.
    Returns sum(new_weight - old_weight) for qualifying rows.
    """
    if as_of is None:
        as_of = date.today().isoformat()
    init_paper_db()
    try:
        with _conn() as con:
            rows = con.execute(
                """SELECT old_weight, new_weight FROM weight_changes
                   WHERE factor = ?
                     AND changed_at <= ?
                     AND changed_at >= date(?, '-365 days')
                   ORDER BY changed_at""",
                (factor, as_of, as_of),
            ).fetchall()
    except Exception as exc:
        logger.warning("get_annual_weight_delta failed for %s: %s", factor, exc)
        return 0.0

    return round(sum(row["new_weight"] - row["old_weight"] for row in rows), 4)


def log_warren_decision(
    decision_type: str,
    recommendation: str,
    rationale: str,
    ticker: str | None = None,
    model_score: float | None = None,
    regime: str | None = None,
    session_id: str = "",
    as_of: str | None = None,
) -> None:
    """Log a Warren B recommendation to the decision log."""
    if as_of is None:
        as_of = date.today().isoformat()
    init_paper_db()
    try:
        with _conn() as con:
            con.execute(
                """INSERT INTO warren_b_decisions
                   (decision_date, ticker, decision_type, recommendation, rationale,
                    model_score, regime, session_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (as_of, ticker, decision_type, recommendation, rationale,
                 model_score, regime, session_id),
            )
    except Exception as exc:
        logger.warning("log_warren_decision failed: %s", exc)


def get_recent_warren_decisions(days: int = 30, as_of: str | None = None) -> list[dict]:
    """Return Warren B decisions from the last `days` calendar days."""
    if as_of is None:
        as_of = date.today().isoformat()
    init_paper_db()
    try:
        with _conn() as con:
            rows = con.execute(
                """SELECT * FROM warren_b_decisions
                   WHERE decision_date >= date(?, ?)
                     AND decision_date <= ?
                   ORDER BY decision_date DESC, id DESC""",
                (as_of, f"-{days} days", as_of),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("get_recent_warren_decisions failed: %s", exc)
        return []


def log_warren_conversation(
    session_id: str,
    interface: str,
    role: str,
    content: str,
    as_of: str | None = None,
) -> None:
    """Store one turn of conversation (role = 'user' or 'warren')."""
    if as_of is None:
        as_of = datetime.now().isoformat(timespec="seconds")
    init_paper_db()
    try:
        with _conn() as con:
            con.execute(
                """INSERT INTO warren_b_conversations
                   (session_id, interface, role, content, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, interface, role, content, as_of),
            )
    except Exception as exc:
        logger.warning("log_warren_conversation failed: %s", exc)


def get_warren_conversation_history(
    session_id: str,
    limit: int = 50,
) -> list[dict]:
    """Return conversation turns for a session, oldest first."""
    init_paper_db()
    try:
        with _conn() as con:
            rows = con.execute(
                """SELECT role, content, timestamp FROM warren_b_conversations
                   WHERE session_id = ?
                   ORDER BY id ASC
                   LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("get_warren_conversation_history failed: %s", exc)
        return []


def log_daily_scores(scores: dict[str, float], date_str: str | None = None) -> None:
    """
    Write composite scores for all scored tickers to score_history.
    Upserts — safe to call multiple times per day.
    date_str: ISO date string e.g. "2026-01-15". Defaults to today.
    """
    if not scores:
        return
    if date_str is None:
        date_str = date.today().isoformat()
    init_paper_db()
    clean = []
    for t, s in scores.items():
        try:
            clean.append((t.upper(), date_str, round(float(s), 4)))
        except (TypeError, ValueError):
            logger.warning("log_daily_scores: skipping bad score for %s: %r", t, s)
    if not clean:
        return
    try:
        with _conn() as con:
            con.executemany(
                """INSERT INTO score_history (ticker, score_date, composite_score)
                   VALUES (?, ?, ?)
                   ON CONFLICT(ticker, score_date) DO UPDATE SET composite_score = excluded.composite_score""",
                clean,
            )
    except Exception as exc:
        logger.warning("log_daily_scores DB error: %s", exc)


def get_score_trend(ticker: str, as_of: str | None = None) -> dict:
    """
    Return the latest composite score and 5-day delta for ticker.
    as_of: ISO date string for testing (defaults to today).
    Returns: {latest_score, delta_5d, direction}
    direction: "rising" | "falling" | "flat" | "insufficient_data"
    """
    init_paper_db()
    if as_of is None:
        as_of = date.today().isoformat()
    try:
        with _conn() as con:
            rows = con.execute(
                """SELECT composite_score FROM score_history
                   WHERE ticker = ? AND score_date <= ?
                   ORDER BY score_date DESC LIMIT 6""",
                (ticker.upper(), as_of),
            ).fetchall()
    except Exception as exc:
        logger.warning("get_score_trend failed for %s: %s", ticker, exc)
        return {"latest_score": None, "delta_5d": None, "direction": "insufficient_data"}

    if not rows:
        return {"latest_score": None, "delta_5d": None, "direction": "insufficient_data"}

    scores_desc = [r[0] for r in rows]
    latest = scores_desc[0]

    if len(scores_desc) < 6:
        return {"latest_score": latest, "delta_5d": None, "direction": "insufficient_data"}

    oldest = scores_desc[-1]
    delta = round(latest - oldest, 4)

    if delta > 0.02:
        direction = "rising"
    elif delta < -0.02:
        direction = "falling"
    else:
        direction = "flat"

    return {"latest_score": latest, "delta_5d": delta, "direction": direction}


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


def update_peak_prices() -> None:
    """Refresh the all-time-high price for each held position. Call once per daily run."""
    raw = get_raw_positions()
    if not raw:
        return
    # Guard against corrupt zero-cost positions
    valid = [p for p in raw if p.get("avg_cost") and p.get("shares")]
    if not valid:
        return
    prices = _fetch_prices([p["ticker"] for p in valid])
    # Single connection for write phase
    with _conn() as con:
        for p in valid:
            ticker = p["ticker"]
            current = prices.get(ticker)
            if current is None:
                continue
            peak = p.get("peak_price") or p["avg_cost"]
            if current > peak:
                con.execute(
                    "UPDATE paper_positions SET peak_price = ? WHERE ticker = ?",
                    (round(current, 4), ticker),
                )


def check_trailing_stops(trail_pct: float = 0.20) -> list[dict]:
    """
    Return positions whose current price is strictly below peak * (1 - trail_pct).
    A drop of exactly trail_pct does NOT trigger.
    Each entry: {ticker, price, peak_price, trail_drop_pct, reason}.
    """
    raw = get_raw_positions()
    if not raw:
        return []
    prices = _fetch_prices([p["ticker"] for p in raw])
    stops = []
    for p in raw:
        ticker = p["ticker"]
        if not p.get("avg_cost") or not p.get("shares"):
            logger.warning("Skipping position %s: zero avg_cost or shares", ticker)
            continue
        current = prices.get(ticker, p["avg_cost"])
        peak = p.get("peak_price") or p["avg_cost"]
        if peak > 0 and current < peak * (1.0 - trail_pct):
            drop_pct = round((current / peak - 1.0) * 100, 2)
            stops.append({
                "ticker": ticker,
                "price": current,
                "peak_price": peak,
                "trail_drop_pct": drop_pct,
                "reason": f"Trailing stop: {drop_pct:.1f}% from ${peak:.2f} peak",
            })
    return stops


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
