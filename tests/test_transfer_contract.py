"""Tests for the schematic-to-PCB transfer contract.

TDD RED phase -- all tests written first, then implementation follows.

Tests cover:
- TransferContract construction and completeness checks
- PadNetAssignmentResult structured result
- PadNetAssigner.pad_pad_nets
- NetIdVerifier.verify_net_ids
- Power symbol exclusion
- Multi-unit symbol flattening
- TransferContractValidator with auto-run SchematicIntentGate
- Empty schematic handling
- Net name case sensitivity
- Missing footprint / pin count mismatch / net name mismatch failures
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.project.design_rules import NetClassDef
from kicad_agent.validation.gate_types import DesignStage, GateResult


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_component(
    reference: str = "R1",
    lib_id: str = "Device:R",
    footprint: str = "Resistor_SMD:R_0805_2012Metric",
    value: str = "1k",
    dnp: bool = False,
) -> MagicMock:
    """Create a mock schematic component."""
    comp = MagicMock()
    comp.libId = lib_id
    comp.dnp = dnp
    comp.properties = [
        MagicMock(key="Reference", value=reference),
        MagicMock(key="Value", value=value),
        MagicMock(key="Footprint", value=footprint),
    ]
    return comp


def _make_schematic_ir(
    components: list | None = None,
    lib_symbols: list | None = None,
    get_component_by_ref_returns: dict | None = None,
    get_component_footprint_returns: dict | None = None,
    verify_pin_map_returns: dict | None = None,
) -> MagicMock:
    """Create a mock SchematicIR."""
    ir = MagicMock()
    ir.components = components or []
    ir.schematic.libSymbols = lib_symbols or []

    def _get_component_by_ref(ref):
        if get_component_by_ref_returns and ref in get_component_by_ref_returns:
            return get_component_by_ref_returns[ref]
        for c in ir.components:
            for p in c.properties:
                if p.key == "Reference" and p.value == ref:
                    return c
        return None

    ir.get_component_by_ref.side_effect = _get_component_by_ref

    def _get_component_footprint(ref):
        if get_component_footprint_returns:
            return get_component_footprint_returns.get(ref)
        comp = _get_component_by_ref(ref)
        if comp is None:
            return None
        for p in comp.properties:
            if p.key == "Footprint":
                return p.value
        return None

    ir.get_component_footprint.side_effect = _get_component_footprint

    def _get_component_property(comp, key):
        if comp is None:
            return None
        for p in comp.properties:
            if p.key == key:
                return p.value
        return None

    ir.get_component_property.side_effect = _get_component_property

    def _verify_pin_map(ref, footprint_lib_id):
        if verify_pin_map_returns and ref in verify_pin_map_returns:
            return verify_pin_map_returns[ref]
        return {"symbol_pins": set(), "footprint_pads": set(), "missing_in_footprint": set(), "extra_in_footprint": set(), "match": True}

    ir.verify_pin_map.side_effect = _verify_pin_map

    return ir


def _make_pcb_ir(
    footprints: dict | None = None,
    pad_nets: dict | None = None,
    net_names: list | None = None,
) -> MagicMock:
    """Create a mock PcbIR.

    Args:
        footprints: dict of ref -> list of pad numbers (strings).
        pad_nets: dict of ref -> dict of pad_number -> net_name.
        net_names: list of net names present in the PCB.
    """
    pcb = MagicMock()
    pcb.board.nets = []
    pcb.board.footprints = []
    pcb.nets = pcb.board.nets  # Mirror for direct pcb_ir.nets access

    for name in (net_names or []):
        net = MagicMock()
        net.name = name
        net.number = 0
        pcb.board.nets.append(net)

    for ref, pad_nums in (footprints or {}).items():
        fp = MagicMock()
        fp.properties = {"Reference": ref, "Value": ""}
        fp.pads = []
        for pn in pad_nums:
            pad = MagicMock()
            pad.number = pn
            pad.net = MagicMock()
            pad.net.name = ""
            pad.net.number = 0
            if pad_nets and ref in pad_nets and pn in pad_nets[ref]:
                pad.net.name = pad_nets[ref][pn]
            fp.pads.append(pad)
        pcb.board.footprints.append(fp)

    def _get_footprint_by_ref(ref):
        for fp in pcb.board.footprints:
            if fp.properties.get("Reference") == ref:
                return fp
        return None

    pcb.get_footprint_by_ref.side_effect = _get_footprint_by_ref

    def _get_footprint_pads(ref):
        fp = _get_footprint_by_ref(ref)
        if fp is None:
            return []
        return [(p.number, p.net.name if p.net else "") for p in fp.pads]

    pcb.get_footprint_pads.side_effect = _get_footprint_pads

    def _get_net_by_name(name):
        for n in pcb.board.nets:
            if n.name == name:
                return n
        return None

    pcb.get_net_by_name.side_effect = _get_net_by_name

    return pcb


# ===========================================================================
# Test: TransferContract construction
# ===========================================================================

class TestTransferContractConstruction:
    """Test TransferContract BaseModel creation and field access."""

    def test_basic_construction(self):
        """TransferContract constructs with all required fields."""
        from kicad_agent.validation.gates.transfer_contract import TransferContract

        contract = TransferContract(
            symbol_footprint_map={"R1": "Resistor_SMD:R_0805_2012Metric"},
            pin_pad_map={"R1": {"1": "1", "2": "2"}},
            net_assignments={"VCC": "VCC", "GND": "GND"},
            net_classes={"Default": NetClassDef(name="Default", track_width=0.25)},
        )

        assert contract.symbol_footprint_map == {"R1": "Resistor_SMD:R_0805_2012Metric"}
        assert contract.pin_pad_map == {"R1": {"1": "1", "2": "2"}}
        assert contract.net_assignments == {"VCC": "VCC", "GND": "GND"}
        assert "Default" in contract.net_classes

    def test_frozen_model(self):
        """TransferContract is frozen (immutable) -- field reassignment raises error."""
        from kicad_agent.validation.gates.transfer_contract import TransferContract

        contract = TransferContract(
            symbol_footprint_map={"R1": "Resistor_SMD:R_0805_2012Metric"},
            pin_pad_map={},
            net_assignments={},
            net_classes={},
        )

        with pytest.raises(Exception):  # ValidationError for frozen model
            contract.symbol_footprint_map = {"R2": "other"}

    def test_is_complete_all_populated(self):
        """is_complete() returns True when all components have footprints and pins assigned."""
        from kicad_agent.validation.gates.transfer_contract import TransferContract

        contract = TransferContract(
            symbol_footprint_map={"R1": "Resistor_SMD:R_0805_2012Metric"},
            pin_pad_map={"R1": {"1": "1", "2": "2"}},
            net_assignments={"VCC": "VCC", "GND": "GND"},
            net_classes={},
        )

        assert contract.is_complete() is True

    def test_is_complete_missing_footprint(self):
        """is_complete() returns False when a component has no footprint."""
        from kicad_agent.validation.gates.transfer_contract import TransferContract

        contract = TransferContract(
            symbol_footprint_map={},  # R1 not mapped
            pin_pad_map={"R1": {"1": "1", "2": "2"}},
            net_assignments={"VCC": "VCC", "GND": "GND"},
            net_classes={},
        )

        assert contract.is_complete() is False

    def test_is_complete_missing_pin_pad(self):
        """is_complete() returns False when pin-pad map is empty for a mapped component."""
        from kicad_agent.validation.gates.transfer_contract import TransferContract

        contract = TransferContract(
            symbol_footprint_map={"R1": "Resistor_SMD:R_0805_2012Metric"},
            pin_pad_map={},  # no pin-pad entries
            net_assignments={"VCC": "VCC", "GND": "GND"},
            net_classes={},
        )

        assert contract.is_complete() is False

    def test_missing_items(self):
        """missing_items() lists unfulfilled contract items."""
        from kicad_agent.validation.gates.transfer_contract import TransferContract

        contract = TransferContract(
            symbol_footprint_map={},  # R1 missing
            pin_pad_map={"R1": {"1": "1"}},  # pin 2 missing
            net_assignments={"GND": "GND"},
            net_classes={},
        )

        missing = contract.missing_items()
        assert len(missing) > 0
        # At minimum, R1 should be listed for missing footprint
        assert any("R1" in item and "footprint" in item.lower() for item in missing)


# ===========================================================================
# Test: PadNetAssignmentResult
# ===========================================================================

class TestPadNetAssignmentResult:
    """Test PadNetAssignmentResult structured result."""

    def test_construction(self):
        """PadNetAssignmentResult constructs with assignments, blockers, warnings."""
        from kicad_agent.validation.gates.transfer_contract import PadNetAssignmentResult

        result = PadNetAssignmentResult(
            assignments_made={"R1": {"1": "VCC", "2": "GND"}},
            blockers=[],
            warnings=[],
        )

        assert result.assignments_made == {"R1": {"1": "VCC", "2": "GND"}}
        assert result.blockers == []
        assert result.warnings == []

    def test_with_blockers(self):
        """PadNetAssignmentResult can hold blockers."""
        from kicad_agent.validation.gates.transfer_contract import PadNetAssignmentResult

        result = PadNetAssignmentResult(
            assignments_made={},
            blockers=["R1: pad count mismatch"],
            warnings=[],
        )

        assert len(result.blockers) == 1
        assert "R1" in result.blockers[0]


# ===========================================================================
# Test: PadNetAssigner
# ===========================================================================

class TestPadNetAssigner:
    """Test PadNetAssigner.assign_pad_nets."""

    def test_successful_assignment(self):
        """PadNetAssigner assigns PCB pad nets from schematic netlist."""
        from kicad_agent.validation.gates.transfer_contract import (
            PadNetAssigner,
            TransferContract,
        )

        contract = TransferContract(
            symbol_footprint_map={"R1": "Resistor_SMD:R_0805_2012Metric"},
            pin_pad_map={"R1": {"1": "1", "2": "2"}},
            net_assignments={"VCC": "VCC", "GND": "GND"},
            net_classes={},
        )

        pcb_ir = _make_pcb_ir(
            footprints={"R1": ["1", "2"]},
            net_names=["VCC", "GND"],
        )

        assigner = PadNetAssigner()
        result = assigner.assign_pad_nets(contract, pcb_ir)

        assert len(result.blockers) == 0
        assert "R1" in result.assignments_made

    def test_returns_structured_result(self):
        """PadNetAssigner.assign_pad_nets returns PadNetAssignmentResult."""
        from kicad_agent.validation.gates.transfer_contract import (
            PadNetAssigner,
            PadNetAssignmentResult,
            TransferContract,
        )

        contract = TransferContract(
            symbol_footprint_map={"R1": "Resistor_SMD:R_0805_2012Metric"},
            pin_pad_map={"R1": {"1": "1", "2": "2"}},
            net_assignments={},
            net_classes={},
        )

        pcb_ir = _make_pcb_ir(
            footprints={"R1": ["1", "2"]},
        )

        assigner = PadNetAssigner()
        result = assigner.assign_pad_nets(contract, pcb_ir)

        assert isinstance(result, PadNetAssignmentResult)

    def test_pad_count_mismatch(self):
        """PadNetAssigner detects pin-pad count mismatch."""
        from kicad_agent.validation.gates.transfer_contract import (
            PadNetAssigner,
            TransferContract,
        )

        contract = TransferContract(
            symbol_footprint_map={"R1": "Resistor_SMD:R_0805_2012Metric"},
            pin_pad_map={"R1": {"1": "1", "2": "2", "3": "3"}},  # 3 pins
            net_assignments={},
            net_classes={},
        )

        pcb_ir = _make_pcb_ir(
            footprints={"R1": ["1", "2"]},  # only 2 pads
        )

        assigner = PadNetAssigner()
        result = assigner.assign_pad_nets(contract, pcb_ir)

        assert len(result.blockers) > 0
        assert any("R1" in b for b in result.blockers)


# ===========================================================================
# Test: NetIdVerifier
# ===========================================================================

class TestNetIdVerifier:
    """Test NetIdVerifier.verify_net_ids."""

    def test_matching_net_ids(self):
        """NetIdVerifier passes when schematic and PCB net names match."""
        from kicad_agent.validation.gates.transfer_contract import (
            NetIdVerifier,
            TransferContract,
        )

        contract = TransferContract(
            symbol_footprint_map={},
            pin_pad_map={},
            net_assignments={"VCC": "VCC", "GND": "GND"},
            net_classes={},
        )

        pcb_ir = _make_pcb_ir(net_names=["VCC", "GND"])

        verifier = NetIdVerifier()
        result = verifier.verify_net_ids(contract, pcb_ir)

        assert len(result.blockers) == 0

    def test_returns_structured_result(self):
        """NetIdVerifier.verify_net_ids returns PadNetAssignmentResult."""
        from kicad_agent.validation.gates.transfer_contract import (
            NetIdVerifier,
            PadNetAssignmentResult,
            TransferContract,
        )

        contract = TransferContract(
            symbol_footprint_map={},
            pin_pad_map={},
            net_assignments={"VCC": "VCC"},
            net_classes={},
        )

        pcb_ir = _make_pcb_ir(net_names=["VCC"])

        verifier = NetIdVerifier()
        result = verifier.verify_net_ids(contract, pcb_ir)

        assert isinstance(result, PadNetAssignmentResult)

    def test_missing_net_in_pcb(self):
        """NetIdVerifier detects schematic net missing from PCB."""
        from kicad_agent.validation.gates.transfer_contract import (
            NetIdVerifier,
            TransferContract,
        )

        contract = TransferContract(
            symbol_footprint_map={},
            pin_pad_map={},
            net_assignments={"VCC": "VCC", "GND": "GND", "LED_K": "LED_K"},
            net_classes={},
        )

        pcb_ir = _make_pcb_ir(net_names=["VCC", "GND"])  # LED_K missing

        verifier = NetIdVerifier()
        result = verifier.verify_net_ids(contract, pcb_ir)

        assert len(result.blockers) > 0
        assert any("LED_K" in b for b in result.blockers)

    def test_case_sensitive_net_names(self):
        """NetIdVerifier treats net names as case-sensitive: GND != gnd."""
        from kicad_agent.validation.gates.transfer_contract import (
            NetIdVerifier,
            TransferContract,
        )

        contract = TransferContract(
            symbol_footprint_map={},
            pin_pad_map={},
            net_assignments={"GND": "GND"},
            net_classes={},
        )

        pcb_ir = _make_pcb_ir(net_names=["gnd"])  # lowercase

        verifier = NetIdVerifier()
        result = verifier.verify_net_ids(contract, pcb_ir)

        assert len(result.blockers) > 0
        assert any("GND" in b and "gnd" in b for b in result.blockers)


# ===========================================================================
# Test: TransferContractValidator -- power symbol exclusion
# ===========================================================================

class TestPowerSymbolExclusion:
    """Test that power symbols are excluded from footprint/pin-pad validation."""

    def test_power_pwr_symbol_excluded(self):
        """Component with lib_id containing #PWR is excluded."""
        from kicad_agent.validation.gates.transfer_contract import TransferContractValidator

        pwr_comp = _make_component(
            reference="#PWR0101",
            lib_id="power:GND",
            footprint="",
            value="GND",
        )

        ir = _make_schematic_ir(components=[pwr_comp])
        validator = TransferContractValidator()
        result = validator.validate(ir)

        # Power symbol should not cause a "no footprint" blocker
        assert result.pass_bool is True

    def test_power_lib_id_pwr_prefix_excluded(self):
        """Component with lib_id starting with 'power:' is excluded."""
        from kicad_agent.validation.gates.transfer_contract import TransferContractValidator

        vcc_comp = _make_component(
            reference="#PWR0102",
            lib_id="power:+3V3",
            footprint="",
            value="+3V3",
        )

        ir = _make_schematic_ir(components=[vcc_comp])
        validator = TransferContractValidator()
        result = validator.validate(ir)

        assert result.pass_bool is True


# ===========================================================================
# Test: Multi-unit symbol handling
# ===========================================================================

class TestMultiUnitSymbols:
    """Test that multi-unit symbols flatten to base ref_des in pin_pad_map."""

    def test_multi_unit_flat_pin_pad_map(self):
        """Multi-unit symbols (U1.A, U1.B) map to flat 'U1' in pin_pad_map."""
        from kicad_agent.validation.gates.transfer_contract import TransferContractValidator

        comp_a = _make_component(
            reference="U1.A",
            lib_id="CD4066",
            footprint="Package_SO:SOIC-14",
            value="CD4066",
        )
        comp_b = _make_component(
            reference="U1.B",
            lib_id="CD4066",
            footprint="Package_SO:SOIC-14",
            value="CD4066",
        )

        ir = _make_schematic_ir(
            components=[comp_a, comp_b],
            get_component_footprint_returns={
                "U1.A": "Package_SO:SOIC-14",
                "U1.B": "Package_SO:SOIC-14",
            },
            verify_pin_map_returns={
                "U1.A": {
                    "symbol_pins": {"1", "2", "3", "4", "5", "6", "7"},
                    "footprint_pads": set(),
                    "missing_in_footprint": set(),
                    "extra_in_footprint": set(),
                    "match": True,
                },
                "U1.B": {
                    "symbol_pins": {"8", "9", "10", "11", "12", "13", "14"},
                    "footprint_pads": set(),
                    "missing_in_footprint": set(),
                    "extra_in_footprint": set(),
                    "match": True,
                },
            },
        )
        validator = TransferContractValidator()
        result = validator.validate(ir)

        # Should pass -- multi-unit flattened to base U1
        assert result.pass_bool is True

        # Artifacts should reflect 1 flattened component (U1.A + U1.B -> U1)
        assert any("component" in a.lower() for a in result.artifacts)

    def test_multi_unit_pins_merged(self):
        """All pins from all units merge into single pin_pad_map entry."""
        from kicad_agent.validation.gates.transfer_contract import TransferContractValidator

        comp_a = _make_component(
            reference="U1.A",
            lib_id="CD4066",
            footprint="Package_SO:SOIC-14",
            value="CD4066",
        )
        comp_b = _make_component(
            reference="U1.B",
            lib_id="CD4066",
            footprint="Package_SO:SOIC-14",
            value="CD4066",
        )

        # Unit A has pins 1-7, Unit B has pins 8-14
        ir = _make_schematic_ir(
            components=[comp_a, comp_b],
            get_component_footprint_returns={
                "U1.A": "Package_SO:SOIC-14",
                "U1.B": "Package_SO:SOIC-14",
            },
            verify_pin_map_returns={
                "U1.A": {
                    "symbol_pins": {"1", "2", "3", "4", "5", "6", "7"},
                    "footprint_pads": set(),
                    "missing_in_footprint": set(),
                    "extra_in_footprint": set(),
                    "match": True,
                },
                "U1.B": {
                    "symbol_pins": {"8", "9", "10", "11", "12", "13", "14"},
                    "footprint_pads": set(),
                    "missing_in_footprint": set(),
                    "extra_in_footprint": set(),
                    "match": True,
                },
            },
        )
        validator = TransferContractValidator()
        result = validator.validate(ir)

        assert result.pass_bool is True


# ===========================================================================
# Test: TransferContractValidator -- auto-run SchematicIntentGate
# ===========================================================================

class TestSchematicIntentPrerequisite:
    """Test auto-run of SchematicIntentGate as prerequisite."""

    def test_auto_runs_when_not_cached(self):
        """TransferContractValidator auto-runs SchematicIntentGate when not cached."""
        from kicad_agent.validation.gates.transfer_contract import TransferContractValidator

        r1 = _make_component(reference="R1", lib_id="Device:R", footprint="Resistor_SMD:R_0805_2012Metric")
        ir = _make_schematic_ir(components=[r1])

        passing_gate_result = GateResult(
            pass_=True,
            gate_name="schematic_intent",
            stage=DesignStage.PCB_SETUP,
        )

        validator = TransferContractValidator()

        with patch(
            "kicad_agent.validation.gates.schematic_intent_gate.SchematicIntentGate"
        ) as MockGate:
            mock_instance = MockGate.return_value
            mock_instance.run.return_value = passing_gate_result

            result = validator.validate(ir)

            # Should have called the intent gate
            mock_instance.run.assert_called_once()

    def test_skips_auto_run_when_cached(self):
        """TransferContractValidator skips auto-run when schematic_intent_passed=True."""
        from kicad_agent.validation.gates.transfer_contract import TransferContractValidator

        r1 = _make_component(reference="R1", lib_id="Device:R", footprint="Resistor_SMD:R_0805_2012Metric")
        ir = _make_schematic_ir(components=[r1])

        validator = TransferContractValidator()

        with patch(
            "kicad_agent.validation.gates.schematic_intent_gate.SchematicIntentGate"
        ) as MockGate:
            mock_instance = MockGate.return_value

            result = validator.validate(ir, context={"schematic_intent_passed": True})

            # Should NOT have called the intent gate
            mock_instance.run.assert_not_called()

    def test_propagates_intent_gate_failure(self):
        """If SchematicIntentGate fails, TransferContractValidator returns its failure."""
        from kicad_agent.validation.gates.transfer_contract import TransferContractValidator

        r1 = _make_component(reference="R1", lib_id="Device:R", footprint="")
        ir = _make_schematic_ir(components=[r1])

        failing_gate_result = GateResult(
            pass_=False,
            gate_name="schematic_intent",
            stage=DesignStage.SCHEMATIC,
            blockers=["R1 has no footprint assigned"],
        )

        validator = TransferContractValidator()

        with patch(
            "kicad_agent.validation.gates.schematic_intent_gate.SchematicIntentGate"
        ) as MockGate:
            mock_instance = MockGate.return_value
            mock_instance.run.return_value = failing_gate_result

            result = validator.validate(ir)

            assert result.pass_bool is False
            assert "R1" in result.blockers[0]


# ===========================================================================
# Test: Empty schematic
# ===========================================================================

class TestEmptySchematic:
    """Test that an empty schematic returns a clean contract."""

    def test_empty_schematic_clean_contract(self):
        """Empty schematic with no components produces a passing, clean contract."""
        from kicad_agent.validation.gates.transfer_contract import TransferContractValidator

        ir = _make_schematic_ir(components=[])

        validator = TransferContractValidator()
        result = validator.validate(ir)

        assert result.pass_bool is True
        assert len(result.blockers) == 0


# ===========================================================================
# Test: Component without footprint fails
# ===========================================================================

class TestMissingFootprint:
    """Test that component without footprint fails the contract."""

    def test_no_footprint_fails(self):
        """Component with no footprint assigned produces a blocker."""
        from kicad_agent.validation.gates.transfer_contract import TransferContractValidator

        r1 = _make_component(reference="R1", lib_id="Device:R", footprint="")

        ir = _make_schematic_ir(components=[r1])

        validator = TransferContractValidator()
        result = validator.validate(ir)

        assert result.pass_bool is False
        assert any("R1" in b and "footprint" in b.lower() for b in result.blockers)


# ===========================================================================
# Test: Pin count mismatch
# ===========================================================================

class TestPinCountMismatch:
    """Test that pin count mismatch fails the contract."""

    def test_pin_count_mismatch_fails(self):
        """When verify_pin_map indicates mismatch, contract fails."""
        from kicad_agent.validation.gates.transfer_contract import TransferContractValidator

        r1 = _make_component(reference="R1", lib_id="Device:R", footprint="Resistor_SMD:R_0805_2012Metric")

        ir = _make_schematic_ir(
            components=[r1],
            verify_pin_map_returns={
                "R1": {
                    "symbol_pins": {"1", "2", "3"},  # 3 pins
                    "footprint_pads": set(),
                    "missing_in_footprint": {"3"},
                    "extra_in_footprint": set(),
                    "match": False,
                },
            },
        )

        validator = TransferContractValidator()
        result = validator.validate(ir)

        assert result.pass_bool is False
        assert any("pin" in b.lower() or "pad" in b.lower() for b in result.blockers)


# ===========================================================================
# Test: Net name case sensitivity
# ===========================================================================

class TestNetNameCaseSensitivity:
    """Test that net name comparison is case-sensitive."""

    def test_case_mismatch_detected(self):
        """GND vs gnd produces a mismatch blocker."""
        from kicad_agent.validation.gates.transfer_contract import (
            NetIdVerifier,
            TransferContract,
        )

        contract = TransferContract(
            symbol_footprint_map={},
            pin_pad_map={},
            net_assignments={"GND": "GND"},
            net_classes={},
        )

        # PCB has lowercase "gnd" -- case-sensitive mismatch
        pcb_ir = _make_pcb_ir(net_names=["gnd"])

        verifier = NetIdVerifier()
        result = verifier.verify_net_ids(contract, pcb_ir)

        assert len(result.blockers) > 0
        assert any("GND" in b or "gnd" in b for b in result.blockers)


# ===========================================================================
# Test: Golden LED + Resistor circuit
# ===========================================================================

class TestGoldenLedResistor:
    """Golden test: LED+resistor circuit transfers correctly."""

    def test_led_resistor_transfer(self):
        """R1 (Device:R) and D1 (Device:LED) transfer correctly."""
        from kicad_agent.validation.gates.transfer_contract import TransferContractValidator

        r1 = _make_component(
            reference="R1",
            lib_id="Device:R",
            footprint="Resistor_SMD:R_0805_2012Metric",
            value="1k",
        )
        d1 = _make_component(
            reference="D1",
            lib_id="Device:LED",
            footprint="LED_SMD:LED_0805_2012Metric",
            value="LED",
        )

        ir = _make_schematic_ir(
            components=[r1, d1],
            verify_pin_map_returns={
                "R1": {
                    "symbol_pins": {"1", "2"},
                    "footprint_pads": set(),
                    "missing_in_footprint": set(),
                    "extra_in_footprint": set(),
                    "match": True,
                },
                "D1": {
                    "symbol_pins": {"1", "2"},
                    "footprint_pads": set(),
                    "missing_in_footprint": set(),
                    "extra_in_footprint": set(),
                    "match": True,
                },
            },
        )

        validator = TransferContractValidator()
        result = validator.validate(ir)

        assert result.pass_bool is True
        assert len(result.blockers) == 0

    def test_led_resistor_with_pcb_ir(self):
        """LED+resistor with PcbIR runs PadNetAssigner and NetIdVerifier."""
        from kicad_agent.validation.gates.transfer_contract import TransferContractValidator

        r1 = _make_component(
            reference="R1",
            lib_id="Device:R",
            footprint="Resistor_SMD:R_0805_2012Metric",
            value="1k",
        )
        d1 = _make_component(
            reference="D1",
            lib_id="Device:LED",
            footprint="LED_SMD:LED_0805_2012Metric",
            value="LED",
        )

        ir = _make_schematic_ir(
            components=[r1, d1],
            verify_pin_map_returns={
                "R1": {
                    "symbol_pins": {"1", "2"},
                    "footprint_pads": set(),
                    "missing_in_footprint": set(),
                    "extra_in_footprint": set(),
                    "match": True,
                },
                "D1": {
                    "symbol_pins": {"1", "2"},
                    "footprint_pads": set(),
                    "missing_in_footprint": set(),
                    "extra_in_footprint": set(),
                    "match": True,
                },
            },
        )

        pcb_ir = _make_pcb_ir(
            footprints={"R1": ["1", "2"], "D1": ["1", "2"]},
            net_names=["VCC", "GND", "LED_K"],
        )

        validator = TransferContractValidator()
        result = validator.validate(ir, pcb_ir=pcb_ir)

        assert result.pass_bool is True
        assert len(result.blockers) == 0
