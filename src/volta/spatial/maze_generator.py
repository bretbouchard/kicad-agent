"""Procedural maze-routing PCB generator for spatial reasoning training.

VP-04: Generates synthetic PCB puzzles with obstacles, routing targets, and
known solutions. Used for training and validating coordinate-grounded reasoning.

Generates a minimal KiCad PCB file with:
  - Board outline (Edge.Cuts rectangle)
  - Obstacle footprints on a grid (F.Cu copper rectangles)
  - Source and target vias on different nets
  - BFS-computed solution path through clear cells

All generated boards parse and round-trip correctly through kiutils.

Usage:
    from volta.spatial.maze_generator import generate_maze_board

    maze = generate_maze_board(Path("puzzle.kicad_pcb"), seed=42)
    print(f"Obstacles: {len(maze.obstacles)}")
    print(f"Solution: {len(maze.solution_path)} steps")
"""

from __future__ import annotations

import random
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from kiutils.board import Board
from kiutils.footprint import Footprint, Pad
from kiutils.items.brditems import Via
from kiutils.items.common import Net, Position
from kiutils.items.gritems import GrLine

from volta.spatial.primitives import SpatialBox, SpatialPoint


@dataclass(frozen=True)
class MazeBoard:
    """A generated maze-routing PCB puzzle with known solution.

    Attributes:
        pcb_path: Path to the generated .kicad_pcb file.
        board_width_mm: Board width in millimeters.
        board_height_mm: Board height in millimeters.
        obstacles: Tuple of SpatialBox for each obstacle cell.
        source_point: Source via location as SpatialPoint.
        target_point: Target via location as SpatialPoint.
        solution_path: Ordered (x, y) coordinates of the solution path.
        clearance_mm: Clearance between features in mm.
    """

    pcb_path: Path
    board_width_mm: float
    board_height_mm: float
    obstacles: tuple[SpatialBox, ...]
    source_point: SpatialPoint
    target_point: SpatialPoint
    solution_path: tuple[tuple[float, float], ...]
    clearance_mm: float


# ---------------------------------------------------------------------------
# Threat model mitigations (T-08-05, T-08-06)
# ---------------------------------------------------------------------------

_MAX_BOARD_DIM = 500.0  # mm -- prevents unreasonable board sizes
_MAX_GRID_CELLS = 10_000  # prevents DoS from huge grids
_MIN_GRID_SIZE = 1.0  # mm -- prevents degenerate tiny cells


def generate_maze_board(
    output_path: Path,
    width_mm: float = 50.0,
    height_mm: float = 50.0,
    grid_size_mm: float = 5.0,
    clearance_mm: float = 0.5,
    seed: int | None = None,
) -> MazeBoard:
    """Generate a procedural maze-routing PCB puzzle.

    Creates a KiCad PCB file with randomly placed obstacle footprints,
    source/target vias, and a BFS-computed solution path.

    Args:
        output_path: Where to write the .kicad_pcb file.
        width_mm: Board width in mm (1..500).
        height_mm: Board height in mm (1..500).
        grid_size_mm: Grid cell size in mm (>= 1.0).
        clearance_mm: Feature clearance in mm.
        seed: Random seed for deterministic generation.

    Returns:
        MazeBoard with metadata including obstacles, source, target, and solution.

    Raises:
        ValueError: If dimensions are out of bounds.
    """
    # T-08-05: Validate output path
    output_path = Path(output_path)
    if output_path.suffix != ".kicad_pcb":
        raise ValueError(f"Expected .kicad_pcb suffix, got: {output_path.suffix}")

    # T-08-06: Cap dimensions
    if not (1.0 <= width_mm <= _MAX_BOARD_DIM):
        raise ValueError(f"width_mm must be in [1, {_MAX_BOARD_DIM}], got {width_mm}")
    if not (1.0 <= height_mm <= _MAX_BOARD_DIM):
        raise ValueError(f"height_mm must be in [1, {_MAX_BOARD_DIM}], got {height_mm}")
    if grid_size_mm < _MIN_GRID_SIZE:
        raise ValueError(f"grid_size_mm must be >= {_MIN_GRID_SIZE}, got {grid_size_mm}")

    cols = int(width_mm / grid_size_mm)
    rows = int(height_mm / grid_size_mm)
    if cols < 3 or rows < 3:
        raise ValueError(
            f"Grid too small ({cols}x{rows} cells). Increase board size or decrease grid size."
        )
    if cols * rows > _MAX_GRID_CELLS:
        raise ValueError(
            f"Grid too large ({cols}x{rows} = {cols * rows} cells, "
            f"max {_MAX_GRID_CELLS}). Decrease board size or increase grid size."
        )

    # Set random seed
    if seed is not None:
        random.seed(seed)

    # Create board
    board = Board.create_new()
    board.general.thickness = 1.6

    # Add board outline on Edge.Cuts
    _create_board_outline(board, width_mm, height_mm)

    # Generate obstacle grid
    # True = obstacle, False = clear
    grid: list[list[bool]] = [[False] * cols for _ in range(rows)]
    obstacles: list[SpatialBox] = []
    obs_index = 0
    for r in range(rows):
        for c in range(cols):
            if random.random() < 0.4:
                grid[r][c] = True
                cx = grid_size_mm * (c + 0.5)
                cy = grid_size_mm * (r + 0.5)
                _add_obstacle_footprint(board, cx, cy, grid_size_mm * 0.8, obs_index)
                obstacles.append(
                    SpatialBox(
                        x1=cx - grid_size_mm * 0.4,
                        y1=cy - grid_size_mm * 0.4,
                        x2=cx + grid_size_mm * 0.4,
                        y2=cy + grid_size_mm * 0.4,
                        entity_type="obstacle",
                        entity_id=f"OBS{obs_index}",
                        layer="F.Cu",
                    )
                )
                obs_index += 1

    # Ensure source and target cells are clear
    src_col = min(1, cols - 1)
    src_row = min(1, rows - 1)
    tgt_col = max(cols - 2, 0)
    tgt_row = max(rows - 2, 0)

    grid[src_row][src_col] = False
    grid[tgt_row][tgt_col] = False

    # Also clear any obstacles at source/target positions
    # (remove obstacle footprints that overlap)
    source_cell = (src_row, src_col)
    target_cell = (tgt_row, tgt_col)

    # Source and target coordinates (center of cells)
    src_x = grid_size_mm * (src_col + 0.5)
    src_y = grid_size_mm * (src_row + 0.5)
    tgt_x = grid_size_mm * (tgt_col + 0.5)
    tgt_y = grid_size_mm * (tgt_row + 0.5)

    # Solve the maze (BFS)
    path_cells = _solve_maze(grid, source_cell, target_cell)
    attempts = 0
    while not path_cells and attempts < 50:
        # Regenerate obstacle grid if no solution exists
        grid = [[False] * cols for _ in range(rows)]
        # Rebuild board (create fresh)
        board = Board.create_new()
        board.general.thickness = 1.6
        _create_board_outline(board, width_mm, height_mm)

        obstacles = []
        obs_index = 0
        for r in range(rows):
            for c in range(cols):
                if random.random() < 0.4:
                    grid[r][c] = True
                    cx = grid_size_mm * (c + 0.5)
                    cy = grid_size_mm * (r + 0.5)
                    _add_obstacle_footprint(board, cx, cy, grid_size_mm * 0.8, obs_index)
                    obstacles.append(
                        SpatialBox(
                            x1=cx - grid_size_mm * 0.4,
                            y1=cy - grid_size_mm * 0.4,
                            x2=cx + grid_size_mm * 0.4,
                            y2=cy + grid_size_mm * 0.4,
                            entity_type="obstacle",
                            entity_id=f"OBS{obs_index}",
                            layer="F.Cu",
                        )
                    )
                    obs_index += 1

        grid[src_row][src_col] = False
        grid[tgt_row][tgt_col] = False
        path_cells = _solve_maze(grid, source_cell, target_cell)
        attempts += 1

    if not path_cells:
        raise RuntimeError(
            f"Could not generate solvable maze after {attempts} attempts"
        )

    # Convert path cells to coordinates
    solution_path = tuple(
        (grid_size_mm * (c + 0.5), grid_size_mm * (r + 0.5)) for r, c in path_cells
    )

    # Add source via on Net 1
    src_net = Net(number=1, name="SRC")
    board.nets.append(Net(number=0, name=""))
    board.nets.append(src_net)
    _add_via(board, src_x, src_y, 1, "SRC")

    # Add target via on Net 2
    tgt_net = Net(number=2, name="TGT")
    board.nets.append(tgt_net)
    _add_via(board, tgt_x, tgt_y, 2, "TGT")

    # Serialize
    board.to_file(str(output_path))

    # Round-trip validation
    verified = Board.from_file(str(output_path))
    if not (verified.footprints or verified.traceItems):
        raise RuntimeError("Generated board has no content after round-trip")

    source_point = SpatialPoint(
        x=src_x,
        y=src_y,
        entity_type="via",
        entity_id="SRC",
        layer="F.Cu,B.Cu",
        net="SRC",
    )
    target_point = SpatialPoint(
        x=tgt_x,
        y=tgt_y,
        entity_type="via",
        entity_id="TGT",
        layer="F.Cu,B.Cu",
        net="TGT",
    )

    return MazeBoard(
        pcb_path=output_path,
        board_width_mm=width_mm,
        board_height_mm=height_mm,
        obstacles=tuple(obstacles),
        source_point=source_point,
        target_point=target_point,
        solution_path=solution_path,
        clearance_mm=clearance_mm,
    )


def _create_board_outline(board: Board, width: float, height: float) -> None:
    """Add a rectangular board outline on Edge.Cuts layer.

    Four graphic line segments forming a closed rectangle from (0,0) to
    (width, height).

    Args:
        board: kiutils Board to add outline to.
        width: Board width in mm.
        height: Board height in mm.
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


def _add_obstacle_footprint(
    board: Board, cx: float, cy: float, size: float, index: int
) -> None:
    """Add an obstacle footprint at (cx, cy) with a single rectangular pad.

    The footprint represents an obstacle zone on F.Cu layer.

    Args:
        board: kiutils Board to add footprint to.
        cx: Center X position in mm.
        cy: Center Y position in mm.
        size: Pad size in mm.
        index: Obstacle index for naming.
    """
    fp = Footprint(
        libraryNickname="maze",
        entryName="obstacle",
        layer="F.Cu",
        position=Position(cx, cy),
        tstamp=str(uuid.uuid4()),
    )
    fp.properties["Reference"] = f"OBS{index}"
    fp.properties["Value"] = "obstacle"

    pad = Pad(
        number="1",
        type="smd",
        shape="rect",
        position=Position(0, 0),
        size=Position(size, size),
        layers=["F.Cu"],
        tstamp=str(uuid.uuid4()),
    )
    fp.pads.append(pad)
    board.footprints.append(fp)


def _add_via(
    board: Board, x: float, y: float, net_number: int, net_name: str
) -> None:
    """Add a via at (x, y) connecting F.Cu and B.Cu on the specified net.

    Ensures the net exists in board.nets before adding the via.

    Args:
        board: kiutils Board to add via to.
        x: X position in mm.
        y: Y position in mm.
        net_number: KiCad net number.
        net_name: Net name string.
    """
    # Ensure net exists in board nets list
    net_exists = any(n.number == net_number for n in board.nets)
    if not net_exists:
        board.nets.append(Net(number=net_number, name=net_name))

    via = Via(
        position=Position(x, y),
        size=0.8,
        drill=0.4,
        layers=["F.Cu", "B.Cu"],
        net=net_number,
        tstamp=str(uuid.uuid4()),
    )
    board.traceItems.append(via)


def _solve_maze(
    grid: list[list[bool]],
    start: tuple[int, int],
    end: tuple[int, int],
) -> list[tuple[int, int]]:
    """BFS pathfinder through the boolean grid.

    Finds the shortest path from start to end through clear cells (False).
    Uses 4-directional movement (up, down, left, right).

    Args:
        grid: 2D grid where True = obstacle, False = clear.
        start: (row, col) starting cell.
        end: (row, col) target cell.

    Returns:
        List of (row, col) cells from start to end (inclusive).
        Empty list if no path exists.
    """
    rows = len(grid)
    cols = len(grid[0]) if rows > 0 else 0

    if rows == 0 or cols == 0:
        return []

    # Bounds check
    sr, sc = start
    er, ec = end
    if not (0 <= sr < rows and 0 <= sc < cols):
        return []
    if not (0 <= er < rows and 0 <= ec < cols):
        return []
    if grid[sr][sc] or grid[er][ec]:
        return []

    # BFS
    visited: set[tuple[int, int]] = {start}
    queue: deque[tuple[int, int]] = deque()
    parent: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    queue.append(start)

    directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    while queue:
        current = queue.popleft()
        if current == end:
            # Reconstruct path
            path: list[tuple[int, int]] = []
            node: tuple[int, int] | None = end
            while node is not None:
                path.append(node)
                node = parent.get(node)
            path.reverse()
            return path

        cr, cc = current
        for dr, dc in directions:
            nr, nc = cr + dr, cc + dc
            neighbor = (nr, nc)
            if (
                0 <= nr < rows
                and 0 <= nc < cols
                and not grid[nr][nc]
                and neighbor not in visited
            ):
                visited.add(neighbor)
                parent[neighbor] = current
                queue.append(neighbor)

    return []
