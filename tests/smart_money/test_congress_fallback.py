"""
Test Congress trades + SEC EDGAR fallback mechanism.
Verifies fallback is used when Quiver API is missing/fails.
"""
import pytest
from unittest.mock import patch, MagicMock
import os

from smart_money.congress import get_congress_trades


class TestCongressTradeFallback:
    """Test fallback from Quiver Congress to SEC EDGAR insider trades."""

    def test_congress_trades_returns_list(self):
        """get_congress_trades always returns a list (empty if no data)."""
        result = get_congress_trades("AAPL")
        assert isinstance(result, list)

    def test_congress_trades_quiver_success(self):
        """When Quiver API responds, use Quiver data."""
        quiver_trades = [
            {
                "Date": "2026-05-01",
                "Transaction": "Purchase",
                "Range": "$100,000-$250,000",
                "Representative": "John Smith",
            }
        ]

        with patch("smart_money.congress.get_cache") as mock_cache_get:
            with patch("smart_money.congress.set_cache"):
                mock_cache_get.return_value = None  # Cache miss
                with patch("smart_money.congress.requests.get") as mock_get:
                    mock_resp = MagicMock()
                    mock_resp.json.return_value = quiver_trades
                    mock_get.return_value = mock_resp

                    with patch("smart_money.congress.config.QUIVER_API_KEY", "test-key"):
                        result = get_congress_trades("TEST_QUIVER_AAPL")

        assert result == quiver_trades

    def test_congress_trades_quiver_failure_fallback_to_edgar(self):
        """When Quiver fails, fall back to SEC EDGAR insider trades."""
        edgar_trades = [
            {
                "Date": "2026-05-01T12:00:00",
                "Transaction": "Insider Purchase",
                "Range": "$100,000-$300,000",
                "Representative": "Jane Doe",
                "Amount": 1000.0,
            }
        ]

        with patch("smart_money.congress.get_cache") as mock_cache_get:
            with patch("smart_money.congress.set_cache"):
                with patch("smart_money.congress.record_fetch"):
                    mock_cache_get.return_value = None  # Cache miss
                    with patch("smart_money.congress.requests.get") as mock_get:
                        # Quiver API fails
                        mock_get.side_effect = Exception("API timeout")

                        with patch("smart_money.congress._get_edgar_insider_trades") as mock_edgar:
                            mock_edgar.return_value = edgar_trades

                            with patch("smart_money.congress.config.QUIVER_API_KEY", "test-key"):
                                result = get_congress_trades("TEST_EDGAR_AAPL")

        assert result == edgar_trades

    def test_congress_trades_no_quiver_api_key(self):
        """When Quiver API key is missing, skip to EDGAR."""
        edgar_trades = [
            {
                "Date": "2026-05-01T12:00:00",
                "Transaction": "Insider Purchase",
                "Range": "$50,000-$150,000",
                "Representative": "Bob Johnson",
                "Amount": 500.0,
            }
        ]

        with patch("smart_money.congress.get_cache") as mock_cache_get:
            with patch("smart_money.congress.set_cache"):
                with patch("smart_money.congress.record_fetch"):
                    mock_cache_get.return_value = None  # Cache miss
                    with patch("smart_money.congress.config.QUIVER_API_KEY", None):
                        with patch("smart_money.congress._get_edgar_insider_trades") as mock_edgar:
                            mock_edgar.return_value = edgar_trades

                            result = get_congress_trades("TEST_NOKEY_AAPL")

        assert result == edgar_trades

    def test_edgar_trades_parses_shares(self):
        """SEC EDGAR trade parsing handles share counts correctly."""
        with patch("smart_money.congress.yf.Ticker") as mock_ticker:
            mock_t = MagicMock()
            mock_ticker.return_value = mock_t

            # Mock insider_transactions DataFrame
            import pandas as pd

            insider_data = pd.DataFrame(
                {
                    "Date": pd.to_datetime(["2026-05-01", "2026-04-15"]),
                    "Transaction": ["Purchase", "Sale"],
                    "Shares": [1000.0, 500.0],
                    "Insider": ["Alice", "Bob"],
                }
            )
            mock_t.insider_transactions = insider_data

            from smart_money.congress import _get_edgar_insider_trades

            trades = _get_edgar_insider_trades("AAPL")

        assert len(trades) >= 1  # At least one trade parsed
        assert all("Transaction" in t for t in trades)
        assert all("Shares" in t or "Amount" in t for t in trades)

    def test_edgar_trades_empty_response(self):
        """When SEC EDGAR has no data, return empty list."""
        with patch("smart_money.congress.yf.Ticker") as mock_ticker:
            mock_t = MagicMock()
            mock_ticker.return_value = mock_t
            mock_t.insider_transactions = None

            from smart_money.congress import _get_edgar_insider_trades

            trades = _get_edgar_insider_trades("XYZ")

        assert trades == []

    def test_congress_trades_cached(self):
        """Congress trades are cached for 6 hours."""
        with patch("smart_money.congress.get_cache") as mock_cache_get:
            with patch("smart_money.congress.set_cache") as mock_cache_set:
                mock_cache_get.return_value = None  # Cache miss first time

                with patch("smart_money.congress.requests.get") as mock_get:
                    mock_resp = MagicMock()
                    mock_resp.json.return_value = [{"test": "data"}]
                    mock_get.return_value = mock_resp

                    with patch(
                        "smart_money.congress.config.QUIVER_API_KEY", "test-key"
                    ):
                        get_congress_trades("AAPL")

        # Verify set_cache called with 6 hour TTL
        mock_cache_set.assert_called_once()
        call_args = mock_cache_set.call_args
        assert call_args[1]["ttl_seconds"] == 6 * 3600

    def test_data_health_tracking(self):
        """Congress/EDGAR trades trigger data health recording."""
        with patch("smart_money.congress.get_cache") as mock_cache_get:
            with patch("smart_money.congress.set_cache"):
                with patch("smart_money.congress.record_fetch") as mock_record:
                    mock_cache_get.return_value = None  # Cache miss
                    with patch("smart_money.congress.config.QUIVER_API_KEY", "test-key"):
                        with patch("smart_money.congress.requests.get") as mock_get:
                            mock_resp = MagicMock()
                            mock_resp.json.return_value = []
                            mock_get.return_value = mock_resp

                            get_congress_trades("TEST_HEALTH_AAPL")

        # Verify data health recorded for Quiver
        mock_record.assert_called()
        call_args_list = [call[0] for call in mock_record.call_args_list]
        # Check that at least one call mentions quiver or edgar
        sources = [args[0] for args in call_args_list]
        assert "quiver_congress" in sources or "edgar_insider_trades" in sources
