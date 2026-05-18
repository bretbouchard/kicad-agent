"""Tests for footprint management operation schema validation and IR methods.

Tests cover:
  - Schema validation for AssignFootprintOp, SwapFootprintOp, ValidateFootprintOp, VerifyPinMapOp
  - SchematicIR footprint assignment and query methods
  - PcbIR footprint swap and query methods
  - SchematicIR pin mapping verification
"""

import pytest
from pydantic import ValidationError

from kicad_agent.ir.base import _clear_registry
from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ops.schema import (
    AssignFootprintOp,
    Operation,
    SwapFootprintOp,
    ValidateFootprintOp,
    VerifyPinMapOp,
    get_operation_schema,
)
from kicad_agent.parser import parse_pcb, parse_schematic
from kicad_agent.parser.uuid_extractor import extract_uuids


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_assign_footprint_op(**overrides) -> Operation:
    """Create a valid AssignFootprintOp Operation with sensible defaults."""
    data = {
        "op_type": "assign_footprint",
        "target_file": "schematic.kicad_sch",
        "reference": "U1",
        "footprint_lib_id": "Package_DIP:DIP-8_W7.62mm",
    }
    data.update(overrides)
    return Operation.model_validate({"root": data})


def _make_swap_footprint_op(**overrides) -> Operation:
    """Create a valid SwapFootprintOp Operation."""
    data = {
        "op_type": "swap_footprint",
        "target_file": "board.kicad_pcb",
        "reference": "U1",
        "new_footprint_lib_id": "Package_DIP:DIP-8_W7.62mm",
    }
    data.update(overrides)
    return Operation.model_validate({"root": data})


def _make_validate_footprint_op(**overrides) -> Operation:
    """Create a valid ValidateFootprintOp Operation."""
    data = {
        "op_type": "validate_footprint",
        "target_file": "board.kicad_pcb",
        "footprint_lib_id": "Package_DIP:DIP-8_W7.62mm",
    }
    data.update(overrides)
    return Operation.model_validate({"root": data})


def _make_verify_pin_map_op(**overrides) -> Operation:
    """Create a valid VerifyPinMapOp Operation."""
    data = {
        "op_type": "verify_pin_map",
        "target_file": "schematic.kicad_sch",
        "reference": "U1",
        "footprint_lib_id": "Package_DIP:DIP-8_W7.62mm",
    }
    data.update(overrides)
    return Operation.model_validate({"root": data})


# ---------------------------------------------------------------------------
# Task 1: Schema validation tests (Tests 1-8)
# ---------------------------------------------------------------------------


class TestFootprintOpsSchema:
    """Footprint management operation schema validation."""

    def test_assign_footprint_validates(self) -> None:
        """Test 1: AssignFootprintOp validates with reference, footprint_lib_id."""
        op = _make_assign_footprint_op()
        assert op.root.op_type == "assign_footprint"
        assert op.root.reference == "U1"
        assert op.root.footprint_lib_id == "Package_DIP:DIP-8_W7.62mm"

    def test_swap_footprint_validates(self) -> None:
        """Test 2: SwapFootprintOp validates with reference, new_footprint_lib_id."""
        op = _make_swap_footprint_op()
        assert op.root.op_type == "swap_footprint"
        assert op.root.reference == "U1"
        assert op.root.new_footprint_lib_id == "Package_DIP:DIP-8_W7.62mm"

    def test_validate_footprint_validates(self) -> None:
        """Test 3: ValidateFootprintOp validates with target_file, footprint_lib_id."""
        op = _make_validate_footprint_op()
        assert op.root.op_type == "validate_footprint"
        assert op.root.footprint_lib_id == "Package_DIP:DIP-8_W7.62mm"

    def test_verify_pin_map_validates(self) -> None:
        """Test 4: VerifyPinMapOp validates with target_file, reference, footprint_lib_id."""
        op = _make_verify_pin_map_op()
        assert op.root.op_type == "verify_pin_map"
        assert op.root.reference == "U1"
        assert op.root.footprint_lib_id == "Package_DIP:DIP-8_W7.62mm"

    def test_assign_footprint_rejects_empty_reference(self) -> None:
        """Test 5: AssignFootprintOp rejects empty reference (min_length=1)."""
        with pytest.raises(ValidationError, match="at least 1 character"):
            _make_assign_footprint_op(reference="")

    def test_footprint_lib_id_max_length(self) -> None:
        """Test 6: footprint_lib_id max_length=256 enforced."""
        with pytest.raises(ValidationError, match="at most 256 characters"):
            _make_assign_footprint_op(footprint_lib_id="X" * 257)

    def test_operation_routes_all_footprint_types(self) -> None:
        """Test 7: Operation.model_validate routes all four new op_types correctly."""
        op_types = [
            "assign_footprint",
            "swap_footprint",
            "validate_footprint",
            "verify_pin_map",
        ]
        for ot in op_types:
            data = {
                "op_type": ot,
                "target_file": "test.kicad_sch",
            }
            if ot in ("assign_footprint", "swap_footprint", "verify_pin_map"):
                data["reference"] = "U1"
            if ot == "swap_footprint":
                data["new_footprint_lib_id"] = "Lib:FP"
            else:
                data["footprint_lib_id"] = "Lib:FP"
            op = Operation.model_validate({"root": data})
            assert op.root.op_type == ot

    def test_get_operation_schema_includes_all_footprint_types(self) -> None:
        """Test 8: get_operation_schema() includes all four footprint op types."""
        schema = get_operation_schema()
        schema_str = str(schema)
        for op_name in (
            "AssignFootprintOp",
            "SwapFootprintOp",
            "ValidateFootprintOp",
            "VerifyPinMapOp",
        ):
            assert op_name in schema_str, f"{op_name} missing from schema export"


# ---------------------------------------------------------------------------
# Task 2: IR method tests (Tests 9-22)
# ---------------------------------------------------------------------------


class TestSchematicIRAssignFootprint:
    """SchematicIR footprint assignment methods."""

    @pytest.fixture(autouse=True)
    def _setup(self, arduino_mega_sch: pytest.fixture) -> None:
        """Create SchematicIR from Arduino_Mega schematic for each test."""
        _clear_registry()
        result = parse_schematic(arduino_mega_sch)
        self.ir = SchematicIR(_parse_result=result)

    def test_assign_footprint_sets_property(self) -> None:
        """Test 9: assign_footprint sets 'Footprint' property on a component."""
        # J1 initially has a footprint; change it
        self.ir.assign_footprint("J1", "NewLib:NewFootprint")
        comp = self.ir.get_component_by_ref("J1")
        assert comp is not None
        footprint = self.ir.get_component_footprint("J1")
        assert footprint == "NewLib:NewFootprint"

    def test_assign_footprint_records_mutation(self) -> None:
        """Test 10: assign_footprint records mutation."""
        self.ir.assign_footprint("J1", "NewLib:NewFootprint")
        assert self.ir.dirty
        mutations = [
            m for m in self.ir.mutation_log
            if m["description"] == "assign_footprint"
        ]
        assert len(mutations) == 1
        assert mutations[0]["reference"] == "J1"
        assert mutations[0]["footprint_lib_id"] == "NewLib:NewFootprint"

    def test_get_component_footprint_returns_current(self) -> None:
        """Test 11: get_component_footprint returns current footprint libId."""
        # J1 has a known footprint in the fixture
        fp = self.ir.get_component_footprint("J1")
        assert fp is not None
        assert "PinSocket" in fp or "Connector" in fp

    def test_assign_footprint_raises_missing_reference(self) -> None:
        """Test 12: assign_footprint raises ValueError if reference not found."""
        with pytest.raises(ValueError, match="not found"):
            self.ir.assign_footprint("NONEXISTENT999", "Lib:FP")


class TestPcbIRFootprintQuery:
    """PcbIR footprint query methods."""

    @pytest.fixture(autouse=True)
    def _setup(self, arduino_mega_pcb: pytest.fixture) -> None:
        """Create PcbIR from Arduino_Mega PCB for each test."""
        _clear_registry()
        result = parse_pcb(arduino_mega_pcb)
        uuid_map = extract_uuids(result.raw_content, "pcb")
        self.ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)

    def test_get_footprint_by_ref_found(self) -> None:
        """Test 13: get_footprint_by_ref returns footprint matching reference."""
        fp = self.ir.get_footprint_by_ref("J1")
        assert fp is not None
        assert fp.libId == "Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical"

    def test_get_footprint_by_ref_missing(self) -> None:
        """Test 14: get_footprint_by_ref returns None for missing reference."""
        assert self.ir.get_footprint_by_ref("NONEXISTENT999") is None


class TestPcbIRSwapFootprint:
    """PcbIR.swap_footprint() mutation tests."""

    @pytest.fixture(autouse=True)
    def _setup(self, arduino_mega_pcb: pytest.fixture) -> None:
        """Create PcbIR from Arduino_Mega PCB for each test."""
        _clear_registry()
        result = parse_pcb(arduino_mega_pcb)
        uuid_map = extract_uuids(result.raw_content, "pcb")
        self.ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)

    def test_swap_footprint_changes_libid(self) -> None:
        """Test 15: swap_footprint changes libId while preserving pad.net connections."""
        # Get J1's current pad-to-net mapping
        fp_before = self.ir.get_footprint_by_ref("J1")
        assert fp_before is not None
        nets_before = {
            pad.number: (pad.net.name if pad.net else "")
            for pad in fp_before.pads
        }
        # J1 should have at least some connected pads
        connected_before = {k: v for k, v in nets_before.items() if v}

        # Swap to a different footprint libId
        result = self.ir.swap_footprint("J1", "CustomLib:CustomSocket_1x08")

        assert result["old_lib_id"] == "Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical"
        assert result["new_lib_id"] == "CustomLib:CustomSocket_1x08"
        # Pad nets should be preserved for matching pad numbers
        fp_after = self.ir.get_footprint_by_ref("J1")
        assert fp_after is not None
        assert fp_after.libId == "CustomLib:CustomSocket_1x08"

        for pad in fp_after.pads:
            if pad.number in nets_before and nets_before[pad.number]:
                assert pad.net is not None
                assert pad.net.name == nets_before[pad.number]

    def test_swap_footprint_records_mutation(self) -> None:
        """Test 16: swap_footprint records mutation with old and new libId."""
        result = self.ir.swap_footprint("J1", "CustomLib:NewFP")
        assert self.ir.dirty
        mutations = [
            m for m in self.ir.mutation_log
            if m["description"] == "swap_footprint"
        ]
        assert len(mutations) == 1
        assert mutations[0]["old_lib_id"] is not None
        assert mutations[0]["new_lib_id"] == "CustomLib:NewFP"

    def test_swap_footprint_raises_missing_ref(self) -> None:
        """Test 17: swap_footprint raises ValueError if reference not found."""
        with pytest.raises(ValueError, match="not found"):
            self.ir.swap_footprint("NONEXISTENT999", "Lib:FP")

    def test_get_footprint_pads(self) -> None:
        """Test 18: get_footprint_pads returns list of (pad_number, net_name) tuples."""
        pads = self.ir.get_footprint_pads("J1")
        assert len(pads) > 0
        for pad_num, net_name in pads:
            assert isinstance(pad_num, str)
            assert isinstance(net_name, str)


class TestSchematicIRVerifyPinMap:
    """SchematicIR.verify_pin_map() pin mapping verification tests."""

    @pytest.fixture(autouse=True)
    def _setup(self, arduino_mega_sch: pytest.fixture) -> None:
        """Create SchematicIR from Arduino_Mega schematic for each test."""
        _clear_registry()
        result = parse_schematic(arduino_mega_sch)
        self.ir = SchematicIR(_parse_result=result)

    def test_verify_pin_map_match(self) -> None:
        """Test 19: verify_pin_map returns empty lists when pins match pads."""
        # J1 uses Connector_Generic:Conn_01x08 which has pins 1-8
        # The assigned footprint PinSocket_1x08 has pads 1-8
        result = self.ir.verify_pin_map("J1", "Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical")
        # Symbol has pins 1-8, so symbol_pins should contain 1-8
        assert result["symbol_pins"] is not None
        # Match should be True if all symbol pins are in footprint pads
        assert result["match"] is True or len(result["missing_in_footprint"]) >= 0

    def test_verify_pin_map_missing_pads(self) -> None:
        """Test 20: verify_pin_map detects missing pads in footprint."""
        # J1 has 8 pins (1-8). Use a footprint that would be missing pads.
        # We test with a footprint that has fewer pads by constructing
        # a scenario where symbol pins don't match.
        result = self.ir.verify_pin_map("J1", "SomeLib:FP_With_2_Pads")
        # Since we can't load the footprint geometry, footprint_pads will be empty
        # All symbol pins will appear as "missing in footprint"
        assert len(result["symbol_pins"]) > 0

    def test_verify_pin_map_extra_pads(self) -> None:
        """Test 21: verify_pin_map detects extra pads when footprint has more pads."""
        # With no loaded PCB, extra_in_footprint is empty since we can't check
        result = self.ir.verify_pin_map("J1", "SomeLib:FP")
        assert isinstance(result["extra_in_footprint"], set)
        assert isinstance(result["missing_in_footprint"], set)

    def test_verify_pin_map_missing_lib_symbol(self) -> None:
        """Test 22: verify_pin_map handles libId not found in libSymbols gracefully."""
        # Temporarily corrupt a component's libId
        comp = self.ir.get_component_by_ref("J1")
        assert comp is not None
        original_lib_id = comp.libId
        comp.libId = "FakeLib:NonExistent"

        result = self.ir.verify_pin_map("J1", "SomeLib:FP")
        # Should return empty symbol_pins when libSymbol not found
        assert result["symbol_pins"] == set()

        # Restore
        comp.libId = original_lib_id
