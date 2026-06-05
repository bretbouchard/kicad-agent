"""Tests for add_component operation -- TDD RED phase.

Verifies:
- add_component creates a SchematicSymbol with correct library_id, reference, value, position
- add_component generates a valid UUID v4 for the new symbol
- add_component creates standard properties (Reference, Value, Footprint, Datasheet)
- add_component sets inBom=True, onBoard=True
- add_component appends to SchematicIR.components and records mutation
- add_component raises AddComponentError on invalid library_id (missing colon)
- add_component raises AddComponentError on duplicate reference
- OperationExecutor dispatches add_component correctly
- OperationExecutor raises ValueError for unknown op_type
- Full pipeline: validate Operation -> executor -> add_component -> serialize -> file on disk
"""

import shutil
import uuid
from pathlib import Path

import pytest

from kicad_agent.ir.base import _clear_registry
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ops.schema import AddComponentOp, Operation, PositionSpec
from kicad_agent.parser import parse_schematic
from kicad_agent.serializer import serialize_schematic


@pytest.fixture(autouse=True)
def _reset_ir_registry():
    """Clear the IR registry before and after each test."""
    _clear_registry()
    yield
    _clear_registry()


FIXTURE_DIR = Path(__file__).parent / "fixtures"


class TestAddComponent:
    """Tests for the add_component operation handler."""

    @pytest.fixture
    def setup_schematic(self, tmp_path: Path) -> dict:
        """Copy RaspberryPi fixture to tmp_path, parse it, return IR and paths."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "RaspberryPi-uHAT.kicad_sch"
        shutil.copy2(src, dst)
        result = parse_schematic(dst)
        ir = SchematicIR(_parse_result=result)
        return {"ir": ir, "file_path": dst, "parse_result": result}

    def test_creates_symbol_with_correct_library_reference(
        self, setup_schematic: dict
    ) -> None:
        """add_component creates a SchematicSymbol with correct libraryNickname and entryName."""
        from kicad_agent.ops.add_component import add_component

        op = AddComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            library_id="Device:R_Small_US",
            reference="R99",
            value="10k",
            position=PositionSpec(x=50.0, y=30.0),
        )
        result = add_component(op, setup_schematic["ir"], setup_schematic["file_path"])

        # Find the newly added component
        component = setup_schematic["ir"].get_component_by_ref("R99")
        assert component is not None
        assert component.libraryNickname == "Device"
        assert component.entryName == "R_Small_US"
        assert component.libName == "Device:R_Small_US"

    def test_generates_valid_uuid_v4(self, setup_schematic: dict) -> None:
        """add_component generates a valid UUID v4 for the new symbol."""
        from kicad_agent.ops.add_component import add_component

        op = AddComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            library_id="Device:R_Small_US",
            reference="R100",
            value="4.7k",
            position=PositionSpec(x=25.0, y=40.0),
        )
        result = add_component(op, setup_schematic["ir"], setup_schematic["file_path"])

        # UUID should be valid v4
        parsed_uuid = uuid.UUID(result["uuid"])
        assert parsed_uuid.version == 4

        # Component should have the same UUID
        component = setup_schematic["ir"].get_component_by_ref("R100")
        assert component is not None
        component_uuid = uuid.UUID(component.uuid)
        assert component_uuid.version == 4

    def test_creates_standard_properties(self, setup_schematic: dict) -> None:
        """add_component creates Reference, Value, Footprint, Datasheet properties."""
        from kicad_agent.ops.add_component import add_component

        op = AddComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            library_id="Device:C_Small",
            reference="C99",
            value="100nF",
            position=PositionSpec(x=10.0, y=20.0),
        )
        add_component(op, setup_schematic["ir"], setup_schematic["file_path"])

        component = setup_schematic["ir"].get_component_by_ref("C99")
        assert component is not None

        props = {p.key: p for p in component.properties}
        assert "Reference" in props
        assert props["Reference"].value == "C99"
        assert "Value" in props
        assert props["Value"].value == "100nF"
        assert "Footprint" in props
        assert "Datasheet" in props

    def test_sets_inbom_and_onboard(self, setup_schematic: dict) -> None:
        """add_component sets inBom=True and onBoard=True (KiCad defaults for real components)."""
        from kicad_agent.ops.add_component import add_component

        op = AddComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            library_id="Device:R_Small_US",
            reference="R101",
            value="1k",
            position=PositionSpec(x=5.0, y=10.0),
        )
        add_component(op, setup_schematic["ir"], setup_schematic["file_path"])

        component = setup_schematic["ir"].get_component_by_ref("R101")
        assert component is not None
        assert component.inBom is True
        assert component.onBoard is True

    def test_appends_to_components_and_records_mutation(
        self, setup_schematic: dict
    ) -> None:
        """add_component appends to SchematicIR.components and records mutation."""
        from kicad_agent.ops.add_component import add_component

        initial_count = len(setup_schematic["ir"].components)
        initial_mutations = len(setup_schematic["ir"].mutation_log)

        op = AddComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            library_id="Device:R_Small_US",
            reference="R102",
            value="2.2k",
            position=PositionSpec(x=15.0, y=25.0),
        )
        add_component(op, setup_schematic["ir"], setup_schematic["file_path"])

        assert len(setup_schematic["ir"].components) == initial_count + 1
        assert len(setup_schematic["ir"].mutation_log) == initial_mutations + 1

        last_mutation = setup_schematic["ir"].mutation_log[-1]
        assert last_mutation["type"] == "add_component"
        assert last_mutation["reference"] == "R102"

    def test_raises_on_invalid_library_id(self, setup_schematic: dict) -> None:
        """add_component raises AddComponentError when library_id has no colon."""
        from kicad_agent.ops.add_component import AddComponentError, add_component

        op = AddComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            library_id="InvalidNoColon",
            reference="R103",
            value="1k",
            position=PositionSpec(x=5.0, y=10.0),
        )

        with pytest.raises(AddComponentError, match="library_id"):
            add_component(op, setup_schematic["ir"], setup_schematic["file_path"])

    def test_raises_on_duplicate_reference(self, setup_schematic: dict) -> None:
        """add_component raises AddComponentError when reference already exists."""
        from kicad_agent.ops.add_component import AddComponentError, add_component

        # J1 already exists in the RaspberryPi fixture
        op = AddComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            library_id="Device:R_Small_US",
            reference="J1",
            value="10k",
            position=PositionSpec(x=5.0, y=10.0),
        )

        with pytest.raises(AddComponentError, match="already exists"):
            add_component(op, setup_schematic["ir"], setup_schematic["file_path"])

    def test_position_matches_input(self, setup_schematic: dict) -> None:
        """add_component sets the correct position coordinates."""
        from kicad_agent.ops.add_component import add_component

        op = AddComponentOp(
            target_file="RaspberryPi-uHAT.kicad_sch",
            library_id="Device:R_Small_US",
            reference="R104",
            value="330",
            position=PositionSpec(x=42.5, y=67.3, angle=90.0),
        )
        add_component(op, setup_schematic["ir"], setup_schematic["file_path"])

        component = setup_schematic["ir"].get_component_by_ref("R104")
        assert component is not None
        assert component.position.X == 42.5
        assert component.position.Y == 67.3
        assert component.position.angle == 90.0


class TestOperationExecutorAdd:
    """Tests for OperationExecutor dispatching add_component."""

    @pytest.fixture
    def setup_schematic(self, tmp_path: Path) -> dict:
        """Copy RaspberryPi fixture to tmp_path for executor tests."""
        src = FIXTURE_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
        dst = tmp_path / "RaspberryPi-uHAT.kicad_sch"
        shutil.copy2(src, dst)
        return {"file_path": dst, "base_dir": tmp_path}

    def test_executor_dispatches_add_component(
        self, setup_schematic: dict
    ) -> None:
        """OperationExecutor dispatches add_component op_type correctly."""
        from kicad_agent.ops.executor import OperationExecutor

        executor = OperationExecutor(base_dir=setup_schematic["base_dir"])

        op = Operation.model_validate({
            "root": {
                "op_type": "add_component",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "library_id": "Device:R_Small_US",
                "reference": "R200",
                "value": "10k",
                "position": {"x": 250.0, "y": 200.0},
            }
        })

        result = executor.execute(op)
        assert result["success"] is True
        assert result["operation"] == "add_component"
        assert "R200" in str(result["details"])

    def test_executor_raises_on_unknown_op_type(self) -> None:
        """OperationExecutor raises ValueError for unknown op_type."""
        # This test validates the dispatch guard without needing a file
        from kicad_agent.ops.executor import OperationExecutor

        executor = OperationExecutor(base_dir=Path("/tmp"))

        # Create an Operation with unknown op_type via model_construct to bypass validation
        # Since Pydantic validates op_type, we test the dispatch guard differently
        # by checking that the executor handles all known types and raises on unknown
        with pytest.raises(ValueError, match="Unknown op_type"):
            executor._dispatch("unknown_type", None, None, None)

    def test_full_pipeline_add_component(
        self, setup_schematic: dict
    ) -> None:
        """Full pipeline: validate Operation -> executor -> add_component -> serialize -> file on disk."""
        from kicad_agent.ops.executor import OperationExecutor

        executor = OperationExecutor(base_dir=setup_schematic["base_dir"])

        op = Operation.model_validate({
            "root": {
                "op_type": "add_component",
                "target_file": "RaspberryPi-uHAT.kicad_sch",
                "library_id": "Device:C_Small",
                "reference": "C200",
                "value": "22uF",
                "position": {"x": 100.0, "y": 200.0},
            }
        })

        result = executor.execute(op)
        assert result["success"] is True

        # Re-parse the file and verify the component is present
        re_parsed = parse_schematic(setup_schematic["file_path"])
        re_ir = SchematicIR(_parse_result=re_parsed)
        component = re_ir.get_component_by_ref("C200")
        assert component is not None

        # Verify properties on re-parsed component
        props = {p.key: p for p in component.properties}
        assert props["Reference"].value == "C200"
        assert props["Value"].value == "22uF"
        assert component.position.X == 100.0
        assert component.position.Y == 200.0

        # Verify UUID is valid
        parsed_uuid = uuid.UUID(component.uuid)
        assert parsed_uuid.version == 4
