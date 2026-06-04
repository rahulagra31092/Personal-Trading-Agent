import pytest
from unittest.mock import patch
from api.paper_portfolio import (
    initialize_portfolio,
    is_initialized,
    get_positions,
    get_portfolio_value,
    get_account,
    rebalance,
    STARTING_CAPITAL,
    get_raw_positions,
    update_peak_prices,
    check_trailing_stops,
    log_daily_scores,
    get_score_trend,
)
from api.paper_portfolio import log_weight_change, get_annual_weight_delta
from api.paper_portfolio import (
    log_warren_decision, get_recent_warren_decisions,
    log_warren_conversation, get_warren_conversation_history,
)


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    import api.paper_portfolio as pp
    monkeypatch.setattr(pp, "PAPER_DB_PATH", tmp_path / "paper_portfolio.db")
    pp.init_paper_db()


_BUYS = [
    {"ticker": "NVDA", "shares": 3.812, "price": 131.20},
    {"ticker": "AVGO", "shares": 2.564, "price": 195.00},
    {"ticker": "MU",   "shares": 4.459, "price": 112.10},
]


def test_not_initialized_by_default():
    assert not is_initialized()


def test_initialize_creates_account():
    initialize_portfolio(_BUYS, capital=STARTING_CAPITAL)
    assert is_initialized()
    acct = get_account()
    assert acct["starting_capital"] == STARTING_CAPITAL
    assert acct["cash"] > 0


def test_cash_equals_unspent_capital():
    initialize_portfolio(_BUYS, capital=STARTING_CAPITAL)
    spent = sum(b["shares"] * b["price"] for b in _BUYS)
    acct = get_account()
    assert abs(acct["cash"] - (STARTING_CAPITAL - spent)) < 0.01


def test_positions_count_matches_buys():
    initialize_portfolio(_BUYS, capital=STARTING_CAPITAL)
    with patch("api.paper_portfolio._fetch_prices", return_value={}):
        positions = get_positions()
    assert len(positions) == len(_BUYS)
    tickers = {p["ticker"] for p in positions}
    assert tickers == {"NVDA", "AVGO", "MU"}


def test_portfolio_value_total():
    initialize_portfolio(_BUYS, capital=STARTING_CAPITAL)
    # Mock prices equal to avg_cost → P&L = 0
    prices = {b["ticker"]: b["price"] for b in _BUYS}
    with patch("api.paper_portfolio._fetch_prices", return_value=prices), \
         patch("api.paper_portfolio._spy_return_since", return_value=0.0):
        pv = get_portfolio_value()
    assert abs(pv["total_pnl"]) < 0.10  # ~0 since prices == cost
    assert pv["total_value"] == pytest.approx(STARTING_CAPITAL, abs=1.0)


def test_portfolio_value_with_gain():
    initialize_portfolio(_BUYS, capital=STARTING_CAPITAL)
    # All positions up 10%
    prices = {b["ticker"]: b["price"] * 1.10 for b in _BUYS}
    with patch("api.paper_portfolio._fetch_prices", return_value=prices), \
         patch("api.paper_portfolio._spy_return_since", return_value=0.0):
        pv = get_portfolio_value()
    assert pv["total_pnl"] > 0
    assert pv["total_pnl_pct"] > 0


def test_rebalance_sell_removes_position():
    initialize_portfolio(_BUYS, capital=STARTING_CAPITAL)
    rebalance(
        sells=[{"ticker": "MU", "price": 112.10, "reason": "test"}],
        buys=[],
    )
    with patch("api.paper_portfolio._fetch_prices", return_value={}):
        positions = get_positions()
    tickers = {p["ticker"] for p in positions}
    assert "MU" not in tickers


def test_rebalance_sell_returns_cash():
    initialize_portfolio(_BUYS, capital=STARTING_CAPITAL)
    cash_before = get_account()["cash"]
    mu = next(b for b in _BUYS if b["ticker"] == "MU")
    rebalance(
        sells=[{"ticker": "MU", "price": mu["price"], "reason": "test"}],
        buys=[],
    )
    cash_after = get_account()["cash"]
    assert cash_after > cash_before


def test_rebalance_buy_adds_position():
    initialize_portfolio(_BUYS, capital=STARTING_CAPITAL)
    rebalance(
        sells=[],
        buys=[{"ticker": "ARM", "shares": 5.0, "price": 98.0}],
    )
    with patch("api.paper_portfolio._fetch_prices", return_value={}):
        positions = get_positions()
    tickers = {p["ticker"] for p in positions}
    assert "ARM" in tickers


def test_initialize_is_idempotent():
    initialize_portfolio(_BUYS, capital=STARTING_CAPITAL)
    # Re-initialize with different buys
    new_buys = [{"ticker": "AAPL", "shares": 5.0, "price": 180.0}]
    initialize_portfolio(new_buys, capital=STARTING_CAPITAL)
    with patch("api.paper_portfolio._fetch_prices", return_value={}):
        positions = get_positions()
    assert len(positions) == 1
    assert positions[0]["ticker"] == "AAPL"


def test_update_peak_prices_sets_initial_peak():
    initialize_portfolio([{"ticker": "NVDA", "shares": 1.0, "price": 100.0}])
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 120.0}):
        update_peak_prices()
    raw = get_raw_positions()
    nvda = next(p for p in raw if p["ticker"] == "NVDA")
    assert nvda["peak_price"] == pytest.approx(120.0)


def test_update_peak_prices_does_not_decrease_peak():
    initialize_portfolio([{"ticker": "NVDA", "shares": 1.0, "price": 100.0}])
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 150.0}):
        update_peak_prices()
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 90.0}):
        update_peak_prices()
    raw = get_raw_positions()
    nvda = next(p for p in raw if p["ticker"] == "NVDA")
    assert nvda["peak_price"] == pytest.approx(150.0)


def test_check_trailing_stops_no_trigger_within_threshold():
    initialize_portfolio([{"ticker": "NVDA", "shares": 1.0, "price": 100.0}])
    # Peak=110, current=92 → drop 16.4% < 20% → no trigger
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 110.0}):
        update_peak_prices()
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 92.0}):
        stops = check_trailing_stops()
    assert stops == []


def test_check_trailing_stops_fires_at_20pct_drop():
    initialize_portfolio([{"ticker": "NVDA", "shares": 1.0, "price": 100.0}])
    # Peak=125, current=99 → drop 20.8% > 20% → trigger
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 125.0}):
        update_peak_prices()
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 99.0}):
        stops = check_trailing_stops()
    assert len(stops) == 1
    assert stops[0]["ticker"] == "NVDA"
    assert stops[0]["trail_drop_pct"] < -20.0


def test_check_trailing_stops_uses_avg_cost_as_initial_peak():
    # No peak_price set yet → avg_cost is treated as initial peak
    initialize_portfolio([{"ticker": "NVDA", "shares": 1.0, "price": 100.0}])
    # Drop 22% from cost before any peak update
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 78.0}):
        stops = check_trailing_stops()
    assert len(stops) == 1
    assert stops[0]["ticker"] == "NVDA"


def test_check_trailing_stops_no_positions_returns_empty():
    stops = check_trailing_stops()
    assert stops == []


def test_check_trailing_stops_exact_boundary_does_not_fire():
    # current == peak * 0.80 exactly — strict less-than means NO trigger
    initialize_portfolio([{"ticker": "NVDA", "shares": 1.0, "price": 100.0}])
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 125.0}):
        update_peak_prices()
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 100.0}):
        stops = check_trailing_stops()
    assert stops == []


def test_check_trailing_stops_one_cent_below_boundary_fires():
    initialize_portfolio([{"ticker": "NVDA", "shares": 1.0, "price": 100.0}])
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 125.0}):
        update_peak_prices()
    with patch("api.paper_portfolio._fetch_prices", return_value={"NVDA": 99.99}):
        stops = check_trailing_stops()
    assert len(stops) == 1


def test_check_trailing_stops_returns_all_triggered():
    initialize_portfolio([
        {"ticker": "NVDA", "shares": 1.0, "price": 100.0},
        {"ticker": "AVGO", "shares": 1.0, "price": 200.0},
        {"ticker": "MU",   "shares": 1.0, "price": 50.0},
    ])
    with patch("api.paper_portfolio._fetch_prices",
               return_value={"NVDA": 120.0, "AVGO": 220.0, "MU": 60.0}):
        update_peak_prices()
    # NVDA: 90/120 = 25% drop → fires; AVGO: 170/220 = 22.7% drop → fires; MU: 55/60 = 8.3% → no fire
    with patch("api.paper_portfolio._fetch_prices",
               return_value={"NVDA": 90.0, "AVGO": 170.0, "MU": 55.0}):
        stops = check_trailing_stops()
    triggered = {s["ticker"] for s in stops}
    assert triggered == {"NVDA", "AVGO"}
    assert "MU" not in triggered


def test_log_daily_scores_stores_records():
    scores = {"NVDA": 0.72, "AAPL": 0.55, "XOM": 0.38}
    log_daily_scores(scores, date_str="2026-01-10")
    trend = get_score_trend("NVDA", as_of="2026-01-10")
    assert trend["latest_score"] == pytest.approx(0.72)


def test_get_score_trend_no_history_returns_none_delta():
    trend = get_score_trend("UNKNOWN_TICKER_ZZZ", as_of="2026-01-10")
    assert trend["delta_5d"] is None
    assert trend["latest_score"] is None


def test_get_score_trend_rising_signal():
    # Score rises from 0.50 to 0.65 over 6 days
    for i, score in enumerate([0.50, 0.53, 0.56, 0.58, 0.61, 0.65]):
        log_daily_scores({"MSFT_TEST": score}, date_str=f"2026-01-0{i+1}")
    trend = get_score_trend("MSFT_TEST", as_of="2026-01-06")
    assert trend["delta_5d"] == pytest.approx(0.65 - 0.50, abs=0.001)
    assert trend["direction"] == "rising"


def test_get_score_trend_falling_signal():
    for i, score in enumerate([0.70, 0.67, 0.64, 0.61, 0.58, 0.54]):
        log_daily_scores({"AMZN_TEST": score}, date_str=f"2026-01-0{i+1}")
    trend = get_score_trend("AMZN_TEST", as_of="2026-01-06")
    assert trend["delta_5d"] < 0
    assert trend["direction"] == "falling"


def test_get_score_trend_flat_signal():
    for i in range(6):
        log_daily_scores({"META_TEST": 0.60}, date_str=f"2026-01-0{i+1}")
    trend = get_score_trend("META_TEST", as_of="2026-01-06")
    assert trend["direction"] == "flat"


def test_log_daily_scores_idempotent_same_day():
    # Writing the same ticker/date twice should update (upsert)
    log_daily_scores({"NVDA_TEST": 0.60}, date_str="2026-01-15")
    log_daily_scores({"NVDA_TEST": 0.65}, date_str="2026-01-15")
    trend = get_score_trend("NVDA_TEST", as_of="2026-01-15")
    assert trend["latest_score"] == pytest.approx(0.65)


def test_log_daily_scores_writes_all_tickers():
    scores = {"ALPHA_T": 0.72, "BETA_T": 0.55, "GAMMA_T": 0.38}
    log_daily_scores(scores, date_str="2026-02-10")
    for t, s in scores.items():
        assert get_score_trend(t, as_of="2026-02-10")["latest_score"] == pytest.approx(s)


def test_get_score_trend_excludes_future_scores():
    log_daily_scores({"FUTURE_T": 0.5}, date_str="2026-02-10")
    log_daily_scores({"FUTURE_T": 0.9}, date_str="2026-02-20")
    trend = get_score_trend("FUTURE_T", as_of="2026-02-10")
    assert trend["latest_score"] == pytest.approx(0.5)


def test_score_trend_ticker_case_insensitive():
    log_daily_scores({"lower_t": 0.7}, date_str="2026-02-10")
    trend = get_score_trend("LOWER_T", as_of="2026-02-10")
    assert trend["latest_score"] == pytest.approx(0.7)


def test_log_weight_change_and_retrieve():
    log_weight_change("momentum", 0.25, 0.28, as_of="2026-01-10")
    delta = get_annual_weight_delta("momentum", as_of="2026-01-10")
    assert abs(delta - 0.03) < 0.001


def test_get_annual_weight_delta_no_history_returns_zero():
    delta = get_annual_weight_delta("unknown_factor_xyz", as_of="2026-01-10")
    assert delta == 0.0


def test_get_annual_weight_delta_sums_multiple_changes():
    log_weight_change("technical", 0.20, 0.23, as_of="2026-01-10")
    log_weight_change("technical", 0.23, 0.25, as_of="2026-04-01")
    delta = get_annual_weight_delta("technical", as_of="2026-04-01")
    assert abs(delta - 0.05) < 0.001


def test_get_annual_weight_delta_ignores_changes_older_than_365_days():
    log_weight_change("quality", 0.15, 0.18, as_of="2025-01-01")
    log_weight_change("quality", 0.18, 0.20, as_of="2026-04-01")
    # Only the 2026-04-01 change is within 365 days of 2026-04-01
    delta = get_annual_weight_delta("quality", as_of="2026-04-01")
    assert abs(delta - 0.02) < 0.001


def test_log_weight_change_defaults_to_today():
    from datetime import date
    log_weight_change("earnings", 0.15, 0.17)
    delta = get_annual_weight_delta("earnings")
    assert abs(delta - 0.02) < 0.001


def test_log_warren_decision_stores_record():
    log_warren_decision(
        decision_type="buy",
        recommendation="Buy 5 shares of AMD at market",
        rationale="Highest conviction signal today at 0.78",
        ticker="AMD",
        model_score=0.78,
        regime="normal",
        as_of="2026-06-04",
    )
    decisions = get_recent_warren_decisions(days=7, as_of="2026-06-04")
    assert len(decisions) >= 1
    amd = next((d for d in decisions if d["ticker"] == "AMD"), None)
    assert amd is not None
    assert amd["decision_type"] == "buy"
    assert amd["model_score"] == pytest.approx(0.78)


def test_get_recent_warren_decisions_respects_days_window():
    log_warren_decision(
        decision_type="hold",
        recommendation="Hold everything",
        rationale="Regime is elevated, patience is the call",
        ticker=None,
        model_score=None,
        regime="elevated",
        as_of="2025-01-01",
    )
    decisions = get_recent_warren_decisions(days=7, as_of="2026-06-04")
    old = [d for d in decisions if d["decision_date"] == "2025-01-01"]
    assert old == []


def test_log_warren_conversation_stores_record():
    session = "test-session-001"
    log_warren_conversation(session_id=session, interface="web", role="user",
                            content="What do you think about AMD?")
    log_warren_conversation(session_id=session, interface="web", role="warren",
                            content="AMD is our highest conviction signal...")
    history = get_warren_conversation_history(session_id=session)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "warren"


def test_get_warren_conversation_history_chronological():
    session = "test-session-002"
    log_warren_conversation(session_id=session, interface="web", role="user",
                            content="First message", as_of="2026-06-04T09:00:00")
    log_warren_conversation(session_id=session, interface="web", role="warren",
                            content="Second message", as_of="2026-06-04T09:01:00")
    history = get_warren_conversation_history(session_id=session)
    assert history[0]["content"] == "First message"
    assert history[1]["content"] == "Second message"
