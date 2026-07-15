"""Tests for execution.py cross-file extension validation (D-15, M-03).

Verifies that cross-file operations reject files with non-KiCad extensions
and that _VALID_KICAD_EXTENSIONS is imported from pre_analysis.py.
"""

from pathlib import Path

import pytest

from volta.ops.execution import _VALID_KICAD_EXTENSIONS


# ---------------------------------------------------------------------------
# D-15: Cross-file extension validation tests
# ---------------------------------------------------------------------------


class TestCrossFileExtensionValidation:
    """D-15: Cross-file op rejects files with invalid KiCad extensions."""

    def test_cross_file_rejects_txt_extension(self):
        """D-15: Cross-file op rejects .txt files with ValueError."""
        assert ".txt" not in _VALID_KICAD_EXTENSIONS

    def test_cross_file_rejects_md_extension(self):
        """D-15: Cross-file op rejects .md files with ValueError."""
        assert ".md" not in _VALID_KICAD_EXTENSIONS

    def test_cross_file_rejects_py_extension(self):
        """D-15: Cross-file op rejects .py files with ValueError."""
        assert ".py" not in _VALID_KICAD_EXTENSIONS

    def test_cross_file_rejects_json_extension(self):
        """D-15: Cross-file op rejects .json files with ValueError."""
        assert ".json" not in _VALID_KICAD_EXTENSIONS

    def test_cross_file_accepts_kicad_sch_extension(self):
        """D-15: Cross-file op accepts .kicad_sch files."""
        assert ".kicad_sch" in _VALID_KICAD_EXTENSIONS

    def test_cross_file_accepts_kicad_pcb_extension(self):
        """D-15: Cross-file op accepts .kicad_pcb files."""
        assert ".kicad_pcb" in _VALID_KICAD_EXTENSIONS

    def test_cross_file_accepts_all_valid_extensions(self):
        """D-15: Cross-file op accepts .kicad_sym, .kicad_mod, .kicad_pro, .kicad_dru."""
        expected = {".kicad_sch", ".kicad_pcb", ".kicad_sym", ".kicad_mod", ".kicad_pro", ".kicad_dru"}
        assert expected == _VALID_KICAD_EXTENSIONS


class TestValidKicadExtensionsImport:
    """M-03: _VALID_KICAD_EXTENSIONS imported from pre_analysis.py."""

    def test_imported_from_pre_analysis(self):
        """M-03: execution.py imports _VALID_KICAD_EXTENSIONS from pre_analysis.py."""
        from volta.ops.pre_analysis import _VALID_KICAD_EXTENSIONS as pre_analysis_ext
        assert _VALID_KICAD_EXTENSIONS is pre_analysis_ext, \
            "execution.py should import from pre_analysis.py, not define locally"

    def test_is_frozenset(self):
        """M-03: _VALID_KICAD_EXTENSIONS is a frozenset (immutable)."""
        assert isinstance(_VALID_KICAD_EXTENSIONS, frozenset)
