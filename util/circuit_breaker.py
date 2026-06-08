"""
Circuit breaker pattern for data quality — halts signal generation if data quality degrades.

Implements state machine: HEALTHY → DEGRADED → OPEN
- HEALTHY: All signals go through
- DEGRADED: Tracking failures (2+ consecutive)
- OPEN: Halt all signal generation (return 503 error)

Automatically recovers to HEALTHY on successful fetch.
"""
import logging
import time
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker state machine."""
    HEALTHY = "HEALTHY"      # All systems go
    DEGRADED = "DEGRADED"    # Tracking failures, be cautious
    OPEN = "OPEN"            # Halt signal generation


class DataQualityCircuitBreaker:
    """
    Monitors data quality across all API sources.

    Transitions:
    - HEALTHY: Normal operation (≤1 consecutive failures)
    - DEGRADED: Caution mode (2 consecutive failures)
    - OPEN: Emergency stop (3+ consecutive failures, or recovery timeout expired)

    Auto-recovery: OPEN → DEGRADED → HEALTHY on successful fetch
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout_seconds: int = 300,
    ):
        """
        Args:
            failure_threshold: Transition to OPEN after this many consecutive failures
            recovery_timeout_seconds: Minimum time in OPEN before allowing recovery attempt
        """
        self.state = CircuitState.HEALTHY
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout_seconds

        self.last_failure_time: Optional[float] = None
        self.last_state_change_time = time.time()
        self.failure_sources: list[str] = []

    def record_failure(self, source: str, error: str) -> None:
        """Record a data fetch failure."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        self.failure_sources.append(source)

        # Keep only last 10 sources
        if len(self.failure_sources) > 10:
            self.failure_sources.pop(0)

        old_state = self.state

        # State transitions based on failure count
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
        elif self.failure_count >= 2:
            self.state = CircuitState.DEGRADED
        else:
            self.state = CircuitState.HEALTHY

        # Log state change
        if self.state != old_state:
            self.last_state_change_time = time.time()
            logger.critical(
                f"Circuit breaker: {old_state} → {self.state} "
                f"(failures: {self.failure_count}/{self.failure_threshold}, "
                f"source: {source}, error: {error})"
            )
        else:
            logger.warning(
                f"Circuit breaker: {source} failure #{self.failure_count} "
                f"(state: {self.state}, error: {error})"
            )

    def record_success(self) -> None:
        """Record a successful fetch — reset failure counter."""
        old_state = self.state
        old_failures = self.failure_count

        self.failure_count = 0
        self.failure_sources.clear()
        self.state = CircuitState.HEALTHY

        if old_state != CircuitState.HEALTHY:
            logger.info(
                f"Circuit breaker: {old_state} → HEALTHY "
                f"(recovered from {old_failures} failures)"
            )

    def should_generate_signals(self) -> bool:
        """Check if OK to generate signals (return signal or 503 error)."""
        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has elapsed
            time_in_open = time.time() - self.last_state_change_time
            if time_in_open >= self.recovery_timeout:
                # Allow one recovery attempt
                logger.info(
                    f"Circuit breaker: Timeout elapsed ({time_in_open:.0f}s), "
                    f"attempting recovery..."
                )
                return True  # Let next request attempt recovery
            else:
                # Still in recovery timeout
                time_left = self.recovery_timeout - time_in_open
                logger.warning(
                    f"Circuit breaker OPEN: Recovery in {time_left:.0f}s"
                )
                return False

        return True  # HEALTHY or DEGRADED allow signals

    def get_status(self) -> dict:
        """Export current status."""
        time_in_state = time.time() - self.last_state_change_time
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "time_in_state_seconds": round(time_in_state, 1),
            "last_failure_time": self.last_failure_time,
            "recent_failure_sources": self.failure_sources[-5:],  # Last 5
            "should_generate_signals": self.should_generate_signals(),
            "can_attempt_recovery": (
                self.state == CircuitState.OPEN and
                time_in_state >= self.recovery_timeout
            ),
        }

    def reset(self) -> None:
        """Reset to HEALTHY (for testing)."""
        self.state = CircuitState.HEALTHY
        self.failure_count = 0
        self.failure_sources.clear()
        self.last_failure_time = None
        self.last_state_change_time = time.time()
        logger.info("Circuit breaker reset to HEALTHY")


# Global singleton
_breaker = DataQualityCircuitBreaker(
    failure_threshold=3,
    recovery_timeout_seconds=300,
)


def record_failure(source: str, error: str) -> None:
    """Record a data fetch failure (main API for codebase)."""
    _breaker.record_failure(source, error)


def record_success() -> None:
    """Record a successful fetch (main API for codebase)."""
    _breaker.record_success()


def should_generate_signals() -> bool:
    """Check if OK to generate signals."""
    return _breaker.should_generate_signals()


def get_status() -> dict:
    """Get circuit breaker status."""
    return _breaker.get_status()


def reset() -> None:
    """Reset circuit breaker (for testing)."""
    _breaker.reset()


def get_circuit_breaker_state() -> dict:
    """Get circuit breaker state for monitoring (alias for get_status)."""
    status = get_status()
    return {
        "state": status["state"],
        "failure_count": status["failure_count"],
        "last_transition": status.get("last_failure_time"),
    }
