"""Tests for Warren B FastAPI routes."""
import pytest
from unittest.mock import patch
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
    with patch("api.warren_b_routes.chat", return_value="Here is what I think..."):
        resp = client.post("/warren-b/slack-command", data={
            "text": "Should I add AMD?",
            "user_id": "U12345",
            "response_url": "https://hooks.slack.com/fake",
        })
    assert resp.status_code == 200
