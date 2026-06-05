"""Tests for circuit breaker pattern."""
import pytest
import time
from util.circuit_breaker import (
    DataQualityCircuitBreaker,
    CircuitState,
    record_failure,
    record_success,
    should_generate_signals,
    reset,
)


def test_circuit_breaker_starts_healthy():
    """Circuit breaker starts in HEALTHY state."""
    breaker = DataQualityCircuitBreaker()
    assert breaker.state == CircuitState.HEALTHY
    assert breaker.should_generate_signals()


def test_circuit_breaker_transitions_to_degraded():
    """Circuit breaker transitions HEALTHY → DEGRADED on 2 failures."""
    breaker = DataQualityCircuitBreaker(failure_threshold=3)

    breaker.record_failure("yfinance", "timeout")
    assert breaker.state == CircuitState.HEALTHY  # 1 failure

    breaker.record_failure("yfinance", "timeout")
    assert breaker.state == CircuitState.DEGRADED  # 2 failures
    assert breaker.should_generate_signals()  # Still generates


def test_circuit_breaker_transitions_to_open():
    """Circuit breaker transitions DEGRADED → OPEN on 3rd failure."""
    breaker = DataQualityCircuitBreaker(failure_threshold=3)

    breaker.record_failure("source1", "error")  # 1
    breaker.record_failure("source2", "error")  # 2
    assert breaker.state == CircuitState.DEGRADED

    breaker.record_failure("source3", "error")  # 3
    assert breaker.state == CircuitState.OPEN
    assert not breaker.should_generate_signals()  # Halts


def test_circuit_breaker_recovers_on_success():
    """Circuit breaker resets to HEALTHY on successful fetch."""
    breaker = DataQualityCircuitBreaker(failure_threshold=2)

    # Trigger OPEN
    breaker.record_failure("s1", "e")
    breaker.record_failure("s2", "e")
    breaker.record_failure("s3", "e")
    assert breaker.state == CircuitState.OPEN

    # Recovery on success
    breaker.record_success()
    assert breaker.state == CircuitState.HEALTHY
    assert breaker.failure_count == 0


def test_circuit_breaker_respects_recovery_timeout():
    """Circuit breaker enforces recovery timeout in OPEN state."""
    breaker = DataQualityCircuitBreaker(failure_threshold=1, recovery_timeout_seconds=5)

    breaker.record_failure("source", "error")
    assert breaker.state == CircuitState.OPEN
    assert not breaker.should_generate_signals()  # Blocked immediately

    # Within timeout: still blocked
    time.sleep(0.5)
    assert not breaker.should_generate_signals()  # Still blocked

    # After timeout: allows recovery attempt
    breaker.last_state_change_time = time.time() - 6  # 6 seconds ago
    assert breaker.should_generate_signals()  # Recovery attempt allowed


def test_circuit_breaker_failure_sources_tracked():
    """Circuit breaker tracks source of failures."""
    breaker = DataQualityCircuitBreaker()

    breaker.record_failure("yfinance", "timeout")
    breaker.record_failure("quiver", "connection")
    breaker.record_failure("news_api", "rate limit")

    assert len(breaker.failure_sources) == 3
    assert "yfinance" in breaker.failure_sources
    assert "news_api" in breaker.failure_sources[-1]


def test_circuit_breaker_get_status():
    """Circuit breaker exports complete status."""
    breaker = DataQualityCircuitBreaker(failure_threshold=3)
    breaker.record_failure("src", "err")
    breaker.record_failure("src2", "err")

    status = breaker.get_status()
    assert status["state"] == "DEGRADED"
    assert status["failure_count"] >= 2
    assert "time_in_state_seconds" in status
    assert isinstance(status["can_attempt_recovery"], bool)


def test_circuit_breaker_reset():
    """Circuit breaker can reset for testing."""
    breaker = DataQualityCircuitBreaker()
    breaker.record_failure("src", "err")
    assert breaker.failure_count > 0

    breaker.reset()
    assert breaker.state == CircuitState.HEALTHY
    assert breaker.failure_count == 0
    assert len(breaker.failure_sources) == 0


def test_global_circuit_breaker_api():
    """Global API functions work correctly."""
    reset()  # Start fresh

    record_failure("source1", "error")
    assert should_generate_signals()  # 1 failure OK

    record_failure("source2", "error")
    record_failure("source3", "error")
    assert not should_generate_signals()  # 3 failures = OPEN

    record_success()
    assert should_generate_signals()  # Recovered


def test_circuit_breaker_limits_failure_sources_history():
    """Circuit breaker doesn't grow failure history unbounded."""
    breaker = DataQualityCircuitBreaker()

    # Record 15 failures
    for i in range(15):
        breaker.record_failure(f"source_{i}", "error")

    # Should keep only last 10
    assert len(breaker.failure_sources) == 10
