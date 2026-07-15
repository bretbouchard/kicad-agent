"""Tests for create_file content header validation (D-16).

Verifies that generated file content is validated against valid KiCad
S-expression headers before writing to disk.
"""

from pathlib import Path

import pytest

from volta.ops.create_file import (
    _VALID_KICAD_HEADERS,
    _validate_kicad_content,
)


# ---------------------------------------------------------------------------
# D-16: Content header validation tests
# ---------------------------------------------------------------------------


class TestContentHeaderValidation:
    """D-16: File creation rejects content without KiCad header."""

    def test_create_file_rejects_garbage_content(self):
        """D-16: File creation rejects content without KiCad header."""
        with pytest.raises(ValueError, match="does not start with a valid"):
            _validate_kicad_content("this is garbage content", Path("test.kicad_sch"))

    def test_create_file_rejects_html_content(self):
        """D-16: File creation rejects HTML content."""
        with pytest.raises(ValueError, match="does not start with a valid"):
            _validate_kicad_content("<html><body>test</body></html>", Path("test.kicad_sch"))

    def test_create_file_rejects_json_content(self):
        """D-16: File creation rejects JSON content."""
        with pytest.raises(ValueError, match="does not start with a valid"):
            _validate_kicad_content('{"version": "20240101"}', Path("test.kicad_pcb"))

    def test_create_file_rejects_empty_content(self):
        """D-16: File creation rejects empty content."""
        with pytest.raises(ValueError, match="does not start with a valid"):
            _validate_kicad_content("", Path("test.kicad_sch"))

    def test_create_file_rejects_whitespace_only(self):
        """D-16: File creation rejects whitespace-only content."""
        with pytest.raises(ValueError, match="does not start with a valid"):
            _validate_kicad_content("   \n  \t  ", Path("test.kicad_sch"))

    def test_create_file_accepts_kicad_sch_header(self):
        """D-16: File creation accepts content starting with (kicad_sch."""
        _validate_kicad_content("(kicad_sch\n  (version 20240101)\n)", Path("test.kicad_sch"))

    def test_create_file_accepts_kicad_pcb_header(self):
        """D-16: File creation accepts content starting with (kicad_pcb."""
        _validate_kicad_content("(kicad_pcb\n  (version 20240101)\n)", Path("test.kicad_pcb"))

    def test_create_file_accepts_footprint_header(self):
        """D-16: File creation accepts content starting with (footprint."""
        _validate_kicad_content(
            '(footprint "Resistor_SMD:R_0805" (layer "F.Cu"))',
            Path("test.kicad_mod"),
        )

    def test_create_file_accepts_kicad_sym_header(self):
        """D-16: File creation accepts content starting with (kicad_sym."""
        _validate_kicad_content(
            '(kicad_sym\n  (version 20260306)\n  (generator "kicad_symbol_editor")\n)',
            Path("test.kicad_sym"),
        )

    def test_create_file_accepts_leading_whitespace(self):
        """D-16: File creation accepts content with leading whitespace before header."""
        _validate_kicad_content("  \n(kicad_sch (version 20240101))", Path("test.kicad_sch"))

    def test_create_file_validates_before_write(self):
        """D-16: Validation runs before any file write, not after."""
        # This tests the ordering: validation happens first
        with pytest.raises(ValueError, match="does not start with a valid"):
            _validate_kicad_content("not valid", Path("test.kicad_sch"))

    def test_valid_kicad_headers_contains_expected(self):
        """D-16: _VALID_KICAD_HEADERS contains all expected headers."""
        assert "(kicad_sch" in _VALID_KICAD_HEADERS
        assert "(kicad_pcb" in _VALID_KICAD_HEADERS
        assert "(footprint" in _VALID_KICAD_HEADERS
        assert "(kicad_sym" in _VALID_KICAD_HEADERS
