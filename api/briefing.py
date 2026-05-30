import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from api.analyze import analyze_ticker
import config

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

BRIEFING_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AVGO",
    "AMD", "QCOM", "JPM", "BAC", "GS", "V", "MA", "LLY", "UNH", "JNJ",
    "HD", "COST", "XOM", "CVX", "GE", "CAT", "NEE", "NFLX", "DDOG",
    "CRM", "PLTR", "ARM",
]


def screen_tickers(tickers: list[str]) -> list[dict]:
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker))
        except Exception as exc:
            logger.warning("Skipping %s: %s", ticker, exc)
    return results


def build_briefing_message(results: list[dict]) -> str:
    buys = sorted(
        [r for r in results if r["signal"]["label"] == "BUY"],
        key=lambda r: r["signal"]["composite_score"],
        reverse=True,
    )
    top = buys[:5]
    now_et = datetime.now(_ET).strftime("%Y-%m-%d %H:%M ET")
    lines = [f"*Trading Analyst — Morning Brief* ({now_et})", ""]

    if not top:
        lines.append("No BUY signals today.")
    else:
        lines.append(f"*:green_circle: Top BUY Signals ({len(buys)} found):*")
        for i, r in enumerate(top, 1):
            sig = r["signal"]
            mc = r["confidence"]
            lines.append(
                f"{i}. *{r['ticker']}*  Score: {sig['composite_score']:.2f}"
                f"  Prob: {mc['prob_success']:.0%}"
                f"  Price: ${r['current_price']:.2f}"
                f"  Stop: ${r['atr_stop']:.2f}"
            )

    lines.append("")
    lines.append(f"_Screened {len(results)} tickers_")
    return "\n".join(lines)


def send_slack_briefing(tickers: list[str]) -> None:
    results = screen_tickers(tickers)
    message = build_briefing_message(results)
    resp = requests.post(
        config.SLACK_WEBHOOK_URL,
        json={"text": message},
        timeout=10,
    )
    resp.raise_for_status()
    logger.info("Slack briefing sent: %d tickers screened", len(results))
