import logging

from data.earnings import days_to_earnings

logger = logging.getLogger(__name__)


def compute_earnings_score(ticker: str) -> float:
    try:
        days = days_to_earnings(ticker)
    except Exception as exc:
        logger.warning("days_to_earnings failed for %s: %s", ticker, exc)
        return 0.5

    if days is None or days > 30:
        return 0.5
    if days > 7:
        return 0.55
    if days >= 1:
        return 0.2
    if days >= -3:
        return 0.7
    return 0.5
