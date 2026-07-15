"""Tests for hierarchical sheet operations.

Covers schema validation, executor dispatch, and handler-level behavior
for add_sheet, add_sheet_pin, and navigate_hierarchy.
"""

import json
from pathlib import Path

import pytest

from volta.ir.base import _clear_registry
from volta.ops._schema_sheet import (
    AddSheetOp,
    AddSheetPinOp,
    NavigateSheetsOp,
)
from volta.ops.schema import Operation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def schematic_path(tmp_path: Path) -> Path:
    """Create a minimal schematic file for testing."""
    _clear_registry()
    sch_path = tmp_path / "test.kicad_sch"
    import uuid

    content = (
        "(kicad_sch\n"
        "  (version 20250114)\n"
        "  (generator volta)\n"
        f"  (uuid {uuid.uuid4()})\n"
        '  (paper "A4")\n'
        "  (lib_symbols)\n"
        "  (sheet_instances\n"
        '    (path "/" (page "1"))\n'
        "  )\n"
        ")\n"
    )
    sch_path.write_text(content, encoding="utf-8")
    return sch_path


@pytest.fixture
def ir_with_sheet(schematic_path: Path) -> tuple:
    """Create a SchematicIR with one existing sheet, return (ir, sheet_uuid)."""
    _clear_registry()
    from volta.ir.schematic_ir import SchematicIR
    from volta.parser import parse_schematic

    import uuid as uuid_mod

    from kiutils.items.common import ColorRGBA, Position, Property, Stroke
    from kiutils.items.schitems import HierarchicalSheet

    parse_result = parse_schematic(schematic_path)
    ir = SchematicIR(_parse_result=parse_result)

    sheet_uuid = str(uuid_mod.uuid4())
    sheet = HierarchicalSheet(
        position=Position(X=50.0, Y=30.0),
        width=30.0,
        height=20.0,
        stroke=Stroke(width=0.1524, type="solid", color=ColorRGBA(R=0, G=0, B=0, A=1)),
        fill=ColorRGBA(R=0, G=0, B=0, A=0),
        uuid=sheet_uuid,
        sheetName=Property(key="Sheetname", value="ExistingSheet"),
        fileName=Property(key="Filename", value="child.kicad_sch"),
        pins=[],
        instances=[],
    )
    ir._parse_result.kiutils_obj.sheets.append(sheet)

    return ir, sheet_uuid


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestAddSheetSchema:
    """Schema validation for AddSheetOp."""

    def test_valid_minimal(self) -> None:
        op = AddSheetOp(
            target_file="test.kicad_sch",
            sheet_name="PowerSupply",
            file_name="power.kicad_sch",
            position={"x": 50.0, "y": 30.0},
        )
        assert op.op_type == "add_sheet"
        assert op.sheet_name == "PowerSupply"
        assert op.file_name == "power.kicad_sch"
        assert op.width == 30.0
        assert op.height == 20.0
        assert op.create_sub_sheet is True

    def test_valid_with_all_fields(self) -> None:
        op = AddSheetOp(
            target_file="test.kicad_sch",
            sheet_name="ADC",
            file_name="adc_section.kicad_sch",
            position={"x": 100.0, "y": 50.0, "angle": 90.0},
            width=50.0,
            height=40.0,
            create_sub_sheet=False,
        )
        assert op.width == 50.0
        assert op.height == 40.0
        assert op.create_sub_sheet is False

    def test_rejects_unsafe_sheet_name(self) -> None:
        with pytest.raises(Exception, match="unsafe"):
            AddSheetOp(
                target_file="test.kicad_sch",
                sheet_name='Sheet"name',
                file_name="sub.kicad_sch",
                position={"x": 0, "y": 0},
            )

    def test_rejects_empty_sheet_name(self) -> None:
        with pytest.raises(Exception):
            AddSheetOp(
                target_file="test.kicad_sch",
                sheet_name="",
                file_name="sub.kicad_sch",
                position={"x": 0, "y": 0},
            )

    def test_rejects_zero_width(self) -> None:
        with pytest.raises(Exception):
            AddSheetOp(
                target_file="test.kicad_sch",
                sheet_name="Sheet",
                file_name="sub.kicad_sch",
                position={"x": 0, "y": 0},
                width=0,
            )

    def test_rejects_negative_height(self) -> None:
        with pytest.raises(Exception):
            AddSheetOp(
                target_file="test.kicad_sch",
                sheet_name="Sheet",
                file_name="sub.kicad_sch",
                position={"x": 0, "y": 0},
                height=-5,
            )


class TestAddSheetPinSchema:
    """Schema validation for AddSheetPinOp."""

    def test_valid(self) -> None:
        op = AddSheetPinOp(
            target_file="test.kicad_sch",
            sheet_uuid="12345678-1234-1234-1234-123456789012",
            pin_name="VCC",
            connection_type="input",
            position={"x": 50.0, "y": 30.0},
        )
        assert op.op_type == "add_sheet_pin"
        assert op.connection_type == "input"

    def test_default_connection_type(self) -> None:
        op = AddSheetPinOp(
            target_file="test.kicad_sch",
            sheet_uuid="12345678-1234-1234-1234-123456789012",
            pin_name="SDA",
            position={"x": 0, "y": 0},
        )
        assert op.connection_type == "bidirectional"

    def test_rejects_unsafe_pin_name(self) -> None:
        with pytest.raises(Exception, match="unsafe"):
            AddSheetPinOp(
                target_file="test.kicad_sch",
                sheet_uuid="12345678-1234-1234-1234-123456789012",
                pin_name="pin(with)paren",
                position={"x": 0, "y": 0},
            )

    def test_rejects_invalid_uuid_length(self) -> None:
        with pytest.raises(Exception):
            AddSheetPinOp(
                target_file="test.kicad_sch",
                sheet_uuid="short",
                pin_name="VCC",
                position={"x": 0, "y": 0},
            )


class TestNavigateSheetsSchema:
    """Schema validation for NavigateSheetsOp."""

    def test_valid(self) -> None:
        op = NavigateSheetsOp(
            target_file="test.kicad_sch",
        )
        assert op.op_type == "navigate_hierarchy"
        assert op.max_depth == -1

    def test_with_max_depth(self) -> None:
        op = NavigateSheetsOp(
            target_file="test.kicad_sch",
            max_depth=3,
        )
        assert op.max_depth == 3

    def test_rejects_negative_two(self) -> None:
        with pytest.raises(Exception):
            NavigateSheetsOp(
                target_file="test.kicad_sch",
                max_depth=-2,
            )


# ---------------------------------------------------------------------------
# Operation union dispatch tests
# ---------------------------------------------------------------------------


class TestOperationUnionDispatch:
    """Verify all 3 new ops work through the Operation discriminated union."""

    def test_add_sheet_through_union(self) -> None:
        op = Operation.model_validate({
            "root": {
                "op_type": "add_sheet",
                "target_file": "test.kicad_sch",
                "sheet_name": "Power",
                "file_name": "power.kicad_sch",
                "position": {"x": 50.0, "y": 30.0},
            }
        })
        assert op.root.op_type == "add_sheet"

    def test_add_sheet_pin_through_union(self) -> None:
        op = Operation.model_validate({
            "root": {
                "op_type": "add_sheet_pin",
                "target_file": "test.kicad_sch",
                "sheet_uuid": "12345678-1234-1234-1234-123456789012",
                "pin_name": "GND",
                "position": {"x": 10.0, "y": 20.0},
            }
        })
        assert op.root.op_type == "add_sheet_pin"

    def test_navigate_hierarchy_through_union(self) -> None:
        op = Operation.model_validate({
            "root": {
                "op_type": "navigate_hierarchy",
                "target_file": "test.kicad_sch",
                "max_depth": 5,
            }
        })
        assert op.root.op_type == "navigate_hierarchy"


# ---------------------------------------------------------------------------
# Executor dispatch tests
# ---------------------------------------------------------------------------


class TestExecutorDispatch:
    """Verify executor routes to correct handlers for sheet operations."""

    def test_add_sheet_dispatches(self, schematic_path: Path) -> None:
        from volta.ops.executor import OperationExecutor

        executor = OperationExecutor(base_dir=schematic_path.parent)
        result = executor.execute(Operation.model_validate({
            "root": {
                "op_type": "add_sheet",
                "target_file": schematic_path.name,
                "sheet_name": "PowerSection",
                "file_name": "power_section.kicad_sch",
                "position": {"x": 50.0, "y": 30.0},
            }
        }))
        assert result["success"] is True
        assert result["operation"] == "add_sheet"
        assert "sheet_uuid" in result["details"]
        assert result["details"]["sheet_name"] == "PowerSection"

    def test_navigate_hierarchy_dispatches(self, schematic_path: Path) -> None:
        from volta.ops.executor import OperationExecutor

        executor = OperationExecutor(base_dir=schematic_path.parent)
        result = executor.execute(Operation.model_validate({
            "root": {
                "op_type": "navigate_hierarchy",
                "target_file": schematic_path.name,
            }
        }))
        assert result["success"] is True
        assert result["operation"] == "navigate_hierarchy"
        assert "sheets" in result["details"]

    def test_add_sheet_pin_dispatches(self, schematic_path: Path) -> None:
        from volta.ops.executor import OperationExecutor

        # First add a sheet so we have a UUID to target
        executor = OperationExecutor(base_dir=schematic_path.parent)
        sheet_result = executor.execute(Operation.model_validate({
            "root": {
                "op_type": "add_sheet",
                "target_file": schematic_path.name,
                "sheet_name": "SubSheet",
                "file_name": "sub.kicad_sch",
                "position": {"x": 50.0, "y": 30.0},
            }
        }))
        sheet_uuid = sheet_result["details"]["sheet_uuid"]

        # Now add a pin to that sheet
        pin_result = executor.execute(Operation.model_validate({
            "root": {
                "op_type": "add_sheet_pin",
                "target_file": schematic_path.name,
                "sheet_uuid": sheet_uuid,
                "pin_name": "SDA",
                "connection_type": "bidirectional",
                "position": {"x": 55.0, "y": 30.0},
            }
        }))
        assert pin_result["success"] is True
        assert pin_result["operation"] == "add_sheet_pin"
        assert pin_result["details"]["pin_name"] == "SDA"


# ---------------------------------------------------------------------------
# Handler-level tests
# ---------------------------------------------------------------------------


class TestAddSheetHandler:
    """Direct handler tests for add_sheet."""

    def test_creates_sheet_in_graphical_items(self, schematic_path: Path) -> None:
        from volta.ir.schematic_ir import SchematicIR
        from volta.ops.sheet_ops import add_sheet
        from volta.parser import parse_schematic

        parse_result = parse_schematic(schematic_path)
        ir = SchematicIR(_parse_result=parse_result)

        op = AddSheetOp(
            target_file="test.kicad_sch",
            sheet_name="NewSheet",
            file_name="new_sheet.kicad_sch",
            position={"x": 100.0, "y": 200.0},
            width=40.0,
            height=30.0,
        )

        result = add_sheet(op, ir, schematic_path)
        assert "sheet_uuid" in result
        assert result["sheet_name"] == "NewSheet"
        assert result["file_name"] == "new_sheet.kicad_sch"
        assert result["sub_sheet_created"] is True

        # Verify the sheet was appended to sheets
        from kiutils.items.schitems import HierarchicalSheet
        sheets = [
            item for item in ir._parse_result.kiutils_obj.sheets
            if isinstance(item, HierarchicalSheet)
        ]
        assert len(sheets) == 1
        assert sheets[0].sheetName.value == "NewSheet"
        assert sheets[0].fileName.value == "new_sheet.kicad_sch"
        assert sheets[0].width == 40.0
        assert sheets[0].height == 30.0

    def test_sub_sheet_not_created_when_disabled(self, schematic_path: Path) -> None:
        from volta.ir.schematic_ir import SchematicIR
        from volta.ops.sheet_ops import add_sheet
        from volta.parser import parse_schematic

        parse_result = parse_schematic(schematic_path)
        ir = SchematicIR(_parse_result=parse_result)

        op = AddSheetOp(
            target_file="test.kicad_sch",
            sheet_name="NoFile",
            file_name="nofile.kicad_sch",
            position={"x": 0, "y": 0},
            create_sub_sheet=False,
        )

        result = add_sheet(op, ir, schematic_path)
        assert result["sub_sheet_created"] is False
        assert not (schematic_path.parent / "nofile.kicad_sch").exists()

    def test_sub_sheet_not_overwritten_if_exists(self, schematic_path: Path) -> None:
        from volta.ir.schematic_ir import SchematicIR
        from volta.ops.sheet_ops import add_sheet
        from volta.parser import parse_schematic

        # Pre-create the child file
        child_path = schematic_path.parent / "existing_child.kicad_sch"
        child_path.write_text("(kicad_sch (version 20250114))", encoding="utf-8")

        parse_result = parse_schematic(schematic_path)
        ir = SchematicIR(_parse_result=parse_result)

        op = AddSheetOp(
            target_file="test.kicad_sch",
            sheet_name="WithChild",
            file_name="existing_child.kicad_sch",
            position={"x": 0, "y": 0},
        )

        result = add_sheet(op, ir, schematic_path)
        assert result["sub_sheet_created"] is False
        # Original content preserved
        assert child_path.read_text() == "(kicad_sch (version 20250114))"

    def test_records_mutation(self, schematic_path: Path) -> None:
        from volta.ir.schematic_ir import SchematicIR
        from volta.ops.sheet_ops import add_sheet
        from volta.parser import parse_schematic

        parse_result = parse_schematic(schematic_path)
        ir = SchematicIR(_parse_result=parse_result)

        op = AddSheetOp(
            target_file="test.kicad_sch",
            sheet_name="MutTest",
            file_name="mut.kicad_sch",
            position={"x": 0, "y": 0},
        )

        add_sheet(op, ir, schematic_path)
        assert ir.dirty is True
        assert len(ir._mutation_log) == 1
        assert ir._mutation_log[0]["type"] == "add_sheet"


class TestAddSheetPinHandler:
    """Direct handler tests for add_sheet_pin."""

    def test_adds_pin_to_correct_sheet(self, ir_with_sheet: tuple) -> None:
        ir, sheet_uuid = ir_with_sheet

        op = AddSheetPinOp(
            target_file="test.kicad_sch",
            sheet_uuid=sheet_uuid,
            pin_name="CLK",
            connection_type="input",
            position={"x": 55.0, "y": 30.0},
        )

        from volta.ops.sheet_ops import add_sheet_pin
        result = add_sheet_pin(op, ir, Path("/tmp/test.kicad_sch"))

        assert result["pin_name"] == "CLK"
        assert result["sheet_uuid"] == sheet_uuid
        assert result["connection_type"] == "input"

        # Verify the pin was added to the sheet
        from kiutils.items.schitems import HierarchicalSheet
        for item in ir._parse_result.kiutils_obj.graphicalItems:
            if isinstance(item, HierarchicalSheet) and item.uuid == sheet_uuid:
                assert len(item.pins) == 1
                assert item.pins[0].name == "CLK"
                assert item.pins[0].connectionType == "input"
                break

    def test_raises_for_missing_uuid(self, ir_with_sheet: tuple) -> None:
        ir, _ = ir_with_sheet

        op = AddSheetPinOp(
            target_file="test.kicad_sch",
            sheet_uuid="00000000-0000-0000-0000-000000000000",
            pin_name="DNE",
            position={"x": 0, "y": 0},
        )

        from volta.ops.sheet_ops import add_sheet_pin
        with pytest.raises(ValueError, match="No HierarchicalSheet found"):
            add_sheet_pin(op, ir, Path("/tmp/test.kicad_sch"))

    def test_multiple_pins_on_same_sheet(self, ir_with_sheet: tuple) -> None:
        ir, sheet_uuid = ir_with_sheet

        from volta.ops.sheet_ops import add_sheet_pin

        for name, ctype in [("SDA", "bidirectional"), ("SCL", "bidirectional"), ("VCC", "input")]:
            op = AddSheetPinOp(
                target_file="test.kicad_sch",
                sheet_uuid=sheet_uuid,
                pin_name=name,
                connection_type=ctype,
                position={"x": 50.0, "y": 30.0},
            )
            add_sheet_pin(op, ir, Path("/tmp/test.kicad_sch"))

        from kiutils.items.schitems import HierarchicalSheet
        for item in ir._parse_result.kiutils_obj.graphicalItems:
            if isinstance(item, HierarchicalSheet) and item.uuid == sheet_uuid:
                assert len(item.pins) == 3
                break


class TestNavigateHierarchyHandler:
    """Direct handler tests for navigate_hierarchy."""

    def test_empty_schematic_returns_empty(self, schematic_path: Path) -> None:
        from volta.ir.schematic_ir import SchematicIR
        from volta.ops.sheet_ops import navigate_hierarchy
        from volta.parser import parse_schematic

        parse_result = parse_schematic(schematic_path)
        ir = SchematicIR(_parse_result=parse_result)

        op = NavigateSheetsOp(target_file="test.kicad_sch")
        result = navigate_hierarchy(op, ir, schematic_path)

        assert result["sheet_count"] == 0
        assert result["sheets"] == []
        assert result["root_file"] == "test.kicad_sch"

    def test_returns_sheet_info(self, ir_with_sheet: tuple, schematic_path: Path) -> None:
        ir, sheet_uuid = ir_with_sheet

        op = NavigateSheetsOp(target_file="test.kicad_sch")
        from volta.ops.sheet_ops import navigate_hierarchy
        result = navigate_hierarchy(op, ir, schematic_path)

        assert result["sheet_count"] == 1
        sheet = result["sheets"][0]
        assert sheet["sheet_name"] == "ExistingSheet"
        assert sheet["file_name"] == "child.kicad_sch"
        assert sheet["uuid"] == sheet_uuid
        assert sheet["pin_count"] == 0

    def test_includes_pin_info(self, ir_with_sheet: tuple, schematic_path: Path) -> None:
        ir, sheet_uuid = ir_with_sheet

        # Add a pin first
        from volta.ops.sheet_ops import add_sheet_pin
        pin_op = AddSheetPinOp(
            target_file="test.kicad_sch",
            sheet_uuid=sheet_uuid,
            pin_name="DATA",
            connection_type="bidirectional",
            position={"x": 50.0, "y": 30.0},
        )
        add_sheet_pin(pin_op, ir, schematic_path)

        op = NavigateSheetsOp(target_file="test.kicad_sch")
        from volta.ops.sheet_ops import navigate_hierarchy
        result = navigate_hierarchy(op, ir, schematic_path)

        sheet = result["sheets"][0]
        assert sheet["pin_count"] == 1
        assert sheet["pins"][0]["name"] == "DATA"
        assert sheet["pins"][0]["connection_type"] == "bidirectional"

    def test_does_not_mutate_ir(self, ir_with_sheet: tuple, schematic_path: Path) -> None:
        ir, _ = ir_with_sheet

        op = NavigateSheetsOp(target_file="test.kicad_sch")
        from volta.ops.sheet_ops import navigate_hierarchy
        navigate_hierarchy(op, ir, schematic_path)

        assert ir.dirty is False

    def test_max_depth_zero_returns_no_sheets(self, ir_with_sheet: tuple, schematic_path: Path) -> None:
        ir, _ = ir_with_sheet

        op = NavigateSheetsOp(target_file="test.kicad_sch", max_depth=0)
        from volta.ops.sheet_ops import navigate_hierarchy
        result = navigate_hierarchy(op, ir, schematic_path)

        assert result["sheet_count"] == 0
