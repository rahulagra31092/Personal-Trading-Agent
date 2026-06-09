"""Tests for circuit breaker alerting system."""
import pytest
from unittest.mock import patch, MagicMock
from api.circuit_breaker_alerts import (
    send_circuit_breaker_alert,
    send_data_quality_alert,
    send_recovery_alert,
)


class TestCircuitBreakerAlerts:
    """Test circuit breaker alert functionality."""

    @patch.dict("os.environ", {"SLACK_WEBHOOK_CRITICAL": "https://hooks.slack.com/test"})
    @patch("api.circuit_breaker_alerts.requests.post")
    def test_send_daily_loss_alert(self, mock_post):
        """Test sending daily loss circuit breaker alert."""
        mock_post.return_value = MagicMock(status_code=200)

        result = send_circuit_breaker_alert(
            reason="daily_loss",
            daily_loss_pct=-0.035,
            consecutive_losses=1,
            max_daily_loss=0.025,
            max_consecutive_losses=3,
        )

        assert result is True
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        payload = call_args.kwargs["json"]
        assert "attachments" in payload
        assert "Daily Loss Limit Exceeded" in payload["attachments"][0]["title"]

    @patch.dict("os.environ", {"SLACK_WEBHOOK_CRITICAL": "https://hooks.slack.com/test"})
    @patch("api.circuit_breaker_alerts.requests.post")
    def test_send_consecutive_loss_alert(self, mock_post):
        """Test sending consecutive loss circuit breaker alert."""
        mock_post.return_value = MagicMock(status_code=200)

        result = send_circuit_breaker_alert(
            reason="consecutive_losses",
            daily_loss_pct=-0.015,
            consecutive_losses=3,
            max_daily_loss=0.025,
            max_consecutive_losses=3,
        )

        assert result is True
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        payload = call_args.kwargs["json"]
        assert "Consecutive Loss Streak" in payload["attachments"][0]["title"]

    @patch.dict("os.environ", {})
    def test_alert_not_sent_without_webhook_url(self):
        """Alert should not be sent if webhook URL not configured."""
        result = send_circuit_breaker_alert(
            reason="daily_loss",
            daily_loss_pct=-0.035,
            consecutive_losses=1,
        )

        assert result is False

    @patch.dict("os.environ", {"SLACK_WEBHOOK_CRITICAL": "https://hooks.slack.com/test"})
    @patch("api.circuit_breaker_alerts.requests.post")
    def test_alert_handles_request_failure(self, mock_post):
        """Alert should handle HTTP failures gracefully."""
        mock_post.return_value = MagicMock(status_code=500)

        result = send_circuit_breaker_alert(
            reason="daily_loss",
            daily_loss_pct=-0.035,
            consecutive_losses=1,
        )

        assert result is False

    @patch.dict("os.environ", {"SLACK_WEBHOOK_CRITICAL": "https://hooks.slack.com/test"})
    @patch("api.circuit_breaker_alerts.requests.post")
    def test_alert_handles_exception(self, mock_post):
        """Alert should handle request exceptions gracefully."""
        mock_post.side_effect = Exception("Network error")

        result = send_circuit_breaker_alert(
            reason="daily_loss",
            daily_loss_pct=-0.035,
            consecutive_losses=1,
        )

        assert result is False


class TestDataQualityAlerts:
    """Test data quality alert functionality."""

    @patch.dict("os.environ", {"SLACK_WEBHOOK_DATA_QUALITY": "https://hooks.slack.com/test"})
    @patch("api.circuit_breaker_alerts.requests.post")
    def test_send_critical_data_quality_alert(self, mock_post):
        """Test sending critical data quality alert."""
        mock_post.return_value = MagicMock(status_code=200)

        result = send_data_quality_alert(
            portfolio_health_pct=0.35,
            degraded_count=20,
            dead_count=15,
            alert_type="critical",
        )

        assert result is True
        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["json"]
        assert "Data Quality Critical" in payload["attachments"][0]["title"]
        assert "#FF0000" == payload["attachments"][0]["color"]  # Red

    @patch.dict("os.environ", {"SLACK_WEBHOOK_DATA_QUALITY": "https://hooks.slack.com/test"})
    @patch("api.circuit_breaker_alerts.requests.post")
    def test_send_degraded_data_quality_alert(self, mock_post):
        """Test sending degraded data quality alert."""
        mock_post.return_value = MagicMock(status_code=200)

        result = send_data_quality_alert(
            portfolio_health_pct=0.65,
            degraded_count=20,
            dead_count=5,
            alert_type="degraded",
        )

        assert result is True
        payload = mock_post.call_args.kwargs["json"]
        assert "Data Quality Degraded" in payload["attachments"][0]["title"]
        assert "#FF9900" == payload["attachments"][0]["color"]  # Orange

    @patch.dict("os.environ", {"SLACK_WEBHOOK_DATA_QUALITY": "https://hooks.slack.com/test"})
    @patch("api.circuit_breaker_alerts.requests.post")
    def test_send_healthy_data_quality_alert(self, mock_post):
        """Test sending healthy data quality alert."""
        mock_post.return_value = MagicMock(status_code=200)

        result = send_data_quality_alert(
            portfolio_health_pct=0.90,
            degraded_count=5,
            dead_count=2,
            alert_type="healthy",
        )

        assert result is True
        payload = mock_post.call_args.kwargs["json"]
        assert "Data Quality Healthy" in payload["attachments"][0]["title"]
        assert "#00AA00" == payload["attachments"][0]["color"]  # Green

    @patch.dict("os.environ", {})
    def test_data_quality_alert_not_sent_without_webhook(self):
        """Alert should not be sent if webhook URL not configured."""
        result = send_data_quality_alert(
            portfolio_health_pct=0.35,
            degraded_count=20,
            dead_count=15,
            alert_type="critical",
        )

        assert result is False


class TestRecoveryAlerts:
    """Test recovery alert functionality."""

    @patch.dict("os.environ", {"SLACK_WEBHOOK_CRITICAL": "https://hooks.slack.com/test"})
    @patch("api.circuit_breaker_alerts.requests.post")
    def test_send_circuit_breaker_recovery_alert(self, mock_post):
        """Test sending circuit breaker recovery alert."""
        mock_post.return_value = MagicMock(status_code=200)

        result = send_recovery_alert("circuit_breaker_reset")

        assert result is True
        payload = mock_post.call_args.kwargs["json"]
        assert "Circuit Breaker Reset" in payload["attachments"][0]["title"]
        assert "#00AA00" == payload["attachments"][0]["color"]  # Green

    @patch.dict("os.environ", {"SLACK_WEBHOOK_CRITICAL": "https://hooks.slack.com/test"})
    @patch("api.circuit_breaker_alerts.requests.post")
    def test_send_data_quality_recovery_alert(self, mock_post):
        """Test sending data quality recovery alert."""
        mock_post.return_value = MagicMock(status_code=200)

        result = send_recovery_alert("data_quality_recovered")

        assert result is True
        payload = mock_post.call_args.kwargs["json"]
        assert "Data Quality Recovered" in payload["attachments"][0]["title"]

    @patch.dict("os.environ", {})
    def test_recovery_alert_not_sent_without_webhook(self):
        """Alert should not be sent if webhook URL not configured."""
        result = send_recovery_alert("circuit_breaker_reset")

        assert result is False


class TestAlertPayloads:
    """Test alert payload structure and content."""

    @patch.dict("os.environ", {"SLACK_WEBHOOK_CRITICAL": "https://hooks.slack.com/test"})
    @patch("api.circuit_breaker_alerts.requests.post")
    def test_alert_payload_includes_timestamp(self, mock_post):
        """Alert payload should include timestamp."""
        mock_post.return_value = MagicMock(status_code=200)

        send_circuit_breaker_alert(
            reason="daily_loss",
            daily_loss_pct=-0.035,
            consecutive_losses=1,
        )

        payload = mock_post.call_args.kwargs["json"]
        assert "ts" in payload["attachments"][0]
        assert isinstance(payload["attachments"][0]["ts"], int)

    @patch.dict("os.environ", {"SLACK_WEBHOOK_DATA_QUALITY": "https://hooks.slack.com/test"})
    @patch("api.circuit_breaker_alerts.requests.post")
    def test_data_quality_payload_includes_metrics(self, mock_post):
        """Data quality alert should include metrics."""
        mock_post.return_value = MagicMock(status_code=200)

        send_data_quality_alert(
            portfolio_health_pct=0.65,
            degraded_count=20,
            dead_count=5,
            alert_type="degraded",
        )

        payload = mock_post.call_args.kwargs["json"]
        text = payload["attachments"][0]["text"]
        assert "65.0%" in text  # portfolio health
        assert "20" in text  # degraded count
        assert "5" in text  # dead count
