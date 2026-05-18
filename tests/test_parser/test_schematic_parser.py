"""Tests for schematic (.kicad_sch) parser -- FND-01.

Verifies parse_schematic returns a ParseResult with correct kiutils type,
non-empty raw content, correct file_type, and proper error handling.
"""

from pathlib import Path

import pytest
from kiutils.schematic import Schematic

from kicad_agent.parser.schematic_parser import parse_schematic, ParseResult


class TestParseSchematic:
    """FND-01: Parse .kicad_sch files into structured AST."""

    def test_parse_schematic_returns_parse_result(self, arduino_mega_sch: Path) -> None:
        """parse_schematic returns ParseResult with correct types and fields."""
        result = parse_schematic(arduino_mega_sch)

        assert isinstance(result, ParseResult)
        assert isinstance(result.kiutils_obj, Schematic)
        assert isinstance(result.raw_content, str)
        assert len(result.raw_content) > 0
        assert result.file_type == "schematic"
        assert result.file_path == arduino_mega_sch

    def test_parse_schematic_has_components(self, arduino_mega_sch: Path) -> None:
        """Arduino_Mega schematic has components (schematicSymbols non-empty)."""
        result = parse_schematic(arduino_mega_sch)

        assert isinstance(result.kiutils_obj.schematicSymbols, list)
        assert len(result.kiutils_obj.schematicSymbols) > 0

    def test_parse_schematic_has_uuid(self, arduino_mega_sch: Path) -> None:
        """Arduino_Mega schematic has a non-empty uuid string."""
        result = parse_schematic(arduino_mega_sch)

        assert isinstance(result.kiutils_obj.uuid, str)
        assert len(result.kiutils_obj.uuid) > 0

    def test_parse_schematic_file_not_found(self) -> None:
        """FileNotFoundError raised for nonexistent path."""
        with pytest.raises(FileNotFoundError, match="Schematic file not found"):
            parse_schematic(Path("/nonexistent/file.kicad_sch"))

    def test_parse_schematic_wrong_extension(self, tmp_path: Path) -> None:
        """ValueError raised for wrong file extension."""
        wrong_file = tmp_path / "test.kicad_pcb"
        wrong_file.write_text("(kicad_pcb)")

        with pytest.raises(ValueError, match="Expected .kicad_sch file"):
            parse_schematic(wrong_file)
