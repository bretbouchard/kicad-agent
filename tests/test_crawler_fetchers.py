"""Tests for crawler bulk and file fetcher modules."""

import pytest


class TestBulkFetcherDetailed:
    """Detailed tests for BulkFetcher."""

    def test_import(self):
        """BulkFetcher is importable."""
        from kicad_agent.crawler.bulk_fetcher import BulkFetcher
        assert BulkFetcher is not None


class TestFileFetcherDetailed:
    """Detailed tests for FileFetcher."""

    def test_import(self):
        """FileFetcher is importable."""
        from kicad_agent.crawler.file_fetcher import FileFetcher
        assert FileFetcher is not None


class TestEasyedaApi:
    """Tests for EasyEDA API module."""

    def test_import(self):
        """EasyEDA API module is importable."""
        from kicad_agent.crawler.easyeda_api import EasyEdaClient
        assert EasyEdaClient is not None
