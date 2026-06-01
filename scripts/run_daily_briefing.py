"""
Daily / monthly briefing runner.

Usage:
  python scripts/run_daily_briefing.py              # daily briefing
  python scripts/run_daily_briefing.py --monthly    # monthly (25 picks + rebalance summary)
  python scripts/run_daily_briefing.py --init       # initialize $10K paper portfolio then send daily brief

Run from project root: python scripts/run_daily_briefing.py
"""
import argparse
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path when run directly
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("run_daily_briefing")


def init_paper_portfolio() -> None:
    """Score universe, pick top 20, buy $500 each, record in DB."""
    from api.paper_portfolio import (
        STARTING_CAPITAL,
        POSITION_SIZE,
        initialize_portfolio,
        is_initialized,
    )
    from api.briefing import BLUE_CHIP_UNIVERSE, MIDCAP_UNIVERSE, screen_tickers

    if is_initialized():
        print("Paper portfolio already initialized — use --force to reinitialize.")
        return

    print("Scoring universe to pick initial 20 positions…")
    all_tickers = BLUE_CHIP_UNIVERSE + MIDCAP_UNIVERSE
    results = screen_tickers(all_tickers)

    # Pick top 20 by composite score
    ranked = sorted(results, key=lambda r: r["signal"]["composite_score"], reverse=True)
    top20 = ranked[:20]

    buys = []
    for r in top20:
        price = r["current_price"]
        if price <= 0:
            continue
        shares = round(POSITION_SIZE / price, 6)
        buys.append({"ticker": r["ticker"], "shares": shares, "price": price})

    initialize_portfolio(buys=buys, capital=STARTING_CAPITAL)

    print(f"\nInitial portfolio — ${STARTING_CAPITAL:,.0f} across {len(buys)} positions:")
    for b in buys:
        print(f"  {b['ticker']:6s}  {b['shares']:.3f} sh @ ${b['price']:.2f}  = ${b['shares']*b['price']:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Trading Analyst briefing runner")
    parser.add_argument("--monthly", action="store_true", help="Send monthly briefing (25 picks)")
    parser.add_argument("--init", action="store_true", help="Initialize $10K paper portfolio")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-initialize paper portfolio (overwrites existing)",
    )
    args = parser.parse_args()

    if args.init or args.force:
        if args.force:
            # Allow re-init by clearing is_initialized guard
            from api import paper_portfolio as pp
            pp.PAPER_DB_PATH.unlink(missing_ok=True)
        init_paper_portfolio()

    if args.monthly:
        logger.info("Sending monthly briefing…")
        from api.briefing import send_monthly_briefing
        send_monthly_briefing()
    else:
        logger.info("Sending daily briefing…")
        from api.briefing import send_daily_briefing
        send_daily_briefing()

    print("Done.")


if __name__ == "__main__":
    main()
