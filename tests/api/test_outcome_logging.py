"""Tests for signal_outcomes entry/exit logging."""
import pytest
from api.paper_portfolio import (
    log_trade_entry,
    log_trade_exit,
    get_closed_outcomes,
    get_open_outcome_tickers,
    init_paper_db,
)
import api.paper_portfolio as pp


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "PAPER_DB_PATH", tmp_path / "paper_portfolio.db")
    init_paper_db()


_SCORES = {
    "technical": 0.65, "momentum": 0.72, "quality": 0.55,
    "congress": 0.60, "estimate_revisions": 0.55, "news_reaction": 0.50, "earnings": 0.58,
}


def test_log_entry_creates_open_record():
    log_trade_entry("NVDA", "2026-06-01", 130.50, _SCORES, 0.63, vix=15.2, regime="low_vol", sector="Semis")
    open_tickers = get_open_outcome_tickers()
    assert "NVDA" in open_tickers


def test_log_exit_closes_record_and_computes_return():
    log_trade_entry("NVDA", "2026-06-01", 100.0, _SCORES, 0.63)
    log_trade_exit("NVDA", "2026-07-01", 115.0, "rank_drop")
    closed = get_closed_outcomes()
    assert len(closed) == 1
    assert abs(closed[0]["realized_return_pct"] - 15.0) < 0.01
    assert closed[0]["days_held"] == 30
    assert closed[0]["exit_reason"] == "rank_drop"


def test_log_exit_on_no_open_record_is_silent():
    log_trade_exit("ZZZ", "2026-07-01", 100.0, "stop")  # should not raise
    assert get_closed_outcomes() == []


def test_open_tickers_excludes_closed():
    log_trade_entry("AAPL", "2026-06-01", 200.0, _SCORES, 0.68)
    log_trade_entry("MSFT", "2026-06-01", 400.0, _SCORES, 0.71)
    log_trade_exit("AAPL", "2026-07-01", 210.0, "rebalance")
    open_set = get_open_outcome_tickers()
    assert "AAPL" not in open_set
    assert "MSFT" in open_set


def test_closed_outcomes_min_filter():
    log_trade_entry("T1", "2026-06-01", 100.0, _SCORES, 0.60)
    log_trade_exit("T1", "2026-07-01", 105.0, "stop")
    result = get_closed_outcomes(min_closed=5)
    assert result == []    # only 1 closed, below min of 5
    result = get_closed_outcomes(min_closed=1)
    assert len(result) == 1


def test_layer_scores_stored():
    log_trade_entry("AMD", "2026-06-01", 150.0, _SCORES, 0.63, vix=18.5, regime="normal", sector="Semis")
    log_trade_exit("AMD", "2026-07-15", 160.0, "rebalance")
    closed = get_closed_outcomes()
    assert closed[0]["score_momentum"] == pytest.approx(0.72)
    assert closed[0]["vix_at_entry"] == pytest.approx(18.5)
    assert closed[0]["sector"] == "Semis"
