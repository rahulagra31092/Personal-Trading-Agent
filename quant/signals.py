import config


def compute_signal(
    technical_score: float,
    momentum_score: float = 0.5,
    quality_score: float = 0.5,
    congress_score: float = 0.5,
    estimate_revisions_score: float = 0.5,
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
        + w["estimate_revisions"] * estimate_revisions_score
        + w["news_reaction"] * news_score
        + w["earnings"] * earnings_score,
        4,
    )

    # Interaction gate: quality < 0.35 with high composite = momentum trap.
    # Cap below BUY threshold to force WATCH.
    if quality_score < 0.35 and composite > 0.57:
        composite = 0.57

    label = "BUY" if composite > 0.58 else ("AVOID" if composite < 0.42 else "WATCH")

    return {
        "composite_score": composite,
        "label": label,
        "layer_scores": {
            "technical": technical_score,
            "momentum": momentum_score,
            "quality": quality_score,
            "congress": congress_score,
            "estimate_revisions": estimate_revisions_score,
            "news_reaction": news_score,
            "earnings": earnings_score,
        },
    }
