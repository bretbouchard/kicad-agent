"""Tests for project context module."""

import pytest


class TestContextModule:
    """Tests for context loading module."""

    def test_import(self):
        """Context module is importable."""
        from volta import context
        assert context is not None
