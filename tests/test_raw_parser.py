"""Tests for parser modules: raw_parser, schematic parser, PCB parser helpers."""

import tempfile
from pathlib import Path

import pytest

from kicad_agent.parser.raw_parser import (
    _pre_scan_depth,
    parse_raw_sexp,
    parse_raw_sexp_file,
)


class TestPreScanDepth:
    """Tests for depth pre-scan function."""

    def test_empty_content(self):
        """Empty content returns 0."""
        assert _pre_scan_depth("") == 0

    def test_single_paren(self):
        """Single paren pair returns 1."""
        assert _pre_scan_depth("(data)") == 1

    def test_nested(self):
        """Nested parens return correct depth."""
        assert _pre_scan_depth("(a (b (c)))") == 3

    def test_string_ignored(self):
        """Parens inside strings are not counted."""
        result = _pre_scan_depth('(data "(nested)")')
        assert result == 1

    def test_max_depth_exceeded(self):
        """Raises ValueError when max depth exceeded."""
        deep = "(" * 201 + "data" + ")" * 201
        with pytest.raises(ValueError):
            _pre_scan_depth(deep, max_depth=200)

    def test_escape_char(self):
        """Escaped quote in string handled correctly."""
        result = _pre_scan_depth(r'(data "escaped \" quote")')
        assert result == 1


class TestParseRawSexp:
    """Tests for parse_raw_sexp function."""

    def test_empty_raises(self):
        """Empty content raises ValueError."""
        with pytest.raises(ValueError):
            parse_raw_sexp("")

    def test_simple_list(self):
        """Simple S-expression parses to list."""
        result = parse_raw_sexp("(a b c)")
        assert isinstance(result, list)
        assert len(result) == 4  # [Symbol(a), Symbol(b), Symbol(c)]

    def test_nested(self):
        """Nested S-expression parses correctly."""
        result = parse_raw_sexp("(a (b c) d)")
        assert isinstance(result, list)
        assert len(result) == 4

    def test_string_values(self):
        """String values preserved."""
        result = parse_raw_sexp('(a "hello world")')
        assert result[1] == "hello world"

    def test_size_limit(self):
        """Content over 50MB raises ValueError."""
        huge = "(data)" * (12 * 1024 * 1024)
        with pytest.raises(ValueError):
            parse_raw_sexp(huge)


class TestParseRawSexpFile:
    """Tests for parse_raw_sexp_file function."""

    def test_nonexistent_raises(self):
        """Nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            parse_raw_sexp_file(Path("/nonexistent/file.sexp"))

    def test_valid_file(self):
        """Valid file parses correctly."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sexp", delete=False) as f:
            f.write("(a b c)")
            path = Path(f.name)
        try:
            result = parse_raw_sexp_file(path)
            assert isinstance(result, list)
        finally:
            path.unlink(missing_ok=True)
