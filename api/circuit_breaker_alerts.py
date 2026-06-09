"""Circuit breaker alerting via Slack webhooks.

Sends real-time alerts when trading is halted due to:
- Daily loss limit exceeded (2.5% of capital)
- Consecutive loss streak (3+ losses)
- Data quality degradation
"""
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional
import requests

logger = logging.getLogger(__name__)

_ET = timezone(timedelta(hours=-5))


def send_circuit_breaker_alert(
    reason: str,
    daily_loss_pct: float,
    consecutive_losses: int,
    max_daily_loss: float = 0.025,
    max_consecutive_losses: int = 3,
) -> bool:
    """
    Send Slack alert when circuit breaker opens.

    Args:
        reason: Why circuit breaker opened ("daily_loss" or "consecutive_losses")
        daily_loss_pct: Current daily loss percentage
        consecutive_losses: Current consecutive loss count
        max_daily_loss: Maximum daily loss threshold
        max_consecutive_losses: Maximum consecutive losses threshold

    Returns:
        True if alert sent successfully, False otherwise
    """
    webhook_url = os.getenv("SLACK_WEBHOOK_CRITICAL", "")
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_CRITICAL not configured; alert not sent")
        return False

    if reason == "daily_loss":
        title = f"🚨 Circuit Breaker: Daily Loss Limit Exceeded"
        message = (
            f"Daily loss: *{daily_loss_pct:.2%}* (limit: {max_daily_loss:.2%})\n"
            f"Trading halted immediately.\n"
            f"Manual intervention required."
        )
        color = "#FF0000"  # Red for critical
    elif reason == "consecutive_losses":
        title = f"🚨 Circuit Breaker: Consecutive Loss Streak"
        message = (
            f"Consecutive losses: *{consecutive_losses}* (limit: {max_consecutive_losses})\n"
            f"Trading halted immediately.\n"
            f"Manual intervention required."
        )
        color = "#FF6600"  # Orange for critical
    else:
        logger.error("Unknown circuit breaker reason: %s", reason)
        return False

    payload = {
        "attachments": [
            {
                "color": color,
                "title": title,
                "text": message,
                "footer": "Warren B Trading System",
                "ts": int(datetime.now(_ET).timestamp()),
            }
        ]
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=5)
        if resp.status_code == 200:
            logger.info("Circuit breaker alert sent to Slack")
            return True
        else:
            logger.warning("Failed to send alert: HTTP %d", resp.status_code)
            return False
    except Exception as exc:
        logger.error("Failed to send circuit breaker alert: %s", exc)
        return False


def send_data_quality_alert(
    portfolio_health_pct: float,
    degraded_count: int,
    dead_count: int,
    alert_type: str = "degraded",
) -> bool:
    """
    Send Slack alert when data quality degrades.

    Args:
        portfolio_health_pct: Percentage of healthy signals
        degraded_count: Number of degraded stocks
        dead_count: Number of dead signals
        alert_type: "healthy", "degraded", or "critical"

    Returns:
        True if alert sent successfully, False otherwise
    """
    webhook_url = os.getenv("SLACK_WEBHOOK_DATA_QUALITY", "")
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_DATA_QUALITY not configured; alert not sent")
        return False

    if alert_type == "critical":
        title = f"🚨 Data Quality Critical"
        color = "#FF0000"
    elif alert_type == "degraded":
        title = f"⚠️ Data Quality Degraded"
        color = "#FF9900"
    else:
        title = f"✅ Data Quality Healthy"
        color = "#00AA00"

    message = (
        f"Portfolio Health: *{portfolio_health_pct:.1%}*\n"
        f"Degraded stocks: {degraded_count}\n"
        f"Dead stocks: {dead_count}\n"
        f"Recommendation: Reduce position sizing or halt trading."
    )

    payload = {
        "attachments": [
            {
                "color": color,
                "title": title,
                "text": message,
                "footer": "Warren B Trading System",
                "ts": int(datetime.now(_ET).timestamp()),
            }
        ]
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=5)
        if resp.status_code == 200:
            logger.info("Data quality alert sent to Slack")
            return True
        else:
            logger.warning("Failed to send data quality alert: HTTP %d", resp.status_code)
            return False
    except Exception as exc:
        logger.error("Failed to send data quality alert: %s", exc)
        return False


def send_recovery_alert(recovery_type: str) -> bool:
    """
    Send Slack alert when system recovers from alert condition.

    Args:
        recovery_type: "circuit_breaker_reset", "data_quality_recovered", etc.

    Returns:
        True if alert sent successfully, False otherwise
    """
    webhook_url = os.getenv("SLACK_WEBHOOK_CRITICAL", "")
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_CRITICAL not configured; alert not sent")
        return False

    if recovery_type == "circuit_breaker_reset":
        title = f"✅ Circuit Breaker Reset — Trading Resumed"
        message = "Daily loss limit reset at market open. Ready to trade."
        color = "#00AA00"
    elif recovery_type == "data_quality_recovered":
        title = f"✅ Data Quality Recovered"
        message = "Signal quality is healthy again. Resume normal position sizing."
        color = "#00AA00"
    else:
        logger.error("Unknown recovery type: %s", recovery_type)
        return False

    payload = {
        "attachments": [
            {
                "color": color,
                "title": title,
                "text": message,
                "footer": "Warren B Trading System",
                "ts": int(datetime.now(_ET).timestamp()),
            }
        ]
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=5)
        if resp.status_code == 200:
            logger.info("Recovery alert sent to Slack")
            return True
        else:
            logger.warning("Failed to send recovery alert: HTTP %d", resp.status_code)
            return False
    except Exception as exc:
        logger.error("Failed to send recovery alert: %s", exc)
        return False
