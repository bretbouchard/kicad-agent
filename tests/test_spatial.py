"""Tests for spatial module."""

import pytest


class TestSpatialModule:
    """Tests for spatial reasoning module."""

    def test_import(self):
        """Spatial module is importable."""
        from volta.spatial import SpatialQueryEngine
        assert SpatialQueryEngine is not None
