def test_signal_weights_sum_to_one():
    """All signal weights must sum to 1.0."""
    import config
    assert abs(sum(config.SIGNAL_WEIGHTS.values()) - 1.0) < 1e-9


def test_news_removed_from_weights():
    """News sentiment removed due to keyword-matching noise."""
    import config
    assert "news_reaction" not in config.SIGNAL_WEIGHTS

    # Remaining weights (technical, momentum, quality, congress, estimate_revisions, earnings)
    expected_weights = {"technical", "momentum", "quality", "congress", "estimate_revisions", "earnings"}
    assert set(config.SIGNAL_WEIGHTS.keys()) == expected_weights


def test_regime_weights_sum_to_one():
    """All regime-specific weights must sum to 1.0."""
    import config
    for regime, weights in config.REGIME_WEIGHTS.items():
        assert abs(sum(weights.values()) - 1.0) < 1e-9, f"Regime {regime} doesn't sum to 1.0"
