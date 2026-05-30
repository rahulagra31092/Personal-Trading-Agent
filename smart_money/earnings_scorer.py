from data.earnings import days_to_earnings


def compute_earnings_score(ticker: str) -> float:
    try:
        days = days_to_earnings(ticker)
    except Exception:
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
