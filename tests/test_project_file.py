"""Unit tests for project file parsing and project-level operations.

Tests .kicad_pro parsing, operation schema for library/net class/rule operations,
and executor dispatch for project file types.
"""

import json
from pathlib import Path

import pytest

from kicad_agent.ops.executor import OperationExecutor
from kicad_agent.ops.schema import (
    AddDesignRuleOp,
    AddLibEntryOp,
    AddNetClassOp,
    Operation,
    RemoveLibEntryOp,
)
from kicad_agent.project.project_file import (
    ProjectFile,
    get_project_settings,
    parse_project_file,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

PRO_CONTENT = json.dumps({
    "version": "20240517",
    "general": {
        "links": 0,
        "no_connects": 0,
    },
    "pcbnew": {
        "last_paths": {},
        "page_layout_descr_file": "",
    },
    "schematic": {
        "legacy_lib_dir": "",
        "legacy_lib_list": [],
    },
}, indent=2)

SYM_LIB_TABLE_CONTENT = """(sym_lib_table
  (version 7)
  (lib (name "Device")(type "KiCad")(uri "${KICAD8_SYMBOL_DIR}/Device.kicad_sym")(options "")(descr "Device symbols"))
  (lib (name "power")(type "KiCad")(uri "${KICAD8_SYMBOL_DIR}/power.kicad_sym")(options "")(descr "Power symbols"))
)"""

FP_LIB_TABLE_CONTENT = """(fp_lib_table
  (version 7)
  (lib (name "tile")(type "KiCad")(uri "${KIPRJMOD}/tile.pretty")(options "")(descr "Tile footprints"))
)"""

DRU_CONTENT = """(version 20240517)
(net_class "Default" ""
  (clearance 0.2)
  (trace_width 0.25)
  (via_dia 0.8)
  (via_drill 0.4)
)
"""


@pytest.fixture
def pro_file(tmp_path: Path) -> Path:
    """Create a temporary .kicad_pro file."""
    path = tmp_path / "board.kicad_pro"
    path.write_text(PRO_CONTENT, encoding="utf-8")
    return path


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a temporary project directory with all project files."""
    (tmp_path / "board.kicad_pro").write_text(PRO_CONTENT, encoding="utf-8")
    (tmp_path / "sym-lib-table").write_text(SYM_LIB_TABLE_CONTENT, encoding="utf-8")
    (tmp_path / "fp-lib-table").write_text(FP_LIB_TABLE_CONTENT, encoding="utf-8")
    (tmp_path / "board.kicad_dru").write_text(DRU_CONTENT, encoding="utf-8")
    return tmp_path


@pytest.fixture
def sym_lib_file(tmp_path: Path) -> Path:
    """Create a temporary sym-lib-table file."""
    path = tmp_path / "sym-lib-table"
    path.write_text(SYM_LIB_TABLE_CONTENT, encoding="utf-8")
    return path


@pytest.fixture
def fp_lib_file(tmp_path: Path) -> Path:
    """Create a temporary fp-lib-table file."""
    path = tmp_path / "fp-lib-table"
    path.write_text(FP_LIB_TABLE_CONTENT, encoding="utf-8")
    return path


@pytest.fixture
def dru_file(tmp_path: Path) -> Path:
    """Create a temporary .kicad_dru file."""
    path = tmp_path / "board.kicad_dru"
    path.write_text(DRU_CONTENT, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProjectFileParsing:
    """Tests for .kicad_pro file parsing."""

    def test_parse_project_file(self, pro_file: Path) -> None:
        """Parse .kicad_pro, verify version and sections present."""
        proj = parse_project_file(pro_file)
        assert proj.version == "20240517"
        assert isinstance(proj.general, dict)
        assert isinstance(proj.pcbnew, dict)
        assert isinstance(proj.schematic, dict)
        assert proj.general.get("no_connects") == 0

    def test_parse_nonexistent_raises(self, tmp_path: Path) -> None:
        """Parsing a non-existent .kicad_pro raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            parse_project_file(tmp_path / "nonexistent.kicad_pro")

    def test_get_project_settings(self, project_dir: Path) -> None:
        """get_project_settings discovers all project files."""
        settings = get_project_settings(project_dir)
        assert "project" in settings
        assert settings["project"]["version"] == "20240517"
        assert "symbol_libraries" in settings
        assert len(settings["symbol_libraries"]) == 2
        assert "footprint_libraries" in settings
        assert len(settings["footprint_libraries"]) == 1


class TestAddLibEntryOp:
    """Tests for add_lib_entry operation via executor."""

    def test_add_lib_entry_op(self, sym_lib_file: Path) -> None:
        """Execute add_lib_entry, verify entry added."""
        executor = OperationExecutor(base_dir=sym_lib_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "add_lib_entry",
                "target_file": "sym-lib-table",
                "lib_name": "MyCustom",
                "lib_type": "KiCad",
                "uri": "${KIPRJMOD}/custom.kicad_sym",
                "description": "Custom symbols",
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        assert result["details"]["lib_name"] == "MyCustom"

        # Verify on disk
        from kicad_agent.project.lib_table import parse_lib_table
        table = parse_lib_table(sym_lib_file)
        assert len(table.entries) == 3
        assert table.get("MyCustom").uri == "${KIPRJMOD}/custom.kicad_sym"


class TestRemoveLibEntryOp:
    """Tests for remove_lib_entry operation via executor."""

    def test_remove_lib_entry_op(self, fp_lib_file: Path) -> None:
        """Execute remove_lib_entry on fp-lib-table, verify removed."""
        executor = OperationExecutor(base_dir=fp_lib_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "remove_lib_entry",
                "target_file": "fp-lib-table",
                "lib_name": "tile",
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        assert result["details"]["lib_name"] == "tile"

        # Verify on disk
        from kicad_agent.project.lib_table import parse_lib_table
        table = parse_lib_table(fp_lib_file)
        assert len(table.entries) == 0


class TestAddNetClassOp:
    """Tests for add_net_class operation via executor."""

    def test_add_net_class_op(self, dru_file: Path) -> None:
        """Execute add_net_class, verify net class added."""
        executor = OperationExecutor(base_dir=dru_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "add_net_class",
                "target_file": "board.kicad_dru",
                "name": "Power",
                "clearance": 0.3,
                "track_width": 0.5,
                "via_diameter": 1.0,
                "via_drill": 0.6,
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        assert result["details"]["net_class"] == "Power"

        # Verify on disk
        from kicad_agent.project.design_rules import parse_design_rules
        dru = parse_design_rules(dru_file)
        names = [nc.name for nc in dru.net_classes]
        assert "Power" in names
        power = next(nc for nc in dru.net_classes if nc.name == "Power")
        assert power.clearance == 0.3


class TestAddDesignRuleOp:
    """Tests for add_design_rule operation via executor."""

    def test_add_design_rule_op(self, dru_file: Path) -> None:
        """Execute add_design_rule, verify rule added."""
        executor = OperationExecutor(base_dir=dru_file.parent)
        op = Operation.model_validate({
            "root": {
                "op_type": "add_design_rule",
                "target_file": "board.kicad_dru",
                "name": "HV_clearance",
                "constraint_type": "clearance",
                "constraint_values": {"min": "0.5"},
                "condition": "A.NetClass == 'HV'",
            }
        })
        result = executor.execute(op)
        assert result["success"] is True
        assert result["details"]["rule_name"] == "HV_clearance"

        # Verify on disk
        from kicad_agent.project.design_rules import parse_design_rules
        dru = parse_design_rules(dru_file)
        assert len(dru.custom_rules) == 1
        assert dru.custom_rules[0].name == "HV_clearance"


class TestTargetFileValidation:
    """Tests for TargetFile validator with project file types."""

    def test_sym_lib_table_accepted(self) -> None:
        """sym-lib-table is a valid TargetFile."""
        op = Operation.model_validate({
            "root": {
                "op_type": "add_lib_entry",
                "target_file": "sym-lib-table",
                "lib_name": "Test",
                "uri": "/path/to/test.kicad_sym",
            }
        })
        assert op.root.target_file == "sym-lib-table"

    def test_fp_lib_table_accepted(self) -> None:
        """fp-lib-table is a valid TargetFile."""
        op = Operation.model_validate({
            "root": {
                "op_type": "add_lib_entry",
                "target_file": "fp-lib-table",
                "lib_name": "Test",
                "uri": "/path/to/test.pretty",
            }
        })
        assert op.root.target_file == "fp-lib-table"

    def test_dru_file_accepted(self) -> None:
        """kicad_dru is a valid TargetFile."""
        op = Operation.model_validate({
            "root": {
                "op_type": "add_net_class",
                "target_file": "board.kicad_dru",
                "name": "Power",
                "clearance": 0.3,
                "track_width": 0.5,
                "via_diameter": 1.0,
                "via_drill": 0.6,
            }
        })
        assert op.root.target_file == "board.kicad_dru"

    def test_invalid_extension_rejected(self) -> None:
        """Non-KiCad extension is rejected by TargetFile."""
        with pytest.raises(Exception):
            Operation.model_validate({
                "root": {
                    "op_type": "add_lib_entry",
                    "target_file": "random.txt",
                    "lib_name": "Test",
                    "uri": "/path",
                }
            })
