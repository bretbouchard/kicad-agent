"""Tests for PCB (.kicad_pcb) parser -- FND-02.

Verifies parse_pcb returns a ParseResult with correct kiutils type,
non-empty raw content (critical for UUID preservation), and proper error handling.
"""

from pathlib import Path

import pytest
from kiutils.board import Board

from kicad_agent.parser.pcb_parser import parse_pcb, ParseResult


class TestParsePcb:
    """FND-02: Parse .kicad_pcb files into structured AST."""

    def test_parse_pcb_returns_parse_result(self, arduino_mega_pcb: Path) -> None:
        """parse_pcb returns ParseResult with Board object, raw content preserved."""
        result = parse_pcb(arduino_mega_pcb)

        assert isinstance(result, ParseResult)
        assert isinstance(result.kiutils_obj, Board)
        assert isinstance(result.raw_content, str)
        assert len(result.raw_content) > 0
        assert result.file_type == "pcb"
        assert result.file_path == arduino_mega_pcb

    def test_parse_pcb_has_footprints(self, arduino_mega_pcb: Path) -> None:
        """Arduino_Mega PCB has footprints (non-empty list)."""
        result = parse_pcb(arduino_mega_pcb)

        assert isinstance(result.kiutils_obj.footprints, list)
        assert len(result.kiutils_obj.footprints) > 0

    def test_parse_pcb_file_not_found(self) -> None:
        """FileNotFoundError raised for nonexistent path."""
        with pytest.raises(FileNotFoundError, match="PCB file not found"):
            parse_pcb(Path("/nonexistent/file.kicad_pcb"))

    def test_parse_pcb_wrong_extension(self, tmp_path: Path) -> None:
        """ValueError raised for wrong file extension."""
        wrong_file = tmp_path / "test.kicad_sch"
        wrong_file.write_text("(kicad_sch)")

        with pytest.raises(ValueError, match="Expected .kicad_pcb file"):
            parse_pcb(wrong_file)
