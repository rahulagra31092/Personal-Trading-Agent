from unittest.mock import patch
import pytest

from quant.quality import compute_quality_score


def _info(roe=None, gm=None):
    result = {}
    if roe is not None:
        result["returnOnEquity"] = roe
    if gm is not None:
        result["grossMargins"] = gm
    return result


def test_high_roe_and_gm_scores_high():
    with patch("quant.quality.get_cache", return_value=None), \
         patch("quant.quality.set_cache"), \
         patch("quant.quality.yf.Ticker") as mock_t:
        mock_t.return_value.info = _info(roe=0.35, gm=0.75)
        score = compute_quality_score("AAPL")
    assert score > 0.70


def test_low_roe_and_gm_scores_low():
    with patch("quant.quality.get_cache", return_value=None), \
         patch("quant.quality.set_cache"), \
         patch("quant.quality.yf.Ticker") as mock_t:
        mock_t.return_value.info = _info(roe=-0.10, gm=0.05)
        score = compute_quality_score("XYZ")
    assert score < 0.45


def test_missing_data_returns_neutral():
    with patch("quant.quality.get_cache", return_value=None), \
         patch("quant.quality.set_cache"), \
         patch("quant.quality.yf.Ticker") as mock_t:
        mock_t.return_value.info = {}
        score = compute_quality_score("XYZ")
    assert score == 0.5


def test_only_roe_present_uses_roe():
    with patch("quant.quality.get_cache", return_value=None), \
         patch("quant.quality.set_cache"), \
         patch("quant.quality.yf.Ticker") as mock_t:
        mock_t.return_value.info = _info(roe=0.20)
        score = compute_quality_score("AAPL")
    assert 0.20 <= score <= 0.85


def test_score_bounded():
    with patch("quant.quality.get_cache", return_value=None), \
         patch("quant.quality.set_cache"), \
         patch("quant.quality.yf.Ticker") as mock_t:
        mock_t.return_value.info = _info(roe=5.0, gm=1.0)  # extreme values
        score = compute_quality_score("AAPL")
    assert 0.0 <= score <= 1.0


def test_cache_hit_skips_yfinance():
    with patch("quant.quality.get_cache", return_value=0.68), \
         patch("quant.quality.yf.Ticker") as mock_t:
        score = compute_quality_score("AAPL")
    assert score == 0.68
    mock_t.assert_not_called()


def test_exception_returns_neutral():
    with patch("quant.quality.get_cache", return_value=None), \
         patch("quant.quality.yf.Ticker", side_effect=RuntimeError("api error")):
        score = compute_quality_score("AAPL")
    assert score == 0.5


def test_negative_roe_floors_at_020():
    with patch("quant.quality.get_cache", return_value=None), \
         patch("quant.quality.set_cache"), \
         patch("quant.quality.yf.Ticker") as mock_t:
        mock_t.return_value.info = _info(roe=-10.0, gm=0.0)  # extreme negative
        score = compute_quality_score("AAPL")
    assert score >= 0.20
