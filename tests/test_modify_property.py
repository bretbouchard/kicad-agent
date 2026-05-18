"""Tests for modify_property operation -- TDD RED phase.

Verifies:
- modify_property updates an existing property value (e.g., Value "GPIO" -> "MyConnector")
- modify_property updates the Reference property and also updates the instances list
- modify_property adds a new custom property when property_name does not exist
- modify_property raises ModifyPropertyError when reference not found
- modify_property records mutation with old and new values
- After modification, re-parsing the serialized file shows the new value
- Modifying the Reference property updates symbol_instances when present
- OperationExecutor dispatches modify_property op_type correctly
"""

import shutil
from pathlib import Path

import pytest

from kicad_agent.ir.base import _clear_registry
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ops.schema import ModifyPropertyOp, Operation
from kicad_agent.parser import parse_schematic
from kicad_agent.serializer import serialize_schematic


@pytest.fixture(autouse=True)
def _reset_ir_registry():
    """Clear the IR registry before and after each test."""
    _clear_registry()
    yield
    _clear_registry()


FIXTURE_DIR = Path(__file__).parent / "fixtures"


class TestModifyProperty:
    """Tests for the modify_property operation handler."""

    @pytest.fixture
    def setup_schematic(self, tmp_path: Path) -> dict:
        """Copy RaspberryPi fixture to tmp_path, parse it, return IR and paths."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "RaspberryPi-uHAT.kicad_sch"
        shutil.copy2(src, dst)
        result = parse_schematic(dst)
        ir = SchematicIR(_parse_result=result)
        return {"ir": ir, "file_path": dst, "parse_result": result}

    def test_modify_value(self, setup_schematic: dict) -> None:
        """modify_property updates an existing Value property."""
        from kicad_agent.ops.modify_property import modify_property

        # J1 has Value="GPIO" in the fixture
        op = ModifyPropertyOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
            property_name="Value",
            new_value="MyConnector",
        )
        result = modify_property(op, setup_schematic["ir"])

        component = setup_schematic["ir"].get_component_by_ref("J1")
        assert component is not None
        assert _get_prop(component, "Value") == "MyConnector"
        assert result["old_value"] == "GPIO"
        assert result["new_value"] == "MyConnector"

    def test_modify_footprint(self, setup_schematic: dict) -> None:
        """modify_property updates the Footprint property."""
        from kicad_agent.ops.modify_property import modify_property

        op = ModifyPropertyOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
            property_name="Footprint",
            new_value="Connector:USB_A",
        )
        modify_property(op, setup_schematic["ir"])

        component = setup_schematic["ir"].get_component_by_ref("J1")
        assert component is not None
        assert _get_prop(component, "Footprint") == "Connector:USB_A"

    def test_modify_reference(self, setup_schematic: dict) -> None:
        """modify_property updates the Reference property on the component."""
        from kicad_agent.ops.modify_property import modify_property

        op = ModifyPropertyOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
            property_name="Reference",
            new_value="J99",
        )
        modify_property(op, setup_schematic["ir"])

        # After changing Reference from J1 to J99, the old ref lookup should fail
        assert setup_schematic["ir"].get_component_by_ref("J1") is None
        # New ref should find the component
        component = setup_schematic["ir"].get_component_by_ref("J99")
        assert component is not None
        assert _get_prop(component, "Reference") == "J99"

    def test_modify_reference_updates_instances(self, setup_schematic: dict) -> None:
        """modifying the Reference property updates symbol_instances when present."""
        from kiutils.items.common import Property
        from kiutils.schematic import SymbolProjectInstance, SymbolProjectPath

        from kicad_agent.ops.modify_property import modify_property

        # Add a mock symbolInstance for J1 so we can verify it gets updated
        sch = setup_schematic["ir"]._parse_result.kiutils_obj
        mock_path = SymbolProjectPath(
            sheetInstancePath="/abc123",
            reference="J1",
        )
        mock_instance = SymbolProjectInstance(
            paths=[mock_path],
        )
        sch.symbolInstances = [mock_instance]

        op = ModifyPropertyOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
            property_name="Reference",
            new_value="J99",
        )
        modify_property(op, setup_schematic["ir"])

        # Instance path reference should be updated to J99
        assert sch.symbolInstances[0].paths[0].reference == "J99"

    def test_add_custom_property(self, setup_schematic: dict) -> None:
        """modify_property adds a new custom property when it does not exist."""
        from kicad_agent.ops.modify_property import modify_property

        op = ModifyPropertyOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
            property_name="Manufacturer",
            new_value="Amphenol",
        )
        result = modify_property(op, setup_schematic["ir"])

        component = setup_schematic["ir"].get_component_by_ref("J1")
        assert component is not None
        assert _get_prop(component, "Manufacturer") == "Amphenol"
        assert result["old_value"] is None  # new property has no old value

    def test_add_custom_property_has_id(self, setup_schematic: dict) -> None:
        """New custom property gets correct sequential id."""
        from kicad_agent.ops.modify_property import modify_property

        component = setup_schematic["ir"].get_component_by_ref("J1")
        assert component is not None
        existing_count = len(component.properties)

        op = ModifyPropertyOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
            property_name="MPN",
            new_value="ABC-123",
        )
        modify_property(op, setup_schematic["ir"])

        component = setup_schematic["ir"].get_component_by_ref("J1")
        assert component is not None
        assert len(component.properties) == existing_count + 1
        # New property should be last in the list
        new_prop = component.properties[-1]
        assert new_prop.key == "MPN"
        assert new_prop.value == "ABC-123"

    def test_modify_not_found_component(self, setup_schematic: dict) -> None:
        """modify_property raises ModifyPropertyError when reference not found."""
        from kicad_agent.ops.modify_property import ModifyPropertyError, modify_property

        op = ModifyPropertyOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="X999",
            property_name="Value",
            new_value="test",
        )

        with pytest.raises(ModifyPropertyError, match="Component not found"):
            modify_property(op, setup_schematic["ir"])

    def test_modify_mutation_logged(self, setup_schematic: dict) -> None:
        """modify_property records mutation with old and new values."""
        from kicad_agent.ops.modify_property import modify_property

        initial_mutations = len(setup_schematic["ir"].mutation_log)

        op = ModifyPropertyOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
            property_name="Value",
            new_value="UpdatedGPIO",
        )
        modify_property(op, setup_schematic["ir"])

        assert len(setup_schematic["ir"].mutation_log) == initial_mutations + 1
        last_mutation = setup_schematic["ir"].mutation_log[-1]
        assert last_mutation["description"] == "modify_property"
        assert last_mutation["reference"] == "J1"
        assert last_mutation["property"] == "Value"
        assert last_mutation["old_value"] == "GPIO"
        assert last_mutation["new_value"] == "UpdatedGPIO"

    def test_modify_reparse(self, setup_schematic: dict) -> None:
        """After modification, re-parsing the serialized file shows the new value."""
        from kicad_agent.ops.modify_property import modify_property

        op = ModifyPropertyOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
            property_name="Value",
            new_value="MyNewValue",
        )
        modify_property(op, setup_schematic["ir"])

        # Serialize
        serialize_schematic(setup_schematic["parse_result"], setup_schematic["file_path"])

        # Re-parse
        re_parsed = parse_schematic(setup_schematic["file_path"])
        re_ir = SchematicIR(_parse_result=re_parsed)
        component = re_ir.get_component_by_ref("J1")
        assert component is not None
        assert _get_prop(component, "Value") == "MyNewValue"

    def test_modify_preserves_other_properties(self, setup_schematic: dict) -> None:
        """Modifying Value does not change Footprint or other properties."""
        from kicad_agent.ops.modify_property import modify_property

        component = setup_schematic["ir"].get_component_by_ref("J1")
        assert component is not None
        original_footprint = _get_prop(component, "Footprint")
        original_datasheet = _get_prop(component, "Datasheet")

        op = ModifyPropertyOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            reference="J1",
            property_name="Value",
            new_value="NewVal",
        )
        modify_property(op, setup_schematic["ir"])

        component = setup_schematic["ir"].get_component_by_ref("J1")
        assert component is not None
        assert _get_prop(component, "Footprint") == original_footprint
        assert _get_prop(component, "Datasheet") == original_datasheet


class TestModifyPropertyExecutor:
    """Tests for OperationExecutor dispatching modify_property."""

    @pytest.fixture
    def setup_schematic(self, tmp_path: Path) -> dict:
        """Copy RaspberryPi fixture to tmp_path for executor tests."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "RaspberryPi-uHAT.kicad_sch"
        shutil.copy2(src, dst)
        return {"file_path": dst, "base_dir": tmp_path}

    def test_executor_dispatch(self, setup_schematic: dict) -> None:
        """OperationExecutor dispatches modify_property op_type correctly."""
        from kicad_agent.ops.executor import OperationExecutor

        executor = OperationExecutor(base_dir=setup_schematic["base_dir"])

        op = Operation.model_validate({
            "root": {
                "op_type": "modify_property",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "reference": "J1",
                "property_name": "Value",
                "new_value": "TestValue",
            }
        })

        result = executor.execute(op)
        assert result["success"] is True
        assert result["operation"] == "modify_property"
        assert "J1" in str(result["details"])


def _get_prop(component, key: str) -> str | None:
    """Helper to get a property value from a component."""
    for prop in component.properties:
        if prop.key == key:
            return prop.value
    return None
