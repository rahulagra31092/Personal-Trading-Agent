import pytest
from smart_money.analyst_revisions import (
    get_analyst_revisions_history,
    compute_analyst_revision_trend,
)


def test_get_analyst_revisions_history_returns_list():
    """get_analyst_revisions_history returns list of dicts."""
    result = get_analyst_revisions_history("AAPL")
    assert isinstance(result, list)


def test_get_analyst_revisions_has_expected_fields():
    """Revisions contain expected fields."""
    result = get_analyst_revisions_history("MSFT")

    if len(result) > 0:
        rev = result[0]
        assert "date" in rev
        # num_analysts, target_mean, recommendation might be None but keys should exist or be absent
        assert any(k in rev for k in ["num_analysts", "target_mean", "recommendation"])


def test_compute_analyst_revision_trend_returns_float():
    """compute_analyst_revision_trend returns float in [0, 1]."""
    result = compute_analyst_revision_trend("AAPL")

    assert isinstance(result, float)
    assert 0.0 <= result <= 1.0


def test_compute_analyst_revision_trend_is_placeholder():
    """For now, revision trend always returns 0.5 (neutral) as placeholder."""
    # This test documents current limitation
    result = compute_analyst_revision_trend("GOOG")
    assert result == 0.5
