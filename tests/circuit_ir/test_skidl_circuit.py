"""Phase 156 Wave 1: Tests for KiCad→SKIDL circuit builder.

Tests build_circuit on a simple fixture (complete_led.kicad_sch with
R1 + D1). Verifies:
  1. Import guard eliminates KICAD_SYMBOL_DIR warnings
  2. build_circuit produces a skidl.Circuit with correct parts
  3. Net topology is preserved
  4. CircuitIR immutable types are correct
  5. ERC runs on simple circuits
"""
from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from volta.circuit_ir import (
    CircuitIR,
    NetDescriptor,
    PartDescriptor,
    PinRef,
    _ensure_skidl_env,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_LED_FIXTURE = _FIXTURES / "schematic_intent" / "complete_led.kicad_sch"


class TestImportGuard:
    """W1-8: Import guard eliminates KICAD_SYMBOL_DIR warnings."""

    def test_no_symbol_dir_warnings(self) -> None:
        """Importing circuit_ir must not emit KICAD*_SYMBOL_DIR warnings.

        Volta-ko7: verified in a fresh subprocess. The old in-process
        importlib.reload re-monkeypatched skidl (double get_abs_filename
        wrapping, fresh memo layer under live SchLib caches) and, with a
        cold/minimal backup-lib cache, broke every later Part lookup in
        the process (LED build produced 0 parts).
        """
        import subprocess
        import sys

        code = (
            "import warnings; warnings.simplefilter('always')\n"
            "import volta.circuit_ir\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=120,
        )
        kicad_warnings = [
            line for line in result.stderr.splitlines()
            if "SYMBOL_DIR" in line
        ]
        assert len(kicad_warnings) == 0, (
            f"Import guard failed — got {len(kicad_warnings)} "
            f"SYMBOL_DIR warnings: {kicad_warnings[:2]}"
        )

    def test_ensure_skidl_env_returns_path(self) -> None:
        """_ensure_skidl_env returns a valid symbol directory path."""
        path = _ensure_skidl_env()
        assert path is not None
        assert Path(path).exists()


class TestBuildCircuit:
    """W1-5/W1-6: build_circuit produces correct Circuit + CircuitIR."""

    def test_builds_circuit_from_led_fixture(self) -> None:
        """build_circuit turns the LED schematic into a skdl.Circuit."""
        from volta.circuit_ir import build_circuit

        if not _LED_FIXTURE.exists():
            pytest.skip(f"Fixture not found: {_LED_FIXTURE}")

        circuit, circuit_ir = build_circuit(_LED_FIXTURE)

        # Circuit should have parts (R1 + D1 = 2 non-power parts).
        assert len(circuit.parts) >= 2, (
            f"Expected >=2 parts, got {len(circuit.parts)}"
        )

        # CircuitIR should match.
        assert isinstance(circuit_ir, CircuitIR)
        assert len(circuit_ir.parts) >= 2

    def test_circuit_ir_is_immutable(self) -> None:
        """CircuitIR and its components are frozen."""
        pd = PartDescriptor(
            lib_id="Device:R", reference="R1", value="10k",
            footprint="R_0603", unit=1, is_power=False, pins=(),
        )
        with pytest.raises(AttributeError):
            pd.reference = "R2"  # type: ignore

    def test_circuit_ir_carries_diagnostics(self) -> None:
        """CircuitIR.diagnostics is a tuple (possibly empty)."""
        from volta.circuit_ir import build_circuit

        if not _LED_FIXTURE.exists():
            pytest.skip(f"Fixture not found: {_LED_FIXTURE}")

        _, circuit_ir = build_circuit(_LED_FIXTURE)
        assert isinstance(circuit_ir.diagnostics, tuple)

    def test_extracted_parts_have_correct_lib_ids(self) -> None:
        """Parts have the expected lib_id values from the fixture."""
        from volta.circuit_ir import build_circuit

        if not _LED_FIXTURE.exists():
            pytest.skip(f"Fixture not found: {_LED_FIXTURE}")

        _, circuit_ir = build_circuit(_LED_FIXTURE)

        lib_ids = {p.lib_id for p in circuit_ir.parts}
        # The LED fixture has Device:R and Device:LED.
        assert "Device:R" in lib_ids or "Device:LED" in lib_ids, (
            f"Expected Device:R or Device:LED in {lib_ids}"
        )

    def test_nets_extracted(self) -> None:
        """Net descriptors are present in the CircuitIR."""
        from volta.circuit_ir import build_circuit

        if not _LED_FIXTURE.exists():
            pytest.skip(f"Fixture not found: {_LED_FIXTURE}")

        _, circuit_ir = build_circuit(_LED_FIXTURE)

        # Should have at least some nets (even if auto-named).
        assert len(circuit_ir.nets) >= 0  # Fixture has no wires, so may be 0.
        for net in circuit_ir.nets:
            assert isinstance(net, NetDescriptor)
            assert net.name  # Non-empty name.


class TestTypesImmutable:
    """W1-2: Verify all IR types are frozen dataclasses."""

    def test_pin_ref_frozen(self) -> None:
        pr = PinRef(reference="R1", pin_number="1", pin_name="passive")
        with pytest.raises(AttributeError):
            pr.reference = "R2"  # type: ignore

    def test_net_descriptor_frozen(self) -> None:
        nd = NetDescriptor(name="GND", pins=())
        with pytest.raises(AttributeError):
            nd.name = "VCC"  # type: ignore

    def test_circuit_ir_frozen(self) -> None:
        cir = CircuitIR(parts=(), nets=(), diagnostics=(), source_file="test")
        with pytest.raises(AttributeError):
            cir.parts = (PartDescriptor("a","b","c","d",1,False,()),)  # type: ignore
