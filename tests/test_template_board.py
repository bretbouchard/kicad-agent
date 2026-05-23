"""Tests for template board generator.

Covers:
- Empty board generation (outline only)
- Board with components
- Round-trip validation (write -> re-parse)
- Board dimensions verification
- Auto-placement within board bounds
"""

import tempfile
from pathlib import Path

from kicad_agent.generation.intent import BoardSpec, ComponentSpec, NetSpec, PositionSpec
from kicad_agent.generation.template_board import generate_board


class TestGenerateBoard:
    """Tests for generate_board function."""

    def test_generate_empty_board(self, tmp_path):
        """Generate board with just outline (no components), verify file parses."""
        output = tmp_path / "empty.kicad_pcb"
        spec = BoardSpec(width_mm=50.0, height_mm=50.0)

        result = generate_board(output, spec)

        assert result.pcb_path == output
        assert result.component_count == 0
        assert result.net_count == 0
        assert output.exists()

        # Verify file content is valid by re-parsing
        from kiutils.board import Board

        board = Board.from_file(str(output))
        assert board.general.thickness == 1.6
        # Should have outline graphic items
        assert len(board.graphicItems) >= 4  # 4 outline segments

    def test_generate_board_with_components(self, tmp_path):
        """Generate board with 5 components, verify component_count."""
        output = tmp_path / "with_comps.kicad_pcb"
        spec = BoardSpec(width_mm=100.0, height_mm=80.0)
        components = [
            ComponentSpec(
                library_id="Device:R_Small_US",
                reference=f"R{i}",
                value=f"{v}k",
            )
            for i, v in enumerate([1, 2, 3, 4, 5], start=1)
        ]

        result = generate_board(output, spec, components=components)

        assert result.component_count == 5
        assert result.pcb_path == output

        from kiutils.board import Board

        board = Board.from_file(str(output))
        assert len(board.footprints) == 5

    def test_generate_board_round_trip(self, tmp_path):
        """Generate board, re-parse via existing parser, verify success."""
        output = tmp_path / "roundtrip.kicad_pcb"
        spec = BoardSpec(width_mm=60.0, height_mm=40.0)
        components = [
            ComponentSpec(
                library_id="Device:R_Small_US",
                reference="R1",
                value="10k",
            ),
        ]
        nets = [NetSpec(name="VCC", pins=["R1.1"])]

        result = generate_board(output, spec, components=components, nets=nets)

        assert result.component_count == 1
        assert result.net_count == 1

        # Re-parse through the project's own parser for round-trip validation
        from kicad_agent.parser import parse_pcb

        parse_result = parse_pcb(output)
        assert parse_result is not None
        assert parse_result.raw_content is not None
        assert "R1" in parse_result.raw_content

    def test_generate_board_dimensions(self, tmp_path):
        """Generate 100x80mm board, verify outline bounds."""
        output = tmp_path / "dim_test.kicad_pcb"
        spec = BoardSpec(width_mm=100.0, height_mm=80.0)

        generate_board(output, spec)

        from kiutils.board import Board

        board = Board.from_file(str(output))

        # Extract outline segments and verify dimensions
        outline_lines = [
            item for item in board.graphicItems if hasattr(item, "layer") and item.layer == "Edge.Cuts"
        ]
        assert len(outline_lines) == 4

        # Check that max coordinate is (100, 80)
        all_x = []
        all_y = []
        for line in outline_lines:
            all_x.extend([line.start.X, line.end.X])
            all_y.extend([line.start.Y, line.end.Y])

        assert max(all_x) == 100.0
        assert max(all_y) == 80.0
        assert min(all_x) == 0.0
        assert min(all_y) == 0.0

    def test_generate_board_auto_placement(self, tmp_path):
        """Generate with 10 components (no positions), verify all placed within bounds."""
        output = tmp_path / "auto_place.kicad_pcb"
        spec = BoardSpec(width_mm=100.0, height_mm=80.0)
        components = [
            ComponentSpec(
                library_id="Device:R_Small_US",
                reference=f"R{i}",
                value="1k",
            )
            for i in range(1, 11)
        ]

        result = generate_board(output, spec, components=components)
        assert result.component_count == 10

        from kiutils.board import Board

        board = Board.from_file(str(output))
        assert len(board.footprints) == 10

        # Verify all footprints are within board bounds
        for fp in board.footprints:
            x = fp.position.X
            y = fp.position.Y
            # Components should be within board area (with margin)
            assert 0 <= x <= 100.0, f"Component at x={x} is outside board width"
            assert 0 <= y <= 80.0, f"Component at y={y} is outside board height"

    def test_generate_board_invalid_suffix(self, tmp_path):
        """generate_board rejects non-.kicad_pcb suffix."""
        import pytest

        output = tmp_path / "wrong.txt"
        spec = BoardSpec()

        with pytest.raises(ValueError, match="Expected .kicad_pcb"):
            generate_board(output, spec)
