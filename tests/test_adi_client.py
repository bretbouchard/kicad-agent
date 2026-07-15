"""Unit tests for SamacSys HTTP client.

All tests use mocked httpx responses to avoid network dependencies.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from volta.project.adi_library.client import (
    SAMACSYS_BASE_URL,
    SamacSysClient,
    SearchResult,
)


class TestSearchResult:
    def test_search_result_frozen(self):
        """SearchResult is immutable."""
        result = SearchResult(
            part_number="AD8606ARMZ",
            part_id="12345",
            description="Op-Amp",
            has_kicad=True,
            download_url="https://example.com/download",
        )
        with pytest.raises(AttributeError):
            result.part_number = "CHANGED"  # type: ignore[misc]

    def test_search_result_with_error(self):
        """SearchResult can represent an error state."""
        result = SearchResult(
            part_number="BAD",
            part_id=None,
            description=None,
            has_kicad=False,
            download_url=None,
            error="Search failed",
        )
        assert result.error == "Search failed"
        assert not result.has_kicad


class TestSearchPart:
    def _mock_response(self, status_code: int = 200, text: str = "") -> httpx.Response:
        """Create a mock httpx Response."""
        response = MagicMock(spec=httpx.Response)
        response.status_code = status_code
        response.text = text
        response.content = text.encode("utf-8") if text else b""
        response.headers = {}
        return response

    def test_search_with_kicad_link(self):
        """Search returns result with download URL when KiCad link found."""
        html = (
            '<html><body>'
            '<a href="/downloads/kicad/AD8606ARMZ.zip">Download KiCad</a>'
            '<span class="description">AD8606ARMZ - Precision Op-Amp</span>'
            '</body></html>'
        )
        client = SamacSysClient()
        with patch.object(client._client, "get", return_value=self._mock_response(text=html)):
            result = client.search_part("AD8606ARMZ")
        assert result.has_kicad is True
        assert result.download_url is not None
        assert "kicad" in result.download_url.lower()
        assert result.error is None
        client.close()

    def test_search_no_kicad_link(self):
        """Search returns error when no KiCad download link found."""
        html = '<html><body><p>No downloads available</p></body></html>'
        client = SamacSysClient()
        with patch.object(client._client, "get", return_value=self._mock_response(text=html)):
            result = client.search_part("AD8606ARMZ")
        assert result.has_kicad is False
        assert result.error is not None
        assert "manual" in result.error.lower() or "fallback" in result.error.lower()
        client.close()

    def test_search_invalid_part_number(self):
        """Search returns error for invalid part numbers."""
        client = SamacSysClient()
        result = client.search_part("AD8606;DROP TABLE")
        assert result.error is not None
        assert "invalid" in result.error.lower()
        client.close()

    def test_search_http_429_rate_limited(self):
        """Search handles rate limiting (HTTP 429)."""
        client = SamacSysClient()
        with patch.object(client._client, "get", return_value=self._mock_response(status_code=429)):
            result = client.search_part("AD8606ARMZ")
        assert result.error is not None
        assert "429" in result.error or "rate" in result.error.lower()
        client.close()

    def test_search_http_500_error(self):
        """Search handles server errors gracefully."""
        client = SamacSysClient()
        with patch.object(client._client, "get", return_value=self._mock_response(status_code=500)):
            result = client.search_part("AD8606ARMZ")
        assert result.error is not None
        assert "500" in result.error
        client.close()

    def test_search_timeout(self):
        """Search handles request timeout."""
        client = SamacSysClient()
        with patch.object(client._client, "get", side_effect=httpx.TimeoutException("timeout")):
            result = client.search_part("AD8606ARMZ")
        assert result.error is not None
        assert "timed out" in result.error.lower()
        client.close()

    def test_search_connection_error(self):
        """Search handles connection failure."""
        client = SamacSysClient()
        with patch.object(client._client, "get", side_effect=httpx.ConnectError("refused")):
            result = client.search_part("AD8606ARMZ")
        assert result.error is not None
        assert "connect" in result.error.lower()
        client.close()


class TestDownloadLibrary:
    def test_download_success(self, tmp_path):
        """Download saves ZIP file to target directory."""
        client = SamacSysClient()
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.content = b"PK\x03\x04fake zip content"
        response.headers = {"content-disposition": 'attachment; filename="AD8606ARMZ.zip"'}

        with patch.object(client._client, "get", return_value=response):
            result = client.download_library("https://example.com/download", tmp_path)

        assert result is not None
        assert result.exists()
        assert result.name == "AD8606ARMZ.zip"
        client.close()

    def test_download_http_error(self, tmp_path):
        """Download returns None on HTTP error."""
        client = SamacSysClient()
        response = MagicMock(spec=httpx.Response)
        response.status_code = 403

        with patch.object(client._client, "get", return_value=response):
            result = client.download_library("https://example.com/download", tmp_path)

        assert result is None
        client.close()

    def test_download_empty_response(self, tmp_path):
        """Download returns None on empty response."""
        client = SamacSysClient()
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.content = b""

        with patch.object(client._client, "get", return_value=response):
            result = client.download_library("https://example.com/download", tmp_path)

        assert result is None
        client.close()

    def test_download_timeout(self, tmp_path):
        """Download returns None on timeout."""
        client = SamacSysClient()
        with patch.object(client._client, "get", side_effect=httpx.TimeoutException("timeout")):
            result = client.download_library("https://example.com/download", tmp_path)

        assert result is None
        client.close()


class TestContextManager:
    def test_context_manager(self):
        """SamacSysClient works as context manager."""
        with SamacSysClient() as client:
            assert client is not None
