"""
Data freshness tracking — ensures all API sources are monitored for staleness.

Tracks when each data source was last successfully fetched and alerts if data
exceeds acceptable staleness thresholds (e.g., yfinance >24h, congress >6h).
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Staleness tolerance per data source (in seconds)
STALENESS_LIMITS = {
    "yfinance_bars": 86400,        # 24 hours
    "yfinance_info": 604800,       # 7 days (quarterly data)
    "quiver_congress": 21600,      # 6 hours
    "earnings_calendar": 21600,    # 6 hours
    "news_api": 3600,              # 1 hour
    "estimate_revisions": 86400,   # 24 hours
}


@dataclass
class DataSource:
    """Tracks freshness of a single data source."""
    name: str
    last_fetch_time: Optional[float] = None
    last_fetch_success: bool = False
    failure_count: int = 0

    def record_fetch(self, success: bool) -> None:
        """Record a fetch attempt."""
        self.last_fetch_success = success
        if success:
            self.last_fetch_time = time.time()  # Only update on success
            self.failure_count = 0
        else:
            self.failure_count += 1

    def staleness_seconds(self) -> float:
        """Seconds since last successful fetch."""
        if self.last_fetch_time is None:
            return float('inf')
        return time.time() - self.last_fetch_time

    def is_stale(self) -> bool:
        """Check if data exceeds staleness limit."""
        # Never fetched = not considered stale yet (infinite = OK)
        if self.last_fetch_time is None:
            return False
        if self.name not in STALENESS_LIMITS:
            return False  # Unknown source, assume OK
        limit = STALENESS_LIMITS[self.name]
        return self.staleness_seconds() > limit

    def staleness_pct(self) -> float:
        """Staleness as percentage of limit (0.0=fresh, 1.0=at limit, >1.0=exceeded)."""
        if self.name not in STALENESS_LIMITS:
            return 0.0
        limit = STALENESS_LIMITS[self.name]
        return self.staleness_seconds() / limit

    def to_dict(self) -> dict:
        """Export as JSON-serializable dict."""
        age_sec = self.staleness_seconds()
        return {
            "name": self.name,
            "age_seconds": int(age_sec) if age_sec != float('inf') else None,
            "is_stale": self.is_stale(),
            "staleness_pct": round(self.staleness_pct(), 2),
            "failures": self.failure_count,
            "last_success": bool(self.last_fetch_success),
        }


class DataHealthMonitor:
    """Monitors freshness of all data sources in the pipeline."""

    def __init__(self):
        self.sources = {
            name: DataSource(name)
            for name in STALENESS_LIMITS.keys()
        }

    def record_fetch(self, source_name: str, success: bool) -> None:
        """Record a fetch result."""
        if source_name not in self.sources:
            logger.warning(f"Unknown data source: {source_name}")
            return
        self.sources[source_name].record_fetch(success)

        if success:
            logger.debug(f"Data source {source_name} healthy")
        else:
            self.sources[source_name].failure_count += 1
            logger.warning(f"Data source {source_name} failed (attempt #{self.sources[source_name].failure_count})")

    def get_staleness_warnings(self) -> list[str]:
        """List all sources that are stale."""
        warnings = []
        for source in self.sources.values():
            if source.is_stale():
                staleness_hours = source.staleness_seconds() // 3600
                limit_hours = STALENESS_LIMITS[source.name] // 3600
                warnings.append(
                    f"{source.name} data is {staleness_hours}h old (limit: {limit_hours}h)"
                )
        return warnings

    def get_health_report(self) -> dict:
        """Return complete health status."""
        warnings = self.get_staleness_warnings()
        return {
            "timestamp": time.time(),
            "sources": {name: source.to_dict() for name, source in self.sources.items()},
            "staleness_warnings": warnings,
            "is_healthy": len(warnings) == 0,
        }

    def reset(self) -> None:
        """Reset all tracking (for testing)."""
        for source in self.sources.values():
            source.last_fetch_time = None
            source.last_fetch_success = False
            source.failure_count = 0


# Global singleton
_monitor = DataHealthMonitor()


def record_fetch(source_name: str, success: bool) -> None:
    """Record a data fetch (main API for codebase)."""
    _monitor.record_fetch(source_name, success)


def get_health_report() -> dict:
    """Get complete health status (main API for codebase)."""
    return _monitor.get_health_report()


def get_staleness_warnings() -> list[str]:
    """Get list of stale data sources."""
    return _monitor.get_staleness_warnings()
