"""Daily and monthly Slack briefings — two messages per run."""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from api.analyze import analyze_ticker
from api.paper_portfolio import get_portfolio_value, is_initialized
from quant.regime import get_market_regime
from smart_money.market_intel import (
    build_market_brief,
    get_index_snapshot,
    get_market_news,
    get_sector_snapshot,
)
import config

logger = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Universes
# ---------------------------------------------------------------------------

BLUE_CHIP_UNIVERSE: list[str] = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AVGO",
    "LLY", "V", "MA", "UNH", "JPM", "XOM", "COST", "HD", "NFLX",
    "CRM", "AMD", "QCOM", "BAC", "GS", "JNJ", "CVX", "WMT", "MU",
    "LRCX", "AMAT", "ARM", "PLTR", "GE", "CAT", "ABBV", "PG", "KO",
]

MIDCAP_UNIVERSE: list[str] = [
    "DDOG", "NET", "ZS", "BILL", "CELH", "DUOL", "MNDY", "HIMS",
    "NTNX", "PSTG", "GTLB", "AFRM", "SMCI", "FSLR", "ENPH",
    "PAYC", "CAVA", "ELF", "CROX", "CHWY", "SAIA", "GMED", "PODD",
    "RXRX", "ASAN", "LYFT", "HOOD", "SOFI", "APP", "RBLX",
]

BRIEFING_TICKERS: list[str] = BLUE_CHIP_UNIVERSE + MIDCAP_UNIVERSE


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def screen_tickers(tickers: list[str], max_workers: int = 8) -> list[dict]:
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(analyze_ticker, t): t for t in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                logger.warning("Skipping %s: %s", ticker, exc)
    return results


def build_briefing_message(results: list[dict], now: datetime | None = None) -> str:
    """Plain-text fallback / notification preview."""
    buys = sorted(
        [r for r in results if r["signal"]["label"] == "BUY"],
        key=lambda r: r["signal"]["composite_score"],
        reverse=True,
    )
    if now is None:
        now = datetime.now(_ET)
    now_et = now.strftime("%Y-%m-%d %H:%M ET")
    lines = [f"Trading Analyst — Morning Brief ({now_et})"]
    if not buys:
        lines.append("No BUY signals today.")
    else:
        lines.append(f"Top BUY Signals ({len(buys)} found):")
        for i, r in enumerate(buys[:5], 1):
            sig = r["signal"]
            lines.append(
                f"{i}. {r['ticker']}  Score: {sig['composite_score']:.2f}"
                f"  Price: ${r['current_price']:.2f}"
            )
    lines.append(f"Screened {len(results)} tickers")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Score → human conviction label
# ---------------------------------------------------------------------------

def _conviction(score: float) -> str:
    if score >= 0.75:
        return "Very High"
    if score >= 0.65:
        return "High"
    if score >= 0.55:
        return "Moderate"
    if score >= 0.45:
        return "Low"
    return "Avoid"


def _signal_emoji(label: str) -> str:
    return {"BUY": "BUY", "WATCH": "WATCH", "AVOID": "AVOID"}.get(label, label)


# ---------------------------------------------------------------------------
# Caution alerts
# ---------------------------------------------------------------------------

def _caution_alerts(portfolio_value: dict, regime: dict) -> list[str]:
    alerts = []
    vix = regime.get("vix", 0.0)
    if vix >= 30:
        alerts.append(
            f"*VIX AT {vix:.1f} — CRISIS TERRITORY*\n"
            f"Market stress is extreme. Reduce new positions and hold cash."
        )
    elif vix >= 25:
        alerts.append(
            f"*VIX SPIKE: {vix:.1f}*\n"
            f"Volatility elevated above normal. Don't add new risk — hold steady."
        )
    for p in portfolio_value.get("positions", []):
        if p["pnl_pct"] <= -15:
            alerts.append(
                f"*{p['ticker']} down {p['pnl_pct']:.1f}%*\n"
                f"Hit our -15% exit threshold. Flag for rebalance."
            )
        elif p["pnl_pct"] <= -10:
            alerts.append(
                f"*{p['ticker']} down {p['pnl_pct']:.1f}%*\n"
                f"Approaching -15% exit threshold. Watch closely."
            )
    return alerts


# ---------------------------------------------------------------------------
# News section builder (curated headlines)
# ---------------------------------------------------------------------------

def _news_blocks(news: list[dict]) -> list[dict]:
    """Top 5-6 stories, each on its own line with source. Mobile-friendly."""
    if not news:
        return []

    lines = ["*Top News to Read Today*"]
    for a in news[:6]:
        title = a.get("title", "").strip()
        desc = a.get("description", "").strip()
        source = a.get("source", "").strip()

        # Truncate title at 70 chars for mobile
        if len(title) > 70:
            title = title[:67] + "…"

        # One-sentence summary from description (first sentence only)
        summary = ""
        if desc:
            first_sentence = desc.split(". ")[0].strip()
            if len(first_sentence) > 80:
                first_sentence = first_sentence[:77] + "…"
            summary = f" — {first_sentence}"

        source_tag = f" [{source}]" if source else ""
        lines.append(f"• *{title}*{source_tag}{summary}")

    return [{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}]


# ---------------------------------------------------------------------------
# Picks section (mobile-friendly: one ticker per line, short)
# ---------------------------------------------------------------------------

def _picks_blocks(label: str, results: list[dict], n: int) -> list[dict]:
    top_buys = sorted(
        [r for r in results if r["signal"]["label"] == "BUY"],
        key=lambda r: r["signal"]["composite_score"],
        reverse=True,
    )[:n]

    if not top_buys:
        top_buys = sorted(
            [r for r in results if r["signal"]["label"] == "WATCH"],
            key=lambda r: r["signal"]["composite_score"],
            reverse=True,
        )[:n]

    if not top_buys:
        return [{"type": "section", "text": {"type": "mrkdwn", "text": f"*{label}*\nNo signals today."}}]

    lines = [f"*{label}*"]
    for i, r in enumerate(top_buys, 1):
        sig = r["signal"]
        score = sig["composite_score"]
        conviction = _conviction(score)
        # Short line fits mobile: "#1 NVDA — BUY — 0.72 (High) — $224"
        price_str = f"${r['current_price']:.0f}" if r["current_price"] >= 10 else f"${r['current_price']:.2f}"
        lines.append(
            f"*{i}. {r['ticker']}* — {sig['label']} — {score:.2f} ({conviction}) — {price_str}"
        )

    return [{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}]


# ---------------------------------------------------------------------------
# Real portfolio section (Google Sheets)
# ---------------------------------------------------------------------------

def _real_portfolio_blocks(real_positions: list[dict]) -> list[dict]:
    """Compact, mobile-readable real portfolio scores."""
    if not real_positions:
        return []

    lines = ["*Your Portfolio*"]
    total_invested = sum(p.get("market_value", 0) for p in real_positions)
    total_pnl = sum(p.get("pnl", 0) for p in real_positions)
    total_pnl_pct = round(total_pnl / (total_invested - total_pnl) * 100, 1) if (total_invested - total_pnl) > 0 else 0.0
    sign = "+" if total_pnl >= 0 else ""
    lines.append(f"Total P&L: {sign}${total_pnl:,.0f} ({sign}{total_pnl_pct:.1f}%)")
    lines.append("")
    for p in real_positions[:20]:
        sig_label = p.get("signal", {}).get("label", "")
        score = p.get("signal", {}).get("composite_score", 0.5)
        sign_p = "+" if p["pnl_pct"] >= 0 else ""
        # Compact: "AAPL  BUY 0.72  +1.8%  ($+9)"
        lines.append(
            f"*{p['ticker']}*  {sig_label} {score:.2f}  "
            f"{sign_p}{p['pnl_pct']:.1f}%"
        )

    return [{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}]


# ---------------------------------------------------------------------------
# Paper portfolio Message 2 (improved readability)
# ---------------------------------------------------------------------------

def _paper_portfolio_blocks(portfolio_value: dict, now: datetime, is_monthly: bool = False) -> list[dict]:
    pv = portfolio_value
    sign = "+" if pv["total_pnl_pct"] >= 0 else ""
    alpha_sign = "+" if pv["alpha_pct"] >= 0 else ""
    date_str = now.strftime("%b %d, %Y")
    created = pv.get("created_date", "")

    perf_lines = [
        f"*${pv['total_value']:,.2f}*  ({sign}{pv['total_pnl_pct']:.2f}%  |  {sign}${pv['total_pnl']:,.2f})",
        f"vs SPY since {created}: SPY {pv['spy_return_pct']:+.2f}%  |  Alpha {alpha_sign}{pv['alpha_pct']:.2f}%",
        f"Cash: ${pv['cash']:,.2f}  |  Invested: ${pv['invested']:,.2f}",
    ]

    positions = pv.get("positions", [])

    # Positions: grouped into winners vs losers for readability
    winners = [p for p in positions if p["pnl_pct"] >= 0]
    losers  = [p for p in positions if p["pnl_pct"] < 0]

    def pos_line(p: dict) -> str:
        sign_p = "+" if p["pnl_pct"] >= 0 else ""
        return (
            f"*{p['ticker']}*  {sign_p}{p['pnl_pct']:.1f}%"
            f"  ({sign_p}${p['pnl']:.0f})"
            f"  ${p['current_price']:.0f}"
        )

    pos_lines = []
    if winners:
        pos_lines.append("*Gainers*")
        pos_lines += [pos_line(p) for p in winners]
    if losers:
        if winners:
            pos_lines.append("")
        pos_lines.append("*Losers*")
        pos_lines += [pos_line(p) for p in losers]

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Paper Portfolio — {date_str}"},
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(perf_lines)}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(pos_lines) if pos_lines else "No positions"}},
    ]

    if is_monthly and positions:
        best  = positions[0]
        worst = positions[-1]
        summary = (
            f"Best: *{best['ticker']}* {best['pnl_pct']:+.1f}%  |  "
            f"Worst: *{worst['ticker']}* {worst['pnl_pct']:+.1f}%"
        )
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": summary}})

    blocks.append(
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "Paper trading · $10K · Top-20 · $500/position · Monthly rebalance"},
            ],
        }
    )
    return blocks


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def _next_rebalance_date(now: datetime) -> str:
    next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
    return next_month.strftime("%b 1, %Y")


def _post_to_slack(payload: dict) -> None:
    if not config.SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not set — skipping post")
        return
    resp = requests.post(config.SLACK_WEBHOOK_URL, json=payload, timeout=15)
    resp.raise_for_status()


def send_daily_briefing(
    blue_chip_tickers: list[str] | None = None,
    midcap_tickers: list[str] | None = None,
    n_picks: int = 10,
) -> None:
    """
    Send 2 Slack messages:
    1. Market intel brief + real portfolio + top picks (blue chip + mid-small)
    2. Paper portfolio P&L
    """
    from data.google_sheets import fetch_google_sheet_portfolio, score_real_portfolio

    if blue_chip_tickers is None:
        blue_chip_tickers = BLUE_CHIP_UNIVERSE
    if midcap_tickers is None:
        midcap_tickers = MIDCAP_UNIVERSE

    now = datetime.now(_ET)
    date_str = now.strftime("%b %d, %Y")

    logger.info("Daily briefing: scoring %d tickers…", len(blue_chip_tickers) + len(midcap_tickers))

    # Score universes + fetch market data concurrently (best-effort)
    blue_results = screen_tickers(blue_chip_tickers)
    mid_results  = screen_tickers(midcap_tickers)
    all_results  = blue_results + mid_results

    all_buys = sorted(
        [r for r in all_results if r["signal"]["label"] == "BUY"],
        key=lambda r: r["signal"]["composite_score"],
        reverse=True,
    )
    all_avoids = sorted(
        [r for r in all_results if r["signal"]["label"] == "AVOID"],
        key=lambda r: r["signal"]["composite_score"],
    )

    # Market data
    regime      = get_market_regime()
    index_snap  = get_index_snapshot()
    sector_snap = get_sector_snapshot()
    news        = get_market_news(n=12)
    vix         = regime.get("vix", 20.0)

    briefing_narrative = build_market_brief(
        index_snap, sector_snap, news, all_buys, all_avoids, regime, vix
    )

    # Real portfolio from Google Sheets
    sheet_positions = fetch_google_sheet_portfolio()
    real_positions  = score_real_portfolio(sheet_positions) if sheet_positions else []

    # Paper portfolio caution check
    paper_value = get_portfolio_value() if is_initialized() else {"positions": []}
    alerts = _caution_alerts(paper_value, regime)

    # Index summary (compact for mobile header)
    index_parts = []
    for sym in ("SPY", "QQQ", "^VIX"):
        if sym in index_snap:
            d = index_snap[sym]
            if sym == "^VIX":
                index_parts.append(f"VIX {d['price']:.1f}")
            else:
                sign = "+" if d["pct_change"] >= 0 else ""
                index_parts.append(f"{d['name']} {sign}{d['pct_change']:.1f}%")
    index_line = "  ·  ".join(index_parts) if index_parts else "Market data unavailable"
    regime_label = regime.get("regime", "normal").replace("_", " ").title()

    rebalance_str = f"Next rebalance: {_next_rebalance_date(now)}"

    # ---- Message 1 blocks ----
    msg1_blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Morning Brief — {date_str}"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{index_line}*  ·  {regime_label} Volatility",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": briefing_narrative},
        },
    ]

    # Curated news headlines
    news_blks = _news_blocks(news)
    if news_blks:
        msg1_blocks.append({"type": "divider"})
        msg1_blocks += news_blks

    msg1_blocks.append({"type": "divider"})

    # Real portfolio (if available)
    if real_positions:
        msg1_blocks += _real_portfolio_blocks(real_positions)
        msg1_blocks.append({"type": "divider"})
    elif not sheet_positions and config.GOOGLE_SHEET_ID:
        msg1_blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*Your Portfolio*\n"
                        "Sheet not publicly accessible. "
                        "In Google Sheets: File → Share → Anyone with the link → Viewer."
                    ),
                },
            }
        )
        msg1_blocks.append({"type": "divider"})

    # Blue chip picks
    msg1_blocks += _picks_blocks(f"Top {n_picks} Blue Chip Picks (Large Cap)", blue_results, n_picks)
    msg1_blocks.append({"type": "divider"})

    # Mid-small picks
    msg1_blocks += _picks_blocks(f"Top {n_picks} Growth Picks (Mid/Small Cap)", mid_results, n_picks)

    # Caution alerts
    if alerts:
        msg1_blocks.append({"type": "divider"})
        alert_text = "*ATTENTION REQUIRED*\n" + "\n\n".join(alerts)
        msg1_blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": alert_text}})

    msg1_blocks.append(
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": rebalance_str},
                {"type": "mrkdwn", "text": "BUY >0.65  ·  WATCH 0.40-0.65  ·  AVOID <0.40  ·  Score = model conviction (not coin flip)"},
            ],
        }
    )

    plain_text = build_briefing_message(all_results, now)
    _post_to_slack({"text": plain_text, "blocks": msg1_blocks})
    logger.info("Message 1 sent.")

    # ---- Message 2: paper portfolio ----
    if is_initialized():
        msg2_blocks = _paper_portfolio_blocks(paper_value, now, is_monthly=False)
        _post_to_slack({"text": f"Paper Portfolio — {date_str}", "blocks": msg2_blocks})
        logger.info("Message 2 sent.")


def send_monthly_briefing(
    blue_chip_tickers: list[str] | None = None,
    midcap_tickers: list[str] | None = None,
    n_picks: int = 25,
) -> None:
    """Monthly version: top 25 picks + full rebalance review."""
    send_daily_briefing(
        blue_chip_tickers=blue_chip_tickers,
        midcap_tickers=midcap_tickers,
        n_picks=n_picks,
    )
    now = datetime.now(_ET)
    if is_initialized():
        paper_value = get_portfolio_value()
        blocks = _paper_portfolio_blocks(paper_value, now, is_monthly=True)
        _post_to_slack(
            {
                "text": f"Monthly Portfolio Summary — {now.strftime('%B %Y')}",
                "blocks": blocks,
            }
        )
        logger.info("Monthly paper summary sent.")
