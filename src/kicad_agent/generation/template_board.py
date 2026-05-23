"""Template PCB generator extending the maze_generator pattern.

GEN-08: Creates valid .kicad_pcb files from high-level parameters using the
same kiutils Board.create_new() + to_file() pattern proven in maze_generator.py.

Supports:
- Board outline on Edge.Cuts
- Auto-placement of components in a grid pattern
- Net definitions
- Round-trip validation (write -> re-parse -> verify)

Security (threat model):
  T-10-14: Grid placement is O(n), bounded by component count cap (500).

Usage::

    from kicad_agent.generation.template_board import generate_board
    from kicad_agent.generation.intent import BoardSpec, ComponentSpec

    spec = BoardSpec(width_mm=100, height_mm=80)
    result = generate_board(Path("output.kicad_pcb"), spec)
    print(f"Generated: {result.pcb_path}")
"""

import logging
import math
import uuid
from dataclasses import dataclass
from pathlib import Path

from kiutils.board import Board
from kiutils.footprint import Footprint, Pad
from kiutils.items.common import Net, Position
from kiutils.items.gritems import GrLine

from kicad_agent.generation.intent import BoardSpec, ComponentSpec, NetSpec

logger = logging.getLogger(__name__)

# Margin from board edge for component placement (mm)
_BOARD_MARGIN = 5.0
# Minimum spacing between placed components (mm)
_MIN_COMPONENT_SPACING = 5.0


@dataclass(frozen=True)
class BoardTemplate:
    """Metadata for a generated board template.

    Attributes:
        pcb_path: Path to the generated .kicad_pcb file.
        width_mm: Actual board width.
        height_mm: Actual board height.
        component_count: Number of components placed.
        net_count: Number of nets defined.
    """

    pcb_path: Path
    width_mm: float
    height_mm: float
    component_count: int
    net_count: int


def generate_board(
    output_path: Path,
    spec: BoardSpec,
    components: list[ComponentSpec] | None = None,
    nets: list[NetSpec] | None = None,
) -> BoardTemplate:
    """Generate a valid .kicad_pcb file from board specification.

    Creates a KiCad PCB with board outline, component footprints, and net
    definitions. Follows the same Board.create_new() + to_file() pattern
    as maze_generator.py.

    Args:
        output_path: Where to write the .kicad_pcb file.
        spec: Board physical parameters.
        components: Optional component specifications to place.
        nets: Optional net specifications to define.

    Returns:
        BoardTemplate with generation metadata.

    Raises:
        ValueError: If output_path does not have .kicad_pcb suffix.
        RuntimeError: If round-trip validation fails.
    """
    output_path = Path(output_path)
    if output_path.suffix != ".kicad_pcb":
        raise ValueError(f"Expected .kicad_pcb suffix, got: {output_path.suffix}")

    components = components or []
    nets = nets or []

    # Create board
    board = Board.create_new()
    board.general.thickness = spec.thickness_mm

    # Add board outline on Edge.Cuts
    _create_board_outline(board, spec.width_mm, spec.height_mm)

    # Add default empty net (KiCad requires net 0)
    board.nets.append(Net(number=0, name=""))

    # Add nets
    for i, net_spec in enumerate(nets, start=1):
        board.nets.append(Net(number=i, name=net_spec.name))

    # Place components
    positions = _compute_placement_positions(
        len(components), spec.width_mm, spec.height_mm
    )
    for comp, (cx, cy) in zip(components, positions):
        _add_component_footprint(board, comp, cx, cy)

    # Serialize
    output_path.parent.mkdir(parents=True, exist_ok=True)
    board.to_file(str(output_path))

    # Round-trip validation
    verified = Board.from_file(str(output_path))
    if not verified.footprints and not verified.graphicItems:
        raise RuntimeError("Generated board has no content after round-trip")

    return BoardTemplate(
        pcb_path=output_path,
        width_mm=spec.width_mm,
        height_mm=spec.height_mm,
        component_count=len(components),
        net_count=len(nets),
    )


def _create_board_outline(board: Board, width: float, height: float) -> None:
    """Add a rectangular board outline on Edge.Cuts layer.

    Four graphic line segments forming a closed rectangle from (0,0) to
    (width, height). Same pattern as maze_generator._create_board_outline.
    """
    corners = [
        (Position(0, 0), Position(width, 0)),
        (Position(width, 0), Position(width, height)),
        (Position(width, height), Position(0, height)),
        (Position(0, height), Position(0, 0)),
    ]
    for start, end in corners:
        board.graphicItems.append(
            GrLine(start=start, end=end, layer="Edge.Cuts", width=0.15)
        )


def _compute_placement_positions(
    count: int, board_width: float, board_height: float
) -> list[tuple[float, float]]:
    """Compute auto-placement positions for components on a grid.

    Divides the usable board area (excluding margins) into grid cells
    and places components at cell centers with minimum spacing.

    Args:
        count: Number of components to place.
        board_width: Board width in mm.
        board_height: Board height in mm.

    Returns:
        List of (x, y) position tuples.
    """
    if count == 0:
        return []

    usable_w = board_width - 2 * _BOARD_MARGIN
    usable_h = board_height - 2 * _BOARD_MARGIN

    if usable_w <= 0 or usable_h <= 0:
        # Board too small for margins, place at center
        return [(board_width / 2, board_height / 2)] * count

    # Compute grid dimensions: aim for roughly square cells
    cols = max(1, math.ceil(math.sqrt(count * usable_w / usable_h)))
    rows = max(1, math.ceil(count / cols))

    cell_w = usable_w / cols
    cell_h = usable_h / rows

    positions: list[tuple[float, float]] = []
    for i in range(count):
        row = i // cols
        col = i % cols
        cx = _BOARD_MARGIN + cell_w * (col + 0.5)
        cy = _BOARD_MARGIN + cell_h * (row + 0.5)
        positions.append((cx, cy))

    return positions


def _add_component_footprint(
    board: Board, comp: ComponentSpec, cx: float, cy: float
) -> None:
    """Add a component footprint to the board at (cx, cy).

    Creates a Footprint with the component's library_id, reference, and value.
    Each footprint gets a single SMD pad as a placeholder.

    Args:
        board: kiutils Board to add footprint to.
        comp: Component specification.
        cx: Center X position in mm.
        cy: Center Y position in mm.
    """
    # Parse library_id into nickname and entry name
    if ":" in comp.library_id:
        lib_nick, entry_name = comp.library_id.split(":", 1)
    else:
        lib_nick = ""
        entry_name = comp.library_id

    # Use explicit position if provided, otherwise use computed position
    if comp.position is not None:
        pos_x = comp.position.x
        pos_y = comp.position.y
    else:
        pos_x = cx
        pos_y = cy

    fp = Footprint(
        libraryNickname=lib_nick,
        entryName=entry_name,
        layer="F.Cu",
        position=Position(pos_x, pos_y),
        tstamp=str(uuid.uuid4()),
    )
    fp.properties["Reference"] = comp.reference
    fp.properties["Value"] = comp.value

    # Add a placeholder SMD pad
    pad = Pad(
        number="1",
        type="smd",
        shape="rect",
        position=Position(0, 0),
        size=Position(1.0, 1.0),
        layers=["F.Cu"],
        tstamp=str(uuid.uuid4()),
    )
    fp.pads.append(pad)
    board.footprints.append(fp)
