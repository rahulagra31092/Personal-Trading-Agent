"""
Warren B memory layer: assembles the full context string injected before each session.
"""
import logging
import re
from datetime import date

from quant.regime import get_market_regime
from api.paper_portfolio import (
    get_portfolio_value,
    get_recent_warren_decisions,
    get_warren_conversation_history,
)
from data.google_sheets import fetch_google_sheet_portfolio

logger = logging.getLogger(__name__)

# Goal constants — fixed for the lifetime of this project
_START_DATE = date(2026, 6, 1)
_TARGET_VALUE = 417_000.0
_INITIAL_CAPITAL = 100_000.0
_MONTHLY_CONTRIBUTION = 2_000.0
_MONTHLY_RATE = 0.20 / 12          # 20% annual compounded monthly
_TOTAL_MONTHS = 54                  # Jun 2026 → Dec 2030

# Known universe tickers for smart extraction
_UNIVERSE_TICKERS = {
    "NVDA", "AAPL", "MSFT", "GOOGL", "GOOG", "META", "AMZN", "TSLA",
    "AMD", "INTC", "QCOM", "AVGO", "LRCX", "AMAT", "MU", "ARM",
    "XOM", "CVX", "COP", "SLB",
    "JPM", "BAC", "GS", "MS", "V", "MA",
    "LLY", "JNJ", "UNH", "PFE", "ABBV",
    "ENPH", "FSLR", "NEE",
    "CELH", "ZS", "SNOW", "PLTR", "CRWD", "NET", "DDOG",
    "SPY", "QQQ", "DIA",
}


def calculate_goal_pacing(current_value: float, months_elapsed: int) -> dict:
    """
    Calculate how actual portfolio value compares to the 20% CAGR on-track value.
    Formula: PV × (1+r)^n + PMT × [(1+r)^n - 1] / r
    """
    if months_elapsed < 0:
        months_elapsed = 0
    growth = (1 + _MONTHLY_RATE) ** months_elapsed
    on_track = (
        _INITIAL_CAPITAL * growth
        + _MONTHLY_CONTRIBUTION * (growth - 1) / _MONTHLY_RATE
    )
    gap = current_value - on_track
    months_remaining = max(0, _TOTAL_MONTHS - months_elapsed)

    if gap >= 1_000:
        status = f"Ahead by ${gap:,.0f}"
    elif gap <= -1_000:
        status = f"Behind by ${abs(gap):,.0f}"
    else:
        status = "On track"

    return {
        "on_track_value": round(on_track, 2),
        "current_value": round(current_value, 2),
        "gap": round(gap, 2),
        "status": status,
        "months_elapsed": months_elapsed,
        "months_remaining": months_remaining,
        "target": _TARGET_VALUE,
    }


def extract_tickers_from_message(message: str) -> list[str]:
    """Extract known universe tickers from a user message."""
    words = re.findall(r"\b[A-Z]{2,5}\b", message.upper())
    return [w for w in words if w in _UNIVERSE_TICKERS]


def get_recent_score_signals(top_n: int = 10) -> list[dict]:
    """Return today's top composite scores from score_history, sorted by score."""
    try:
        from api.paper_portfolio import PAPER_DB_PATH
        import sqlite3
        today = date.today().isoformat()
        with sqlite3.connect(PAPER_DB_PATH) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                """SELECT ticker, composite_score FROM score_history
                   WHERE score_date = ?
                   ORDER BY composite_score DESC LIMIT ?""",
                (today, top_n),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("get_recent_score_signals failed: %s", exc)
        return []


def _months_since_start() -> int:
    today = date.today()
    return (today.year - _START_DATE.year) * 12 + (today.month - _START_DATE.month)


def build_context_string(
    session_id: str,
    interface: str,
    user_message: str | None = None,
    real_portfolio_value: float | None = None,
) -> str:
    """
    Assemble the full context string injected before every Warren B session.
    """
    today = date.today().isoformat()
    months_elapsed = _months_since_start()

    try:
        regime = get_market_regime()
    except Exception:
        regime = {"regime": "unknown", "vix": 0.0, "position_factor": 1.0}

    try:
        paper = get_portfolio_value()
    except Exception:
        paper = {"total_value": 0.0, "cash": 0.0, "invested": 0.0,
                 "total_pnl_pct": 0.0, "positions": []}

    try:
        real_positions = fetch_google_sheet_portfolio()
    except Exception:
        real_positions = []

    if real_portfolio_value is None:
        real_portfolio_value = _INITIAL_CAPITAL

    combined_value = real_portfolio_value + paper.get("total_value", 0.0)
    pacing = calculate_goal_pacing(combined_value, months_elapsed)

    signals = get_recent_score_signals(top_n=10)
    decisions = get_recent_warren_decisions(days=30)
    history = get_warren_conversation_history(session_id=session_id, limit=20)

    # Smart retrieval for mentioned tickers
    smart_context = ""
    if user_message:
        mentioned = extract_tickers_from_message(user_message)
        if mentioned:
            ticker_decisions = get_recent_warren_decisions(days=180)
            relevant = [d for d in ticker_decisions if d.get("ticker") in mentioned]
            if relevant:
                smart_context = "\nPAST DECISIONS ON MENTIONED TICKERS (last 180 days):\n"
                for d in relevant[:10]:
                    smart_context += (
                        f"  {d['decision_date']} — {d['ticker']} — "
                        f"{d['decision_type'].upper()}: {d['recommendation']} | "
                        f"Rationale: {d['rationale']}\n"
                    )

    real_holdings_str = (
        "\n".join(
            f"  {p['ticker']}: {p['shares']} shares @ ${p['avg_cost']:.2f} avg cost"
            for p in real_positions
        )
        if real_positions
        else "  [No Google Sheets data — investor to provide current holdings]"
    )

    signals_str = (
        "\n".join(
            f"  {s['ticker']}: score={s['composite_score']:.2f}"
            for s in signals
        )
        if signals
        else "  [No signals available — daily model may not have run yet]"
    )

    decisions_str = (
        "\n".join(
            f"  {d['decision_date']} — {d.get('ticker', 'Portfolio')} — "
            f"{d['decision_type'].upper()}: {d['recommendation'][:80]}..."
            for d in decisions[:10]
        )
        if decisions
        else "  No decisions logged yet."
    )

    history_str = (
        "\n".join(
            f"  [{h['role'].upper()}]: {h['content'][:200]}"
            for h in history[-10:]
        )
        if history
        else "  No previous conversation this session."
    )

    return f"""=== WARREN B SESSION CONTEXT ===
Date: {today} | Interface: {interface} | Session: {session_id}
Months into journey: {months_elapsed} | Months remaining: {pacing['months_remaining']}

GOAL PACING:
  Target: ${_TARGET_VALUE:,.0f} by December 2030 (20% CAGR)
  On-track value today: ${pacing['on_track_value']:,.0f}
  Actual combined portfolio: ${pacing['current_value']:,.0f}
  Status: {pacing['status']}

MARKET REGIME:
  VIX: {regime.get('vix', 0.0)} | Regime: {regime.get('regime', 'unknown')} | Position factor: {regime.get('position_factor', 1.0)}

PAPER MODEL PORTFOLIO ($10K tracker):
  Total value: ${paper.get('total_value', 0):,.2f} | Cash: ${paper.get('cash', 0):,.2f} | P&L: {paper.get('total_pnl_pct', 0):.1f}%
  Open positions: {len(paper.get('positions', []))}

REAL PORTFOLIO (Google Sheets):
{real_holdings_str}

TODAY'S MODEL SIGNALS (by conviction):
{signals_str}

RECENT DECISIONS (last 30 days):
{decisions_str}
{smart_context}
CONVERSATION HISTORY (this session):
{history_str}
"""
