"""PCB-level operations -- copper zones, board outlines, net class assignment.

Provides operations for:
  - Adding copper zones (ground pours) with net assignment and layer selection
  - Setting board outlines as rectangles on Edge.Cuts
  - Assigning net classes to specific nets

Uses kiutils for Zone and GrLine creation, falling back to raw S-expression
manipulation for net class assignment (kiutils does not handle net_class blocks).

Usage:
    from kicad_agent.ops.pcb_ops import add_copper_zone, set_board_outline, assign_net_class

    zone_result = add_copper_zone(ir, file_path, net_name="GND", layer="F.Cu")
    outline_result = set_board_outline(ir, width=50.0, height=30.0)
    class_result = assign_net_class(ir, file_path, net_name="VCC", net_class_name="Power")
"""

import logging
import uuid
from typing import Any

from kiutils.board import Board
from kiutils.items.common import Net, Position
from kiutils.items.gritems import GrLine

from kicad_agent.ir.pcb_ir import PcbIR

logger = logging.getLogger(__name__)


def add_copper_zone(
    ir: PcbIR,
    file_path: object,
    net_name: str = "",
    layer: str = "F.Cu",
    clearance: float = 0.5,
    min_width: float = 0.25,
    priority: int = 0,
    outline_points: list[tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """Add a copper zone/ground pour to a PCB.

    Uses PcbRawWriter to generate KiCad 10-compatible S-expressions directly,
    bypassing kiutils Zone serialization which has two bugs:
    - Appends plain lists instead of ZonePolygon objects (#34)
    - Generates wrong net format (net "NAME") vs KiCad 10 (net N) (#38)

    Args:
        ir: PcbIR for the target PCB.
        file_path: Path to the PCB file (Path or str).
        net_name: Net name for the zone (e.g. "GND"). Empty means unconnected.
        layer: Copper layer (e.g. "F.Cu", "B.Cu").
        clearance: Zone clearance in mm.
        min_width: Minimum fill width in mm.
        priority: Zone priority (higher = filled first).
        outline_points: Optional polygon outline as [(x,y), ...].
            If None, uses board bounding box with 1mm margin.

    Returns:
        Dict with zone_added, net, layer, clearance.
    """
    from dataclasses import replace

    from kicad_agent.ops.pcb_raw_writer import PcbRawWriter

    board = ir.board

    # Resolve net number from name
    net_number = 0
    if net_name:
        found_net = ir.get_net_by_name(net_name)
        if found_net is not None:
            net_number = found_net.number
        else:
            # Create the net if it doesn't exist
            new_net = ir.add_net(net_name=net_name)
            net_number = new_net.number

    # Determine outline points
    if outline_points is None:
        points = _get_board_bbox_points(board, margin=1.0)
    else:
        points = outline_points

    # Generate KiCad 10 zone S-expression via PcbRawWriter
    zone_uuid = str(uuid.uuid4())
    zone_sexp = PcbRawWriter.build_zone_sexp(
        net_number=net_number,
        net_name=net_name,
        layer=layer,
        polygon=points,
        clearance=clearance,
        min_thickness=min_width,
        priority=priority,
        uuid=zone_uuid,
    )

    # Insert into raw content and write atomically
    raw = ir._parse_result.raw_content
    new_raw = PcbRawWriter.insert_zone(raw, zone_sexp)
    ir.commit_raw_content(new_raw)

    # Re-parse to update in-memory board for subsequent modify/remove operations.
    # Use native parser first (handles boards kiutils can't parse, fixes #64).
    # Fall back to kiutils only if native parser is unavailable.
    from kicad_agent.parser import parse_pcb
    from kicad_agent.parser.uuid_extractor import extract_uuids

    try:
        result = parse_pcb(ir._parse_result.file_path)
        uuid_map = extract_uuids(result.raw_content, "pcb")
        ir._update_parse_result(result, uuid_map)
    except Exception as e:
        # kiutils re-parse failed (e.g. fp_poly corruption on analog board).
        # The write already succeeded via native path — update raw content only.
        logger.warning(
            "Post-write re-parse failed (kiutils): %s. "
            "Zone was written successfully via native path, but in-memory "
            "board is stale. Subsequent operations may need a fresh parse.",
            e,
        )

    ir._record_mutation("add_copper_zone", {
        "net_name": net_name,
        "layer": layer,
        "clearance": clearance,
    })

    return {
        "zone_added": True,
        "net": net_name,
        "layer": layer,
        "clearance": clearance,
    }


def modify_copper_zone(
    ir: PcbIR,
    file_path: object,
    zone_uuid: str,
    net_name: str | None = None,
    layer: str | None = None,
    clearance: float | None = None,
    min_width: float | None = None,
    priority: int | None = None,
) -> dict[str, Any]:
    """Modify an existing copper zone identified by UUID.

    Only non-None parameters are updated on the zone.

    Args:
        ir: PcbIR for the target PCB.
        file_path: Path to the PCB file (Path or str).
        zone_uuid: UUID (tstamp) of the zone to modify.
        net_name: New net name (optional).
        layer: New layer (optional).
        clearance: New clearance in mm (optional).
        min_width: New minimum fill width in mm (optional).
        priority: New priority (optional).

    Returns:
        Dict with modified, zone_uuid, and updated_fields list.

    Raises:
        ValueError: If zone with given UUID is not found.
    """
    target = next((z for z in ir.board.zones if z.tstamp == zone_uuid), None)
    if target is None:
        raise ValueError(f"Zone with UUID '{zone_uuid}' not found")

    updated_fields: list[str] = []

    if net_name is not None:
        found_net = ir.get_net_by_name(net_name)
        if found_net is not None:
            target.net = found_net.number
        else:
            new_net = ir.add_net(net_name=net_name)
            target.net = new_net.number
        target.netName = net_name
        updated_fields.append("net_name")

    if layer is not None:
        target.layers = [layer]
        updated_fields.append("layer")

    if clearance is not None:
        target.clearance = clearance
        updated_fields.append("clearance")

    if min_width is not None:
        target.minThickness = min_width
        updated_fields.append("min_width")

    if priority is not None:
        target.priority = priority
        updated_fields.append("priority")

    ir._record_mutation("modify_copper_zone", {
        "zone_uuid": zone_uuid,
        "updated_fields": updated_fields,
    })

    return {
        "modified": True,
        "zone_uuid": zone_uuid,
        "updated_fields": updated_fields,
    }


def remove_copper_zone(
    ir: PcbIR,
    file_path: object,
    zone_uuid: str | None = None,
    zone_index: int | None = None,
) -> dict[str, Any]:
    """Remove a copper zone from the PCB.

    Tries UUID first, falls back to index.

    Uses PcbRawWriter for raw S-expression splicing so the op works on both
    freshly-parsed boards and boards where prior ops wrote to raw_content
    (e.g. add_copper_zone). Kiutils' in-memory board may be stale after a
    raw write -- operating on raw content is the only reliable path.

    Args:
        ir: PcbIR for the target PCB.
        file_path: Path to the PCB file (Path or str).
        zone_uuid: UUID (tstamp) of the zone (preferred).
        zone_index: Index of the zone as fallback.

    Returns:
        Dict with removed and zone_uuid.

    Raises:
        ValueError: If neither UUID nor index provided, or UUID not found.
        IndexError: If index is out of range.
    """
    from kicad_agent.ops.pcb_raw_writer import PcbRawWriter

    if zone_uuid is not None:
        start, end = PcbRawWriter.find_zone_block(ir.raw_content, zone_uuid)
        if start is None or end is None:
            raise ValueError(f"Zone with UUID '{zone_uuid}' not found")
        identifier = zone_uuid
    elif zone_index is not None:
        start, end = PcbRawWriter.find_zone_block_by_index(ir.raw_content, zone_index)
        if start is None or end is None:
            raise IndexError(
                f"Zone index {zone_index} out of range"
            )
        identifier = f"index:{zone_index}"
    else:
        raise ValueError("Must specify zone_uuid or zone_index")

    raw = ir.raw_content
    trim_start = start
    if trim_start > 0 and raw[trim_start - 1] == "\n":
        trim_start -= 1
    new_content = raw[:trim_start] + raw[end:]
    ir.commit_raw_content(new_content)

    # In-memory zone sync: NativeBoard.zones is a frozen tuple, so use
    # dataclasses.replace (Bead analog-ecosystem-14 fix — previously crashed
    # with 'tuple' object has no attribute 'remove' on frozen dataclass).
    # The raw_content mutation above is the source of truth; this in-memory
    # update keeps the IR cache coherent without forcing a re-parse.
    import dataclasses
    if zone_uuid is not None:
        new_zones = tuple(z for z in ir.board.zones if z.tstamp != zone_uuid)
    else:
        zone_list = list(ir.board.zones)
        if zone_index < len(zone_list):
            zone_list.pop(zone_index)
        new_zones = tuple(zone_list)
    if len(new_zones) != len(ir.board.zones):
        ir._board = dataclasses.replace(ir.board, zones=new_zones)

    ir._record_mutation("remove_copper_zone", {"zone_uuid": identifier})

    return {
        "removed": True,
        "zone_uuid": identifier,
    }


def set_board_outline(
    ir: PcbIR,
    width: float,
    height: float,
    corner_radius: float = 0.0,
) -> dict[str, Any]:
    """Define PCB board shape as a rectangle on Edge.Cuts.

    Removes existing Edge.Cuts graphic items and creates a new rectangular
    outline using four GrLine segments.

    Args:
        ir: PcbIR for the target PCB.
        width: Board width in mm.
        height: Board height in mm.
        corner_radius: Reserved for future rounded corner support.

    Returns:
        Dict with outline_set, width_mm, height_mm.
    """
    board = ir.board

    # Remove existing Edge.Cuts graphic items
    board.graphicItems[:] = [
        item for item in board.graphicItems
        if getattr(item, "layer", None) != "Edge.Cuts"
    ]

    # Create four line segments forming a closed rectangle
    corners = [
        (Position(X=0.0, Y=0.0), Position(X=width, Y=0.0)),
        (Position(X=width, Y=0.0), Position(X=width, Y=height)),
        (Position(X=width, Y=height), Position(X=0.0, Y=height)),
        (Position(X=0.0, Y=height), Position(X=0.0, Y=0.0)),
    ]

    for start, end in corners:
        board.graphicItems.append(
            GrLine(
                start=start,
                end=end,
                layer="Edge.Cuts",
                width=0.15,
                tstamp=str(uuid.uuid4()),
            )
        )

    ir._record_mutation("set_board_outline", {
        "width": width,
        "height": height,
    })

    return {
        "outline_set": True,
        "width_mm": width,
        "height_mm": height,
    }


def assign_net_class(
    ir: PcbIR,
    file_path: object,
    net_name: str,
    net_class_name: str,
) -> dict[str, Any]:
    """Assign a net class to a specific net in the PCB.

    Delegates to PcbRawWriter for raw S-expression manipulation (Council C-02).
    """
    from kicad_agent.ops.pcb_raw_writer import PcbRawWriter

    # Check if net exists in the board
    found_net = ir.get_net_by_name(net_name)
    if found_net is None:
        raise ValueError(f"Net '{net_name}' not found in PCB")

    raw_content = ir.raw_content
    new_content = PcbRawWriter.assign_net_class(raw_content, net_name, net_class_name)

    # Write atomically and update IR cache
    ir.commit_raw_content(new_content)

    ir._record_mutation("assign_net_class", {
        "net_name": net_name,
        "net_class_name": net_class_name,
    })

    return {
        "net": net_name,
        "class": net_class_name,
    }


def _get_board_bbox_points(board: Board, margin: float = 1.0) -> list[tuple[float, float]]:
    """Get board bounding box outline points with margin.

    Scans Edge.Cuts graphic items to find the bounding box. Falls back
    to (0,0)-(100,100) if no outline exists.

    Args:
        board: kiutils Board object.
        margin: Margin to add around the bounding box in mm.

    Returns:
        List of 4 (x, y) tuples forming a rectangle.
    """
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")

    for item in board.graphicItems:
        if getattr(item, "layer", None) == "Edge.Cuts":
            if hasattr(item, "start") and hasattr(item, "end"):
                for pos in [item.start, item.end]:
                    min_x = min(min_x, pos.X)
                    min_y = min(min_y, pos.Y)
                    max_x = max(max_x, pos.X)
                    max_y = max(max_y, pos.Y)

    # Fallback if no Edge.Cuts found
    if min_x == float("inf"):
        min_x, min_y = 0.0, 0.0
        max_x, max_y = 100.0, 100.0

    return [
        (min_x - margin, min_y - margin),
        (max_x + margin, min_y - margin),
        (max_x + margin, max_y + margin),
        (min_x - margin, max_y + margin),
    ]


def modify_zone_polygon(
    ir: PcbIR,
    file_path: object,
    zone_uuid: str,
    polygon: list[tuple[float, float]],
) -> dict[str, Any]:
    """Replace the polygon outline of an existing copper zone.

    Delegates to PcbRawWriter.modify_zone_polygon() for raw S-expression
    manipulation.

    Args:
        ir: PcbIR for the target PCB.
        file_path: Path to the PCB file (Path or str).
        zone_uuid: UUID (tstamp) of the zone to modify.
        polygon: New polygon outline points as [(x, y), ...].

    Returns:
        Dict with modified, zone_uuid.

    Raises:
        ValueError: If zone with given UUID is not found.
    """
    from kicad_agent.ops.pcb_raw_writer import PcbRawWriter

    raw = ir.raw_content
    new_content = PcbRawWriter.modify_zone_polygon(raw, zone_uuid, polygon)

    if new_content == raw:
        raise ValueError(f"Zone with UUID '{zone_uuid}' not found")

    ir.commit_raw_content(new_content)

    ir._record_mutation("modify_zone_polygon", {
        "zone_uuid": zone_uuid,
        "polygon_points": len(polygon),
    })

    return {
        "modified": True,
        "zone_uuid": zone_uuid,
    }


def refill_copper_zone(
    ir: PcbIR,
    file_path: object,
    zone_uuid: str | None = None,
    zone_index: int | None = None,
) -> dict[str, Any]:
    """Strip filled polygon data from a zone so KiCad refills on next save.

    Removes (filled_polygon ...) and (filled_areas ...) blocks from the
    zone. KiCad automatically refills zones when the file is opened or saved.

    Args:
        ir: PcbIR for the target PCB.
        file_path: Path to the PCB file (Path or str).
        zone_uuid: UUID (tstamp) of the zone (preferred).
        zone_index: Index of the zone as fallback.

    Returns:
        Dict with refilled and zone_uuid.
    """
    import re

    from kicad_agent.ops.pcb_raw_writer import PcbRawWriter

    raw = ir.raw_content

    # Find zone block
    if zone_uuid is not None:
        start, end = PcbRawWriter.find_zone_block(raw, zone_uuid)
    elif zone_index is not None:
        start, end = PcbRawWriter.find_zone_block_by_index(raw, zone_index)
    else:
        raise ValueError("Must specify zone_uuid or zone_index")

    if start is None or end is None:
        raise ValueError("Zone not found")

    new_block = raw[start:end]

    # Strip filled_polygon and filled_areas blocks using _find_matching_close
    from kicad_agent.ops.pcb_raw_writer import PcbRawWriter as _PRW
    for marker in ["filled_polygon", "filled_areas"]:
        while True:
            match = re.search(r'\(' + marker + r'\b', new_block)
            if match is None:
                break
            block_start = match.start()
            close = _PRW._find_matching_close(new_block, block_start + 1)
            if close is not None:
                # Include trailing newline if present
                trim_end = close + 1
                if trim_end < len(new_block) and new_block[trim_end] == "\n":
                    trim_end += 1
                trim_start = block_start
                if trim_start > 0 and new_block[trim_start - 1] == "\n":
                    trim_start -= 1
                new_block = new_block[:trim_start] + new_block[trim_end:]
            else:
                break

    new_content = raw[:start] + new_block + raw[end:]

    if new_content == raw:
        logger.warning("No filled data found to strip from zone (may already be unfilled)")

    ir.commit_raw_content(new_content)

    ir._record_mutation("refill_copper_zone", {"zone_uuid": zone_uuid})

    return {
        "refilled": True,
        "zone_uuid": zone_uuid or f"index:{zone_index}",
    }


def add_keepout_area(
    ir: PcbIR,
    file_path: object,
    layer: str = "*",
    keepout_type: str = "through_hole",
    polygon: list[tuple[float, float]] | None = None,
    rule_clearance_mm: float | None = None,
) -> dict[str, Any]:
    """Add a keepout area to the PCB.

    Builds a (zone (net 0) (net_name "") (layer ...) (keepout ...) (polygon ...))
    S-expression and inserts it via PcbRawWriter.insert_zone().

    KiCad 10 format (Phase 101-06, routing-rick M5):
    - Uses paired (net 0) + (net_name "") per KiCad 10 zone rule
    - Adds optional (rule (clearance N)) wrapper when rule_clearance_mm is set
    - Uses (filled_areas_thickness no) token to match KiCad 10 writer output

    Args:
        ir: PcbIR for the target PCB.
        file_path: Path to the PCB file (Path or str).
        layer: Layer restriction ("*" = all layers).
        keepout_type: Type of keepout (through_hole, via, tracks, pads).
        polygon: Keepout outline points. Uses board bbox if None.
        rule_clearance_mm: Optional rule clearance in mm. When set, adds
            ``(rule (clearance N))`` wrapper inside the zone block per
            routing-rick M5 finding.

    Returns:
        Dict with keepout_added, layer, keepout_type, rule_clearance_mm.
    """
    import uuid as _uuid

    from kicad_agent.ops.pcb_raw_writer import PcbRawWriter

    if polygon is None:
        polygon = _get_board_bbox_points(ir.board, margin=1.0)

    keepout_uuid = str(_uuid.uuid4())

    xy_entries = " ".join(
        f"(xy {x:g} {y:g})" for x, y in polygon
    )

    rule_line = (
        f'    (rule\n      (clearance {rule_clearance_mm:g})\n    )\n'
        if rule_clearance_mm is not None else ''
    )

    zone_sexp = f"""  (zone
    (net "")
    (layer "{layer}")
    (uuid "{keepout_uuid}")
    (hatch edge 0.5)
    (connect_pads
      (clearance 0)
    )
    (min_thickness 0.25)
    (filled_areas_thickness no)
    (keepout {keepout_type})
{rule_line}    (polygon
      (pts
        {xy_entries}
      )
    )
  )
"""

    raw = ir.raw_content
    new_raw = PcbRawWriter.insert_zone(raw, zone_sexp)
    ir.commit_raw_content(new_raw)

    ir._record_mutation("add_keepout_area", {
        "layer": layer,
        "keepout_type": keepout_type,
        "rule_clearance_mm": rule_clearance_mm,
    })

    return {
        "keepout_added": True,
        "layer": layer,
        "keepout_type": keepout_type,
        "rule_clearance_mm": rule_clearance_mm,
    }


def remove_keepout_area(
    ir: PcbIR,
    file_path: object,
    zone_uuid: str | None = None,
    zone_index: int | None = None,
) -> dict[str, Any]:
    """Remove a keepout area from the PCB.

    Same mechanism as remove_copper_zone but with keepout-specific messaging.

    Args:
        ir: PcbIR for the target PCB.
        file_path: Path to the PCB file (Path or str).
        zone_uuid: UUID (tstamp) of the keepout (preferred).
        zone_index: Index as fallback.

    Returns:
        Dict with removed and zone_uuid.
    """
    from kicad_agent.ops.pcb_raw_writer import PcbRawWriter

    if zone_uuid is not None:
        start, end = PcbRawWriter.find_zone_block(ir.raw_content, zone_uuid)
        if start is None or end is None:
            raise ValueError(f"Keepout zone with UUID '{zone_uuid}' not found")
        identifier = zone_uuid
    elif zone_index is not None:
        start, end = PcbRawWriter.find_zone_block_by_index(ir.raw_content, zone_index)
        if start is None or end is None:
            raise IndexError(
                f"Zone index {zone_index} out of range"
            )
        identifier = f"index:{zone_index}"
    else:
        raise ValueError("Must specify zone_uuid or zone_index")

    raw = ir.raw_content
    trim_start = start
    if trim_start > 0 and raw[trim_start - 1] == "\n":
        trim_start -= 1
    new_content = raw[:trim_start] + raw[end:]

    ir.commit_raw_content(new_content)

    ir._record_mutation("remove_keepout_area", {"zone_uuid": identifier})

    return {
        "removed": True,
        "zone_uuid": identifier,
    }

