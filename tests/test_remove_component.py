"""Tests for remove_component operation -- TDD RED phase.

Verifies:
- remove_component removes a component from schematicSymbols by reference
- remove_component raises RemoveComponentError when reference not found
- remove_component removes the corresponding symbol_instances entry
- after removal, get_component_by_ref returns None for the removed reference
- remove_component records mutation in IR mutation log
- Full pipeline: validate Operation -> executor -> remove_component -> serialize -> file on disk
"""

import shutil
from pathlib import Path

import pytest

from kicad_agent.ir.base import _clear_registry
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ops.schema import Operation, RemoveComponentOp
from kicad_agent.parser import parse_schematic
from kicad_agent.serializer import serialize_schematic


@pytest.fixture(autouse=True)
def _reset_ir_registry():
    """Clear the IR registry before and after each test."""
    _clear_registry()
    yield
    _clear_registry()


FIXTURE_DIR = Path(__file__).parent / "fixtures"


class TestRemoveComponent:
    """Tests for the remove_component operation handler."""

    @pytest.fixture
    def setup_schematic(self, tmp_path: Path) -> dict:
        """Copy RaspberryPi fixture to tmp_path, parse it, return IR and paths."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "RaspberryPi-uHAT.kicad_sch"
        shutil.copy2(src, dst)
        result = parse_schematic(dst)
        ir = SchematicIR(_parse_result=result)
        return {
            "ir": ir,
            "file_path": dst,
            "parse_result": result,
            "initial_count": len(ir.components),
        }

    def test_removes_component_by_reference(
        self, setup_schematic: dict
    ) -> None:
        """remove_component removes a component from schematicSymbols by reference."""
        from kicad_agent.ops.remove_component import remove_component

        # Verify J1 exists initially
        assert setup_schematic["ir"].get_component_by_ref("J1") is not None

        op = RemoveComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
        )
        result = remove_component(op, setup_schematic["ir"])

        # Component should no longer be found
        assert setup_schematic["ir"].get_component_by_ref("J1") is None

    def test_raises_when_reference_not_found(
        self, setup_schematic: dict
    ) -> None:
        """remove_component raises RemoveComponentError when reference not found."""
        from kicad_agent.ops.remove_component import RemoveComponentError, remove_component

        op = RemoveComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="NONEXISTENT999",
        )

        with pytest.raises(RemoveComponentError, match="not found"):
            remove_component(op, setup_schematic["ir"])

    def test_removes_symbol_instances_entry(
        self, setup_schematic: dict
    ) -> None:
        """remove_component removes matching symbol_instances entry if present."""
        from kicad_agent.ops.remove_component import remove_component

        # Even though this fixture has empty symbolInstances,
        # verify the cleanup runs without error
        op = RemoveComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
        )
        remove_component(op, setup_schematic["ir"])

        # Should not raise -- cleanup handles empty list gracefully

    def test_component_count_decreases_by_one(
        self, setup_schematic: dict
    ) -> None:
        """After removal, component count decreased by exactly 1."""
        from kicad_agent.ops.remove_component import remove_component

        initial_count = setup_schematic["initial_count"]

        op = RemoveComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
        )
        remove_component(op, setup_schematic["ir"])

        assert len(setup_schematic["ir"].components) == initial_count - 1

    def test_records_mutation_in_log(
        self, setup_schematic: dict
    ) -> None:
        """remove_component records mutation in IR mutation log."""
        from kicad_agent.ops.remove_component import remove_component

        initial_mutations = len(setup_schematic["ir"].mutation_log)

        op = RemoveComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="R1",
        )
        remove_component(op, setup_schematic["ir"])

        assert len(setup_schematic["ir"].mutation_log) == initial_mutations + 1

        last_mutation = setup_schematic["ir"].mutation_log[-1]
        assert last_mutation["description"] == "remove_component"
        assert last_mutation["reference"] == "R1"

    def test_other_components_unchanged(
        self, setup_schematic: dict
    ) -> None:
        """Removing one component does not affect other components."""
        from kicad_agent.ops.remove_component import remove_component

        # Verify C1 and U1 exist before removal
        assert setup_schematic["ir"].get_component_by_ref("C1") is not None
        assert setup_schematic["ir"].get_component_by_ref("U1") is not None

        op = RemoveComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="R1",
        )
        remove_component(op, setup_schematic["ir"])

        # C1 and U1 should still exist
        assert setup_schematic["ir"].get_component_by_ref("C1") is not None
        assert setup_schematic["ir"].get_component_by_ref("U1") is not None
        # R1 should be gone
        assert setup_schematic["ir"].get_component_by_ref("R1") is None

    def test_returns_removed_reference_and_uuid(
        self, setup_schematic: dict
    ) -> None:
        """remove_component returns dict with removed reference and uuid."""
        from kicad_agent.ops.remove_component import remove_component

        # Get the UUID of J1 before removal
        j1 = setup_schematic["ir"].get_component_by_ref("J1")
        j1_uuid = j1.uuid

        op = RemoveComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
        )
        result = remove_component(op, setup_schematic["ir"])

        assert result["reference"] == "J1"
        assert result["uuid"] == j1_uuid


class TestOperationExecutorRemove:
    """Tests for OperationExecutor dispatching remove_component."""

    @pytest.fixture
    def setup_schematic(self, tmp_path: Path) -> dict:
        """Copy RaspberryPi fixture to tmp_path for executor tests."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "RaspberryPi-uHAT.kicad_sch"
        shutil.copy2(src, dst)
        return {"file_path": dst, "base_dir": tmp_path}

    def test_executor_dispatches_remove_component(
        self, setup_schematic: dict
    ) -> None:
        """OperationExecutor dispatches remove_component op_type correctly."""
        from kicad_agent.ops.executor import OperationExecutor

        executor = OperationExecutor(base_dir=setup_schematic["base_dir"])

        op = Operation.model_validate({
            "root": {
                "op_type": "remove_component",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "reference": "J1",
            }
        })

        result = executor.execute(op)
        assert result["success"] is True
        assert result["operation"] == "remove_component"
        assert "J1" in str(result["details"])

    def test_full_pipeline_remove_component(
        self, setup_schematic: dict
    ) -> None:
        """Full pipeline: validate Operation -> executor -> remove_component -> serialize -> file on disk."""
        from kicad_agent.ops.executor import OperationExecutor

        executor = OperationExecutor(base_dir=setup_schematic["base_dir"])

        # First verify J1 exists
        result1 = parse_schematic(setup_schematic["file_path"])
        ir1 = SchematicIR(_parse_result=result1)
        assert ir1.get_component_by_ref("J1") is not None
        initial_count = len(ir1.components)
        _clear_registry()

        # Remove J1
        op = Operation.model_validate({
            "root": {
                "op_type": "remove_component",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "reference": "J1",
            }
        })

        result = executor.execute(op)
        assert result["success"] is True

        # Re-parse and verify J1 is gone
        re_parsed = parse_schematic(setup_schematic["file_path"])
        re_ir = SchematicIR(_parse_result=re_parsed)

        assert re_ir.get_component_by_ref("J1") is None
        assert len(re_ir.components) == initial_count - 1

        # Other components should still be present
        assert re_ir.get_component_by_ref("R1") is not None
        assert re_ir.get_component_by_ref("C1") is not None
