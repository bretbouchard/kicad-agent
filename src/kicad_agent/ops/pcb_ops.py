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
import re
import uuid
from typing import Any

from kiutils.board import Board
from kiutils.items.common import Net, Position
from kiutils.items.gritems import GrLine
from kiutils.items.zones import Zone

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

    Creates a kiutils Zone with the specified parameters and adds it to
    the board's zones list.

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

    # Create polygon positions
    polygon = [Position(X=x, Y=y) for x, y in points]

    zone = Zone(
        net=net_number,
        netName=net_name,
        layers=[layer],
        clearance=clearance,
        minThickness=min_width,
        priority=priority,
        tstamp=str(uuid.uuid4()),
    )
    zone.polygons.append(polygon)
    board.zones.append(zone)

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

    Modifies the raw S-expression content to add or update the net class
    assignment, since kiutils does not natively handle net_class blocks.

    The PCB file stores net classes as:
        (net_class "ClassName" "description"
          (add_net "net_name")
          ...
        )

    Args:
        ir: PcbIR for the target PCB.
        file_path: Path to the PCB file (Path or str).
        net_name: Name of the net to assign.
        net_class_name: Name of the net class to assign.

    Returns:
        Dict with net and class names.
    """
    raw_content = ir.raw_content

    # Check if net exists in the board
    found_net = ir.get_net_by_name(net_name)
    if found_net is None:
        raise ValueError(f"Net '{net_name}' not found in PCB")

    # First, remove this net from any existing net_class blocks
    # Pattern: (add_net "net_name") within a net_class block
    add_net_pattern = re.compile(
        r'\(add_net "' + re.escape(net_name) + r'"\)\s*\n?'
    )
    raw_content = add_net_pattern.sub('', raw_content)

    # Find or create the target net_class block
    class_pattern = re.compile(
        r'\(net_class "' + re.escape(net_class_name) + r'"'
    )
    if class_pattern.search(raw_content):
        # Append add_net to existing net_class block
        # Find the closing paren of this net_class block
        match = class_pattern.search(raw_content)
        start = match.start()
        end = _find_matching_close(raw_content, start)
        if end is not None:
            # Insert (add_net "net_name") before the closing paren
            insertion = f'\n      (add_net "{net_name}")'
            raw_content = raw_content[:end] + insertion + raw_content[end:]
    else:
        # Create new net_class block before the closing (net ... entries or end of setup
        new_class = (
            f'  (net_class "{net_class_name}" ""\n'
            f'    (add_net "{net_name}")\n'
            f'  )\n'
        )
        # Insert before the first (net ... ) line or at end of setup
        first_net = re.search(r'\n  \(net \d+ ', raw_content)
        if first_net:
            raw_content = (
                raw_content[:first_net.start()] + '\n' + new_class + raw_content[first_net.start():]
            )
        else:
            # Append at end before closing paren
            raw_content = raw_content.rstrip() + '\n' + new_class + ')\n'

    # Write the modified content back
    ir._parse_result.file_path.write_text(raw_content, encoding="utf-8")
    ir._raw_written = True

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


def _find_matching_close(content: str, open_pos: int) -> int | None:
    """Find the matching closing paren for an S-expression starting at open_pos."""
    depth = 0
    i = open_pos
    in_string = False

    while i < len(content):
        c = content[i]

        if in_string:
            if c == '"':
                if i + 1 < len(content) and content[i + 1] == '"':
                    i += 2
                    continue
                in_string = False
            i += 1
            continue

        if c == '"':
            in_string = True
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return i
        i += 1

    return None
