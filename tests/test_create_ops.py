"""Tests for file creation operations: create_schematic, create_pcb, create_project, create_symbol.

Requirements covered:
  OPS-01: JSON operation schema for all edit intents (Pydantic v2 models).
  OPS-02: Reject structurally invalid intents before mutation.
  BEAD-1: create_schematic operation for new .kicad_sch files.
  BEAD-2: create_symbol operation for new component definitions.
"""

import json
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from kicad_agent.ops.executor import OperationExecutor
from kicad_agent.ops.schema import (
    CreatePcbOp,
    CreateProjectOp,
    CreateSchematicOp,
    CreateSymbolOp,
    Operation,
    PinSpec,
)


# ======================================================================
# Schema validation tests
# ======================================================================


class TestCreateSchematicSchema:
    """Schema validation for create_schematic."""

    def test_valid_minimal(self) -> None:
        op = Operation.model_validate({"root": {
            "op_type": "create_schematic",
            "target_file": "test.kicad_sch",
        }})
        assert op.root.op_type == "create_schematic"
        assert op.root.paper == "A4"
        assert op.root.title == ""

    def test_valid_with_options(self) -> None:
        op = Operation.model_validate({"root": {
            "op_type": "create_schematic",
            "target_file": "subdir/test.kicad_sch",
            "paper": "A3",
            "title": "My Schematic",
        }})
        assert op.root.paper == "A3"
        assert op.root.title == "My Schematic"

    def test_rejects_absolute_path(self) -> None:
        with pytest.raises(ValidationError, match="relative path"):
            Operation.model_validate({"root": {
                "op_type": "create_schematic",
                "target_file": "/tmp/test.kicad_sch",
            }})

    def test_rejects_traversal(self) -> None:
        with pytest.raises(ValidationError, match="traversal"):
            Operation.model_validate({"root": {
                "op_type": "create_schematic",
                "target_file": "../escape.kicad_sch",
            }})


class TestCreatePcbSchema:
    """Schema validation for create_pcb."""

    def test_valid(self) -> None:
        op = Operation.model_validate({"root": {
            "op_type": "create_pcb",
            "target_file": "board.kicad_pcb",
        }})
        assert op.root.op_type == "create_pcb"

    def test_with_title(self) -> None:
        op = Operation.model_validate({"root": {
            "op_type": "create_pcb",
            "target_file": "board.kicad_pcb",
            "title": "Main Board",
        }})
        assert op.root.title == "Main Board"


class TestCreateProjectSchema:
    """Schema validation for create_project."""

    def test_valid(self) -> None:
        op = Operation.model_validate({"root": {
            "op_type": "create_project",
            "target_file": "project.kicad_pro",
        }})
        assert op.root.op_type == "create_project"


class TestCreateSymbolSchema:
    """Schema validation for create_symbol."""

    def test_valid_with_pins(self) -> None:
        op = Operation.model_validate({"root": {
            "op_type": "create_symbol",
            "target_file": "mylib.kicad_sym",
            "symbol_name": "AK4619",
            "reference_prefix": "U",
            "pins": [
                {"number": "1", "name": "VCC", "electrical_type": "power_in",
                 "position": {"x": 0, "y": 5.08}},
                {"number": "2", "name": "GND", "electrical_type": "power_in",
                 "position": {"x": 0, "y": -5.08}},
            ],
        }})
        assert op.root.symbol_name == "AK4619"
        assert len(op.root.pins) == 2
        assert op.root.pins[0].electrical_type == "power_in"

    def test_valid_no_pins(self) -> None:
        op = Operation.model_validate({"root": {
            "op_type": "create_symbol",
            "target_file": "lib.kicad_sym",
            "symbol_name": "Frame_A3",
        }})
        assert len(op.root.pins) == 0

    def test_rejects_unsafe_symbol_name(self) -> None:
        with pytest.raises(ValidationError, match="unsafe characters"):
            Operation.model_validate({"root": {
                "op_type": "create_symbol",
                "target_file": "lib.kicad_sym",
                "symbol_name": "bad name with spaces",
            }})

    def test_custom_properties(self) -> None:
        op = Operation.model_validate({"root": {
            "op_type": "create_symbol",
            "target_file": "lib.kicad_sym",
            "symbol_name": "IC1",
            "properties": [
                {"name": "Manufacturer", "value": "AKM"},
                {"name": "MPN", "value": "AK4619VN"},
            ],
        }})
        assert len(op.root.properties) == 2

    def test_pin_default_electrical_type(self) -> None:
        pin = PinSpec(number="1", name="IO", position={"x": 0, "y": 0})
        assert pin.electrical_type == "passive"
        assert pin.graphical_style == "line"
        assert pin.length == 2.54


# ======================================================================
# Executor integration tests
# ======================================================================


class TestCreateSchematicExecutor:
    """End-to-end tests for create_schematic via OperationExecutor."""

    def test_creates_valid_file(self, tmp_path: Path) -> None:
        ex = OperationExecutor(base_dir=tmp_path)
        result = ex.execute(Operation.model_validate({"root": {
            "op_type": "create_schematic",
            "target_file": "test.kicad_sch",
            "paper": "A4",
            "title": "Test",
        }}))
        assert result["success"] is True
        assert (tmp_path / "test.kicad_sch").exists()

    def test_file_has_valid_structure(self, tmp_path: Path) -> None:
        ex = OperationExecutor(base_dir=tmp_path)
        ex.execute(Operation.model_validate({"root": {
            "op_type": "create_schematic",
            "target_file": "test.kicad_sch",
        }}))
        content = (tmp_path / "test.kicad_sch").read_text()
        assert "(kicad_sch" in content
        assert "(generator eeschema)" in content
        assert "(uuid" in content
        assert 'A4' in content

    def test_creates_subdirectories(self, tmp_path: Path) -> None:
        ex = OperationExecutor(base_dir=tmp_path)
        result = ex.execute(Operation.model_validate({"root": {
            "op_type": "create_schematic",
            "target_file": "sub/dir/test.kicad_sch",
        }}))
        assert result["success"] is True
        assert (tmp_path / "sub" / "dir" / "test.kicad_sch").exists()

    def test_raises_if_file_exists(self, tmp_path: Path) -> None:
        ex = OperationExecutor(base_dir=tmp_path)
        op = Operation.model_validate({"root": {
            "op_type": "create_schematic",
            "target_file": "test.kicad_sch",
        }})
        ex.execute(op)
        with pytest.raises(FileExistsError):
            ex.execute(op)

    def test_can_reparse_with_kiutils(self, tmp_path: Path) -> None:
        ex = OperationExecutor(base_dir=tmp_path)
        ex.execute(Operation.model_validate({"root": {
            "op_type": "create_schematic",
            "target_file": "test.kicad_sch",
            "paper": "A3",
        }}))
        from kiutils.schematic import Schematic
        sch = Schematic.from_file(str(tmp_path / "test.kicad_sch"))
        assert sch.generator == "eeschema"
        assert sch.uuid is not None
        assert sch.paper.paperSize == "A3"


class TestCreatePcbExecutor:
    """End-to-end tests for create_pcb via OperationExecutor."""

    def test_creates_valid_file(self, tmp_path: Path) -> None:
        ex = OperationExecutor(base_dir=tmp_path)
        result = ex.execute(Operation.model_validate({"root": {
            "op_type": "create_pcb",
            "target_file": "board.kicad_pcb",
        }}))
        assert result["success"] is True
        assert (tmp_path / "board.kicad_pcb").exists()

    def test_file_has_valid_structure(self, tmp_path: Path) -> None:
        ex = OperationExecutor(base_dir=tmp_path)
        ex.execute(Operation.model_validate({"root": {
            "op_type": "create_pcb",
            "target_file": "board.kicad_pcb",
        }}))
        content = (tmp_path / "board.kicad_pcb").read_text()
        assert "(kicad_pcb" in content
        assert "(generator pcbnew)" in content
        assert "(layers" in content

    def test_raises_if_file_exists(self, tmp_path: Path) -> None:
        ex = OperationExecutor(base_dir=tmp_path)
        op = Operation.model_validate({"root": {
            "op_type": "create_pcb",
            "target_file": "board.kicad_pcb",
        }})
        ex.execute(op)
        with pytest.raises(FileExistsError):
            ex.execute(op)


class TestCreateProjectExecutor:
    """End-to-end tests for create_project via OperationExecutor."""

    def test_creates_valid_json(self, tmp_path: Path) -> None:
        ex = OperationExecutor(base_dir=tmp_path)
        result = ex.execute(Operation.model_validate({"root": {
            "op_type": "create_project",
            "target_file": "proj.kicad_pro",
        }}))
        assert result["success"] is True
        data = json.loads((tmp_path / "proj.kicad_pro").read_text())
        assert "board" in data
        assert "schematic" in data
        assert "text_variables" in data

    def test_raises_if_file_exists(self, tmp_path: Path) -> None:
        ex = OperationExecutor(base_dir=tmp_path)
        op = Operation.model_validate({"root": {
            "op_type": "create_project",
            "target_file": "proj.kicad_pro",
        }})
        ex.execute(op)
        with pytest.raises(FileExistsError):
            ex.execute(op)


class TestCreateSymbolExecutor:
    """End-to-end tests for create_symbol via OperationExecutor."""

    def test_creates_new_library(self, tmp_path: Path) -> None:
        ex = OperationExecutor(base_dir=tmp_path)
        result = ex.execute(Operation.model_validate({"root": {
            "op_type": "create_symbol",
            "target_file": "mylib.kicad_sym",
            "symbol_name": "MyIC",
            "reference_prefix": "U",
            "pins": [
                {"number": "1", "name": "VCC", "electrical_type": "power_in",
                 "position": {"x": 0, "y": 5.08}},
                {"number": "2", "name": "GND", "electrical_type": "power_in",
                 "position": {"x": 0, "y": -5.08}},
            ],
        }}))
        assert result["success"] is True
        assert result["details"]["pin_count"] == 2
        assert (tmp_path / "mylib.kicad_sym").exists()

    def test_symbol_has_standard_properties(self, tmp_path: Path) -> None:
        ex = OperationExecutor(base_dir=tmp_path)
        ex.execute(Operation.model_validate({"root": {
            "op_type": "create_symbol",
            "target_file": "lib.kicad_sym",
            "symbol_name": "TestIC",
            "reference_prefix": "U",
            "value": "TestValue",
        }}))
        from kiutils.symbol import SymbolLib
        lib = SymbolLib.from_file(str(tmp_path / "lib.kicad_sym"))
        sym = lib.symbols[0]
        prop_keys = [p.key for p in sym.properties]
        assert "Reference" in prop_keys
        assert "Value" in prop_keys
        assert "Footprint" in prop_keys
        assert "Datasheet" in prop_keys

    def test_symbol_has_pins(self, tmp_path: Path) -> None:
        ex = OperationExecutor(base_dir=tmp_path)
        ex.execute(Operation.model_validate({"root": {
            "op_type": "create_symbol",
            "target_file": "lib.kicad_sym",
            "symbol_name": "IC2",
            "pins": [
                {"number": "1", "name": "DIN", "electrical_type": "input",
                 "position": {"x": -5.08, "y": 0}},
                {"number": "2", "name": "DOUT", "electrical_type": "output",
                 "position": {"x": 5.08, "y": 0}},
                {"number": "3", "name": "CLK", "graphical_style": "clock",
                 "position": {"x": 0, "y": 5.08}},
            ],
        }}))
        from kiutils.symbol import SymbolLib
        lib = SymbolLib.from_file(str(tmp_path / "lib.kicad_sym"))
        sym = lib.symbols[0]
        assert len(sym.pins) == 3
        assert sym.pins[0].electricalType == "input"
        assert sym.pins[1].electricalType == "output"
        assert sym.pins[2].graphicalStyle == "clock"

    def test_appends_to_existing_library(self, tmp_path: Path) -> None:
        ex = OperationExecutor(base_dir=tmp_path)
        # Create first symbol
        ex.execute(Operation.model_validate({"root": {
            "op_type": "create_symbol",
            "target_file": "lib.kicad_sym",
            "symbol_name": "Sym1",
        }}))
        # Append second symbol
        ex.execute(Operation.model_validate({"root": {
            "op_type": "create_symbol",
            "target_file": "lib.kicad_sym",
            "symbol_name": "Sym2",
        }}))
        from kiutils.symbol import SymbolLib
        lib = SymbolLib.from_file(str(tmp_path / "lib.kicad_sym"))
        assert len(lib.symbols) == 2
        assert lib.symbols[0].entryName == "Sym1"
        assert lib.symbols[1].entryName == "Sym2"

    def test_rejects_duplicate_symbol_name(self, tmp_path: Path) -> None:
        ex = OperationExecutor(base_dir=tmp_path)
        op = Operation.model_validate({"root": {
            "op_type": "create_symbol",
            "target_file": "lib.kicad_sym",
            "symbol_name": "Dup",
        }})
        ex.execute(op)
        with pytest.raises(ValueError, match="already exists"):
            ex.execute(op)

    def test_empty_pins_body_only(self, tmp_path: Path) -> None:
        ex = OperationExecutor(base_dir=tmp_path)
        result = ex.execute(Operation.model_validate({"root": {
            "op_type": "create_symbol",
            "target_file": "lib.kicad_sym",
            "symbol_name": "Box",
            "body_width": 15.0,
            "body_height": 20.0,
        }}))
        assert result["details"]["pin_count"] == 0
        from kiutils.symbol import SymbolLib
        lib = SymbolLib.from_file(str(tmp_path / "lib.kicad_sym"))
        sym = lib.symbols[0]
        assert len(sym.pins) == 0
        # Body rectangle should be present in graphic items
        assert len(sym.graphicItems) >= 1

    def test_custom_properties(self, tmp_path: Path) -> None:
        ex = OperationExecutor(base_dir=tmp_path)
        ex.execute(Operation.model_validate({"root": {
            "op_type": "create_symbol",
            "target_file": "lib.kicad_sym",
            "symbol_name": "IC3",
            "properties": [
                {"name": "Manufacturer", "value": "TI"},
                {"name": "MPN", "value": "LM358"},
            ],
        }}))
        from kiutils.symbol import SymbolLib
        lib = SymbolLib.from_file(str(tmp_path / "lib.kicad_sym"))
        sym = lib.symbols[0]
        prop_keys = [p.key for p in sym.properties]
        assert "Manufacturer" in prop_keys
        assert "MPN" in prop_keys


# ======================================================================
# Schema export test
# ======================================================================


class TestSchemaExport:
    """Verify all new ops are included in the exported JSON schema."""

    def test_create_ops_in_schema(self) -> None:
        from kicad_agent.ops.schema import get_operation_schema
        schema = get_operation_schema()
        root = schema.get("properties", {}).get("root", {})
        mapping = root.get("discriminator", {}).get("mapping", {})
        assert "create_schematic" in mapping
        assert "create_pcb" in mapping
        assert "create_project" in mapping
        assert "create_symbol" in mapping
