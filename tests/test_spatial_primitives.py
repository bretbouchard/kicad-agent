"""Tests for spatial primitive dataclasses.

VP-03: Validates that SpatialPoint, SpatialBox, SpatialPath, SpatialRegion
are frozen dataclasses with correct to_json() and to_shapely() methods.
"""

from dataclasses import FrozenInstanceError

import pytest

from volta.spatial.primitives import (
    SpatialBox,
    SpatialPath,
    SpatialPoint,
    SpatialRegion,
)


class TestSpatialPoint:
    """Tests for SpatialPoint primitive."""

    def test_spatial_point_creation(self):
        """SpatialPoint stores all fields correctly."""
        pt = SpatialPoint(10.5, 20.3, "via", "v1", layer="F.Cu", net="GND")
        assert pt.x == 10.5
        assert pt.y == 20.3
        assert pt.entity_type == "via"
        assert pt.entity_id == "v1"
        assert pt.layer == "F.Cu"
        assert pt.net == "GND"

    def test_spatial_point_defaults(self):
        """SpatialPoint defaults layer and net to empty strings."""
        pt = SpatialPoint(5.0, 10.0, "pad", "U1.1")
        assert pt.layer == ""
        assert pt.net == ""

    def test_spatial_point_to_json(self):
        """to_json returns dict with correct keys and type='point'."""
        pt = SpatialPoint(10.5, 20.3, "via", "v1", layer="F.Cu", net="GND")
        result = pt.to_json()

        assert result["type"] == "point"
        assert result["x"] == 10.5
        assert result["y"] == 20.3
        assert result["entity_type"] == "via"
        assert result["entity_id"] == "v1"
        assert result["layer"] == "F.Cu"
        assert result["net"] == "GND"

        # Verify all expected keys are present
        expected_keys = {"type", "x", "y", "entity_type", "entity_id", "layer", "net"}
        assert set(result.keys()) == expected_keys

    def test_spatial_point_to_shapely(self):
        """to_shapely returns a shapely Point at the correct coordinates."""
        pt = SpatialPoint(15.0, 25.0, "pin", "p1")
        geom = pt.to_shapely()

        from shapely.geometry import Point

        assert isinstance(geom, Point)
        assert geom.x == 15.0
        assert geom.y == 25.0

    def test_point_coordinate_rounding(self):
        """to_json rounds coordinates to 4 decimal places."""
        pt = SpatialPoint(10.123456789, 20.987654321, "pad", "U1.1")
        result = pt.to_json()

        assert result["x"] == 10.1235
        assert result["y"] == 20.9877


class TestSpatialBox:
    """Tests for SpatialBox primitive."""

    def test_spatial_box_creation(self):
        """SpatialBox stores all fields correctly."""
        box = SpatialBox(1.0, 2.0, 10.0, 20.0, "footprint", "lib:fp1",
                         layer="F.Cu", reference="U1")
        assert box.x1 == 1.0
        assert box.y1 == 2.0
        assert box.x2 == 10.0
        assert box.y2 == 20.0
        assert box.entity_type == "footprint"
        assert box.reference == "U1"

    def test_spatial_box_to_json(self):
        """to_json returns dict with type='box' and correct keys."""
        box = SpatialBox(1.0, 2.0, 10.0, 20.0, "footprint", "lib:fp1")
        result = box.to_json()

        assert result["type"] == "box"
        assert result["x1"] == 1.0
        assert result["y1"] == 2.0
        assert result["x2"] == 10.0
        assert result["y2"] == 20.0

    def test_spatial_box_to_shapely(self):
        """to_shapely returns a shapely Polygon with correct bounds."""
        box = SpatialBox(1.0, 2.0, 10.0, 20.0, "footprint", "lib:fp1")
        geom = box.to_shapely()

        assert geom.bounds == (1.0, 2.0, 10.0, 20.0)
        assert geom.area > 0


class TestSpatialPath:
    """Tests for SpatialPath primitive."""

    def test_spatial_path_creation(self):
        """SpatialPath stores points tuple and metadata."""
        path = SpatialPath(
            points=((0.0, 0.0), (10.0, 0.0), (10.0, 5.0)),
            entity_type="segment",
            entity_id="s1",
            layer="F.Cu",
            net="VCC",
            width=0.25,
        )
        assert len(path.points) == 3
        assert path.entity_type == "segment"
        assert path.width == 0.25

    def test_spatial_path_to_shapely(self):
        """to_shapely returns a LineString with correct coordinates."""
        pts = ((0.0, 0.0), (10.0, 0.0), (10.0, 5.0))
        path = SpatialPath(points=pts, entity_type="segment", entity_id="s1")
        geom = path.to_shapely()

        from shapely.geometry import LineString

        assert isinstance(geom, LineString)
        assert len(geom.coords) == 3

    def test_spatial_path_to_json(self):
        """to_json returns points as list of [x, y] pairs."""
        path = SpatialPath(
            points=((0.0, 0.0), (10.0, 5.0)),
            entity_type="arc",
            entity_id="a1",
        )
        result = path.to_json()

        assert result["type"] == "path"
        assert result["points"] == [[0.0, 0.0], [10.0, 5.0]]
        assert result["entity_type"] == "arc"


class TestSpatialRegion:
    """Tests for SpatialRegion primitive."""

    def test_spatial_region_creation(self):
        """SpatialRegion stores boundary and metadata."""
        boundary = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        region = SpatialRegion(
            boundary=boundary,
            entity_type="zone",
            entity_id="z1",
            layer="F.Cu",
            net="GND",
            region_type="fill",
        )
        assert len(region.boundary) == 4
        assert region.entity_type == "zone"

    def test_spatial_region_to_shapely(self):
        """to_shapely returns a Polygon with correct boundary."""
        boundary = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
        region = SpatialRegion(boundary=boundary, entity_type="zone", entity_id="z1")
        geom = region.to_shapely()

        from shapely.geometry import Polygon

        assert isinstance(geom, Polygon)
        assert abs(geom.area - 100.0) < 0.001

    def test_spatial_region_to_json(self):
        """to_json returns boundary as list of [x, y] pairs."""
        boundary = ((0.0, 0.0), (5.0, 0.0), (5.0, 5.0), (0.0, 5.0))
        region = SpatialRegion(
            boundary=boundary,
            entity_type="keepout",
            entity_id="k1",
            region_type="keepout",
        )
        result = region.to_json()

        assert result["type"] == "region"
        assert result["entity_type"] == "keepout"
        assert result["region_type"] == "keepout"


class TestFrozenImmutability:
    """Tests that all primitives are truly immutable (frozen)."""

    def test_frozen_immutability(self):
        """Assigning to SpatialPoint.x raises FrozenInstanceError."""
        pt = SpatialPoint(1.0, 2.0, "via", "v1")
        with pytest.raises(FrozenInstanceError):
            pt.x = 99.0

    def test_frozen_box_immutability(self):
        """Assigning to SpatialBox.x1 raises FrozenInstanceError."""
        box = SpatialBox(1.0, 2.0, 3.0, 4.0, "footprint", "f1")
        with pytest.raises(FrozenInstanceError):
            box.x1 = 99.0

    def test_frozen_path_immutability(self):
        """Assigning to SpatialPath.width raises FrozenInstanceError."""
        path = SpatialPath(points=((0, 0), (1, 1)), entity_type="segment", entity_id="s1")
        with pytest.raises(FrozenInstanceError):
            path.width = 99.0

    def test_frozen_region_immutability(self):
        """Assigning to SpatialRegion.entity_type raises FrozenInstanceError."""
        region = SpatialRegion(
            boundary=((0, 0), (1, 0), (1, 1), (0, 1)),
            entity_type="zone",
            entity_id="z1",
        )
        with pytest.raises(FrozenInstanceError):
            region.entity_type = "other"
