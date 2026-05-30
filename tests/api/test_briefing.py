from unittest.mock import patch, MagicMock
from api.briefing import build_briefing_message, send_slack_briefing, BRIEFING_TICKERS

_FAKE_BUY = {
    "ticker": "NVDA",
    "signal": {"label": "BUY", "composite_score": 0.72, "layer_scores": {}},
    "confidence": {
        "prob_success": 0.54,
        "base_target": 900.0,
        "lower_80": 860.0,
        "upper_80": 940.0,
        "downside_pct": -0.04,
        "upside_pct": 0.04,
    },
    "current_price": 880.0,
    "atr_stop": 842.0,
    "vol_regime": "medium",
    "rsi": 55.0,
    "ema_trend": "bullish",
}

_FAKE_WATCH = {
    "ticker": "AAPL",
    "signal": {"label": "WATCH", "composite_score": 0.51, "layer_scores": {}},
    "confidence": {
        "prob_success": 0.49,
        "base_target": 195.0,
        "lower_80": 188.0,
        "upper_80": 202.0,
        "downside_pct": -0.03,
        "upside_pct": 0.03,
    },
    "current_price": 193.5,
    "atr_stop": 185.0,
    "vol_regime": "low",
    "rsi": 50.0,
    "ema_trend": "neutral",
}


def test_build_briefing_message_includes_buy_ticker():
    msg = build_briefing_message([_FAKE_BUY, _FAKE_WATCH])
    assert "NVDA" in msg


def test_build_briefing_message_no_buys():
    msg = build_briefing_message([_FAKE_WATCH])
    assert "No BUY signals" in msg


def test_build_briefing_message_shows_screened_count():
    msg = build_briefing_message([_FAKE_BUY, _FAKE_WATCH])
    assert "2 tickers" in msg


def test_send_slack_briefing_posts_to_webhook():
    with patch("api.briefing.screen_tickers", return_value=[_FAKE_BUY]), \
         patch("api.briefing.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status.return_value = None
        send_slack_briefing(["NVDA"])
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert "text" in kwargs["json"]


def test_briefing_tickers_is_nonempty_list():
    assert isinstance(BRIEFING_TICKERS, list)
    assert len(BRIEFING_TICKERS) > 0
