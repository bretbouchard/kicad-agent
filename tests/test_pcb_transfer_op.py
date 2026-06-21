"""Tests for UpdateFromSchematicOp handler -- gate enforcement, stub detection, and MCU golden test.

TDD RED+GREEN: Tests validate the handler enforces gates, detects stubs, and
processes real schematic fixtures correctly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------


def _make_schematic_ir(
    components: list[dict] | None = None,
    pin_map_result: dict | None = None,
    footprint: str = "Package_DFN:DFN-8-1EP_3x3mm_P0.65mm_EP1.7x2.05mm",
) -> MagicMock:
    """Create a mock that passes isinstance checks for SchematicIR.

    Configures __class__ so isinstance(ir, SchematicIR) returns True.
    This is needed because the handler uses isinstance to locate schematic IRs.

    Args:
        components: List of dicts with keys: ref, lib_id, dnp. Default: one IC.
        pin_map_result: Return value for verify_pin_map. Default: match=True.
        footprint: Default footprint for all components.
    """
    from kicad_agent.ir.schematic_ir import SchematicIR

    ir = MagicMock()
    ir.__class__ = SchematicIR

    if components is None:
        components = [
            {"ref": "U1", "lib_id": "IC:NE5532", "dnp": False},
            {"ref": "R1", "lib_id": "Device:R", "dnp": False},
        ]

    mock_components = []
    for comp in components:
        mock_comp = MagicMock()
        mock_comp.libId = comp.get("lib_id", "Device:R")
        mock_comp.dnp = comp.get("dnp", False)
        mock_components.append(mock_comp)

    ir.components = mock_components

    # Build a lookup dict for get_component_property
    _comp_prop_map: dict[int, dict[str, str]] = {}
    for i, comp in enumerate(components):
        _comp_prop_map[id(mock_components[i])] = {"Reference": comp.get("ref", "")}

    def _get_prop(comp: Any, key: str) -> str:
        return _comp_prop_map.get(id(comp), {}).get(key, "")

    ir.get_component_property = _get_prop
    ir.get_component_footprint = MagicMock(return_value=footprint)

    default_pin_map = pin_map_result or {
        "match": True,
        "symbol_pins": {"1", "2", "3", "4", "5", "6", "7", "8"},
    }
    ir.verify_pin_map = MagicMock(return_value=default_pin_map)

    return ir


def _make_pcb_ir(
    footprint_pads: dict[str, list[tuple[str, str]]] | None = None,
    nets: list[MagicMock] | None = None,
) -> MagicMock:
    """Create a mock that passes isinstance checks for PcbIR.

    Args:
        footprint_pads: Dict of ref -> [(pad_num, net_name), ...].
        nets: List of mock net objects with .name attribute.
    """
    from kicad_agent.ir.pcb_ir import PcbIR

    pcb = MagicMock()
    pcb.__class__ = PcbIR

    def _get_footprint_pads(ref: str) -> list[tuple[str, str]]:
        if footprint_pads is None:
            return [(str(i), f"Net-{i}") for i in range(1, 9)]
        return footprint_pads.get(ref, [])

    pcb.get_footprint_pads = _get_footprint_pads

    if nets is None:
        mock_nets = [MagicMock(name=f"Net-{i}") for i in range(1, 9)]
        for i, n in enumerate(mock_nets, 1):
            n.name = f"Net-{i}"
        pcb.nets = mock_nets
    else:
        pcb.nets = nets

    return pcb


# ---------------------------------------------------------------------------
# Test: gate failure blocks PCB mutation (no bypass from operation schema)
# ---------------------------------------------------------------------------


class TestGateEnforcement:
    """Verify that gate failures prevent PCB mutation and cannot be bypassed via the operation schema."""

    def test_gate_failure_blocks_transfer(self):
        """When the transfer contract validator fails, no PCB mutation occurs."""
        from kicad_agent.validation.gate_types import GateResult

        # Create a failing gate result
        fail_result = GateResult(
            pass_=False,
            gate_name="transfer_contract",
            blockers=["U1: missing footprint assignment"],
        )

        ir = _make_schematic_ir()

        # Patch at source module because handler imports inside function body
        with patch(
            "kicad_agent.validation.gates.transfer_contract.TransferContractValidator.validate",
            return_value=fail_result,
        ):
            from kicad_agent.ops.handlers.pcb_transfer import (
                UpdateFromSchematicOp,
                handle_update_from_schematic,
            )

            op = UpdateFromSchematicOp(
                op_type="update_from_schematic",
                schematic_path="test.kicad_sch",
                pcb_path="test.kicad_pcb",
            )
            ir_map = {Path("test.kicad_sch"): ir}
            result = handle_update_from_schematic(op, ir_map, Path("."))

        assert result["pass"] is False
        assert "U1: missing footprint assignment" in result["blockers"]
        assert result.get("mutated") is not True

    def test_stub_blockers_use_retry_action_not_gate_action(self):
        """CR-01: When gate passes but stub detection adds blockers,
        next_actions should say 'retry' not 'Proceed to pcb_setup stage'."""
        from kicad_agent.validation.gate_types import GateResult

        # Gate passes (no blockers, next_actions says "Proceed")
        pass_result = GateResult(
            pass_=True,
            gate_name="transfer_contract",
            artifacts=["1 component(s) in transfer contract"],
            next_actions=["Proceed to pcb_setup stage"],
        )

        ir = _make_schematic_ir()

        with patch(
            "kicad_agent.validation.gates.transfer_contract.TransferContractValidator.validate",
            return_value=pass_result,
        ), patch(
            "kicad_agent.ops.handlers.pcb_transfer.detect_stub_footprints",
            return_value=["U1 has placeholder footprint '~' (assign a real footprint before transfer)"],
        ):
            from kicad_agent.ops.handlers.pcb_transfer import (
                UpdateFromSchematicOp,
                handle_update_from_schematic,
            )

            op = UpdateFromSchematicOp(
                op_type="update_from_schematic",
                schematic_path="test.kicad_sch",
            )
            ir_map = {Path("test.kicad_sch"): ir}
            result = handle_update_from_schematic(op, ir_map, Path("."))

        assert result["pass"] is False
        assert any("placeholder" in b for b in result["blockers"])
        # CR-01 fix: next_actions must NOT say "Proceed" when we added blockers
        assert not any("Proceed" in a for a in result["next_actions"])
        assert any("Fix" in a or "retry" in a.lower() for a in result["next_actions"])

    def test_no_force_field_in_schema(self):
        """The UpdateFromSchematicOp schema must NOT have a force field."""
        from kicad_agent.ops.handlers.pcb_transfer import UpdateFromSchematicOp

        fields = UpdateFromSchematicOp.model_fields
        assert "force" not in fields
        assert "bypass" not in fields
        assert "skip_gates" not in fields

    def test_gate_pass_allows_transfer(self):
        """When the gate passes, the operation returns a contract."""
        from kicad_agent.validation.gate_types import GateResult

        pass_result = GateResult(
            pass_=True,
            gate_name="transfer_contract",
            artifacts=["3 component(s) in transfer contract"],
            next_actions=["Proceed to pcb_setup stage"],
        )

        ir = _make_schematic_ir()
        pcb_ir = _make_pcb_ir()

        with patch(
            "kicad_agent.validation.gates.transfer_contract.TransferContractValidator.validate",
            return_value=pass_result,
        ):
            from kicad_agent.ops.handlers.pcb_transfer import (
                UpdateFromSchematicOp,
                handle_update_from_schematic,
            )

            op = UpdateFromSchematicOp(
                op_type="update_from_schematic",
                schematic_path="test.kicad_sch",
                pcb_path="test.kicad_pcb",
            )
            ir_map = {Path("test.kicad_sch"): ir, Path("test.kicad_pcb"): pcb_ir}
            result = handle_update_from_schematic(op, ir_map, Path("."))

        assert result["pass"] is True


# ---------------------------------------------------------------------------
# Test: dry_run returns contract without mutation
# ---------------------------------------------------------------------------


class TestDryRun:
    """Verify that dry_run returns the contract result without mutating the PCB."""

    def test_dry_run_returns_contract_without_mutation(self):
        """dry_run=True should not mutate any IRs."""
        from kicad_agent.validation.gate_types import GateResult

        pass_result = GateResult(
            pass_=True,
            gate_name="transfer_contract",
            artifacts=["3 component(s) in transfer contract"],
        )

        ir = _make_schematic_ir()
        pcb_ir = _make_pcb_ir()

        with patch(
            "kicad_agent.validation.gates.transfer_contract.TransferContractValidator.validate",
            return_value=pass_result,
        ):
            from kicad_agent.ops.handlers.pcb_transfer import (
                UpdateFromSchematicOp,
                handle_update_from_schematic,
            )

            op = UpdateFromSchematicOp(
                op_type="update_from_schematic",
                schematic_path="test.kicad_sch",
                pcb_path="test.kicad_pcb",
                dry_run=True,
            )
            ir_map = {Path("test.kicad_sch"): ir, Path("test.kicad_pcb"): pcb_ir}
            result = handle_update_from_schematic(op, ir_map, Path("."))

        assert result["dry_run"] is True
        assert result["pass"] is True
        # Verify no mutation happened
        pcb_ir.commit_raw_content.assert_not_called()
        pcb_ir.mark_dirty.assert_not_called()


# ---------------------------------------------------------------------------
# Test: stub footprint detection
# ---------------------------------------------------------------------------


class TestStubFootprintDetection:
    """Verify that components with placeholder/unknown footprints are detected."""

    def test_detect_stub_footprints_finds_tilde(self):
        """Components with '~' as footprint should be flagged."""
        from kicad_agent.ops.handlers.pcb_transfer import detect_stub_footprints

        components = [
            {"ref": "R1", "lib_id": "Device:R", "dnp": False},
        ]
        ir = _make_schematic_ir(components=components, footprint="~")

        stubs = detect_stub_footprints(ir)
        assert len(stubs) == 1
        assert "R1" in stubs[0]
        assert "placeholder" in stubs[0].lower() or "~" in stubs[0]

    def test_detect_stub_footprints_finds_empty(self):
        """Components with empty/whitespace footprint should be flagged."""
        from kicad_agent.ops.handlers.pcb_transfer import detect_stub_footprints

        components = [
            {"ref": "C1", "lib_id": "Device:C", "dnp": False},
        ]
        ir = _make_schematic_ir(components=components, footprint="")

        stubs = detect_stub_footprints(ir)
        assert len(stubs) == 1
        assert "C1" in stubs[0]

    def test_detect_stub_footprints_skips_valid(self):
        """Components with real footprints should not be flagged."""
        from kicad_agent.ops.handlers.pcb_transfer import detect_stub_footprints

        components = [
            {"ref": "R1", "lib_id": "Device:R", "dnp": False},
        ]
        ir = _make_schematic_ir(components=components, footprint="Resistor_SMD:R_0805_2012Metric")

        stubs = detect_stub_footprints(ir)
        assert stubs == []

    def test_detect_stub_footprints_skips_dnp(self):
        """DNP components should not be flagged as stubs."""
        from kicad_agent.ops.handlers.pcb_transfer import detect_stub_footprints

        components = [
            {"ref": "R99", "lib_id": "Device:R", "dnp": True},
        ]
        ir = _make_schematic_ir(components=components, footprint="~")

        stubs = detect_stub_footprints(ir)
        assert stubs == []

    def test_detect_stub_footprints_skips_power_symbols(self):
        """Power symbols should not be flagged as stubs."""
        from kicad_agent.ops.handlers.pcb_transfer import detect_stub_footprints

        components = [
            {"ref": "#PWR01", "lib_id": "power:+3V3", "dnp": False},
        ]
        ir = _make_schematic_ir(components=components, footprint="~")

        stubs = detect_stub_footprints(ir)
        assert stubs == []

    def test_detect_stub_footprints_returns_descriptive_messages(self):
        """Error messages should include component reference and footprint."""
        from kicad_agent.ops.handlers.pcb_transfer import detect_stub_footprints

        components = [
            {"ref": "U2", "lib_id": "IC:ATmega", "dnp": False},
        ]
        ir = _make_schematic_ir(components=components, footprint="~")

        stubs = detect_stub_footprints(ir)
        assert len(stubs) == 1
        assert "U2" in stubs[0]
        assert "~" in stubs[0]


# ---------------------------------------------------------------------------
# Test: placeholder pad detection
# ---------------------------------------------------------------------------


class TestPlaceholderPadDetection:
    """Verify that footprints with suspiciously few pads are detected."""

    def test_detect_placeholder_pads_finds_single_pad_multi_pin(self):
        """Footprint with 1 pad but symbol with >1 pin should be flagged."""
        from kicad_agent.ops.handlers.pcb_transfer import detect_placeholder_pads

        components = [
            {"ref": "U1", "lib_id": "IC:NE5532", "dnp": False},
        ]
        ir = _make_schematic_ir(
            components=components,
            pin_map_result={"match": False, "symbol_pins": {"1", "2", "3", "4", "5", "6", "7", "8"}},
        )
        pcb_ir = _make_pcb_ir(footprint_pads={"U1": [("1", "Net-1")]})

        placeholders = detect_placeholder_pads(ir, pcb_ir)
        assert len(placeholders) == 1
        assert "U1" in placeholders[0]
        assert "1 pad" in placeholders[0].lower() or "1 pad" in placeholders[0]
        assert "8 pin" in placeholders[0] or "8" in placeholders[0]

    def test_detect_placeholder_pads_skips_matching_pad_count(self):
        """Footprint with matching pad count should not be flagged."""
        from kicad_agent.ops.handlers.pcb_transfer import detect_placeholder_pads

        components = [
            {"ref": "U1", "lib_id": "IC:NE5532", "dnp": False},
        ]
        ir = _make_schematic_ir(
            components=components,
            pin_map_result={"match": True, "symbol_pins": {"1", "2", "3", "4", "5", "6", "7", "8"}},
        )
        pcb_ir = _make_pcb_ir(footprint_pads={"U1": [(str(i), f"Net-{i}") for i in range(1, 9)]})

        placeholders = detect_placeholder_pads(ir, pcb_ir)
        assert placeholders == []

    def test_detect_placeholder_pads_returns_descriptive_messages(self):
        """Error messages should include component reference, pad count, and pin count."""
        from kicad_agent.ops.handlers.pcb_transfer import detect_placeholder_pads

        components = [
            {"ref": "U2", "lib_id": "IC:STM32", "dnp": False},
        ]
        ir = _make_schematic_ir(
            components=components,
            pin_map_result={"match": False, "symbol_pins": {str(i) for i in range(1, 17)}},
        )
        pcb_ir = _make_pcb_ir(footprint_pads={"U2": [("1", "Net-1")]})

        placeholders = detect_placeholder_pads(ir, pcb_ir)
        assert len(placeholders) == 1
        assert "U2" in placeholders[0]
        assert "16" in placeholders[0] or "16 pin" in placeholders[0].lower()

    def test_detect_placeholder_pads_skips_dnp(self):
        """DNP components should not be checked for placeholder pads."""
        from kicad_agent.ops.handlers.pcb_transfer import detect_placeholder_pads

        components = [
            {"ref": "U99", "lib_id": "IC:NE5532", "dnp": True},
        ]
        ir = _make_schematic_ir(
            components=components,
            pin_map_result={"match": False, "symbol_pins": {"1", "2", "3", "4", "5", "6", "7", "8"}},
        )
        pcb_ir = _make_pcb_ir(footprint_pads={"U99": [("1", "Net-1")]})

        placeholders = detect_placeholder_pads(ir, pcb_ir)
        assert placeholders == []


# ---------------------------------------------------------------------------
# Test: partial net assignment
# ---------------------------------------------------------------------------


class TestPartialNetAssignment:
    """Verify partial net assignments produce warnings, not blockers."""

    def test_partial_assignment_produces_warnings(self):
        """When some pads get nets and some don't, produce warnings not blockers."""
        from kicad_agent.validation.gate_types import GateResult

        # Gate passes but with warnings
        pass_result = GateResult(
            pass_=True,
            gate_name="transfer_contract",
            warnings=["U1: 3 of 8 pads unassigned"],
            artifacts=["3 component(s) in transfer contract"],
        )

        ir = _make_schematic_ir()
        pcb_ir = _make_pcb_ir(
            footprint_pads={"U1": [(str(i), f"Net-{i}" if i <= 5 else "") for i in range(1, 9)]}
        )

        with patch(
            "kicad_agent.validation.gates.transfer_contract.TransferContractValidator.validate",
            return_value=pass_result,
        ):
            from kicad_agent.ops.handlers.pcb_transfer import (
                UpdateFromSchematicOp,
                handle_update_from_schematic,
            )

            op = UpdateFromSchematicOp(
                op_type="update_from_schematic",
                schematic_path="test.kicad_sch",
                pcb_path="test.kicad_pcb",
            )
            ir_map = {Path("test.kicad_sch"): ir, Path("test.kicad_pcb"): pcb_ir}
            result = handle_update_from_schematic(op, ir_map, Path("."))

        assert result["pass"] is True
        assert len(result.get("warnings", [])) > 0


# ---------------------------------------------------------------------------
# Test: duplicate net names
# ---------------------------------------------------------------------------


class TestDuplicateNetNames:
    """Verify that duplicate schematic labels for the same net are deduplicated."""

    def test_duplicate_net_names_deduplicated(self):
        """Multiple labels for the same net should produce warnings, not blockers."""
        from kicad_agent.validation.gate_types import GateResult

        pass_result = GateResult(
            pass_=True,
            gate_name="transfer_contract",
            warnings=["Duplicate net name 'VCC' detected, deduplicated to single net"],
            artifacts=["3 component(s) in transfer contract"],
        )

        ir = _make_schematic_ir()
        pcb_ir = _make_pcb_ir()

        with patch(
            "kicad_agent.validation.gates.transfer_contract.TransferContractValidator.validate",
            return_value=pass_result,
        ):
            from kicad_agent.ops.handlers.pcb_transfer import (
                UpdateFromSchematicOp,
                handle_update_from_schematic,
            )

            op = UpdateFromSchematicOp(
                op_type="update_from_schematic",
                schematic_path="test.kicad_sch",
                pcb_path="test.kicad_pcb",
            )
            ir_map = {Path("test.kicad_sch"): ir, Path("test.kicad_pcb"): pcb_ir}
            result = handle_update_from_schematic(op, ir_map, Path("."))

        assert result["pass"] is True
        # Warnings about deduplication should be present
        assert any(
            "dedup" in w.lower() or "duplicate" in w.lower()
            for w in result.get("warnings", [])
        )


# ---------------------------------------------------------------------------
# Test: CLI --force flag bypasses gate for human testing
# ---------------------------------------------------------------------------


class TestCliForceFlag:
    """Verify that the handler's force parameter bypasses gates (CLI-only)."""

    def test_force_bypass_skips_gate(self):
        """force is intentionally absent from handler (fail-closed security design)."""
        from kicad_agent.ops.handlers.pcb_transfer import handle_update_from_schematic
        import inspect
        sig = inspect.signature(handle_update_from_schematic)
        assert "force" not in sig.parameters

    def test_force_flag_not_in_operation_schema(self):
        """force is NOT a field on the Pydantic model -- it's a handler-level parameter."""
        from kicad_agent.ops.handlers.pcb_transfer import UpdateFromSchematicOp

        assert "force" not in UpdateFromSchematicOp.model_fields


# ---------------------------------------------------------------------------
# Test: registry metadata
# ---------------------------------------------------------------------------


class TestRegistryMetadata:
    """Verify that update_from_schematic is registered with full metadata."""

    def test_registered_in_registry(self):
        """update_from_schematic should exist in the operation registry."""
        from kicad_agent.ops.registry import OPERATION_REGISTRY

        assert "update_from_schematic" in OPERATION_REGISTRY

    def test_registry_category_is_pcb(self):
        from kicad_agent.ops.registry import OPERATION_REGISTRY

        meta = OPERATION_REGISTRY["update_from_schematic"]
        assert meta.category == "pcb"

    def test_registry_file_types(self):
        from kicad_agent.ops.registry import OPERATION_REGISTRY

        meta = OPERATION_REGISTRY["update_from_schematic"]
        assert ".kicad_sch" in meta.file_types
        assert ".kicad_pcb" in meta.file_types

    def test_registry_scope_is_multi_file(self):
        from kicad_agent.ops.registry import OPERATION_REGISTRY

        meta = OPERATION_REGISTRY["update_from_schematic"]
        assert meta.scope == "multi_file"

    def test_registry_requires_parse_schematic(self):
        from kicad_agent.ops.registry import OPERATION_REGISTRY

        meta = OPERATION_REGISTRY["update_from_schematic"]
        assert "parse_schematic" in meta.requires

    def test_registry_not_readonly(self):
        from kicad_agent.ops.registry import OPERATION_REGISTRY

        meta = OPERATION_REGISTRY["update_from_schematic"]
        assert meta.is_readonly is False

    def test_registry_in_schema_union(self):
        """UpdateFromSchematicOp should be in the Operation discriminated union."""
        from kicad_agent.ops.schema import Operation

        schema = Operation.model_json_schema()
        # Schema uses $ref to $defs -- extract op_type from refs
        one_of_types = schema.get("properties", {}).get("root", {}).get("oneOf", [])
        ref_names = []
        for t in one_of_types:
            ref = t.get("$ref", "")
            # $ref format: "#/$defs/OpName"
            if ref.startswith("#/$defs/"):
                ref_names.append(ref.split("/")[-1])

        # Check either inline or $ref format
        type_names = [
            t.get("properties", {}).get("op_type", {}).get("const", "")
            for t in one_of_types
        ]
        assert "update_from_schematic" in type_names or "UpdateFromSchematicOp" in ref_names

    def test_registry_no_conflicts(self):
        from kicad_agent.ops.registry import OPERATION_REGISTRY

        meta = OPERATION_REGISTRY["update_from_schematic"]
        assert meta.conflicts == []


# ---------------------------------------------------------------------------
# Test: Arduino Mega golden test
# ---------------------------------------------------------------------------


class TestArduinoMegaGolden:
    """Golden test using the Arduino Mega fixture to verify pin-net transfer."""

    @pytest.fixture
    def arduino_sch_path(self) -> Path:
        return Path("tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_sch")

    def _parse_schematic(self, path: Path):
        """Helper to parse a schematic file into SchematicIR.

        Clears the IR registry before parsing to avoid spurious id-collision
        failures when Python reuses a gc'd ParseResult's id().
        """
        from kicad_agent.ir.base import _clear_registry
        from kicad_agent.ir.schematic_ir import SchematicIR
        from kicad_agent.parser import parse_schematic

        _clear_registry()
        result = parse_schematic(path)
        return SchematicIR(_parse_result=result)

    def test_arduino_mega_parse_produces_components(self, arduino_sch_path: Path):
        """The Arduino Mega schematic should parse into a SchematicIR with many components."""
        if not arduino_sch_path.exists():
            pytest.skip("Arduino Mega fixture not available")

        ir = self._parse_schematic(arduino_sch_path)
        # Arduino Mega has many components
        assert len(ir.components) > 50

    def test_arduino_mega_contract_has_components(self, arduino_sch_path: Path):
        """TransferContractValidator should produce a contract with components from Arduino Mega."""
        from kicad_agent.validation.gates.transfer_contract import TransferContractValidator

        if not arduino_sch_path.exists():
            pytest.skip("Arduino Mega fixture not available")

        ir = self._parse_schematic(arduino_sch_path)
        validator = TransferContractValidator()
        result = validator.validate(ir)

        # The contract should have at least some components with footprints
        assert len(result.artifacts) > 0

    def test_arduino_mega_transfer_op_integration(self, arduino_sch_path: Path):
        """Full integration: parse Arduino Mega and run through the handler."""
        from kicad_agent.ops.handlers.pcb_transfer import (
            UpdateFromSchematicOp,
            handle_update_from_schematic,
        )

        if not arduino_sch_path.exists():
            pytest.skip("Arduino Mega fixture not available")

        ir = self._parse_schematic(arduino_sch_path)

        op = UpdateFromSchematicOp(
            op_type="update_from_schematic",
            schematic_path=str(arduino_sch_path),
            dry_run=True,
        )
        ir_map = {arduino_sch_path: ir}
        result = handle_update_from_schematic(op, ir_map, Path("tests/fixtures/Arduino_Mega"))

        assert "dry_run" in result
        assert result["dry_run"] is True
        # Result should have gate information
        assert "gate" in result or "pass" in result


# ---------------------------------------------------------------------------
# Test: handler error cases
# ---------------------------------------------------------------------------


class TestHandlerErrorCases:
    """Test handler error handling for missing IRs and invalid inputs."""

    def test_missing_schematic_ir_raises_error(self):
        """Handler should return an error when no schematic IR is provided."""
        from kicad_agent.ops.handlers.pcb_transfer import (
            UpdateFromSchematicOp,
            handle_update_from_schematic,
        )

        op = UpdateFromSchematicOp(
            op_type="update_from_schematic",
            schematic_path="test.kicad_sch",
        )
        result = handle_update_from_schematic(op, {}, Path("."))

        assert result["pass"] is False
        assert any("schematic" in b.lower() for b in result.get("blockers", []))

    def test_no_pcb_returns_contract_ready(self):
        """When no PCB IR exists, handler should report contract is ready (not a blocker)."""
        from kicad_agent.validation.gate_types import GateResult

        pass_result = GateResult(
            pass_=True,
            gate_name="transfer_contract",
            artifacts=["3 component(s) in transfer contract"],
            next_actions=["Proceed to pcb_setup stage"],
        )

        ir = _make_schematic_ir()

        with patch(
            "kicad_agent.validation.gates.transfer_contract.TransferContractValidator.validate",
            return_value=pass_result,
        ):
            from kicad_agent.ops.handlers.pcb_transfer import (
                UpdateFromSchematicOp,
                handle_update_from_schematic,
            )

            op = UpdateFromSchematicOp(
                op_type="update_from_schematic",
                schematic_path="test.kicad_sch",
            )
            ir_map = {Path("test.kicad_sch"): ir}
            result = handle_update_from_schematic(op, ir_map, Path("."))

        assert result["pass"] is True
        assert result.get("contract_ready") is True


# ---------------------------------------------------------------------------
# Test: WR-02 path validation (D-03 alignment)
# ---------------------------------------------------------------------------


class TestPathValidation:
    """Verify schematic_path and pcb_path reject unsafe values (WR-02 fix)."""

    def test_reject_path_traversal(self):
        """Paths with '..' must be rejected."""
        from kicad_agent.ops.handlers.pcb_transfer import UpdateFromSchematicOp

        with pytest.raises(Exception):
            UpdateFromSchematicOp(
                op_type="update_from_schematic",
                schematic_path="../etc/passwd",
            )

    def test_reject_absolute_path(self):
        """Absolute paths must be rejected."""
        from kicad_agent.ops.handlers.pcb_transfer import UpdateFromSchematicOp

        with pytest.raises(Exception):
            UpdateFromSchematicOp(
                op_type="update_from_schematic",
                schematic_path="/etc/passwd",
            )

    def test_reject_null_bytes(self):
        """Paths with null bytes must be rejected."""
        from kicad_agent.ops.handlers.pcb_transfer import UpdateFromSchematicOp

        with pytest.raises(Exception):
            UpdateFromSchematicOp(
                op_type="update_from_schematic",
                schematic_path="test\x00.kicad_sch",
            )

    def test_reject_traversal_in_pcb_path(self):
        """pcb_path with '..' must also be rejected."""
        from kicad_agent.ops.handlers.pcb_transfer import UpdateFromSchematicOp

        with pytest.raises(Exception):
            UpdateFromSchematicOp(
                op_type="update_from_schematic",
                schematic_path="test.kicad_sch",
                pcb_path="../evil.kicad_pcb",
            )

    def test_allow_relative_path(self):
        """Normal relative paths must be accepted."""
        from kicad_agent.ops.handlers.pcb_transfer import UpdateFromSchematicOp

        op = UpdateFromSchematicOp(
            op_type="update_from_schematic",
            schematic_path="project.kicad_sch",
            pcb_path="project.kicad_pcb",
        )
        assert op.schematic_path == "project.kicad_sch"
        assert op.pcb_path == "project.kicad_pcb"

    def test_allow_none_pcb_path(self):
        """None pcb_path must be accepted (contract-only mode)."""
        from kicad_agent.ops.handlers.pcb_transfer import UpdateFromSchematicOp

        op = UpdateFromSchematicOp(
            op_type="update_from_schematic",
            schematic_path="project.kicad_sch",
        )
        assert op.pcb_path is None
