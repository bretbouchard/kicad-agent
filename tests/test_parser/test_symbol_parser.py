"""Tests for symbol library (.kicad_sym) parser -- FND-03.

Verifies parse_symbol_lib returns a ParseResult with correct kiutils type,
non-empty symbols list, and proper error handling.
"""

from pathlib import Path

import pytest
from kiutils.symbol import SymbolLib

from volta.parser.symbol_parser import parse_symbol_lib, ParseResult


class TestParseSymbolLib:
    """FND-03: Parse .kicad_sym files into structured AST."""

    def test_parse_symbol_lib_returns_parse_result(self, sample_sym_lib: Path) -> None:
        """parse_symbol_lib returns ParseResult with SymbolLib object."""
        result = parse_symbol_lib(sample_sym_lib)

        assert isinstance(result, ParseResult)
        assert isinstance(result.kiutils_obj, SymbolLib)
        assert isinstance(result.raw_content, str)
        assert len(result.raw_content) > 0
        assert result.file_type == "symbol_lib"
        assert result.file_path == sample_sym_lib

    def test_parse_symbol_lib_has_symbols(self, sample_sym_lib: Path) -> None:
        """Device symbol library has symbols (non-empty list)."""
        result = parse_symbol_lib(sample_sym_lib)

        assert isinstance(result.kiutils_obj.symbols, list)
        assert len(result.kiutils_obj.symbols) > 0

    def test_parse_symbol_lib_file_not_found(self) -> None:
        """FileNotFoundError raised for nonexistent path."""
        with pytest.raises(FileNotFoundError, match="Symbol library file not found"):
            parse_symbol_lib(Path("/nonexistent/file.kicad_sym"))

    def test_parse_symbol_lib_wrong_extension(self, tmp_path: Path) -> None:
        """ValueError raised for wrong file extension."""
        wrong_file = tmp_path / "test.kicad_pcb"
        wrong_file.write_text("(kicad_pcb)")

        with pytest.raises(ValueError, match="Expected .kicad_sym file"):
            parse_symbol_lib(wrong_file)
