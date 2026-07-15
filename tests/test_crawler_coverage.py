"""Tests for crawler module: RateLimiter, GithubDiscovery, FileFetcher."""

import time
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from volta.crawler import (
    FileFetcher,
    GithubDiscovery,
    KicadFilePair,
    RateLimiter,
    RepoInfo,
)


class TestRateLimiter:
    """Tests for GitHub API rate limiter."""

    def test_rate_limiter_creation(self):
        """RateLimiter can be created with a mock client."""
        mock_client = MagicMock()
        limiter = RateLimiter(mock_client)
        assert limiter._client is mock_client

    def test_remaining_property(self):
        """RateLimiter.remaining returns remaining API requests."""
        mock_client = MagicMock()

        # Mock the rate limit chain: get_rate_limit() -> resources.core.remaining
        mock_remaining = PropertyMock(return_value=4500)
        mock_core = MagicMock()
        type(mock_core).remaining = mock_remaining
        mock_resources = MagicMock()
        mock_resources.core = mock_core
        mock_rate_limit = MagicMock()
        mock_rate_limit.resources = mock_resources
        mock_client.get_rate_limit.return_value = mock_rate_limit

        limiter = RateLimiter(mock_client)
        assert limiter.remaining == 4500

    def test_wait_if_needed_above_threshold(self):
        """wait_if_needed does not sleep when remaining > threshold."""
        mock_client = MagicMock()

        mock_remaining = PropertyMock(return_value=4500)
        mock_core = MagicMock()
        type(mock_core).remaining = mock_remaining
        type(mock_core).limit = 5000
        mock_resources = MagicMock()
        mock_resources.core = mock_core
        mock_rate_limit = MagicMock()
        mock_rate_limit.resources = mock_resources
        mock_client.get_rate_limit.return_value = mock_rate_limit

        limiter = RateLimiter(mock_client)
        start = time.perf_counter()
        limiter.wait_if_needed()
        elapsed = time.perf_counter() - start
        assert elapsed < 0.1, "Should not sleep when above threshold"

    def test_wait_if_needed_below_threshold(self):
        """wait_if_needed sleeps when remaining < threshold."""
        mock_client = MagicMock()

        from datetime import datetime, timezone, timedelta
        reset_time = datetime.now(timezone.utc) + timedelta(seconds=0.01)

        mock_remaining = PropertyMock(return_value=5)
        mock_core = MagicMock()
        type(mock_core).remaining = mock_remaining
        type(mock_core).limit = 5000
        type(mock_core).reset = PropertyMock(return_value=reset_time)
        mock_resources = MagicMock()
        mock_resources.core = mock_core
        mock_rate_limit = MagicMock()
        mock_rate_limit.resources = mock_resources
        mock_client.get_rate_limit.return_value = mock_rate_limit

        limiter = RateLimiter(mock_client)
        start = time.perf_counter()
        limiter.wait_if_needed()
        elapsed = time.perf_counter() - start
        assert elapsed >= 0.005, "Should sleep when below threshold"


class TestGithubDiscovery:
    """Tests for GithubDiscovery types."""

    def test_repo_info_creation(self):
        """RepoInfo can be created with fields."""
        info = RepoInfo(
            full_name="user/repo",
            html_url="https://github.com/user/repo",
            stars=42,
            description="A KiCad project",
            default_branch="main",
        )
        assert info.full_name == "user/repo"
        assert info.stars == 42

    def test_kicad_file_pair_creation(self):
        """KicadFilePair can be created."""
        pair = KicadFilePair(
            schematic_path="board.kicad_sch",
            pcb_path="board.kicad_pcb",
            base_name="board",
        )
        assert pair.schematic_path == "board.kicad_sch"


class TestCrawlerImports:
    """Verify all crawler module exports."""

    def test_all_exports_importable(self):
        """All __all__ exports can be imported."""
        from volta import crawler
        for name in crawler.__all__:
            assert hasattr(crawler, name), f"Missing export: {name}"
