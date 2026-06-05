"""Tests for Warren B memory and context builder."""
import pytest
from unittest.mock import patch
from data.warren_b_memory import (
    calculate_goal_pacing,
    extract_tickers_from_message,
    build_context_string,
)


def test_calculate_goal_pacing_month_zero():
    result = calculate_goal_pacing(current_value=100_000.0, months_elapsed=0)
    assert result["on_track_value"] == pytest.approx(100_000.0, rel=0.01)
    assert result["target"] == 417_000.0
    assert "months_remaining" in result


def test_calculate_goal_pacing_ahead():
    result = calculate_goal_pacing(current_value=160_000.0, months_elapsed=12)
    assert result["gap"] > 0
    assert "Ahead" in result["status"]


def test_calculate_goal_pacing_behind():
    result = calculate_goal_pacing(current_value=120_000.0, months_elapsed=12)
    assert result["gap"] < 0
    assert "Behind" in result["status"]


def test_calculate_goal_pacing_month_12_on_track_value():
    result = calculate_goal_pacing(current_value=0.0, months_elapsed=12)
    # On-track value at 12 months ≈ $148,265
    assert 145_000 < result["on_track_value"] < 152_000


def test_extract_tickers_single():
    tickers = extract_tickers_from_message("What do you think about AMD today?")
    assert "AMD" in tickers


def test_extract_tickers_multiple():
    tickers = extract_tickers_from_message("Should I add to NVDA or switch to GOOGL?")
    assert "NVDA" in tickers
    assert "GOOGL" in tickers


def test_extract_tickers_none():
    tickers = extract_tickers_from_message("How am I pacing against the goal?")
    assert tickers == []


def test_extract_tickers_common_words_ignored():
    tickers = extract_tickers_from_message("I want to buy and sell today")
    assert tickers == []


def test_build_context_string_includes_regime():
    mock_regime = {"regime": "normal", "vix": 15.4, "position_factor": 1.0}
    mock_portfolio = {
        "total_value": 9800.0, "cash": 8000.0, "invested": 1800.0,
        "total_pnl_pct": -2.0, "positions": []
    }
    with patch("data.warren_b_memory.get_market_regime", return_value=mock_regime), \
         patch("data.warren_b_memory.get_portfolio_value", return_value=mock_portfolio), \
         patch("data.warren_b_memory.fetch_google_sheet_portfolio", return_value=[]), \
         patch("data.warren_b_memory.get_recent_score_signals", return_value=[]), \
         patch("data.warren_b_memory.get_recent_warren_decisions", return_value=[]), \
         patch("data.warren_b_memory.get_warren_conversation_history", return_value=[]):
        ctx = build_context_string(session_id="test-123", interface="web")
    assert "15.4" in ctx
    assert "normal" in ctx
    assert "417,000" in ctx


def test_build_context_string_includes_goal_pacing():
    mock_regime = {"regime": "normal", "vix": 15.4, "position_factor": 1.0}
    mock_portfolio = {"total_value": 108_000.0, "cash": 8000.0, "invested": 100_000.0,
                      "total_pnl_pct": 0.0, "positions": []}
    with patch("data.warren_b_memory.get_market_regime", return_value=mock_regime), \
         patch("data.warren_b_memory.get_portfolio_value", return_value=mock_portfolio), \
         patch("data.warren_b_memory.fetch_google_sheet_portfolio", return_value=[]), \
         patch("data.warren_b_memory.get_recent_score_signals", return_value=[]), \
         patch("data.warren_b_memory.get_recent_warren_decisions", return_value=[]), \
         patch("data.warren_b_memory.get_warren_conversation_history", return_value=[]):
        ctx = build_context_string(session_id="test-456", interface="web",
                                   real_portfolio_value=100_000.0)
    assert "GOAL PACING" in ctx
