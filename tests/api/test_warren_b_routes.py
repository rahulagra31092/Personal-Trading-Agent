"""Tests for Warren B FastAPI routes."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_warren_b_chat_returns_200():
    with patch("api.warren_b_routes.chat", return_value="Here is my analysis..."):
        resp = client.post("/warren-b/chat", json={
            "message": "What do you think about AMD?",
            "session_id": "test-001",
            "interface": "web",
        })
    assert resp.status_code == 200
    assert "response" in resp.json()


def test_warren_b_chat_rejects_empty_message():
    resp = client.post("/warren-b/chat", json={
        "message": "",
        "session_id": "test-002",
        "interface": "web",
    })
    assert resp.status_code == 422


def test_warren_b_briefing_returns_202():
    with patch("api.warren_b_routes.generate_briefing", return_value="Good morning..."), \
         patch("api.warren_b_routes._post_warren_to_slack"):
        resp = client.post("/warren-b/briefing")
    assert resp.status_code == 202


def test_warren_b_monthly_returns_202():
    with patch("api.warren_b_routes.generate_monthly_strategy", return_value="This month..."), \
         patch("api.warren_b_routes._post_warren_to_slack"):
        resp = client.post("/warren-b/monthly")
    assert resp.status_code == 202


def test_warren_b_ui_returns_html():
    resp = client.get("/warren-b/ui")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_warren_b_decisions_returns_list():
    with patch("api.warren_b_routes.get_recent_warren_decisions", return_value=[]):
        resp = client.get("/warren-b/decisions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_warren_b_slack_command_returns_200():
    # Slack signature verification is skipped if SLACK_SIGNING_SECRET is not set
    # (which it isn't in tests, so we can post without a valid signature)
    with patch("api.warren_b_routes.chat", return_value="Here is what I think..."):
        resp = client.post("/warren-b/slack-command", data={
            "text": "Should I add AMD?",
            "user_id": "U12345",
            "response_url": "https://hooks.slack.com/fake",
        }, headers={
            "X-Slack-Signature": "",
            "X-Slack-Request-Timestamp": str(int(__import__("time").time())),
        })
    assert resp.status_code == 200


def test_warren_b_stream_returns_sse():
    with patch("anthropic.Anthropic") as mock_anthropic_cls, \
         patch("data.warren_b_memory.build_context_string", return_value="context"), \
         patch("api.paper_portfolio.log_warren_conversation"):
        mock_client = mock_anthropic_cls.return_value
        mock_stream = MagicMock()
        mock_stream.text_stream = ["Hello", " ", "Warren"]
        mock_stream.__enter__ = MagicMock(return_value=mock_stream)
        mock_stream.__exit__ = MagicMock(return_value=None)
        mock_client.messages.stream.return_value = mock_stream

        resp = client.post("/warren-b/stream", json={
            "message": "Test message",
            "session_id": "test-stream-001",
        })
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


def test_warren_b_sessions_returns_list():
    with patch("api.warren_b_routes.sqlite3.connect"):
        resp = client.get("/warren-b/sessions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
