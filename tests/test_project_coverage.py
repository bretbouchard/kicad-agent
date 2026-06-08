"""Tests for project module: lib_table, design_rules, project_file parsing."""

from pathlib import Path

import pytest

from kicad_agent.project import (
    DesignRule as ProjectDesignRule,
    DesignRulesFile,
    LibEntry,
    LibTable,
    NetClassDef,
    ProjectFile,
    get_project_settings,
    parse_design_rules,
    parse_lib_table,
    parse_project_file,
    serialize_design_rules,
    serialize_lib_table,
)


class TestLibEntry:
    """Tests for LibEntry dataclass."""

    def test_creation_minimal(self):
        """LibEntry with name, type, uri creates valid entry."""
        entry = LibEntry(name="Device", type="KiCad", uri="${KIPRJMOD}/Device.kicad_sym")
        assert entry.name == "Device"
        assert entry.type == "KiCad"
        assert entry.options == ""
        assert entry.descr == ""

    def test_creation_full(self):
        """LibEntry with all fields."""
        entry = LibEntry(
            name="Device",
            type="KiCad",
            uri="${KIPRJMOD}/Device.kicad_sym",
            options="disabled",
            descr="Standard devices library",
        )
        assert entry.options == "disabled"
        assert entry.descr == "Standard devices library"

    def test_frozen(self):
        """LibEntry is frozen."""
        entry = LibEntry(name="X", type="KiCad", uri="/tmp/x.sym")
        with pytest.raises(AttributeError):
            entry.name = "Y"


class TestLibTable:
    """Tests for LibTable parsing and serialization."""

    def test_empty_table_serialization(self):
        """Empty LibTable serializes to valid S-expression."""
        import tempfile
        table = LibTable(table_type="sym_lib_table", entries=[])
        with tempfile.NamedTemporaryFile(suffix=".lib-table", mode="w", delete=False) as f:
            path = Path(f.name)
        try:
            serialize_lib_table(table, path)
            content = path.read_text()
            assert "sym_lib_table" in content
        finally:
            path.unlink(missing_ok=True)

    def test_table_with_entries(self):
        """LibTable with entries serializes correctly."""
        import tempfile
        entries = [
            LibEntry(name="Device", type="KiCad", uri="${KIPRJMOD}/Device.kicad_sym"),
            LibEntry(name="power", type="KiCad", uri="${KIPRJMOD}/power.kicad_sym"),
        ]
        table = LibTable(table_type="sym_lib_table", entries=entries)
        with tempfile.NamedTemporaryFile(suffix=".lib-table", mode="w", delete=False) as f:
            path = Path(f.name)
        try:
            serialize_lib_table(table, path)
            content = path.read_text()
            assert "Device" in content
            assert "power" in content
        finally:
            path.unlink(missing_ok=True)

    def test_parse_lib_table_nonexistent(self):
        """parse_lib_table raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            parse_lib_table(Path("/nonexistent/sym-lib-table"))


class TestDesignRulesFile:
    """Tests for design rules parsing."""

    def test_parse_design_rules_nonexistent(self):
        """parse_design_rules raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            parse_design_rules(Path("/nonexistent/board.kicad_dru"))

    def test_serialize_empty_rules(self):
        """serialize_design_rules produces output for empty rules."""
        import tempfile
        rules = DesignRulesFile()
        with tempfile.NamedTemporaryFile(suffix=".kicad_dru", mode="w", delete=False) as f:
            path = Path(f.name)
        try:
            serialize_design_rules(rules, path)
            content = path.read_text()
            assert isinstance(content, str)
            assert len(content) > 0
        finally:
            path.unlink(missing_ok=True)


class TestProjectFile:
    """Tests for project file parsing."""

    def test_parse_project_file_nonexistent(self):
        """parse_project_file raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            parse_project_file(Path("/nonexistent/board.kicad_pro"))

    def test_get_project_settings_nonexistent(self):
        """get_project_settings raises for nonexistent directory."""
        with pytest.raises((FileNotFoundError, ValueError)):
            get_project_settings(Path("/nonexistent/board.kicad_pro"))


class TestProjectImports:
    """Verify all project module exports."""

    def test_all_exports_importable(self):
        """All __all__ exports can be imported."""
        from kicad_agent import project
        for name in project.__all__:
            assert hasattr(project, name), f"Missing export: {name}"
