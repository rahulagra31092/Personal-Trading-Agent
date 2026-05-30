import pytest
from unittest.mock import patch

from smart_money.trump_scorer import (
    POLICY_TAGS,
    TICKER_POLICY,
    score_active_tags,
    compute_trump_modifier,
)


# ---------------------------------------------------------------------------
# score_active_tags
# ---------------------------------------------------------------------------

def test_score_active_tags_empty_texts_returns_zeros():
    result = score_active_tags([])
    assert all(v == 0.0 for v in result.values())
    assert set(result.keys()) == set(POLICY_TAGS.keys())


def test_score_active_tags_tariff_keyword_hit():
    texts = ["trump announces new tariff on chinese goods"] * 10
    result = score_active_tags(texts)
    assert result["tariff"] == 1.0


def test_score_active_tags_no_match_returns_zero():
    texts = ["weather report sunny skies" for _ in range(5)]
    result = score_active_tags(texts)
    assert all(v == 0.0 for v in result.values())


def test_score_active_tags_all_values_bounded():
    texts = [
        "tariff china beijing drill energy defense spending crypto bitcoin "
        "artificial intelligence drug price deregulate"
    ] * 20
    result = score_active_tags(texts)
    for tag, v in result.items():
        assert 0.0 <= v <= 1.0, f"{tag} out of bounds: {v}"


def test_score_active_tags_word_boundary_no_partial_match():
    # "retariff" should NOT match the "tariff" keyword
    texts = ["the retariff policy discussion"]
    result = score_active_tags(texts)
    assert result["tariff"] == 0.0


def test_score_active_tags_partial_coverage():
    # 3 out of 10 articles mention tariff
    texts = ["new tariff imposed", "trade war tariff hike", "tariff on steel"] + \
            ["unrelated headline"] * 7
    result = score_active_tags(texts)
    assert abs(result["tariff"] - 0.3) < 1e-9


def test_score_active_tags_multiple_tags_in_one_article():
    texts = ["trump tariff and china tension rising"] * 5
    result = score_active_tags(texts)
    assert result["tariff"] == 1.0
    assert result["china_tension"] == 1.0
    # others should be 0
    for tag in ("energy_boost", "defense_spend", "ai_invest", "pharma_pressure", "crypto_positive"):
        assert result[tag] == 0.0


# ---------------------------------------------------------------------------
# compute_trump_modifier
# ---------------------------------------------------------------------------

def test_compute_trump_modifier_cache_hit():
    with patch("smart_money.trump_scorer.get_cache", return_value=0.07):
        result = compute_trump_modifier("XOM")
    assert result == 0.07


def test_compute_trump_modifier_unknown_ticker():
    with patch("smart_money.trump_scorer.get_cache", return_value=None):
        result = compute_trump_modifier("UNKNOWN_XYZ")
    assert result == 0.0


def test_compute_trump_modifier_api_failure_returns_zero():
    with patch("smart_money.trump_scorer.get_cache", return_value=None), \
         patch("smart_money.trump_scorer.set_cache"), \
         patch("smart_money.trump_scorer._fetch_trump_policy_news", return_value=[]):
        result = compute_trump_modifier("XOM")
    assert result == 0.0


def test_compute_trump_modifier_output_bounded():
    # Simulate very strong signal on all tags simultaneously
    all_one = {tag: 1.0 for tag in POLICY_TAGS}
    with patch("smart_money.trump_scorer.get_cache", return_value=None), \
         patch("smart_money.trump_scorer.set_cache"), \
         patch("smart_money.trump_scorer._fetch_trump_policy_news", return_value=["x"]), \
         patch("smart_money.trump_scorer.score_active_tags", return_value=all_one):
        result = compute_trump_modifier("XOM")
    assert -0.15 <= result <= 0.15


def test_compute_trump_modifier_tailwind_energy():
    # XOM has energy_boost tailwind; simulate energy_boost at full strength
    strong_energy = {tag: 0.0 for tag in POLICY_TAGS}
    strong_energy["energy_boost"] = 1.0
    with patch("smart_money.trump_scorer.get_cache", return_value=None), \
         patch("smart_money.trump_scorer.set_cache"), \
         patch("smart_money.trump_scorer._fetch_trump_policy_news", return_value=["x"]), \
         patch("smart_money.trump_scorer.score_active_tags", return_value=strong_energy):
        result = compute_trump_modifier("XOM")
    assert result > 0.0


def test_compute_trump_modifier_headwind_pharma():
    # LLY has pharma_pressure headwind; simulate pharma signal at full strength
    strong_pharma = {tag: 0.0 for tag in POLICY_TAGS}
    strong_pharma["pharma_pressure"] = 1.0
    with patch("smart_money.trump_scorer.get_cache", return_value=None), \
         patch("smart_money.trump_scorer.set_cache"), \
         patch("smart_money.trump_scorer._fetch_trump_policy_news", return_value=["x"]), \
         patch("smart_money.trump_scorer.score_active_tags", return_value=strong_pharma):
        result = compute_trump_modifier("LLY")
    assert result < 0.0


def test_compute_trump_modifier_below_threshold_no_effect():
    # Strength just below 3% threshold -> modifier stays 0.0
    weak_signal = {tag: 0.02 for tag in POLICY_TAGS}
    with patch("smart_money.trump_scorer.get_cache", return_value=None), \
         patch("smart_money.trump_scorer.set_cache"), \
         patch("smart_money.trump_scorer._fetch_trump_policy_news", return_value=["x"]), \
         patch("smart_money.trump_scorer.score_active_tags", return_value=weak_signal):
        result = compute_trump_modifier("XOM")
    assert result == 0.0


def test_ticker_policy_map_completeness():
    # Every ticker in TICKER_POLICY should reference valid policy tags
    for ticker, policies in TICKER_POLICY.items():
        for tag, direction, base_mod in policies:
            assert tag in POLICY_TAGS, f"{ticker}: unknown tag {tag!r}"
            assert direction in ("tailwind", "headwind"), \
                f"{ticker}: invalid direction {direction!r}"
            assert -0.15 <= base_mod <= 0.15, \
                f"{ticker}: base_mod {base_mod} out of [-0.15, 0.15]"
