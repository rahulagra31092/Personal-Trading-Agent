from fastapi.testclient import TestClient
from api.main import app


def test_health_returns_ok():
    """Health endpoint returns circuit breaker state and data health summary."""
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] in ["ok", "degraded"]
        assert "circuit_breaker" in data
        assert "data_health" in data

        # Verify circuit breaker structure
        cb = data["circuit_breaker"]
        assert cb["state"] in ["HEALTHY", "DEGRADED", "OPEN"]
        assert isinstance(cb["failure_count"], int)

        # Verify data health structure
        dh = data["data_health"]
        assert isinstance(dh["sources_healthy"], int)
        assert isinstance(dh["sources_total"], int)
        assert isinstance(dh["is_healthy"], bool)
        assert isinstance(dh["staleness_warnings"], list)
