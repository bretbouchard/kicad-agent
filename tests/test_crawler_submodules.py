"""Tests for crawler sub-modules: rate_limiter, bulk_fetcher, file_fetcher, github_discovery."""

from unittest.mock import MagicMock, PropertyMock

import pytest


class TestBulkFetcher:
    """Tests for bulk fetcher module."""

    def test_import(self):
        """BulkFetcher is importable."""
        from kicad_agent.crawler.bulk_fetcher import BulkFetcher
        assert BulkFetcher is not None


class TestFileFetcher:
    """Tests for file fetcher module."""

    def test_import(self):
        """FileFetcher is importable."""
        from kicad_agent.crawler.file_fetcher import FileFetcher
        assert FileFetcher is not None


class TestGithubDiscovery:
    """Tests for GitHub discovery module."""

    def test_import(self):
        """GithubDiscovery is importable."""
        from kicad_agent.crawler.github_discovery import GithubDiscovery
        assert GithubDiscovery is not None

    def test_creation(self):
        """GithubDiscovery can be created with mock client."""
        mock_client = MagicMock()
        discovery = GithubDiscovery(mock_client)
        assert discovery is not None
