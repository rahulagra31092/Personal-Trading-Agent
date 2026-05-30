import config


def compute_signal(
    technical_score: float,
    arima_score: float,
    smart_money_score: float = 0.5,
    news_score: float = 0.5,
    earnings_score: float = 0.5,
) -> dict:
    w = config.SIGNAL_WEIGHTS
    composite = round(
        w["technical"] * technical_score
        + w["arima"] * arima_score
        + w["smart_money"] * smart_money_score
        + w["news_reaction"] * news_score
        + w["earnings"] * earnings_score,
        4,
    )

    label = "BUY" if composite > 0.58 else ("AVOID" if composite < 0.42 else "WATCH")

    return {
        "composite_score": composite,
        "label": label,
        "layer_scores": {
            "technical": technical_score,
            "arima": arima_score,
            "smart_money": smart_money_score,
            "news_reaction": news_score,
            "earnings": earnings_score,
        },
    }
