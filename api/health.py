"""Health check endpoint for monitoring dashboards and alerting systems."""
import logging
from fastapi import APIRouter

from util.data_health import get_health_report
from util.circuit_breaker import get_circuit_breaker_state
from util.trading_state import get_trading_state

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def get_health():
    """
    Lightweight health check endpoint.
    Returns:
    - circuit_breaker_state: HEALTHY, DEGRADED, OPEN
    - data_sources_healthy: count of non-stale sources
    - data_sources_total: total sources tracked
    - staleness_warnings: list of stale sources

    Useful for:
    - Monitoring dashboards (Prometheus, DataDog, Grafana)
    - Alerting systems (PagerDuty, Slack)
    - Load balancer health checks

    Expected response size: ~500 bytes
    Expected response time: <100ms
    """
    try:
        health = get_health_report()

        # Count stale sources
        stale_count = sum(
            1 for source in health["sources"].values()
            if source.get("is_stale", False)
        )
        healthy_count = len(health["sources"]) - stale_count

        # Get circuit breaker state
        cb_state = get_circuit_breaker_state()
        trading_state = get_trading_state()

        return {
            "status": "ok",
            "circuit_breaker": {
                "state": cb_state.get("state", "UNKNOWN"),
                "failure_count": cb_state.get("failure_count", 0),
                "last_transition": cb_state.get("last_transition"),
            },
            "trading_state": {
                "daily_pnl": trading_state.daily_pnl,
                "daily_loss_pct": trading_state.daily_loss_pct,
                "consecutive_losses": trading_state.consecutive_losses,
                "circuit_breaker_open": trading_state.is_circuit_breaker_open(),
            },
            "data_health": {
                "sources_healthy": healthy_count,
                "sources_total": len(health["sources"]),
                "is_healthy": health["is_healthy"],
                "staleness_warnings": health["staleness_warnings"],
            },
        }
    except Exception as exc:
        logger.exception("Health check failed")
        return {
            "status": "degraded",
            "error": str(exc),
        }
