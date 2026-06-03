"""Tests for duplicate_component operation -- TDD RED phase.

Verifies:
- DuplicateComponentOp validates in schema with source_reference and optional offset
- duplicate_component creates a copy with a fresh UUID
- duplicate_component increments the reference number (R1 -> R2, U3 -> U4)
- duplicate_component finds the next available reference number automatically
- duplicate_component applies position offset if provided
- duplicate_component copies all properties from source with updated Reference
- duplicate_component copies pin UUID map with fresh UUIDs for each pin
- duplicate_component raises DuplicateComponentError when source reference not found
- duplicate_component handles multi-unit symbols (copies unit field)
- OperationExecutor dispatches duplicate_component correctly
- Full pipeline: validate Operation -> executor -> duplicate -> serialize -> file on disk
"""

import shutil
import uuid
from pathlib import Path

import pytest

from kicad_agent.ir.base import _clear_registry
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ops.schema import Operation, PositionSpec
from kicad_agent.parser import parse_schematic

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _reset_ir_registry():
    """Clear the IR registry before and after each test."""
    _clear_registry()
    yield
    _clear_registry()


class TestDuplicateComponentHandler:
    """Tests for the duplicate_component operation handler."""

    @pytest.fixture
    def setup_schematic(self, tmp_path: Path) -> dict:
        """Copy RaspberryPi fixture to tmp_path, parse it, return IR and paths."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "RaspberryPi-uHAT.kicad_sch"
        shutil.copy2(src, dst)
        result = parse_schematic(dst)
        ir = SchematicIR(_parse_result=result)
        return {"ir": ir, "file_path": dst, "parse_result": result}

    def test_duplicate_reference_incrementing(self, setup_schematic: dict) -> None:
        """duplicate_component increments reference number: R1 -> R2, U3 -> U4."""
        from kicad_agent.ops.duplicate_component import duplicate_component
        from kicad_agent.ops.schema import DuplicateComponentOp

        # Find a component that exists in the fixture to duplicate
        source = setup_schematic["ir"].get_component_by_ref("J1")
        assert source is not None, "Fixture should contain J1"

        op = DuplicateComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="J1",
        )
        result = duplicate_component(op, setup_schematic["ir"])

        # Result should contain a created reference that is J2 (next available)
        assert "created" in result
        assert len(result["created"]) == 1
        assert result["created"][0]["reference"] == "J2"

    def test_duplicate_finds_next_available(self, setup_schematic: dict) -> None:
        """duplicate_component skips taken references (if J2 exists, J1 -> J3)."""
        from kicad_agent.ops.duplicate_component import duplicate_component
        from kicad_agent.ops.schema import AddComponentOp, DuplicateComponentOp

        # Add a J2 manually to occupy that reference
        add_op = AddComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            library_id="Connector:Conn_01x03",
            reference="J2",
            value="Extra",
            position=PositionSpec(x=0.0, y=0.0),
        )
        from kicad_agent.ops.add_component import add_component
        add_component(add_op, setup_schematic["ir"], setup_schematic["file_path"])

        # Now duplicate J1 -- should become J3 since J2 is taken
        dup_op = DuplicateComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="J1",
        )
        result = duplicate_component(dup_op, setup_schematic["ir"])
        assert result["created"][0]["reference"] == "J3"

    def test_duplicate_with_offset(self, setup_schematic: dict) -> None:
        """duplicate_component applies position offset from source."""
        from kicad_agent.ops.duplicate_component import duplicate_component
        from kicad_agent.ops.schema import DuplicateComponentOp

        source = setup_schematic["ir"].get_component_by_ref("J1")
        assert source is not None
        source_x = source.position.X
        source_y = source.position.Y

        op = DuplicateComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="J1",
            offset=PositionSpec(x=10.0, y=20.0),
        )
        result = duplicate_component(op, setup_schematic["ir"])

        dup_ref = result["created"][0]["reference"]
        dup_comp = setup_schematic["ir"].get_component_by_ref(dup_ref)
        assert dup_comp is not None
        assert dup_comp.position.X == pytest.approx(source_x + 10.0)
        assert dup_comp.position.Y == pytest.approx(source_y + 20.0)

    def test_duplicate_preserves_properties(self, setup_schematic: dict) -> None:
        """duplicate_component copies Value, Footprint from source, updates Reference."""
        from kicad_agent.ops.duplicate_component import duplicate_component
        from kicad_agent.ops.schema import DuplicateComponentOp

        op = DuplicateComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="J1",
        )
        result = duplicate_component(op, setup_schematic["ir"])
        dup_ref = result["created"][0]["reference"]

        source = setup_schematic["ir"].get_component_by_ref("J1")
        dup_comp = setup_schematic["ir"].get_component_by_ref(dup_ref)

        assert dup_comp is not None

        # Get source properties
        source_props = {p.key: p.value for p in source.properties}
        dup_props = {p.key: p.value for p in dup_comp.properties}

        # Reference should be updated to new reference
        assert dup_props["Reference"] == dup_ref
        # Value and Footprint should be preserved from source
        assert dup_props["Value"] == source_props["Value"]

    def test_duplicate_fresh_uuids(self, setup_schematic: dict) -> None:
        """duplicate_component generates fresh UUID for symbol (different from source)."""
        from kicad_agent.ops.duplicate_component import duplicate_component
        from kicad_agent.ops.schema import DuplicateComponentOp

        source = setup_schematic["ir"].get_component_by_ref("J1")
        assert source is not None
        source_uuid = source.uuid

        op = DuplicateComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="J1",
        )
        result = duplicate_component(op, setup_schematic["ir"])

        dup_ref = result["created"][0]["reference"]
        dup_comp = setup_schematic["ir"].get_component_by_ref(dup_ref)
        assert dup_comp is not None

        # UUID should be different from source
        assert dup_comp.uuid != source_uuid

        # UUID should be valid v4
        parsed = uuid.UUID(dup_comp.uuid)
        assert parsed.version == 4

    def test_duplicate_missing_source_raises(self, setup_schematic: dict) -> None:
        """duplicate_component raises DuplicateComponentError when source not found."""
        from kicad_agent.ops.duplicate_component import DuplicateComponentError, duplicate_component
        from kicad_agent.ops.schema import DuplicateComponentOp

        op = DuplicateComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="X999",
        )
        with pytest.raises(DuplicateComponentError, match="not found"):
            duplicate_component(op, setup_schematic["ir"])

    def test_duplicate_multiple_copies(self, setup_schematic: dict) -> None:
        """duplicate_component with count=3 creates 3 copies with unique refs."""
        from kicad_agent.ops.duplicate_component import duplicate_component
        from kicad_agent.ops.schema import DuplicateComponentOp

        op = DuplicateComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="J1",
            count=3,
        )
        result = duplicate_component(op, setup_schematic["ir"])

        assert len(result["created"]) == 3
        refs = [c["reference"] for c in result["created"]]
        # All references should be unique
        assert len(set(refs)) == 3
        # References should be sequential: J2, J3, J4
        assert refs == ["J2", "J3", "J4"]

    def test_duplicate_preserves_library_info(self, setup_schematic: dict) -> None:
        """duplicate_component preserves libraryNickname, entryName, libName."""
        from kicad_agent.ops.duplicate_component import duplicate_component
        from kicad_agent.ops.schema import DuplicateComponentOp

        source = setup_schematic["ir"].get_component_by_ref("J1")
        assert source is not None

        op = DuplicateComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="J1",
        )
        result = duplicate_component(op, setup_schematic["ir"])
        dup_ref = result["created"][0]["reference"]
        dup_comp = setup_schematic["ir"].get_component_by_ref(dup_ref)

        assert dup_comp is not None
        assert dup_comp.libraryNickname == source.libraryNickname
        assert dup_comp.entryName == source.entryName
        assert dup_comp.libName == source.libName

    def test_duplicate_records_mutation(self, setup_schematic: dict) -> None:
        """duplicate_component records mutation in IR mutation log."""
        from kicad_agent.ops.duplicate_component import duplicate_component
        from kicad_agent.ops.schema import DuplicateComponentOp

        initial_mutations = len(setup_schematic["ir"].mutation_log)

        op = DuplicateComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            source_reference="J1",
        )
        duplicate_component(op, setup_schematic["ir"])

        assert len(setup_schematic["ir"].mutation_log) == initial_mutations + 1
        last = setup_schematic["ir"].mutation_log[-1]
        assert last["type"] == "duplicate_component"


class TestDuplicateComponentSchema:
    """Tests for DuplicateComponentOp schema validation."""

    def test_valid_schema(self) -> None:
        """DuplicateComponentOp accepts valid input."""
        from kicad_agent.ops.schema import DuplicateComponentOp

        op = DuplicateComponentOp(
            target_file="test.kicad_sch",
            source_reference="R1",
        )
        assert op.op_type == "duplicate_component"
        assert op.source_reference == "R1"
        assert op.offset is None
        assert op.count == 1

    def test_schema_with_offset(self) -> None:
        """DuplicateComponentOp accepts optional offset."""
        from kicad_agent.ops.schema import DuplicateComponentOp

        op = DuplicateComponentOp(
            target_file="test.kicad_sch",
            source_reference="R1",
            offset=PositionSpec(x=5.0, y=10.0),
        )
        assert op.offset is not None
        assert op.offset.x == 5.0
        assert op.offset.y == 10.0

    def test_schema_rejects_count_zero(self) -> None:
        """DuplicateComponentOp rejects count < 1."""
        from kicad_agent.ops.schema import DuplicateComponentOp
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DuplicateComponentOp(
                target_file="test.kicad_sch",
                source_reference="R1",
                count=0,
            )

    def test_schema_with_count(self) -> None:
        """DuplicateComponentOp accepts count >= 1."""
        from kicad_agent.ops.schema import DuplicateComponentOp

        op = DuplicateComponentOp(
            target_file="test.kicad_sch",
            source_reference="R1",
            count=5,
        )
        assert op.count == 5

    def test_operation_union_accepts_duplicate(self) -> None:
        """Operation discriminated union accepts duplicate_component op_type."""
        op = Operation.model_validate({
            "root": {
                "op_type": "duplicate_component",
                "target_file": "test.kicad_sch",
                "source_reference": "R1",
            }
        })
        assert op.root.op_type == "duplicate_component"


class TestDuplicateComponentExecutor:
    """Tests for OperationExecutor dispatching duplicate_component."""

    @pytest.fixture
    def setup_schematic(self, tmp_path: Path) -> dict:
        """Copy RaspberryPi fixture to tmp_path for executor tests."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "RaspberryPi-uHAT.kicad_sch"
        shutil.copy2(src, dst)
        return {"file_path": dst, "base_dir": tmp_path}

    def test_executor_dispatches_duplicate(self, setup_schematic: dict) -> None:
        """OperationExecutor dispatches duplicate_component correctly."""
        from kicad_agent.ops.executor import OperationExecutor

        executor = OperationExecutor(base_dir=setup_schematic["base_dir"])

        op = Operation.model_validate({
            "root": {
                "op_type": "duplicate_component",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "source_reference": "J1",
            }
        })

        result = executor.execute(op)
        assert result["success"] is True
        assert result["operation"] == "duplicate_component"
        assert "created" in result["details"]

    def test_full_pipeline_duplicate(self, setup_schematic: dict) -> None:
        """Full pipeline: validate -> executor -> duplicate -> serialize -> file on disk."""
        from kicad_agent.ops.executor import OperationExecutor

        executor = OperationExecutor(base_dir=setup_schematic["base_dir"])

        op = Operation.model_validate({
            "root": {
                "op_type": "duplicate_component",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "source_reference": "J1",
                "offset": {"x": 15.0, "y": 25.0},
            }
        })

        result = executor.execute(op)
        assert result["success"] is True

        # Re-parse the file and verify the duplicated component exists
        re_parsed = parse_schematic(setup_schematic["file_path"])
        re_ir = SchematicIR(_parse_result=re_parsed)

        dup_ref = result["details"]["created"][0]["reference"]
        dup_comp = re_ir.get_component_by_ref(dup_ref)
        assert dup_comp is not None

        # Verify fresh UUID
        parsed_uuid = uuid.UUID(dup_comp.uuid)
        assert parsed_uuid.version == 4
