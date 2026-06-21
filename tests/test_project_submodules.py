"""Tests for project sub-modules: lib_table, design_rules_cmd, project_file."""

from pathlib import Path
import tempfile

import pytest

from kicad_agent.project.lib_table import LibEntry, LibTable, parse_lib_table, serialize_lib_table
from kicad_agent.project.design_rules import (
    DesignRule as ProjectDR,
    DesignRulesFile,
    NetClassDef,
    parse_design_rules,
    serialize_design_rules,
)
from kicad_agent.project.project_file import parse_project_file


class TestLibEntryDetailed:
    """Detailed tests for LibEntry."""

    def test_to_sexp(self):
        """LibEntry serializes to S-expression."""
        entry = LibEntry(name="Device", type="KiCad", uri="${KIPRJMOD}/Device.kicad_sym")
        sexp = entry.to_sexp()
        assert "Device" in sexp
        assert "KiCad" in sexp

    def test_to_sexp_with_descr(self):
        """LibEntry with description serializes correctly."""
        entry = LibEntry(
            name="Device",
            type="KiCad",
            uri="${KIPRJMOD}/Device.kicad_sym",
            descr="Standard devices",
        )
        sexp = entry.to_sexp()
        assert "Standard devices" in sexp


class TestLibTableDetailed:
    """Detailed tests for LibTable."""

    def test_add_entry(self):
        """LibTable.add appends entry."""
        table = LibTable(table_type="sym_lib_table")
        entry = LibEntry(name="Device", type="KiCad", uri="/tmp/Device.kicad_sym")
        table.add(entry)
        assert len(table.entries) == 1
        assert table.entries[0].name == "Device"

    def test_duplicate_name_raises(self):
        """LibTable.add raises on duplicate name."""
        table = LibTable(table_type="sym_lib_table")
        e1 = LibEntry(name="Device", type="KiCad", uri="/tmp/1.sym")
        e2 = LibEntry(name="Device", type="KiCad", uri="/tmp/2.sym")
        table.add(e1)
        with pytest.raises(ValueError):
            table.add(e2)


class TestNetClassDef:
    """Tests for NetClassDef."""

    def test_creation(self):
        """NetClassDef can be created."""
        nc = NetClassDef(name="Default", clearance=0.2, track_width=0.25)
        assert nc.name == "Default"
        assert nc.clearance == 0.2


class TestProjectDesignRule:
    """Tests for project-level DesignRule."""

    def test_creation(self):
        """DesignRule can be created."""
        rule = ProjectDR(
            name="HV_clearance",
            constraint_type="clearance",
            constraint_values={"clearance": "0.5"},
        )
        assert rule.name == "HV_clearance"

    def test_to_sexp(self):
        """DesignRule serializes to S-expression."""
        rule = ProjectDR(
            name="HV_clearance",
            constraint_type="clearance",
            constraint_values={"clearance": "0.5"},
        )
        sexp = rule.to_sexp()
        assert "HV_clearance" in sexp
