from unittest.mock import patch, MagicMock
from api.briefing import (
    build_briefing_message,
    send_daily_briefing,
    BRIEFING_TICKERS,
    BLUE_CHIP_UNIVERSE,
    MIDCAP_UNIVERSE,
    _caution_alerts,
)
import config as _config

_FAKE_BUY = {
    "ticker": "NVDA",
    "signal": {"label": "BUY", "composite_score": 0.72, "layer_scores": {}},
    "confidence": {"prob_success": 0.54, "base_target": 900.0, "lower_80": 860.0, "upper_80": 940.0, "downside_pct": -0.04, "upside_pct": 0.04},
    "current_price": 880.0,
    "atr_stop": 842.0,
    "vol_regime": "medium",
    "rsi": 55.0,
    "trend_regime": "bullish",
}

_FAKE_WATCH = {
    "ticker": "AAPL",
    "signal": {"label": "WATCH", "composite_score": 0.51, "layer_scores": {}},
    "confidence": {"prob_success": 0.49, "base_target": 195.0, "lower_80": 188.0, "upper_80": 202.0, "downside_pct": -0.03, "upside_pct": 0.03},
    "current_price": 193.5,
    "atr_stop": 185.0,
    "vol_regime": "low",
    "rsi": 50.0,
    "trend_regime": "neutral",
}

_FAKE_AVOID = {
    "ticker": "ZS",
    "signal": {"label": "AVOID", "composite_score": 0.32, "layer_scores": {}},
    "confidence": {"prob_success": 0.40, "base_target": 200.0, "lower_80": 190.0, "upper_80": 210.0, "downside_pct": -0.05, "upside_pct": 0.05},
    "current_price": 205.0,
    "atr_stop": 195.0,
    "vol_regime": "medium",
    "rsi": 40.0,
    "trend_regime": "bearish",
}


# ---------------------------------------------------------------------------
# build_briefing_message (backward compat)
# ---------------------------------------------------------------------------

def test_build_briefing_message_includes_buy_ticker():
    msg = build_briefing_message([_FAKE_BUY, _FAKE_WATCH])
    assert "NVDA" in msg


def test_build_briefing_message_no_buys():
    msg = build_briefing_message([_FAKE_WATCH])
    assert "No BUY signals" in msg


def test_build_briefing_message_shows_screened_count():
    msg = build_briefing_message([_FAKE_BUY, _FAKE_WATCH])
    assert "2 tickers" in msg


# ---------------------------------------------------------------------------
# Universe lists
# ---------------------------------------------------------------------------

def test_briefing_tickers_is_nonempty_list():
    assert isinstance(BRIEFING_TICKERS, list)
    assert len(BRIEFING_TICKERS) > 0


def test_blue_chip_and_midcap_are_disjoint():
    overlap = set(BLUE_CHIP_UNIVERSE) & set(MIDCAP_UNIVERSE)
    assert overlap == set(), f"Overlapping tickers: {overlap}"


def test_blue_chip_nonempty():
    assert len(BLUE_CHIP_UNIVERSE) >= 10


def test_midcap_nonempty():
    assert len(MIDCAP_UNIVERSE) >= 10


# ---------------------------------------------------------------------------
# Caution alerts
# ---------------------------------------------------------------------------

def test_no_caution_on_normal_regime():
    portfolio = {"positions": []}
    regime = {"vix": 16.0, "regime": "normal"}
    assert _caution_alerts(portfolio, regime) == []


def test_caution_on_vix_spike():
    portfolio = {"positions": []}
    regime = {"vix": 28.0, "regime": "elevated"}
    alerts = _caution_alerts(portfolio, regime)
    assert len(alerts) == 1
    assert "28.0" in alerts[0]


def test_caution_on_position_drawdown():
    portfolio = {
        "positions": [
            {**_FAKE_BUY, "pnl_pct": -16.0, "pnl": -80.0,
             "avg_cost": 880.0, "current_price": 739.2,
             "shares": 0.568, "cost_basis": 500.0, "market_value": 420.0,
             "entry_date": "2026-06-01"},
        ]
    }
    regime = {"vix": 16.0, "regime": "normal"}
    alerts = _caution_alerts(portfolio, regime)
    assert any("NVDA" in a for a in alerts)


# ---------------------------------------------------------------------------
# send_daily_briefing — smoke test
# ---------------------------------------------------------------------------

def test_send_daily_briefing_posts_two_messages():
    """With mocked everything, two POST calls should fire (msg1 + msg2)."""
    with patch("api.briefing.screen_tickers", return_value=[_FAKE_BUY, _FAKE_WATCH, _FAKE_AVOID]), \
         patch("api.briefing.get_market_regime", return_value={"vix": 15.9, "regime": "normal", "position_factor": 1.0, "max_positions": 70}), \
         patch("api.briefing.get_index_snapshot", return_value={}), \
         patch("api.briefing.get_sector_snapshot", return_value={}), \
         patch("api.briefing.get_market_news", return_value=[]), \
         patch("api.briefing.build_market_brief", return_value="Good morning. Markets stable."), \
         patch("api.briefing.is_initialized", return_value=True), \
         patch("api.briefing.get_portfolio_value", return_value={
             "starting_capital": 10000, "cash": 500, "invested": 9500,
             "total_value": 10200, "total_pnl": 200, "total_pnl_pct": 2.0,
             "spy_return_pct": 1.0, "alpha_pct": 1.0, "created_date": "2026-06-01",
             "positions": [],
         }), \
         patch("api.briefing.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status.return_value = None
        send_daily_briefing(
            blue_chip_tickers=["NVDA"],
            midcap_tickers=["ZS"],
        )
    assert mock_post.call_count == 2  # msg1 + msg2


def test_send_daily_briefing_sends_text_key():
    """Each Slack payload must include a 'text' key for notification preview."""
    with patch("api.briefing.screen_tickers", return_value=[_FAKE_BUY]), \
         patch("api.briefing.get_market_regime", return_value={"vix": 15.9, "regime": "normal", "position_factor": 1.0, "max_positions": 70}), \
         patch("api.briefing.get_index_snapshot", return_value={}), \
         patch("api.briefing.get_sector_snapshot", return_value={}), \
         patch("api.briefing.get_market_news", return_value=[]), \
         patch("api.briefing.build_market_brief", return_value="Markets up today."), \
         patch("api.briefing.is_initialized", return_value=False), \
         patch("api.briefing.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status.return_value = None
        send_daily_briefing(blue_chip_tickers=["NVDA"], midcap_tickers=[])
    for call in mock_post.call_args_list:
        assert "text" in call.kwargs["json"]


# ---------------------------------------------------------------------------
# Factor-health telemetry in model stats block
# ---------------------------------------------------------------------------

from api.briefing import _model_stats_block

_FACTOR_KEYS = ["technical", "momentum", "quality", "congress",
                "estimate_revisions", "news_reaction", "earnings"]


def _make_results(n: int, degraded_factors: list[str] = None) -> list[dict]:
    """Build fake all_results list. degraded_factors will be set to 0.5 for all tickers."""
    degraded_factors = degraded_factors or []
    results = []
    for i in range(n):
        layer_scores = {k: 0.5 if k in degraded_factors else 0.65 for k in _FACTOR_KEYS}
        results.append({
            "ticker": f"T{i}",
            "signal": {
                "label": "BUY" if i < n // 2 else "WATCH",
                "composite_score": 0.65,
                "layer_scores": layer_scores,
            },
            "current_price": 100.0,
        })
    return results


def test_model_stats_block_includes_factor_health_section():
    results = _make_results(10)
    blocks = _model_stats_block(results)
    # Must contain a block mentioning factor health
    all_text = " ".join(
        b.get("text", {}).get("text", "") for b in blocks if isinstance(b, dict)
    )
    assert "factor" in all_text.lower() or "health" in all_text.lower() or "data" in all_text.lower()


def test_model_stats_block_flags_degraded_factor():
    # All 10 tickers have quality=0.5 → should be flagged
    results = _make_results(10, degraded_factors=["quality"])
    blocks = _model_stats_block(results)
    all_text = " ".join(
        b.get("text", {}).get("text", "") for b in blocks if isinstance(b, dict)
    )
    assert "quality" in all_text.lower()


def test_model_stats_block_no_false_alarm_when_data_ok():
    # All factors vary → no degraded flags
    results = _make_results(10, degraded_factors=[])
    blocks = _model_stats_block(results)
    all_text = " ".join(
        b.get("text", {}).get("text", "") for b in blocks if isinstance(b, dict)
    )
    # "All OK" or "7/7" or similar — should NOT flag any factor
    assert "quality" not in all_text.lower() or "ok" in all_text.lower() or "7/7" in all_text.lower()
