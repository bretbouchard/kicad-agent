"""Tests for MouserSource component provider.

TDD approach: RED → GREEN → REFACTOR
Tests fail first, then implementation follows.
"""

import pytest
import urllib.request
from unittest.mock import Mock, patch, MagicMock
from volta.crawler.mouser_source import MouserSource


class TestMouserSourceAPIKey:
    """Test API key retrieval and validation."""

    def test_api_key_retrieval_from_env(self):
        """API key should be loaded from environment variable."""
        with patch.dict("os.environ", {"MOUSER_API_KEY": "test-key-123"}):
            source = MouserSource()
            assert source.api_key == "test-key-123"

    def test_api_key_missing_returns_empty(self):
        """Missing API key should result in empty string and unavailable source."""
        with patch.dict("os.environ", {}, clear=True):
            source = MouserSource()
            assert source.api_key == ""
            assert not source.is_available

    def test_is_available_with_valid_key(self):
        """Source should be available when API key is configured."""
        with patch.dict("os.environ", {"MOUSER_API_KEY": "valid-key"}):
            source = MouserSource()
            assert source.is_available


class TestMouserSourceSearch:
    """Test component search functionality."""

    @patch("urllib.request.urlopen")
    def test_search_parts_success(self, mock_urlopen: Mock):
        """Successful search should return components."""
        # Mock successful API response
        mock_response = MagicMock()
        mock_response.read.return_value = b'''{
            "SearchResults": [
                {
                    "PartNumber": "STM32F411CEU6",
                    "Manufacturer": "STMicroelectronics",
                    "Description": "ARM Cortex-M4 MCU",
                    "DataSheetUrl": "https://www.mouser.com/datasheet",
                    "PriceBreaks": [
                        {"Quantity": 1, "Price": 5.50},
                        {"Quantity": 100, "Price": 4.80}
                    ],
                    "Availability": "1523 In Stock",
                    "ProductCategory": "Microcontrollers"
                }
            ],
            "TotalResults": 1
        }'''
        mock_urlopen.return_value.__enter__.return_value = mock_response

        with patch.dict("os.environ", {"MOUSER_API_KEY": "test-key"}):
            source = MouserSource()
            components, total = source.search("STM32F411", limit=10)

            assert total == 1
            assert len(components) == 1
            assert components[0].part_number == "STM32F411CEU6"
            assert components[0].manufacturer == "STMicroelectronics"
            assert "Cortex-M4" in components[0].description

    @patch("urllib.request.urlopen")
    def test_search_parts_rate_limit(self, mock_urlopen: Mock):
        """Rate limit (429) should be handled gracefully."""
        # Mock 429 response
        mock_error = urllib.error.HTTPError(
            "https://api.mouser.com/api/v1",
            429,
            "Rate Limit Exceeded",
            {},
            None
        )
        mock_urlopen.side_effect = mock_error

        with patch.dict("os.environ", {"MOUSER_API_KEY": "test-key"}):
            source = MouserSource()
            components, total = source.search("STM32F411", limit=10)

            # Should return empty results on rate limit
            assert components == []
            assert total == 0

    @patch("urllib.request.urlopen")
    def test_invalid_api_key(self, mock_urlopen: Mock):
        """Invalid API key (401) should be handled gracefully."""
        # Mock 401 response
        mock_error = urllib.error.HTTPError(
            "https://api.mouser.com/api/v1",
            401,
            "Unauthorized",
            {},
            None
        )
        mock_urlopen.side_effect = mock_error

        with patch.dict("os.environ", {"MOUSER_API_KEY": "invalid-key"}):
            source = MouserSource()
            components, total = source.search("STM32F411", limit=10)

            # Should return empty results on auth failure
            assert components == []
            assert total == 0

    @patch("urllib.request.urlopen")
    def test_empty_search_results(self, mock_urlopen: Mock):
        """Empty search results should be handled correctly."""
        # Mock empty response
        mock_response = MagicMock()
        mock_response.read.return_value = b'''{
            "SearchResults": [],
            "TotalResults": 0
        }'''
        mock_urlopen.return_value.__enter__.return_value = mock_response

        with patch.dict("os.environ", {"MOUSER_API_KEY": "test-key"}):
            source = MouserSource()
            components, total = source.search("NONEXISTENTPART", limit=10)

            assert components == []
            assert total == 0


class TestMouserSourceHeaders:
    """Test HTTP request headers and signing."""

    @patch("urllib.request.urlopen")
    def test_search_includes_api_key_header(self, mock_urlopen: Mock):
        """API key should be included in request headers."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"SearchResults": [], "TotalResults": 0}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        with patch.dict("os.environ", {"MOUSER_API_KEY": "test-api-key"}):
            source = MouserSource()
            source.search("test", limit=10)

            # Verify request was made
            assert mock_urlopen.called
            call_args = mock_urlopen.call_args
            request = call_args[0][0]

            # Check headers include API key (urllib normalizes header case)
            api_key_header = next(
                (v for k, v in request.headers.items() if k.lower() == "x-mouser-apikey"), ""
            )
            assert "test-api-key" in api_key_header

    @patch("urllib.request.urlopen")
    def test_search_includes_content_type_header(self, mock_urlopen: Mock):
        """Content-Type should be set to application/json."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"SearchResults": [], "TotalResults": 0}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        with patch.dict("os.environ", {"MOUSER_API_KEY": "test-key"}):
            source = MouserSource()
            source.search("test", limit=10)

            # Verify Content-Type header (urllib normalizes header case)
            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            content_type = next(
                (v for k, v in request.headers.items() if k.lower() == "content-type"), ""
            )
            assert content_type == "application/json"


class TestMouserSourcePropertyMapping:
    """Test mapping of Mouser response to Component model."""

    @patch("urllib.request.urlopen")
    def test_price_mapping(self, mock_urlopen: Mock):
        """Price breaks should map to ComponentPrice correctly."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'''{
            "SearchResults": [{
                "PartNumber": "TEST-PART",
                "Manufacturer": "Test Mfr",
                "Description": "Test Description",
                "PriceBreaks": [
                    {"Quantity": 1, "Price": 10.00},
                    {"Quantity": 100, "Price": 8.50},
                    {"Quantity": 1000, "Price": 7.00}
                ]
            }],
            "TotalResults": 1
        }'''
        mock_urlopen.return_value.__enter__.return_value = mock_response

        with patch.dict("os.environ", {"MOUSER_API_KEY": "test-key"}):
            source = MouserSource()
            components, _ = source.search("TEST", limit=10)

            assert len(components) == 1
            pricing = components[0].pricing
            assert len(pricing) == 1
            assert pricing[0].distributor == "Mouser"
            assert pricing[0].unit_price == 10.00
            assert len(pricing[0].tiered_pricing) == 3

    @patch("urllib.request.urlopen")
    def test_stock_mapping(self, mock_urlopen: Mock):
        """Stock availability should map to ComponentStock correctly."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'''{
            "SearchResults": [{
                "PartNumber": "TEST-PART",
                "Manufacturer": "Test Mfr",
                "Description": "Test Description",
                "Availability": "5000 In Stock"
            }],
            "TotalResults": 1
        }'''
        mock_urlopen.return_value.__enter__.return_value = mock_response

        with patch.dict("os.environ", {"MOUSER_API_KEY": "test-key"}):
            source = MouserSource()
            components, _ = source.search("TEST", limit=10)

            assert len(components) == 1
            stock = components[0].stock
            assert len(stock) == 1
            assert stock[0].distributor == "Mouser"
            assert stock[0].quantity == 5000

    @patch("urllib.request.urlopen")
    def test_datasheet_url_mapping(self, mock_urlopen: Mock):
        """Datasheet URL should be preserved correctly."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'''{
            "SearchResults": [{
                "PartNumber": "TEST-PART",
                "Manufacturer": "Test Mfr",
                "Description": "Test Description",
                "DataSheetUrl": "https://example.com/datasheet.pdf"
            }],
            "TotalResults": 1
        }'''
        mock_urlopen.return_value.__enter__.return_value = mock_response

        with patch.dict("os.environ", {"MOUSER_API_KEY": "test-key"}):
            source = MouserSource()
            components, _ = source.search("TEST", limit=10)

            assert len(components) == 1
            assert components[0].datasheet_url == "https://example.com/datasheet.pdf"
