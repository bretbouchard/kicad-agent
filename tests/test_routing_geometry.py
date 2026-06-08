"""Tests for routing geometry module."""

import pytest

from kicad_agent.routing.geometry import (
    point_to_segment_distance,
)


class TestRoutingGeometryDetailed:
    """Detailed tests for routing geometry utilities."""

    def test_import(self):
        """Geometry module is importable."""
        from kicad_agent.routing import geometry
        assert geometry is not None

    def test_point_to_segment_distance_callable(self):
        """point_to_segment_distance is callable."""
        assert callable(point_to_segment_distance)
