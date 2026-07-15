"""Spatial-grounded DRC/ERC enrichment pipeline.

VP-07: Transforms DRC/ERC violation reports from text-only results into
coordinate-grounded findings with spatial context. Each violation item
gets a SpatialPoint reference with precise (x, y) coordinates.

Enrichment converts Violation items (which have raw dicts from kicad-cli
JSON) into SpatialViolation objects with SpatialPoint items and human-
readable spatial context strings.

Usage:
    from volta.validation.spatial_drc import enrich_drc_result

    spatial_violations = enrich_drc_result(drc_result)
    for sv in spatial_violations:
        print(sv.format_report())
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from volta.spatial.primitives import SpatialPoint
from volta.validation.erc_drc import DrcResult, ErcResult, Severity


@dataclass(frozen=True)
class SpatialViolation:
    """DRC/ERC violation with coordinate-grounded spatial context.

    Each violation item is converted to a SpatialPoint with precise
    coordinates extracted from the kicad-cli JSON report.
    """

    description: str
    severity: str  # "error", "warning", "exclusion"
    violation_type: str
    items: tuple[SpatialPoint, ...]  # Each violation item as a coordinate point
    spatial_context: str  # Human-readable spatial description with coordinates
    raw_items: tuple[dict[str, Any], ...] = ()  # Original item dicts

    def to_json(self) -> dict:
        """Serialize to a plain dict for JSON consumption."""
        return {
            "description": self.description,
            "severity": self.severity,
            "violation_type": self.violation_type,
            "items": [p.to_json() for p in self.items],
            "spatial_context": self.spatial_context,
        }

    def format_report(self) -> str:
        """Format as coordinate-grounded report string.

        Example:
            [ERROR] Clearance violation
              at <point> [45.2000, 22.1000] (drc_item)
              Violation involves 2 items at positions: ...
        """
        parts = [f"[{self.severity.upper()}] {self.description}"]
        for item in self.items:
            parts.append(
                f"  at <point> [{item.x:.4f}, {item.y:.4f}] ({item.entity_type})"
            )
        parts.append(f"  {self.spatial_context}")
        return "\n".join(parts)


def _build_spatial_context(
    items: tuple[SpatialPoint, ...], nearby_info: str = ""
) -> str:
    """Format spatial context string from violation item points.

    Args:
        items: SpatialPoints representing violation item coordinates.
        nearby_info: Optional nearby component information string.

    Returns:
        Human-readable spatial context string.
    """
    if len(items) == 0:
        return "No coordinate data available for this violation"
    elif len(items) == 1:
        p = items[0]
        base = f"Violation at <point> [{p.x:.4f}, {p.y:.4f}]"
    else:
        coords = ", ".join(f"[{p.x:.4f}, {p.y:.4f}]" for p in items)
        base = f"Violation involves {len(items)} items at positions: {coords}"
    if nearby_info:
        return f"{base}. {nearby_info}"
    return base


def _fp_position(fp: Any) -> tuple[float, float]:
    """Extract (x, y) from footprint position.

    Works with both kiutils Position objects (with .X, .Y)
    and plain tuples from the native parser.
    """
    pos = fp.position
    if hasattr(pos, "X"):
        return (pos.X, pos.Y)
    return (pos[0], pos[1])


def _find_nearest_footprint(x: float, y: float, pcb_ir: Any) -> str | None:
    """Find the nearest footprint reference to a coordinate.

    Uses simple Euclidean distance to footprint position.

    Args:
        x: Target X coordinate (mm).
        y: Target Y coordinate (mm).
        pcb_ir: PcbIR object with footprints property.

    Returns:
        Reference designator string (e.g. "U1") or None if no footprints.
    """
    if not hasattr(pcb_ir, "footprints"):
        return None

    best_ref: str | None = None
    best_dist = float("inf")

    for fp in pcb_ir.footprints:
        fp_x, fp_y = _fp_position(fp)
        dist = math.sqrt((fp_x - x) ** 2 + (fp_y - y) ** 2)
        if dist < best_dist:
            best_dist = dist
            best_ref = fp.properties.get("Reference", None)

    return best_ref


def enrich_drc_result(
    drc_result: DrcResult, pcb_ir: Any = None
) -> list[SpatialViolation]:
    """Convert DRC violations to spatially-grounded violations.

    For each violation in drc_result.violations and unconnected_items,
    extracts pos.x/pos.y coordinates from item dicts and creates
    SpatialPoint objects. Builds spatial context string with coordinates.

    Args:
        drc_result: Structured DRC result from run_drc().
        pcb_ir: Optional PcbIR for nearby footprint enrichment.

    Returns:
        List of SpatialViolation objects with coordinate-grounded items.
        Returns empty list if drc_result has error_message set (no violations
        to enrich -- kicad-cli invocation failed).
    """
    if drc_result.error_message is not None:
        return []

    violations: list[SpatialViolation] = []

    all_raw = drc_result.violations + drc_result.unconnected_items

    for v in all_raw:
        spatial_items: list[SpatialPoint] = []
        for i, item in enumerate(v.items):
            pos = item.get("pos", {})
            x = pos.get("x", 0.0)
            y = pos.get("y", 0.0)
            spatial_items.append(
                SpatialPoint(
                    x=x,
                    y=y,
                    entity_type="drc_item",
                    entity_id=item.get("uuid", f"drc_{i}"),
                )
            )

        items_tuple = tuple(spatial_items)

        # Optional enrichment: find nearest footprint
        nearby_info = ""
        if pcb_ir is not None and items_tuple:
            nearest = _find_nearest_footprint(
                items_tuple[0].x, items_tuple[0].y, pcb_ir
            )
            if nearest:
                nearby_info = f"near component {nearest}"

        context = _build_spatial_context(items_tuple, nearby_info)

        violations.append(
            SpatialViolation(
                description=v.description,
                severity=v.severity.value,
                violation_type=v.type,
                items=items_tuple,
                spatial_context=context,
                raw_items=v.items,
            )
        )

    return violations


def enrich_erc_result(erc_result: ErcResult) -> list[SpatialViolation]:
    """Convert ERC violations to spatially-grounded violations.

    ERC items may have pos coordinates or may not (depends on violation
    type). Items without pos data get SpatialPoint(0.0, 0.0) with
    entity_type="erc_item_no_pos".

    Args:
        erc_result: Structured ERC result from run_erc().

    Returns:
        List of SpatialViolation objects with coordinate-grounded items.
        Returns empty list if erc_result has error_message set.
    """
    if erc_result.error_message is not None:
        return []

    violations: list[SpatialViolation] = []

    for v in erc_result.violations:
        spatial_items: list[SpatialPoint] = []
        for i, item in enumerate(v.items):
            pos = item.get("pos")
            if pos is not None:
                x = pos.get("x", 0.0)
                y = pos.get("y", 0.0)
                spatial_items.append(
                    SpatialPoint(
                        x=x,
                        y=y,
                        entity_type="erc_item",
                        entity_id=item.get("uuid", f"erc_{i}"),
                    )
                )
            else:
                spatial_items.append(
                    SpatialPoint(
                        x=0.0,
                        y=0.0,
                        entity_type="erc_item_no_pos",
                        entity_id=item.get("uuid", f"erc_{i}"),
                    )
                )

        items_tuple = tuple(spatial_items)
        context = _build_spatial_context(items_tuple)

        violations.append(
            SpatialViolation(
                description=v.description,
                severity=v.severity.value,
                violation_type=v.type,
                items=items_tuple,
                spatial_context=context,
                raw_items=v.items,
            )
        )

    return violations
