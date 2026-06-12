"""Tests for Warren B decision layer."""
import pytest
from unittest.mock import patch, MagicMock
from api.warren_b_decision import format_decision_for_slack


def test_format_decision_for_slack_approval():
    """Format Warren B approval decision for Slack."""
    decision = {
        "approved": True,
        "confidence": 0.85,
        "reasoning": "Strong momentum",
        "recommendation": "PROCEED"
    }
    
    msg = format_decision_for_slack("AAPL", "BUY", decision)
    
    assert "APPROVED" in msg
    assert "AAPL" in msg
    assert "BUY" in msg


def test_format_decision_for_slack_rejection():
    """Format Warren B rejection decision for Slack."""
    decision = {
        "approved": False,
        "confidence": 0.3,
        "reasoning": "Signal too weak",
        "recommendation": "SKIP"
    }
    
    msg = format_decision_for_slack("XYZ", "SELL", decision)
    
    assert "REJECTED" in msg
    assert "XYZ" in msg
    assert "SELL" in msg


def test_warren_b_routes_exist():
    """Verify Warren B routes are registered."""
    from api.warren_b_routes import router
    
    assert router is not None
    # Router should have /warren-b/decide endpoint (includes prefix)
    routes = [route.path for route in router.routes]
    assert "/warren-b/decide" in routes
