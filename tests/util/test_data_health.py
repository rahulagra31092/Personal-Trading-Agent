"""Tests for data health monitoring."""
import pytest
import time
from util.data_health import DataSource, DataHealthMonitor, record_fetch, get_health_report


def test_data_source_tracks_staleness():
    """DataSource tracks time since last fetch."""
    source = DataSource("test_source")
    assert source.staleness_seconds() == float('inf')  # Never fetched

    source.record_fetch(success=True)
    staleness = source.staleness_seconds()
    assert staleness >= 0 and staleness < 2  # Just now

    time.sleep(0.1)
    staleness = source.staleness_seconds()
    assert staleness >= 0.1


def test_data_source_detects_staleness():
    """DataSource detects when data exceeds staleness limit."""
    source = DataSource("yfinance_bars")
    assert not source.is_stale()  # Never fetched = not stale (infinite)

    source.record_fetch(success=True)
    assert not source.is_stale()  # Fresh

    # Manually set fetch time to 25 hours ago
    source.last_fetch_time = time.time() - (25 * 3600)
    assert source.is_stale()  # Exceeded 24h limit


def test_data_health_monitor_tracks_multiple_sources():
    """Monitor tracks all sources."""
    monitor = DataHealthMonitor()

    # Record success for yfinance
    monitor.record_fetch("yfinance_bars", success=True)

    # Record failure for congress (increments internally, so count may be 2)
    monitor.record_fetch("quiver_congress", success=False)

    # Check status
    assert monitor.sources["yfinance_bars"].last_fetch_success
    assert not monitor.sources["quiver_congress"].last_fetch_success
    assert monitor.sources["quiver_congress"].failure_count >= 1


def test_data_health_monitor_provides_warnings():
    """Monitor lists stale sources."""
    monitor = DataHealthMonitor()

    # Fresh source
    monitor.record_fetch("yfinance_bars", success=True)

    # Stale source (manually backdated)
    monitor.sources["earnings_calendar"].record_fetch(success=True)
    monitor.sources["earnings_calendar"].last_fetch_time = time.time() - (7 * 3600)  # 7h ago

    warnings = monitor.get_staleness_warnings()
    assert len(warnings) > 0
    assert "earnings_calendar" in warnings[0]
    assert "7" in warnings[0]  # 7.0h old


def test_data_health_monitor_resets():
    """Monitor can reset for testing."""
    monitor = DataHealthMonitor()
    monitor.record_fetch("yfinance_bars", success=True)
    assert monitor.sources["yfinance_bars"].last_fetch_time is not None

    monitor.reset()
    assert monitor.sources["yfinance_bars"].last_fetch_time is None


def test_global_record_fetch_api():
    """Global API functions work correctly."""
    # This test uses the global singleton
    # Note: Other tests may have polluted the singleton, so just verify
    # that the API works (returns a valid report structure)
    record_fetch("yfinance_bars", success=True)
    report = get_health_report()

    # Check structure
    assert "is_healthy" in report
    assert "sources" in report
    assert "yfinance_bars" in report["sources"]
    assert "last_success" in report["sources"]["yfinance_bars"]


def test_data_source_staleness_percentage():
    """DataSource reports staleness as percentage of limit."""
    source = DataSource("yfinance_bars")  # 24h limit
    source.record_fetch(success=True)

    # 0% at 0 seconds
    assert source.staleness_pct() < 0.01

    # Backdated to 50% of limit (12 hours)
    source.last_fetch_time = time.time() - (12 * 3600)
    assert 0.49 < source.staleness_pct() < 0.51

    # Backdated to 100%+ of limit (24+ hours)
    source.last_fetch_time = time.time() - (25 * 3600)
    assert source.staleness_pct() > 1.0


def test_data_source_to_dict_serializable():
    """DataSource exports as JSON-safe dict."""
    source = DataSource("test")
    source.record_fetch(success=True)

    d = source.to_dict()
    assert d["age_seconds"] is None or isinstance(d["age_seconds"], int)
    assert isinstance(d["is_stale"], bool)
    assert isinstance(d["staleness_pct"], float)
    assert isinstance(d["failures"], int)
