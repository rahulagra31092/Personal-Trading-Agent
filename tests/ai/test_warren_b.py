"""Tests for Warren B AI core — Claude API is mocked."""
import pytest
from unittest.mock import patch, MagicMock


def _mock_claude_response(text: str):
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


def test_chat_returns_string():
    from ai.warren_b import chat
    mock_response = _mock_claude_response("Here is my analysis...")
    with patch("ai.warren_b.anthropic.Anthropic") as mock_client_cls, \
         patch("ai.warren_b.build_context_string", return_value="context"), \
         patch("ai.warren_b.log_warren_conversation"), \
         patch("ai.warren_b.log_warren_decision"):
        mock_client = mock_client_cls.return_value
        mock_client.messages.create.return_value = mock_response
        result = chat("What should I do with AMD?", session_id="test-001", interface="web")
    assert isinstance(result, str)
    assert len(result) > 0


def test_chat_logs_user_and_warren_messages():
    from ai.warren_b import chat
    mock_response = _mock_claude_response("My advice is...")
    log_calls = []
    with patch("ai.warren_b.anthropic.Anthropic") as mock_client_cls, \
         patch("ai.warren_b.build_context_string", return_value="context"), \
         patch("ai.warren_b.log_warren_conversation", side_effect=lambda **kw: log_calls.append(kw)), \
         patch("ai.warren_b.log_warren_decision"):
        mock_client = mock_client_cls.return_value
        mock_client.messages.create.return_value = mock_response
        chat("Should I buy AMD?", session_id="test-002", interface="web")
    roles = [c["role"] for c in log_calls]
    assert "user" in roles
    assert "warren" in roles


def test_generate_briefing_returns_string():
    from ai.warren_b import generate_briefing
    mock_response = _mock_claude_response("Good morning. Here is your briefing...")
    with patch("ai.warren_b.anthropic.Anthropic") as mock_client_cls, \
         patch("ai.warren_b.build_context_string", return_value="context"), \
         patch("ai.warren_b.log_warren_conversation"), \
         patch("ai.warren_b.log_warren_decision"):
        mock_client = mock_client_cls.return_value
        mock_client.messages.create.return_value = mock_response
        result = generate_briefing()
    assert "Good morning" in result


def test_generate_monthly_strategy_returns_string():
    from ai.warren_b import generate_monthly_strategy
    mock_response = _mock_claude_response("This month I recommend deploying $2,000 into AMD...")
    with patch("ai.warren_b.anthropic.Anthropic") as mock_client_cls, \
         patch("ai.warren_b.build_context_string", return_value="context"), \
         patch("ai.warren_b.log_warren_conversation"), \
         patch("ai.warren_b.log_warren_decision"):
        mock_client = mock_client_cls.return_value
        mock_client.messages.create.return_value = mock_response
        result = generate_monthly_strategy()
    assert isinstance(result, str)
    assert len(result) > 0


def test_chat_with_empty_message_raises():
    from ai.warren_b import chat
    with pytest.raises(ValueError, match="message cannot be empty"):
        chat("", session_id="test-003", interface="web")
