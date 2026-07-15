"""Tests for procedural maze-routing PCB generator (VP-04).

Validates:
  - Maze generation produces valid KiCad PCB files
  - Round-trip through kiutils works correctly
  - Obstacles, source, target, and solution path are present
  - Deterministic generation with seed
  - Different seeds produce different boards
"""

from pathlib import Path

import pytest
from kiutils.board import Board

from volta.spatial.maze_generator import MazeBoard, generate_maze_board
from volta.spatial.primitives import SpatialBox, SpatialPoint


class TestMazeGeneration:
    """Tests for generate_maze_board function."""

    def test_generate_maze_creates_valid_pcb(self, tmp_path: Path) -> None:
        """Generated maze creates a valid KiCad PCB that parses with kiutils."""
        output = tmp_path / "maze.kicad_pcb"
        maze = generate_maze_board(output, seed=42)

        assert output.exists()
        board = Board.from_file(str(output))
        assert board is not None

    def test_maze_board_has_obstacles(self, tmp_path: Path) -> None:
        """MazeBoard contains non-empty obstacles tuple."""
        output = tmp_path / "maze.kicad_pcb"
        maze = generate_maze_board(output, seed=42)

        assert isinstance(maze.obstacles, tuple)
        assert len(maze.obstacles) > 0
        assert all(isinstance(obs, SpatialBox) for obs in maze.obstacles)

    def test_maze_has_source_and_target(self, tmp_path: Path) -> None:
        """Maze has distinct source and target SpatialPoints."""
        output = tmp_path / "maze.kicad_pcb"
        maze = generate_maze_board(output, seed=42)

        assert isinstance(maze.source_point, SpatialPoint)
        assert isinstance(maze.target_point, SpatialPoint)
        assert maze.source_point.entity_type == "via"
        assert maze.target_point.entity_type == "via"
        # Source and target should be at different coordinates
        assert (maze.source_point.x, maze.source_point.y) != (
            maze.target_point.x,
            maze.target_point.y,
        )

    def test_maze_has_solution_path(self, tmp_path: Path) -> None:
        """Maze has a non-empty solution path from source to target."""
        output = tmp_path / "maze.kicad_pcb"
        maze = generate_maze_board(output, seed=42)

        assert isinstance(maze.solution_path, tuple)
        assert len(maze.solution_path) >= 2  # At least source and target

        # Solution path starts near source
        first = maze.solution_path[0]
        assert abs(first[0] - maze.source_point.x) < 0.01
        assert abs(first[1] - maze.source_point.y) < 0.01

        # Solution path ends near target
        last = maze.solution_path[-1]
        assert abs(last[0] - maze.target_point.x) < 0.01
        assert abs(last[1] - maze.target_point.y) < 0.01

    def test_deterministic_with_seed(self, tmp_path: Path) -> None:
        """Same seed produces identical obstacle positions."""
        out1 = tmp_path / "maze1.kicad_pcb"
        out2 = tmp_path / "maze2.kicad_pcb"

        maze1 = generate_maze_board(out1, seed=123)
        maze2 = generate_maze_board(out2, seed=123)

        assert len(maze1.obstacles) == len(maze2.obstacles)
        for o1, o2 in zip(maze1.obstacles, maze2.obstacles):
            assert o1.x1 == o2.x1
            assert o1.y1 == o2.y1
            assert o1.x2 == o2.x2
            assert o1.y2 == o2.y2

    def test_different_seeds_different_boards(self, tmp_path: Path) -> None:
        """Different seeds produce boards with different obstacle configurations."""
        out1 = tmp_path / "maze1.kicad_pcb"
        out2 = tmp_path / "maze2.kicad_pcb"

        maze1 = generate_maze_board(out1, seed=1)
        maze2 = generate_maze_board(out2, seed=2)

        # Different seeds should produce different obstacle counts or positions
        same = maze1.obstacles == maze2.obstacles
        assert not same, "Different seeds produced identical boards"

    def test_round_trip_fidelity(self, tmp_path: Path) -> None:
        """Generated PCB round-trips: write -> parse -> write -> parse succeeds."""
        output = tmp_path / "maze.kicad_pcb"
        generate_maze_board(output, seed=42)

        # First parse
        board1 = Board.from_file(str(output))

        # Write to second file
        output2 = tmp_path / "maze2.kicad_pcb"
        board1.to_file(str(output2))

        # Second parse
        board2 = Board.from_file(str(output2))

        # Both parses should have same content counts
        assert len(board1.footprints) == len(board2.footprints)
        assert len(board1.traceItems) == len(board2.traceItems)
        assert len(board1.graphicItems) == len(board2.graphicItems)


class TestMazeValidation:
    """Tests for input validation."""

    def test_invalid_suffix_raises(self, tmp_path: Path) -> None:
        """Non-.kicad_pcb suffix raises ValueError."""
        with pytest.raises(ValueError, match="Expected .kicad_pcb"):
            generate_maze_board(tmp_path / "maze.txt")

    def test_width_too_large_raises(self, tmp_path: Path) -> None:
        """Board width exceeding max raises ValueError."""
        with pytest.raises(ValueError, match="width_mm"):
            generate_maze_board(tmp_path / "maze.kicad_pcb", width_mm=1000)

    def test_grid_too_small_raises(self, tmp_path: Path) -> None:
        """Grid too small (< 3x3) raises ValueError."""
        with pytest.raises(ValueError, match="Grid too small"):
            generate_maze_board(
                tmp_path / "maze.kicad_pcb", width_mm=2, height_mm=2, grid_size_mm=5
            )
