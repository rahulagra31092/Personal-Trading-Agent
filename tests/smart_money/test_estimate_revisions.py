import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from smart_money.estimate_revisions import compute_estimate_revision_score
from data.cache import get_cache, set_cache


@pytest.fixture(autouse=True)
def _clear_est_revision_cache():
    """Prevent live-run cache entries from polluting mocked tests."""
    import sqlite3
    try:
        from data.cache import DB_PATH
        with sqlite3.connect(DB_PATH) as con:
            con.execute("DELETE FROM cache WHERE key LIKE 'est_revision:%'")
    except Exception:
        pass
    yield


def _make_upgrades_df(rows: list[tuple]) -> pd.DataFrame:
    """rows: [(date_str, from_grade, to_grade), ...]"""
    dates = [pd.Timestamp(r[0], tz="UTC") for r in rows]
    return pd.DataFrame(
        {"FromGrade": [r[1] for r in rows], "ToGrade": [r[2] for r in rows]},
        index=pd.DatetimeIndex(dates),
    )


def _mock_ticker(upgrades_df=None, rec_mean=None, num_analysts=5,
                 current_price=100.0, target_mean=None):
    t = MagicMock()
    t.upgrades_downgrades = upgrades_df
    t.info = {
        "recommendationMean": rec_mean,
        "numberOfAnalystOpinions": num_analysts,
        "currentPrice": current_price,
        "targetMeanPrice": target_mean,
    }
    return t


def test_all_upgrades_returns_bullish():
    df = _make_upgrades_df([
        ("2026-05-20", "Hold", "Buy"),
        ("2026-05-25", "Neutral", "Outperform"),
        ("2026-06-01", "Sell", "Buy"),
    ])
    with patch("smart_money.estimate_revisions.yf.Ticker", return_value=_mock_ticker(upgrades_df=df)):
        score = compute_estimate_revision_score("NVDA")
    assert score > 0.60


def test_all_downgrades_returns_bearish():
    df = _make_upgrades_df([
        ("2026-05-20", "Buy", "Sell"),
        ("2026-05-25", "Outperform", "Underperform"),
        ("2026-06-01", "Hold", "Underweight"),
    ])
    with patch("smart_money.estimate_revisions.yf.Ticker", return_value=_mock_ticker(upgrades_df=df)):
        score = compute_estimate_revision_score("XYZ")
    assert score < 0.40


def test_mixed_grades_returns_near_neutral():
    df = _make_upgrades_df([
        ("2026-05-20", "Hold", "Buy"),
        ("2026-05-25", "Buy", "Sell"),
        ("2026-06-01", "Neutral", "Outperform"),
        ("2026-06-02", "Outperform", "Underperform"),
    ])
    with patch("smart_money.estimate_revisions.yf.Ticker", return_value=_mock_ticker(upgrades_df=df)):
        score = compute_estimate_revision_score("AAPL")
    assert 0.40 <= score <= 0.60


def test_no_recent_grades_falls_back_to_rec_mean():
    with patch("smart_money.estimate_revisions.yf.Ticker",
               return_value=_mock_ticker(upgrades_df=pd.DataFrame(), rec_mean=2.0)):
        score = compute_estimate_revision_score("MSFT")
    assert score > 0.50


def test_strong_sell_rec_mean_returns_low_score():
    with patch("smart_money.estimate_revisions.yf.Ticker",
               return_value=_mock_ticker(upgrades_df=pd.DataFrame(), rec_mean=4.5)):
        score = compute_estimate_revision_score("WEAK")
    assert score < 0.25


def test_no_data_returns_neutral():
    with patch("smart_money.estimate_revisions.yf.Ticker",
               return_value=_mock_ticker(upgrades_df=pd.DataFrame(), rec_mean=None)):
        score = compute_estimate_revision_score("NODTA")
    assert score == pytest.approx(0.5)


def test_exception_returns_neutral():
    with patch("smart_money.estimate_revisions.yf.Ticker", side_effect=RuntimeError("network")):
        score = compute_estimate_revision_score("CRASH")
    assert score == pytest.approx(0.5)


def test_score_bounded_0_to_1():
    df = _make_upgrades_df([("2026-06-01", "Sell", "Strong Buy")] * 10)
    with patch("smart_money.estimate_revisions.yf.Ticker", return_value=_mock_ticker(upgrades_df=df)):
        score = compute_estimate_revision_score("NVDA")
    assert 0.05 <= score <= 0.95


def test_cache_hit_skips_yfinance():
    from data.cache import set_cache
    set_cache("est_revision:CACHED", 0.73, ttl_seconds=86400)
    with patch("smart_money.estimate_revisions.yf.Ticker") as mock_yf:
        score = compute_estimate_revision_score("CACHED")
    assert score == pytest.approx(0.73)
    mock_yf.assert_not_called()


def test_rec_mean_exactly_5_returns_near_zero():
    with patch("smart_money.estimate_revisions.yf.Ticker",
               return_value=_mock_ticker(upgrades_df=pd.DataFrame(), rec_mean=5.0)):
        score = compute_estimate_revision_score("BEAR")
    assert score < 0.10
