"""Tests for SchematicIntentGate -- schematic intent completeness checks.

Distribution per council LOW-1:
  - Footprint completeness: 4 tests (pass, fail missing fp, DNP excluded, power symbol excluded)
  - Symbol pin count: 2 tests (mismatch detected, no hint in name is skipped)
  - Component metadata: 2 tests (missing value warns, missing MPN warns)
  - Combined gate: 2 tests (complete passes, incomplete blocks)
  - Gate registration: 1 test (verify registered with GateRunner)
  - Total: 11 tests
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "schematic_intent"


@pytest.fixture(autouse=True)
def _clear_ir_registry():
    """Clear the IR registry between tests to prevent one-IR-per-ParseResult errors."""
    from kicad_agent.ir.base import _clear_registry
    _clear_registry()
    yield


def _load_ir(fixture_name: str):
    """Load a fixture schematic and build SchematicIR."""
    from kicad_agent.parser import parse_schematic
    from kicad_agent.ir.schematic_ir import SchematicIR

    sch_path = FIXTURES_DIR / fixture_name
    parse_result = parse_schematic(sch_path)
    ir = SchematicIR(_parse_result=parse_result)
    return ir


def _make_context(ir=None, sch_path=None):
    """Build a context dict for gate run()."""
    ctx = {}
    if ir is not None:
        ctx["schematic_ir"] = ir
    if sch_path is not None:
        ctx["sch_path"] = sch_path
    return ctx


# ---------------------------------------------------------------------------
# Footprint completeness tests (4)
# ---------------------------------------------------------------------------


class TestFootprintCompleteness:
    """Tests for check_footprint_completeness sub-check."""

    def test_footprint_completeness_pass(self):
        """Complete LED schematic passes footprint check -- no blockers."""
        from kicad_agent.validation.gates.schematic_intent_gate import (
            check_footprint_completeness,
        )

        ir = _load_ir("complete_led.kicad_sch")
        blockers, warnings = check_footprint_completeness(ir)
        assert blockers == [], f"Expected no blockers, got: {blockers}"

    def test_footprint_completeness_fail_missing(self):
        """Schematic with missing footprint produces blocker listing reference and lib_id."""
        from kicad_agent.validation.gates.schematic_intent_gate import (
            check_footprint_completeness,
        )

        ir = _load_ir("missing_footprint.kicad_sch")
        blockers, warnings = check_footprint_completeness(ir)
        assert len(blockers) > 0, "Expected at least one blocker for missing footprint"
        # Blocker should mention D1 (the LED without a footprint)
        assert any("D1" in b for b in blockers), (
            f"Expected blocker to mention D1, got: {blockers}"
        )

    def test_footprint_completeness_dnp_excluded(self):
        """DNP components (dnp=True) are excluded from footprint check."""
        from kicad_agent.validation.gates.schematic_intent_gate import (
            check_footprint_completeness,
        )

        ir = _load_ir("dnp_component.kicad_sch")
        blockers, warnings = check_footprint_completeness(ir)
        # D1 and R2 are both DNP with no footprint, but should not appear as blockers
        for b in blockers:
            assert "D1" not in b, f"DNP component D1 should be excluded: {b}"
            assert "R2" not in b, f"DNP component R2 should be excluded: {b}"

    def test_footprint_completeness_power_symbol_excluded(self):
        """Power symbols (libId starts with 'power:') are excluded from all checks."""
        from kicad_agent.validation.gates.schematic_intent_gate import (
            check_footprint_completeness,
        )

        # Create a mock component with power: libId and no footprint
        mock_ir = MagicMock()
        power_sym = MagicMock()
        power_sym.libId = "power:+3V3"
        power_sym.dnp = False

        # Component with normal libId and valid footprint
        normal_sym = MagicMock()
        normal_sym.libId = "Device:R"
        normal_sym.dnp = False

        mock_ir.components = [power_sym, normal_sym]
        mock_ir.get_component_property = MagicMock(side_effect=lambda c, k: {
            (power_sym, "Reference"): "#PWR01",
            (normal_sym, "Reference"): "R1",
            (normal_sym, "Footprint"): "Resistor_SMD:R_0805",
            (power_sym, "Footprint"): "",
        }.get((c, k)))

        blockers, warnings = check_footprint_completeness(mock_ir)
        assert blockers == [], f"Power symbols should be excluded: {blockers}"


# ---------------------------------------------------------------------------
# Symbol pin count tests (2)
# ---------------------------------------------------------------------------


class TestSymbolPinCount:
    """Tests for check_symbol_pin_count sub-check."""

    def test_pin_count_mismatch_detected(self):
        """Symbol pin count mismatch produces a blocker with expected vs actual count."""
        from kicad_agent.validation.gates.schematic_intent_gate import (
            check_symbol_pin_count,
        )

        # Create a mock IR where a component's lib_symbol has 6 pins
        # but the symbol name suggests 8 (NE5532 is a known 8-pin op-amp)
        mock_ir = MagicMock()

        comp = MagicMock()
        comp.libId = "MyLib:NE5532"
        comp.dnp = False

        # lib_symbol with only 6 pins (mismatch with expected 8 from NE5532)
        lib_sym = MagicMock()
        lib_unit = MagicMock()
        pins_list = []
        for i in range(1, 7):  # Only 6 pins
            p = MagicMock()
            p.number = i
            pins_list.append(p)
        lib_unit.pins = pins_list
        lib_sym.units = [lib_unit]
        lib_sym.libId = "MyLib:NE5532"

        mock_ir.components = [comp]
        mock_ir.schematic.libSymbols = [lib_sym]
        mock_ir.get_component_property = MagicMock(side_effect=lambda c, k: {
            (comp, "Reference"): "U1",
        }.get((c, k)))

        blockers, warnings = check_symbol_pin_count(mock_ir)
        assert len(blockers) > 0, f"Expected blocker for pin count mismatch, got: {blockers}"
        assert "6" in blockers[0] and "8" in blockers[0], (
            f"Blocker should mention actual=6 and expected=8: {blockers[0]}"
        )

    def test_pin_count_no_hint_in_name_skipped(self):
        """If pin count cannot be determined from name, no blocker is produced."""
        from kicad_agent.validation.gates.schematic_intent_gate import (
            check_symbol_pin_count,
        )

        mock_ir = MagicMock()

        comp = MagicMock()
        comp.libId = "CustomLib:MyCustomPart"
        comp.dnp = False

        lib_sym = MagicMock()
        lib_unit = MagicMock()
        pin1 = MagicMock()
        pin1.number = 1
        lib_unit.pins = [pin1]
        lib_sym.units = [lib_unit]
        lib_sym.libId = "CustomLib:MyCustomPart"

        mock_ir.components = [comp]
        mock_ir.schematic.libSymbols = [lib_sym]
        mock_ir.get_component_property = MagicMock(side_effect=lambda c, k: {
            (comp, "Reference"): "U1",
        }.get((c, k)))

        blockers, warnings = check_symbol_pin_count(mock_ir)
        assert blockers == [], (
            f"Expected no blockers when pin count hint is absent: {blockers}"
        )


# ---------------------------------------------------------------------------
# Component metadata tests (2)
# ---------------------------------------------------------------------------


class TestComponentMetadata:
    """Tests for check_component_metadata sub-check."""

    def test_missing_value_warns(self):
        """Missing Value property on a non-DNP component with footprint produces warning."""
        from kicad_agent.validation.gates.schematic_intent_gate import (
            check_component_metadata,
        )

        ir = _load_ir("missing_metadata.kicad_sch")
        blockers, warnings = check_component_metadata(ir)
        # R1 has empty Value
        assert any("R1" in w and "value" in w.lower() for w in warnings), (
            f"Expected warning about R1 missing value, got: {warnings}"
        )
        # Metadata check produces warnings, not blockers
        assert blockers == [], f"Metadata should warn not block: {blockers}"

    def test_missing_mpn_warns(self):
        """Missing MPN property on non-DNP components produces warning."""
        from kicad_agent.validation.gates.schematic_intent_gate import (
            check_component_metadata,
        )

        ir = _load_ir("complete_led.kicad_sch")
        # Both components have MPN, so strip it to test the warning
        # Instead, use missing_metadata which has no MPN on D1
        ir2 = _load_ir("missing_metadata.kicad_sch")
        blockers, warnings = check_component_metadata(ir2)
        # D1 has no MPN property in missing_metadata fixture
        assert any("D1" in w and "MPN" in w for w in warnings), (
            f"Expected warning about D1 missing MPN, got: {warnings}"
        )


# ---------------------------------------------------------------------------
# Combined gate tests (2)
# ---------------------------------------------------------------------------


class TestCombinedGate:
    """Tests for the full SchematicIntentGate.run() method."""

    def test_complete_schematic_passes_gate(self):
        """Complete LED schematic passes all checks (GateResult.pass_=True)."""
        from kicad_agent.validation.gates.schematic_intent_gate import SchematicIntentGate

        ir = _load_ir("complete_led.kicad_sch")
        gate = SchematicIntentGate()
        result = gate.run({"schematic_ir": ir, "sch_path": str(FIXTURES_DIR / "complete_led.kicad_sch")})
        assert result.pass_ is True, f"Expected pass, got blockers: {result.blockers}, warnings: {result.warnings}"

    def test_incomplete_schematic_blocks_gate(self):
        """Schematic with missing footprint blocks the gate (GateResult.pass_=False)."""
        from kicad_agent.validation.gates.schematic_intent_gate import SchematicIntentGate

        ir = _load_ir("missing_footprint.kicad_sch")
        gate = SchematicIntentGate()
        result = gate.run({"schematic_ir": ir, "sch_path": str(FIXTURES_DIR / "missing_footprint.kicad_sch")})
        assert result.pass_ is False, "Expected gate to fail for missing footprint"
        assert len(result.blockers) > 0, "Expected non-empty blockers"

    def test_ir_built_once_passed_to_all_checks(self):
        """SchematicIR is built once and passed to all sub-checks (verify via mock call count)."""
        from kicad_agent.validation.gates.schematic_intent_gate import SchematicIntentGate

        ir = _load_ir("complete_led.kicad_sch")
        gate = SchematicIntentGate()

        # Patch sub-checks to track call count
        with patch(
            "kicad_agent.validation.gates.schematic_intent_gate.check_footprint_completeness"
        ) as mock_fp, patch(
            "kicad_agent.validation.gates.schematic_intent_gate.check_symbol_pin_count"
        ) as mock_pc, patch(
            "kicad_agent.validation.gates.schematic_intent_gate.check_component_metadata"
        ) as mock_md:
            mock_fp.return_value = ([], [])
            mock_pc.return_value = ([], [])
            mock_md.return_value = ([], [])

            gate.run({
                "schematic_ir": ir,
                "sch_path": str(FIXTURES_DIR / "complete_led.kicad_sch"),
            })

            # Each check should be called exactly once with the same IR
            mock_fp.assert_called_once_with(ir)
            mock_pc.assert_called_once_with(ir)
            mock_md.assert_called_once_with(ir)


# ---------------------------------------------------------------------------
# Gate registration tests (1)
# ---------------------------------------------------------------------------


class TestGateRegistration:
    """Tests for gate registration with GateRunner."""

    def test_gate_registered_with_runner(self):
        """SchematicIntentGate registers with GateRunner via register_gate() on module import."""
        from kicad_agent.validation.gate_runner import get_gate_runner

        runner = get_gate_runner()
        gate_def = runner.get_gate("schematic_intent")

        assert gate_def is not None, "schematic_intent gate should be registered"
        assert gate_def.from_stage.value == "schematic"
        assert gate_def.to_stage.value == "pcb_setup"
        assert runner.has_check_fn("schematic_intent"), (
            "schematic_intent gate should have a check function registered"
        )

    def test_gate_coexists_with_pre_pcb_schematic_gate(self):
        """Both schematic_intent and pre_pcb_schematic_gate are registered for schematic->pcb_setup."""
        from kicad_agent.validation.gate_runner import get_gate_runner
        from kicad_agent.validation.gate_types import DesignStage

        runner = get_gate_runner()
        intent_gate = runner.get_gate("schematic_intent")

        # pre_pcb_schematic_gate uses lazy registration (only on first successful call).
        # Use a real fixture to trigger registration without exceptions.
        from kicad_agent.ops.validation_gates import pre_pcb_schematic_gate

        # The complete_led fixture is valid and parseable, so the gate should
        # run through to the registration block. Use require_erc_clean=False
        # to avoid needing kicad-cli.
        fixture_path = FIXTURES_DIR / "complete_led.kicad_sch"
        pre_pcb_schematic_gate(fixture_path, require_erc_clean=False, require_footprints=False)

        pre_pcb_gate = runner.get_gate("pre_pcb_schematic")

        assert intent_gate is not None, "schematic_intent gate must be registered"
        assert pre_pcb_gate is not None, "pre_pcb_schematic_gate must be registered"
        assert intent_gate.from_stage == DesignStage.SCHEMATIC
        assert intent_gate.to_stage == DesignStage.PCB_SETUP
        assert intent_gate.from_stage == pre_pcb_gate.from_stage, (
            "Both gates should share the same from_stage"
        )
        assert intent_gate.to_stage == pre_pcb_gate.to_stage, (
            "Both gates should share the same to_stage"
        )
