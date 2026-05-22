"""Spatial primitive dataclasses for PCB coordinate-grounded reasoning.

VP-03: Four frozen dataclass types representing spatial entities on a PCB.
Each type provides JSON serialization (for LLM consumption) and Shapely
geometry conversion (for spatial queries).

All coordinates are in millimeters (KiCad native unit). Y-axis increases
downward (standard screen coordinate convention).

Usage:
    from kicad_agent.spatial.primitives import SpatialPoint, SpatialBox

    pt = SpatialPoint(10.5, 20.3, "via", "v1")
    d = pt.to_json()       # dict for JSON serialization
    g = pt.to_shapely()    # shapely.Point for spatial queries
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpatialPoint:
    """A single coordinate point on the PCB (pin, via, pad, vertex).

    Immutable frozen dataclass. Coordinates in mm, rounded to 4 decimal
    places in JSON output for consistent display.
    """

    x: float
    y: float
    entity_type: str  # "pin", "via", "pad", "vertex", "drc_item"
    entity_id: str
    layer: str = ""
    net: str = ""

    def to_json(self) -> dict:
        """Serialize to a plain dict for JSON consumption by LLMs.

        Coordinates rounded to 4 decimal places for consistent display.
        """
        return {
            "type": "point",
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "layer": self.layer,
            "net": self.net,
        }

    def to_shapely(self):
        """Convert to a Shapely Point geometry.

        Imports shapely lazily to avoid import-time failures if shapely
        is not installed.
        """
        from shapely.geometry import Point

        return Point(self.x, self.y)


@dataclass(frozen=True)
class SpatialBox:
    """Axis-aligned bounding box for components, footprints, pads.

    Immutable frozen dataclass. Coordinates in mm.
    """

    x1: float  # min X
    y1: float  # min Y
    x2: float  # max X
    y2: float  # max Y
    entity_type: str  # "footprint", "component", "pad"
    entity_id: str
    layer: str = ""
    reference: str = ""  # e.g. "U1"

    def to_json(self) -> dict:
        """Serialize to a plain dict for JSON consumption by LLMs."""
        return {
            "type": "box",
            "x1": round(self.x1, 4),
            "y1": round(self.y1, 4),
            "x2": round(self.x2, 4),
            "y2": round(self.y2, 4),
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "layer": self.layer,
            "reference": self.reference,
        }

    def to_shapely(self):
        """Convert to a Shapely Polygon (box) geometry."""
        from shapely.geometry import box

        return box(self.x1, self.y1, self.x2, self.y2)


@dataclass(frozen=True)
class SpatialPath:
    """Ordered sequence of points forming a trace route.

    Immutable frozen dataclass. Points are (x, y) tuples in mm.
    """

    points: tuple[tuple[float, float], ...]
    entity_type: str  # "segment", "arc", "wire"
    entity_id: str
    layer: str = ""
    net: str = ""
    width: float = 0.0

    def to_json(self) -> dict:
        """Serialize to a plain dict for JSON consumption by LLMs."""
        return {
            "type": "path",
            "points": [[round(x, 4), round(y, 4)] for x, y in self.points],
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "layer": self.layer,
            "net": self.net,
            "width": self.width,
        }

    def to_shapely(self):
        """Convert to a Shapely LineString geometry."""
        from shapely.geometry import LineString

        return LineString(self.points)


@dataclass(frozen=True)
class SpatialRegion:
    """Polygonal region for zones, keepouts, copper pours.

    Immutable frozen dataclass. Boundary vertices are (x, y) tuples in mm.
    """

    boundary: tuple[tuple[float, float], ...]  # polygon vertices
    entity_type: str  # "zone", "keepout", "copper_pour", "net_class_region"
    entity_id: str
    layer: str = ""
    net: str = ""
    region_type: str = ""  # "fill", "keepout", etc.

    def to_json(self) -> dict:
        """Serialize to a plain dict for JSON consumption by LLMs."""
        return {
            "type": "region",
            "boundary": [[round(x, 4), round(y, 4)] for x, y in self.boundary],
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "layer": self.layer,
            "net": self.net,
            "region_type": self.region_type,
        }

    def to_shapely(self):
        """Convert to a Shapely Polygon geometry."""
        from shapely.geometry import Polygon

        return Polygon(self.boundary)
