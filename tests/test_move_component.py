"""Tests for move_component operation -- TDD RED phase.

Verifies:
- move_component updates the component's position to the requested coordinates
- Schematic coordinates are rounded to 4 decimal places
- move sets the angle field (rotation) correctly
- move with angle=0.0 sets angle to None (KiCad convention for no rotation)
- move_component raises MoveComponentError when reference not found
- After move, re-parsing the serialized file shows the new position
- Moving a component preserves all other properties unchanged
- Move records mutation in IR log with old and new positions
- OperationExecutor dispatches move_component op_type correctly
"""

import shutil
from pathlib import Path

import pytest

from volta.ir.base import _clear_registry
from volta.ir.schematic_ir import SchematicIR
from volta.ops.schema import MoveComponentOp, Operation, PositionSpec
from volta.parser import parse_schematic
from volta.serializer import serialize_schematic


@pytest.fixture(autouse=True)
def _reset_ir_registry():
    """Clear the IR registry before and after each test."""
    _clear_registry()
    yield
    _clear_registry()


FIXTURE_DIR = Path(__file__).parent / "fixtures"


class TestMoveComponent:
    """Tests for the move_component operation handler."""

    @pytest.fixture
    def setup_schematic(self, tmp_path: Path) -> dict:
        """Copy RaspberryPi fixture to tmp_path, parse it, return IR and paths."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "RaspberryPi-uHAT.kicad_sch"
        shutil.copy2(src, dst)
        result = parse_schematic(dst)
        ir = SchematicIR(_parse_result=result)
        return {"ir": ir, "file_path": dst, "parse_result": result}

    def test_move_updates_position(self, setup_schematic: dict) -> None:
        """move_component updates the component's position to the requested coordinates."""
        from volta.ops.move_component import move_component

        # J1 is at (66.04, 50.8) in the fixture
        op = MoveComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
            position=PositionSpec(x=100.0, y=75.0),
        )
        result = move_component(op, setup_schematic["ir"])

        component = setup_schematic["ir"].get_component_by_ref("J1")
        assert component is not None
        assert component.position.X == 100.0
        assert component.position.Y == 75.0

        assert result["reference"] == "J1"
        assert result["new_position"]["x"] == 100.0
        assert result["new_position"]["y"] == 75.0

    def test_move_schematic_precision(self, setup_schematic: dict) -> None:
        """Schematic coordinates are rounded to 4 decimal places."""
        from volta.ops.move_component import move_component

        op = MoveComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
            position=PositionSpec(x=100.123456, y=200.654321),
        )
        move_component(op, setup_schematic["ir"])

        component = setup_schematic["ir"].get_component_by_ref("J1")
        assert component is not None
        assert component.position.X == 100.1235  # rounded to 4 decimals
        assert component.position.Y == 200.6543  # rounded to 4 decimals

    def test_move_with_rotation(self, setup_schematic: dict) -> None:
        """move sets the angle field correctly for non-zero rotation."""
        from volta.ops.move_component import move_component

        op = MoveComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
            position=PositionSpec(x=50.0, y=60.0, angle=90.0),
        )
        move_component(op, setup_schematic["ir"])

        component = setup_schematic["ir"].get_component_by_ref("J1")
        assert component is not None
        assert component.position.angle == 90.0

    def test_move_zero_angle(self, setup_schematic: dict) -> None:
        """move with angle=0.0 sets angle to None (KiCad convention)."""
        from volta.ops.move_component import move_component

        op = MoveComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
            position=PositionSpec(x=50.0, y=60.0, angle=0.0),
        )
        move_component(op, setup_schematic["ir"])

        component = setup_schematic["ir"].get_component_by_ref("J1")
        assert component is not None
        assert component.position.angle is None

    def test_move_preserves_properties(self, setup_schematic: dict) -> None:
        """Moving a component preserves all other properties unchanged."""
        from volta.ops.move_component import move_component

        # Get original properties
        component = setup_schematic["ir"].get_component_by_ref("J1")
        assert component is not None
        original_value = ir_get_property(component, "Value")
        original_footprint = ir_get_property(component, "Footprint")

        op = MoveComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
            position=PositionSpec(x=100.0, y=75.0),
        )
        move_component(op, setup_schematic["ir"])

        # Verify properties unchanged
        component = setup_schematic["ir"].get_component_by_ref("J1")
        assert component is not None
        assert ir_get_property(component, "Value") == original_value
        assert ir_get_property(component, "Footprint") == original_footprint

    def test_move_not_found(self, setup_schematic: dict) -> None:
        """move_component raises MoveComponentError when reference not found."""
        from volta.ops.move_component import MoveComponentError, move_component

        op = MoveComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="X999",
            position=PositionSpec(x=10.0, y=20.0),
        )

        with pytest.raises(MoveComponentError, match="Component not found"):
            move_component(op, setup_schematic["ir"])

    def test_move_mutation_logged(self, setup_schematic: dict) -> None:
        """Move records mutation in IR log with old and new positions."""
        from volta.ops.move_component import move_component

        initial_mutations = len(setup_schematic["ir"].mutation_log)

        op = MoveComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
            position=PositionSpec(x=100.0, y=75.0),
        )
        move_component(op, setup_schematic["ir"])

        assert len(setup_schematic["ir"].mutation_log) == initial_mutations + 1
        last_mutation = setup_schematic["ir"].mutation_log[-1]
        assert last_mutation["type"] == "move_component"
        assert last_mutation["reference"] == "J1"
        assert "old_position" in last_mutation
        assert "new_position" in last_mutation

    def test_move_reparse(self, setup_schematic: dict) -> None:
        """After move, re-parsing the serialized file shows the new position."""
        from volta.ops.move_component import move_component

        op = MoveComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
            position=PositionSpec(x=100.0, y=75.0),
        )
        move_component(op, setup_schematic["ir"])

        # Serialize
        serialize_schematic(setup_schematic["parse_result"], setup_schematic["file_path"])

        # Re-parse
        re_parsed = parse_schematic(setup_schematic["file_path"])
        re_ir = SchematicIR(_parse_result=re_parsed)
        component = re_ir.get_component_by_ref("J1")
        assert component is not None
        assert component.position.X == 100.0
        assert component.position.Y == 75.0


class TestMoveComponentExecutor:
    """Tests for OperationExecutor dispatching move_component."""

    @pytest.fixture
    def setup_schematic(self, tmp_path: Path) -> dict:
        """Copy RaspberryPi fixture to tmp_path for executor tests."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "RaspberryPi-uHAT.kicad_sch"
        shutil.copy2(src, dst)
        return {"file_path": dst, "base_dir": tmp_path}

    def test_executor_dispatch(self, setup_schematic: dict) -> None:
        """OperationExecutor dispatches move_component op_type correctly."""
        from volta.ops.executor import OperationExecutor

        executor = OperationExecutor(base_dir=setup_schematic["base_dir"])

        op = Operation.model_validate({
            "root": {
                "op_type": "move_component",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "reference": "J1",
                "position": {"x": 100.0, "y": 75.0},
            }
        })

        result = executor.execute(op)
        assert result["success"] is True
        assert result["operation"] == "move_component"
        assert "J1" in str(result["details"])


def ir_get_property(component, key: str) -> str | None:
    """Helper to get a property value from a component."""
    for prop in component.properties:
        if prop.key == key:
            return prop.value
    return None
