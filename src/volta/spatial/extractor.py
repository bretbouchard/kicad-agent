"""Extract spatial primitives from PcbIR and SchematicIR.

VP-02: Extraction pipeline that converts PcbIR/SchematicIR coordinate data
into typed spatial primitives (SpatialPoint, SpatialBox, SpatialPath,
SpatialRegion).

CRITICAL: Pad positions are LOCAL to footprint origin in kiutils. This
module computes absolute positions by applying the footprint rotation
matrix before creating spatial primitives.

Usage:
    from volta.spatial.extractor import extract_all, extract_schematic_all

    # PCB spatial extraction
    result = extract_all(pcb_ir)

    # Schematic spatial extraction
    result = extract_schematic_all(sch_ir)
"""

from __future__ import annotations

import math
from typing import Any

from volta.ir.pcb_ir import PcbIR
from volta.spatial.primitives import (
    SpatialBox,
    SpatialPath,
    SpatialPoint,
    SpatialRegion,
)


def _net_name(net_obj: Any) -> str:
    """Extract net name from a kiutils net object, handling both formats.

    In older KiCad formats, net is an object with a .name attribute.
    In newer formats, net may be an int (net number) or a string.
    """
    if net_obj is None:
        return ""
    if isinstance(net_obj, str):
        return net_obj
    if isinstance(net_obj, int):
        return str(net_obj)
    if hasattr(net_obj, "name"):
        return net_obj.name
    return str(net_obj)


def _fp_position(fp: Any) -> tuple[float, float, float]:
    """Extract (x, y, angle) from footprint position.

    Works with both kiutils Position objects (with .X, .Y, .angle)
    and plain tuples from the native parser.
    """
    pos = fp.position
    if hasattr(pos, "X"):
        return (pos.X, pos.Y, getattr(pos, "angle", None) or 0.0)
    return (pos[0], pos[1], pos[2] if len(pos) > 2 else 0.0)


def _pad_position(pad: Any) -> tuple[float, float]:
    """Extract (x, y) from pad position.

    Works with both kiutils Position objects (with .X, .Y)
    and plain tuples from the native parser.
    """
    pos = pad.position
    if hasattr(pos, "X"):
        return (pos.X, pos.Y)
    return (pos[0], pos[1])


def _net_name_from_pad(pad: Any) -> str:
    """Extract net name from pad.

    Works with both kiutils (pad.net.name) and NativePad (pad.net_name).
    """
    if hasattr(pad, "net") and pad.net is not None:
        if hasattr(pad.net, "name"):
            return pad.net.name
        return str(pad.net)
    return getattr(pad, "net_name", "")


def _rotate_local_to_absolute(
    fp_x: float,
    fp_y: float,
    fp_angle: float,
    local_x: float,
    local_y: float,
) -> tuple[float, float]:
    """Compute absolute position from footprint origin + local offset + rotation.

    Applies 2D rotation matrix around the footprint origin, then translates
    to absolute board coordinates.

    Args:
        fp_x: Footprint origin X (absolute, mm).
        fp_y: Footprint origin Y (absolute, mm).
        fp_angle: Footprint rotation angle (degrees).
        local_x: Local offset X from footprint origin (mm).
        local_y: Local offset Y from footprint origin (mm).

    Returns:
        (absolute_x, absolute_y) in mm.
    """
    angle_rad = math.radians(fp_angle or 0.0)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    abs_x = fp_x + (local_x * cos_a - local_y * sin_a)
    abs_y = fp_y + (local_x * sin_a + local_y * cos_a)
    return (abs_x, abs_y)


def extract_points(pcb_ir: PcbIR) -> list[SpatialPoint]:
    """Extract spatial points for vias and pads from PcbIR.

    Vias have a 'position' attribute but no 'start'/'end'.
    Pads require absolute position computation from footprint origin + rotation.

    Args:
        pcb_ir: PCB intermediate representation with loaded board data.

    Returns:
        List of SpatialPoint instances for vias and pads.
    """
    points: list[SpatialPoint] = []

    # Extract via points from trace items
    for item in pcb_ir.trace_items:
        if hasattr(item, "position") and not (
            hasattr(item, "start") and hasattr(item, "end")
        ):
            # This is a via
            layers_str = ""
            if hasattr(item, "layers") and item.layers:
                layers_str = ",".join(item.layers)
            net_name = ""
            if hasattr(item, "net") and item.net is not None:
                net_name = _net_name(item.net)
            entity_id = str(item.tstamp) if hasattr(item, "tstamp") else ""
            points.append(
                SpatialPoint(
                    x=item.position.X,
                    y=item.position.Y,
                    entity_type="via",
                    entity_id=entity_id,
                    layer=layers_str,
                    net=net_name,
                )
            )

    # Extract pad points from footprints (absolute position)
    for fp in pcb_ir.footprints:
        fp_x, fp_y, fp_angle = _fp_position(fp)
        fp_ref = fp.properties.get("Reference", "")

        for pad in fp.pads:
            pad_x, pad_y = _pad_position(pad)
            abs_x, abs_y = _rotate_local_to_absolute(
                fp_x, fp_y, fp_angle, pad_x, pad_y
            )
            net_name = _net_name_from_pad(pad)
            points.append(
                SpatialPoint(
                    x=abs_x,
                    y=abs_y,
                    entity_type="pad",
                    entity_id=f"{fp_ref}.{pad.number}",
                    layer=pad.layers[0] if hasattr(pad, "layers") and pad.layers else "",
                    net=net_name,
                )
            )

    return points


def extract_boxes(pcb_ir: PcbIR) -> list[SpatialBox]:
    """Extract bounding boxes for footprints from PcbIR.

    Computes bounding box from pad positions (with 1.0mm margin),
    rotated to absolute coordinates.

    Args:
        pcb_ir: PCB intermediate representation with loaded board data.

    Returns:
        List of SpatialBox instances for each footprint with pads.
    """
    boxes: list[SpatialBox] = []

    for fp in pcb_ir.footprints:
        if not fp.pads:
            continue

        fp_x, fp_y, fp_angle = _fp_position(fp)

        # Compute absolute positions for all pads
        abs_positions: list[tuple[float, float]] = []
        for pad in fp.pads:
            pad_x, pad_y = _pad_position(pad)
            abs_x, abs_y = _rotate_local_to_absolute(
                fp_x, fp_y, fp_angle, pad_x, pad_y
            )
            abs_positions.append((abs_x, abs_y))

        # Bounding box from absolute pad positions + 1.0mm margin
        xs = [p[0] for p in abs_positions]
        ys = [p[1] for p in abs_positions]
        margin = 1.0

        reference = fp.properties.get("Reference", "")
        boxes.append(
            SpatialBox(
                x1=min(xs) - margin,
                y1=min(ys) - margin,
                x2=max(xs) + margin,
                y2=max(ys) + margin,
                entity_type="footprint",
                entity_id=fp.libId,
                layer=fp.layer,
                reference=reference,
            )
        )

    return boxes


def extract_paths(pcb_ir: PcbIR) -> list[SpatialPath]:
    """Extract trace paths (segments and arcs) from PcbIR.

    Segments have start and end positions. Arcs additionally have a midpoint.

    Args:
        pcb_ir: PCB intermediate representation with loaded board data.

    Returns:
        List of SpatialPath instances for each trace item.
    """
    paths: list[SpatialPath] = []

    for item in pcb_ir.trace_items:
        if not (hasattr(item, "start") and hasattr(item, "end")):
            continue  # Skip vias

        # Build points tuple
        pts: list[tuple[float, float]] = [(item.start.X, item.start.Y)]

        is_arc = hasattr(item, "mid")
        if is_arc:
            pts.append((item.mid.X, item.mid.Y))

        pts.append((item.end.X, item.end.Y))

        entity_id = str(item.tstamp) if hasattr(item, "tstamp") else ""
        net_name = _net_name(item.net) if hasattr(item, "net") and item.net else ""
        layer = item.layer if hasattr(item, "layer") else ""
        width = item.width if hasattr(item, "width") else 0.0

        paths.append(
            SpatialPath(
                points=tuple(pts),
                entity_type="arc" if is_arc else "segment",
                entity_id=entity_id,
                layer=layer,
                net=net_name,
                width=width,
            )
        )

    return paths


def extract_regions(pcb_ir: PcbIR) -> list[SpatialRegion]:
    """Extract zone regions from PcbIR.

    Iterates board zones and extracts polygon boundary vertices.

    Args:
        pcb_ir: PCB intermediate representation with loaded board data.

    Returns:
        List of SpatialRegion instances for each zone.
    """
    regions: list[SpatialRegion] = []

    board = pcb_ir.board
    if not hasattr(board, "zones"):
        return regions

    for i, zone in enumerate(board.zones):
        # Extract polygon vertices from zone polygons
        boundary: list[tuple[float, float]] = []
        if hasattr(zone, "polygons") and zone.polygons:
            first_poly = zone.polygons[0]
            # kiutils ZonePolygon stores vertices in 'coordinates' list
            if hasattr(first_poly, "coordinates"):
                for pt in first_poly.coordinates:
                    if hasattr(pt, "X") and hasattr(pt, "Y"):
                        boundary.append((pt.X, pt.Y))
            elif hasattr(first_poly, "outline"):
                for pt in first_poly.outline:
                    if hasattr(pt, "X") and hasattr(pt, "Y"):
                        boundary.append((pt.X, pt.Y))

        if not boundary:
            continue

        # Entity ID from tstamp or index-based
        entity_id = (
            str(zone.tstamp)
            if hasattr(zone, "tstamp") and zone.tstamp is not None
            else f"zone_{i}"
        )

        # Zone layers is a list; join for storage
        layer = ""
        if hasattr(zone, "layers") and zone.layers:
            layer = ",".join(str(l) for l in zone.layers)
        elif hasattr(zone, "layer"):
            layer = zone.layer

        # Net name: kiutils Zone has netName (string) and net (int)
        net_name = ""
        if hasattr(zone, "netName") and zone.netName:
            net_name = zone.netName
        elif hasattr(zone, "net") and zone.net is not None:
            net_name = _net_name(zone.net)

        regions.append(
            SpatialRegion(
                boundary=tuple(boundary),
                entity_type="zone",
                entity_id=entity_id,
                layer=layer,
                net=net_name,
            )
        )

    return regions


def extract_all(pcb_ir: PcbIR) -> dict[str, list]:
    """Extract all spatial primitives from PcbIR.

    Args:
        pcb_ir: PCB intermediate representation with loaded board data.

    Returns:
        Dict with keys "points", "boxes", "paths", "regions", each
        containing a list of the corresponding spatial primitives.
    """
    return {
        "points": extract_points(pcb_ir),
        "boxes": extract_boxes(pcb_ir),
        "paths": extract_paths(pcb_ir),
        "regions": extract_regions(pcb_ir),
    }


# ---------------------------------------------------------------------------
# Schematic spatial extraction
# ---------------------------------------------------------------------------


def extract_schematic_points(sch_ir: Any) -> list[SpatialPoint]:
    """Extract spatial points from SchematicIR.

    Sources: pin positions, label positions, and component symbol positions.

    Args:
        sch_ir: SchematicIR with loaded schematic data.

    Returns:
        List of SpatialPoint instances for pins, labels, and symbols.
    """
    points: list[SpatialPoint] = []

    # Pin positions (highest fidelity — absolute pin coords)
    try:
        for pin in sch_ir.get_pin_positions():
            points.append(
                SpatialPoint(
                    x=pin["x"],
                    y=pin["y"],
                    entity_type="pin",
                    entity_id=f"{pin['reference']}.{pin['pin_number']}",
                    net=pin.get("pin_name", ""),
                )
            )
    except Exception:
        pass

    # Label positions (net labels, global labels, hierarchical labels)
    try:
        for label in sch_ir.get_label_positions():
            points.append(
                SpatialPoint(
                    x=label["x"],
                    y=label["y"],
                    entity_type="label",
                    entity_id=label["name"],
                    net=label["name"],
                )
            )
    except Exception:
        pass

    return points


def extract_schematic_boxes(sch_ir: Any) -> list[SpatialBox]:
    """Extract bounding boxes for schematic symbols from SchematicIR.

    Computes bounding box from pin positions grouped by reference.
    Symbols with no pins get a 2mm x 2mm default box at symbol position.

    Args:
        sch_ir: SchematicIR with loaded schematic data.

    Returns:
        List of SpatialBox instances for each schematic symbol.
    """
    boxes: list[SpatialBox] = []

    try:
        pin_positions = sch_ir.get_pin_positions()
    except Exception:
        pin_positions = []

    # Group pin positions by reference
    from collections import defaultdict
    ref_pins: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for pin in pin_positions:
        ref = pin.get("reference", "")
        if ref:
            ref_pins[ref].append((pin["x"], pin["y"]))

    # Collect symbol positions for components with no pins
    symbol_positions: dict[str, tuple[float, float]] = {}
    sch = sch_ir._parse_result.kiutils_obj
    for sym in sch.schematicSymbols:
        ref = ""
        for prop in sym.properties:
            if prop.key == "Reference":
                ref = prop.value
                break
        if ref and ref not in ref_pins:
            symbol_positions[ref] = (sym.position.X, sym.position.Y)

    # Build boxes from pin positions
    margin = 1.0
    for ref, positions in ref_pins.items():
        xs = [p[0] for p in positions]
        ys = [p[1] for p in positions]
        boxes.append(
            SpatialBox(
                x1=min(xs) - margin,
                y1=min(ys) - margin,
                x2=max(xs) + margin,
                y2=max(ys) + margin,
                entity_type="symbol",
                entity_id=ref,
                reference=ref,
            )
        )

    # Default boxes for symbols without pins
    for ref, (sx, sy) in symbol_positions.items():
        boxes.append(
            SpatialBox(
                x1=sx - 1.0,
                y1=sy - 1.0,
                x2=sx + 1.0,
                y2=sy + 1.0,
                entity_type="symbol",
                entity_id=ref,
                reference=ref,
            )
        )

    return boxes


def extract_schematic_paths(sch_ir: Any) -> list[SpatialPath]:
    """Extract wire paths from SchematicIR.

    Each wire segment becomes a SpatialPath with start/end coordinates.

    Args:
        sch_ir: SchematicIR with loaded schematic data.

    Returns:
        List of SpatialPath instances for schematic wires.
    """
    paths: list[SpatialPath] = []

    try:
        wires = sch_ir.get_wire_endpoints()
    except Exception:
        return paths

    for wire in wires:
        points = ((wire["start_x"], wire["start_y"]), (wire["end_x"], wire["end_y"]))
        paths.append(
            SpatialPath(
                points=points,
                entity_type="wire",
                entity_id=wire.get("uuid", ""),
                width=0.0,
            )
        )

    return paths


def extract_schematic_all(sch_ir: Any) -> dict[str, list]:
    """Extract all spatial primitives from SchematicIR.

    Args:
        sch_ir: SchematicIR with loaded schematic data.

    Returns:
        Dict with keys "points", "boxes", "paths" (no regions for schematics).
    """
    return {
        "points": extract_schematic_points(sch_ir),
        "boxes": extract_schematic_boxes(sch_ir),
        "paths": extract_schematic_paths(sch_ir),
        "regions": [],
    }
