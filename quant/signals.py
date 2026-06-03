import config


def compute_signal(
    technical_score: float,
    momentum_score: float = 0.5,
    quality_score: float = 0.5,
    congress_score: float = 0.5,
    trump_policy_score: float = 0.5,
    news_score: float = 0.5,
    earnings_score: float = 0.5,
    weights: dict[str, float] | None = None,
) -> dict:
    w = weights if weights is not None else config.SIGNAL_WEIGHTS
    composite = round(
        w["technical"] * technical_score
        + w["momentum"] * momentum_score
        + w["quality"] * quality_score
        + w["congress"] * congress_score
        + w["trump_policy"] * trump_policy_score
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
            "momentum": momentum_score,
            "quality": quality_score,
            "congress": congress_score,
            "trump_policy": trump_policy_score,
            "news_reaction": news_score,
            "earnings": earnings_score,
        },
    }
