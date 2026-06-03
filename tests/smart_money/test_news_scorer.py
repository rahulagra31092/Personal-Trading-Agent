import pytest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from smart_money.news_scorer import (
    compute_news_score,
    _count_keywords,
    _recency_weight,
)


def _article(title: str = "", description: str = "", published_at: str = "2024-01-01") -> dict:
    return {"title": title, "description": description, "publishedAt": published_at}


def _articles(titles: list[str], published_at: str = "2024-01-01") -> list[dict]:
    return [_article(title=t, published_at=published_at) for t in titles]


def _ts(hours_ago: float) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


# ---------------------------------------------------------------------------
# _count_keywords — word boundary matching
# ---------------------------------------------------------------------------

def test_count_keywords_basic_bull():
    bull, bear = _count_keywords("the stock rallied on strong earnings")
    assert bull >= 2
    assert bear == 0


def test_count_keywords_basic_bear():
    bull, bear = _count_keywords("downgrade miss weak")
    assert bear >= 2
    assert bull == 0


def test_count_keywords_no_false_positive_bull_in_bulletin():
    # "bulletin" must NOT match "bull"
    bull, bear = _count_keywords("company issues bulletin about new policy")
    assert bull == 0


def test_count_keywords_no_false_positive_sell_in_seller():
    # "seller" must NOT match "sell"
    bull, bear = _count_keywords("top seller reports")
    assert bear == 0


def test_count_keywords_no_false_positive_cut_in_cutting():
    # "cutting" should NOT match the standalone word "cut"
    bull, bear = _count_keywords("cost cutting initiative")
    # "cutting" is not in our set, only "cut" is — boundary should prevent match
    # Actually "cut" with word boundary won't match inside "cutting"
    assert bear == 0


def test_count_keywords_inflections_bullish():
    # beats, surges, rallies, upgraded all in keyword set
    bull, bear = _count_keywords("company beats expectations and surges after upgraded rating")
    assert bull >= 3


def test_count_keywords_inflections_bearish():
    # downgraded, missed, declining, losses all in keyword set
    bull, bear = _count_keywords("downgraded stock missed estimates with declining revenues and losses")
    assert bear >= 4


def test_count_keywords_bullish_phrase():
    bull, bear = _count_keywords("company beat expectations in latest quarter")
    assert bull >= 1


def test_count_keywords_bearish_phrase():
    bull, bear = _count_keywords("guidance cut hurts outlook")
    # "cut" as single word + phrase "guidance cut" — both may fire
    assert bear >= 1


def test_count_keywords_bearish_phrase_going_concern():
    bull, bear = _count_keywords("auditors raise going concern doubt")
    assert bear >= 1


def test_count_keywords_bullish_phrase_raised_guidance():
    bull, bear = _count_keywords("management raised guidance for full year")
    assert bull >= 1


def test_count_keywords_both_present():
    bull, bear = _count_keywords("strong buy upgrade offset by lawsuit investigation")
    assert bull >= 2
    assert bear >= 2


def test_count_keywords_empty_string():
    bull, bear = _count_keywords("")
    assert bull == 0
    assert bear == 0


def test_count_keywords_expects_lowercase():
    # _count_keywords expects pre-lowercased text (compute_news_score calls .lower() before passing)
    bull, bear = _count_keywords("upgraded strong buy")
    assert bull >= 2


# ---------------------------------------------------------------------------
# _recency_weight
# ---------------------------------------------------------------------------

def test_recency_weight_under_12h():
    assert _recency_weight(_ts(6)) == pytest.approx(1.0)


def test_recency_weight_between_12_and_24h():
    assert _recency_weight(_ts(18)) == pytest.approx(0.85)


def test_recency_weight_between_24_and_48h():
    assert _recency_weight(_ts(36)) == pytest.approx(0.70)


def test_recency_weight_older_than_48h():
    assert _recency_weight(_ts(72)) == pytest.approx(0.50)


def test_recency_weight_empty_string_returns_default():
    assert _recency_weight("") == pytest.approx(0.75)


def test_recency_weight_invalid_string_returns_default():
    assert _recency_weight("not-a-date") == pytest.approx(0.75)


def test_recency_weight_z_suffix():
    # pubDate with "Z" suffix should parse correctly
    ts = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert _recency_weight(ts) == pytest.approx(1.0)


def test_recency_weight_alt_field_names():
    # compute_news_score tries publishedAt, pubDate, published_at
    recent = _ts(2)
    article = {"title": "stock surges", "description": "", "pubDate": recent}
    with patch("smart_money.news_scorer.get_ticker_news", return_value=[article]):
        score = compute_news_score("AAPL")
    assert score > 0.5


# ---------------------------------------------------------------------------
# compute_news_score — existing behaviour
# ---------------------------------------------------------------------------

def test_score_bounded():
    with patch("smart_money.news_scorer.get_ticker_news",
               return_value=_articles(["stock rallies on strong earnings"])):
        assert 0.0 <= compute_news_score("AAPL") <= 1.0


def test_bullish_headlines_score_above_half():
    headlines = ["strong buy upgrade", "beats earnings growth rally"]
    with patch("smart_money.news_scorer.get_ticker_news", return_value=_articles(headlines)):
        assert compute_news_score("AAPL") > 0.5


def test_bearish_headlines_score_below_half():
    headlines = ["downgrade miss weak sell", "loss decline bearish"]
    with patch("smart_money.news_scorer.get_ticker_news", return_value=_articles(headlines)):
        assert compute_news_score("AAPL") < 0.5


def test_no_news_returns_neutral():
    with patch("smart_money.news_scorer.get_ticker_news", return_value=[]):
        assert compute_news_score("AAPL") == 0.5


def test_mixed_news_returns_near_half():
    headlines = ["strong buy upgrade", "downgrade miss weak sell"]
    with patch("smart_money.news_scorer.get_ticker_news", return_value=_articles(headlines)):
        score = compute_news_score("AAPL")
        assert 0.3 <= score <= 0.7


def test_fetch_failure_returns_neutral():
    with patch("smart_money.news_scorer.get_ticker_news", side_effect=RuntimeError("api error")):
        assert compute_news_score("AAPL") == 0.5


# ---------------------------------------------------------------------------
# Intensity weighting
# ---------------------------------------------------------------------------

def test_strongly_worded_article_outweighs_weakly_worded():
    # 1 article with 5 bull signals vs 2 articles with 1 bull signal each (but also no bears)
    # Stronger signal weight = 5 vs 1+1=2 → strongly worded wins more toward 1.0
    strong = [_article(title="beats expectations strong surge rally upgrade buyback")]
    weak = [_article(title="good news"), _article(title="positive outlook")]

    with patch("smart_money.news_scorer.get_ticker_news", return_value=strong):
        score_strong = compute_news_score("AAPL")

    # weak has no keyword hits → neutral weight 0.3 each
    with patch("smart_money.news_scorer.get_ticker_news", return_value=weak):
        score_weak = compute_news_score("AAPL")

    # Both should be above 0.5 but strongly worded closer to 1.0
    assert score_strong >= score_weak


def test_neutral_articles_score_neutral():
    articles = [_article(title="company files quarterly report"),
                _article(title="annual meeting scheduled for next week")]
    with patch("smart_money.news_scorer.get_ticker_news", return_value=articles):
        score = compute_news_score("AAPL")
    assert score == pytest.approx(0.5)


def test_single_bull_article_above_half():
    with patch("smart_money.news_scorer.get_ticker_news",
               return_value=[_article(title="stock surges after strong earnings beat")]):
        assert compute_news_score("AAPL") > 0.5


def test_single_bear_article_below_half():
    with patch("smart_money.news_scorer.get_ticker_news",
               return_value=[_article(title="company files for bankruptcy fraud investigation")]):
        assert compute_news_score("AAPL") < 0.5


# ---------------------------------------------------------------------------
# Recency weighting integration
# ---------------------------------------------------------------------------

def test_recent_bull_outweighs_old_neutral():
    recent_bull = _article(title="stock surges on earnings beat", published_at=_ts(2))
    old_neutral = _article(title="quarterly filing submitted", published_at=_ts(96))

    with patch("smart_money.news_scorer.get_ticker_news",
               return_value=[recent_bull, old_neutral]):
        score = compute_news_score("AAPL")
    assert score > 0.5


def test_recent_article_outweighs_stale_opposite():
    # Recent bearish + stale bullish: recent bearish should win
    recent_bear = _article(title="bankruptcy fraud lawsuit layoffs", published_at=_ts(3))
    old_bull = _article(title="upgraded strong buy growth surge rally", published_at=_ts(120))

    with patch("smart_money.news_scorer.get_ticker_news",
               return_value=[recent_bear, old_bull]):
        score = compute_news_score("AAPL")
    assert score < 0.5


def test_description_field_contributes_to_score():
    # Signal is only in description, not title
    article = _article(title="company update", description="stock surges on strong earnings beat")
    with patch("smart_money.news_scorer.get_ticker_news", return_value=[article]):
        score = compute_news_score("AAPL")
    assert score > 0.5


# ---------------------------------------------------------------------------
# Negation detection
# ---------------------------------------------------------------------------

def test_negated_bullish_word_does_not_count_as_bullish():
    bull, bear = _count_keywords("company did not beat expectations this quarter")
    # "beat" is negated by "not" → should NOT count as bullish
    assert bull == 0


def test_negated_bearish_word_counts_as_bullish():
    bull, bear = _count_keywords("stock will not decline further say analysts")
    # "decline" is negated by "not" → flipped to bullish
    assert bull >= 1
    assert bear == 0


def test_non_negated_bullish_still_counts():
    bull, bear = _count_keywords("stock beat expectations and surged higher")
    assert bull >= 2


def test_cannot_negation_works():
    bull2, bear2 = _count_keywords("analysts cannot recommend a buy at this price")
    # "buy" negated by "cannot" → not bullish
    assert bull2 == 0


def test_no_negation_at_start():
    bull, bear = _count_keywords("no growth is expected in q3")
    # "growth" negated by "no" → not bullish
    assert bull == 0
