"""Tests for footprint (.kicad_mod) parser -- FND-04.

Verifies parse_footprint returns a ParseResult with correct kiutils type,
raw content preserved (critical for UUID preservation), and proper error handling.
"""

from pathlib import Path

import pytest
from kiutils.footprint import Footprint

from kicad_agent.parser.footprint_parser import parse_footprint, ParseResult


class TestParseFootprint:
    """FND-04: Parse .kicad_mod files into structured AST."""

    def test_parse_footprint_returns_parse_result(
        self, arduino_mounting_hole_mod: Path
    ) -> None:
        """parse_footprint returns ParseResult with Footprint object, raw content preserved."""
        result = parse_footprint(arduino_mounting_hole_mod)

        assert isinstance(result, ParseResult)
        assert isinstance(result.kiutils_obj, Footprint)
        assert isinstance(result.raw_content, str)
        assert len(result.raw_content) > 0
        assert result.file_type == "footprint"
        assert result.file_path == arduino_mounting_hole_mod

    def test_parse_footprint_has_pads(self, arduino_mounting_hole_mod: Path) -> None:
        """Mounting hole footprint has pads attribute (may be empty list)."""
        result = parse_footprint(arduino_mounting_hole_mod)

        assert isinstance(result.kiutils_obj.pads, list)

    def test_parse_footprint_file_not_found(self) -> None:
        """FileNotFoundError raised for nonexistent path."""
        with pytest.raises(FileNotFoundError, match="Footprint file not found"):
            parse_footprint(Path("/nonexistent/file.kicad_mod"))

    def test_parse_footprint_wrong_extension(self, tmp_path: Path) -> None:
        """ValueError raised for wrong file extension."""
        wrong_file = tmp_path / "test.kicad_sch"
        wrong_file.write_text("(kicad_sch)")

        with pytest.raises(ValueError, match="Expected .kicad_mod file"):
            parse_footprint(wrong_file)
