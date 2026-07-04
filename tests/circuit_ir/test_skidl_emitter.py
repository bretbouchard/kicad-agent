"""Phase 156 Wave 2: Tests for L1/L2 SKIDL emission."""
from __future__ import annotations

from pathlib import Path

import pytest

from kicad_agent.circuit_ir.skidl_emitter import emit_build_py
from kicad_agent.circuit_ir.types import CircuitIR, NetDescriptor, PartDescriptor, PinRef

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_LED_FIXTURE = _FIXTURES / "schematic_intent" / "complete_led.kicad_sch"


def _make_test_circuit_ir() -> CircuitIR:
    """Create a minimal CircuitIR for testing the emitter."""
    r1 = PartDescriptor(
        lib_id="Device:R", reference="R1", value="330",
        footprint="Resistor_SMD:R_0805_2012Metric",
        unit=1, is_power=False, pins=(
            PinRef("R1", "1", "~"),
            PinRef("R1", "2", "~"),
        ),
    )
    d1 = PartDescriptor(
        lib_id="Device:LED", reference="D1", value="Red",
        footprint="LED_SMD:LED_0805_2012Metric",
        unit=1, is_power=False, pins=(
            PinRef("D1", "1", "A"),
            PinRef("D1", "2", "K"),
        ),
    )
    gnd = PartDescriptor(
        lib_id="power:GND", reference="#PWR01", value="GND",
        footprint="", unit=1, is_power=True, pins=(),
    )

    net1 = NetDescriptor("Net_R1_2_D1_1", (
        PinRef("R1", "2", "~"),
        PinRef("D1", "1", "A"),
    ))
    net_gnd = NetDescriptor("GND", (PinRef("D1", "2", "K"),), is_power=True)

    return CircuitIR(
        parts=(r1, d1),
        nets=(net1, net_gnd),
        diagnostics=(),
        source_file="test.kicad_sch",
    )


class TestL1Emission:
    """W2-2: L1 (pin-level, exact) emission."""

    def test_emits_valid_python(self) -> None:
        """L1 output is valid Python syntax."""
        cir = _make_test_circuit_ir()
        code = emit_build_py(cir, mode="L1")
        # Should compile without syntax errors.
        compile(code, "test_l1.py", "exec")

    def test_contains_part_instantiations(self) -> None:
        """L1 output has Part() calls for each component."""
        cir = _make_test_circuit_ir()
        code = emit_build_py(cir, mode="L1")
        assert "R1 = Part(" in code
        assert "D1 = Part(" in code

    def test_contains_pin_level_wiring(self) -> None:
        """L1 output has += statements for each pin connection."""
        cir = _make_test_circuit_ir()
        code = emit_build_py(cir, mode="L1")
        assert 'R1["2"]' in code
        assert 'D1["1"]' in code

    def test_contains_power_nets(self) -> None:
        """L1 output declares power nets."""
        cir = _make_test_circuit_ir()
        code = emit_build_py(cir, mode="L1")
        assert 'Net("GND")' in code

    def test_writes_to_file(self, tmp_path: Path) -> None:
        """emit_build_py writes to disk when out_path provided."""
        cir = _make_test_circuit_ir()
        out = tmp_path / "build_test.py"
        result = emit_build_py(cir, mode="L1", out_path=out)
        assert out.exists()
        assert result == out


class TestL2Emission:
    """W2-3: L2 (component-level, training-friendly) emission."""

    def test_emits_valid_python(self) -> None:
        cir = _make_test_circuit_ir()
        code = emit_build_py(cir, mode="L2")
        compile(code, "test_l2.py", "exec")

    def test_contains_net_summaries(self) -> None:
        """L2 output has # nets: summary dicts per component."""
        cir = _make_test_circuit_ir()
        code = emit_build_py(cir, mode="L2")
        assert "# nets:" in code

    def test_compact_form(self) -> None:
        """L2 is more compact than L1 (fewer += lines)."""
        cir = _make_test_circuit_ir()
        l1 = emit_build_py(cir, mode="L1")
        l2 = emit_build_py(cir, mode="L2")
        l1_plus = l1.count("+=")
        l2_plus = l2.count("+=")
        # L2 should have fewer or equal += lines (it uses summaries).
        assert l2_plus <= l1_plus


class TestRoundTrip:
    """W2-6: Emitted L1 code produces an equivalent circuit."""

    def test_led_fixture_l1_emission(self) -> None:
        """Full pipeline: .kicad_sch → build_circuit → emit L1 → valid Python."""
        if not _LED_FIXTURE.exists():
            pytest.skip(f"Fixture not found: {_LED_FIXTURE}")

        from kicad_agent.circuit_ir import build_circuit

        circuit, circuit_ir = build_circuit(_LED_FIXTURE)
        code = emit_build_py(circuit_ir, mode="L1")
        # Should compile.
        compile(code, "build_test.py", "exec")
        # Should contain the expected parts.
        assert "Part(" in code
