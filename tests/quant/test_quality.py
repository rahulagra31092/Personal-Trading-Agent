from unittest.mock import patch
import pytest

from quant.quality import compute_quality_score, _roe_score, _fcf_score, _gm_score, _debt_score


def _info(roe=None, gm=None, fcf=None, rev=None, de=None):
    result = {}
    if roe is not None: result["returnOnEquity"] = roe
    if gm is not None: result["grossMargins"] = gm
    if fcf is not None: result["freeCashflow"] = fcf
    if rev is not None: result["totalRevenue"] = rev
    if de is not None: result["debtToEquity"] = de
    return result


# ---------------------------------------------------------------------------
# _roe_score
# ---------------------------------------------------------------------------

def test_roe_score_excellent():
    assert _roe_score(0.25) == pytest.approx(1.0)


def test_roe_score_neutral():
    assert _roe_score(0.0) == pytest.approx(0.5)


def test_roe_score_negative():
    assert _roe_score(-0.25) == pytest.approx(0.0)


def test_roe_score_bounded():
    assert _roe_score(5.0) == pytest.approx(1.0)
    assert _roe_score(-5.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _fcf_score
# ---------------------------------------------------------------------------

def test_fcf_score_excellent():
    assert _fcf_score(0.10) == pytest.approx(1.0)


def test_fcf_score_neutral():
    assert _fcf_score(0.0) == pytest.approx(0.5)


def test_fcf_score_negative_margin():
    assert _fcf_score(-0.10) == pytest.approx(0.0)


def test_fcf_score_bounded():
    assert 0.0 <= _fcf_score(1.0) <= 1.0
    assert 0.0 <= _fcf_score(-1.0) <= 1.0


# ---------------------------------------------------------------------------
# _gm_score
# ---------------------------------------------------------------------------

def test_gm_score_high_margin():
    assert _gm_score(0.80) == pytest.approx(1.0)


def test_gm_score_zero():
    assert _gm_score(0.0) == pytest.approx(0.0)


def test_gm_score_midpoint():
    assert _gm_score(0.40) == pytest.approx(0.5)


def test_gm_score_bounded():
    assert 0.0 <= _gm_score(1.5) <= 1.0


# ---------------------------------------------------------------------------
# _debt_score
# ---------------------------------------------------------------------------

def test_debt_score_no_debt():
    assert _debt_score(0.0) == pytest.approx(1.0)


def test_debt_score_moderate():
    # D/E = 3x → 1.0 - 3*0.15 = 0.55
    assert _debt_score(3.0) == pytest.approx(0.55)


def test_debt_score_high_leverage():
    # D/E > 6.7x → clamps to 0.0
    assert _debt_score(7.0) == pytest.approx(0.0)


def test_debt_score_bounded():
    assert 0.0 <= _debt_score(10.0) <= 1.0


# ---------------------------------------------------------------------------
# compute_quality_score — composite
# ---------------------------------------------------------------------------

def test_high_quality_company_scores_high():
    # All-star fundamentals: high ROE, strong FCF, fat margins, low debt
    with patch("quant.quality.get_cache", return_value=None), \
         patch("quant.quality.set_cache"), \
         patch("quant.quality.yf.Ticker") as mock_t:
        mock_t.return_value.info = _info(roe=0.35, gm=0.75, fcf=5e9, rev=20e9, de=30.0)
        score = compute_quality_score("AAPL")
    assert score > 0.80


def test_low_quality_company_scores_low():
    with patch("quant.quality.get_cache", return_value=None), \
         patch("quant.quality.set_cache"), \
         patch("quant.quality.yf.Ticker") as mock_t:
        mock_t.return_value.info = _info(roe=-0.10, gm=0.05, fcf=-1e9, rev=10e9, de=300.0)
        score = compute_quality_score("XYZ")
    assert score < 0.45


def test_missing_all_data_returns_neutral():
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
    assert 0.0 <= score <= 1.0


def test_score_bounded():
    with patch("quant.quality.get_cache", return_value=None), \
         patch("quant.quality.set_cache"), \
         patch("quant.quality.yf.Ticker") as mock_t:
        mock_t.return_value.info = _info(roe=5.0, gm=1.0, fcf=1e10, rev=1e9, de=0.0)
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


def test_missing_fcf_rev_skips_fcf_factor():
    # Only ROE + GM present — weights renormalize to (0.35+0.20)=0.55
    with patch("quant.quality.get_cache", return_value=None), \
         patch("quant.quality.set_cache"), \
         patch("quant.quality.yf.Ticker") as mock_t:
        mock_t.return_value.info = _info(roe=0.25, gm=0.80)
        score = compute_quality_score("AAPL")
    # roe_score=1.0, gm_score=1.0 → composite = 1.0
    assert score == pytest.approx(1.0, abs=0.01)


def test_bank_with_extreme_leverage_skips_debt_factor():
    # de_raw > 500 → debt factor excluded; score driven by ROE + FCF + GM
    with patch("quant.quality.get_cache", return_value=None), \
         patch("quant.quality.set_cache"), \
         patch("quant.quality.yf.Ticker") as mock_t:
        mock_t.return_value.info = _info(roe=0.15, gm=0.60, de=1200.0)
        score = compute_quality_score("JPM")
    assert 0.0 <= score <= 1.0


def test_negative_equity_skips_debt_factor():
    # de_raw < 0 (negative equity from buybacks) → debt factor excluded
    with patch("quant.quality.get_cache", return_value=None), \
         patch("quant.quality.set_cache"), \
         patch("quant.quality.yf.Ticker") as mock_t:
        mock_t.return_value.info = _info(roe=0.30, gm=0.65, de=-50.0)
        score = compute_quality_score("MCD")
    assert 0.0 <= score <= 1.0


def test_high_debt_penalizes_score():
    # Same ROE/GM but high debt → lower score
    base_info = _info(roe=0.20, gm=0.50)
    debt_info = _info(roe=0.20, gm=0.50, de=400.0)  # 4x D/E

    with patch("quant.quality.get_cache", return_value=None), \
         patch("quant.quality.set_cache"), \
         patch("quant.quality.yf.Ticker") as mock_t:
        mock_t.return_value.info = base_info
        score_no_debt = compute_quality_score("A")

    with patch("quant.quality.get_cache", return_value=None), \
         patch("quant.quality.set_cache"), \
         patch("quant.quality.yf.Ticker") as mock_t:
        mock_t.return_value.info = debt_info
        score_with_debt = compute_quality_score("B")

    assert score_no_debt > score_with_debt


def test_positive_fcf_boosts_score_vs_negative():
    good_fcf = _info(roe=0.15, gm=0.40, fcf=2e9, rev=10e9)  # 20% FCF margin
    bad_fcf = _info(roe=0.15, gm=0.40, fcf=-1e9, rev=10e9)  # -10% FCF margin

    with patch("quant.quality.get_cache", return_value=None), \
         patch("quant.quality.set_cache"), \
         patch("quant.quality.yf.Ticker") as mock_t:
        mock_t.return_value.info = good_fcf
        score_good = compute_quality_score("A")

    with patch("quant.quality.get_cache", return_value=None), \
         patch("quant.quality.set_cache"), \
         patch("quant.quality.yf.Ticker") as mock_t:
        mock_t.return_value.info = bad_fcf
        score_bad = compute_quality_score("B")

    assert score_good > score_bad
