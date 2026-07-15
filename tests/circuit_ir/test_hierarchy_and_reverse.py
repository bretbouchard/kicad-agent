"""Phase 156 Wave 4-6: Tests for hierarchy flattener + SKIDL→KiCad."""
from __future__ import annotations

from pathlib import Path

import pytest

from volta.circuit_ir.hierarchy_flattener import flatten_to_circuit_ir
from volta.circuit_ir.skidl_to_kicad import circuit_to_kicad_sch
from volta.circuit_ir.types import CircuitIR

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_LED_FIXTURE = _FIXTURES / "schematic_intent" / "complete_led.kicad_sch"


class TestHierarchyFlattener:
    """W4: flatten_hierarchy produces flat parts + nets from any schematic."""

    def test_flatten_single_sheet(self) -> None:
        """Single-sheet schematic flattens to parts + nets."""
        if not _LED_FIXTURE.exists():
            pytest.skip(f"Fixture not found: {_LED_FIXTURE}")

        circuit_ir = flatten_to_circuit_ir(_LED_FIXTURE)
        assert isinstance(circuit_ir, CircuitIR)
        assert len(circuit_ir.parts) >= 2

    def test_parts_have_sheet_metadata(self) -> None:
        """Flattened parts carry sheet origin metadata."""
        if not _LED_FIXTURE.exists():
            pytest.skip(f"Fixture not found: {_LED_FIXTURE}")

        circuit_ir = flatten_to_circuit_ir(_LED_FIXTURE)
        for part in circuit_ir.parts:
            assert part.sheet is not None  # All tagged with origin.

    def test_diagnostics_is_tuple(self) -> None:
        """Diagnostics is always a tuple."""
        if not _LED_FIXTURE.exists():
            pytest.skip(f"Fixture not found: {_LED_FIXTURE}")

        circuit_ir = flatten_to_circuit_ir(_LED_FIXTURE)
        assert isinstance(circuit_ir.diagnostics, tuple)


class TestSkidlToKiCad:
    """W6: circuit_to_kicad_sch generates valid .kicad_sch output."""

    def test_generates_valid_schematic(self, tmp_path: Path) -> None:
        """SKIDL→KiCad produces a parseable .kicad_sch file."""
        if not _LED_FIXTURE.exists():
            pytest.skip(f"Fixture not found: {_LED_FIXTURE}")

        from volta.circuit_ir import build_circuit

        circuit, _ = build_circuit(_LED_FIXTURE)
        out = tmp_path / "test_output.kicad_sch"
        result = circuit_to_kicad_sch(circuit, out)

        assert result == out
        assert out.exists()
        content = out.read_text()
        assert "(kicad_sch" in content
        assert "(version " in content
        assert "(lib_symbols" in content
        assert "(symbol" in content.lower()

    def test_symbol_placement_on_grid(self, tmp_path: Path) -> None:
        """Generated symbols have (at X Y) coordinates."""
        if not _LED_FIXTURE.exists():
            pytest.skip(f"Fixture not found: {_LED_FIXTURE}")

        from volta.circuit_ir import build_circuit

        circuit, _ = build_circuit(_LED_FIXTURE)
        out = tmp_path / "test_placement.kicad_sch"
        circuit_to_kicad_sch(circuit, out)
        content = out.read_text()
        assert "(at " in content  # Has placement coordinates.

    def test_components_have_references(self, tmp_path: Path) -> None:
        """Generated symbols have Reference properties."""
        if not _LED_FIXTURE.exists():
            pytest.skip(f"Fixture not found: {_LED_FIXTURE}")

        from volta.circuit_ir import build_circuit

        circuit, _ = build_circuit(_LED_FIXTURE)
        out = tmp_path / "test_refs.kicad_sch"
        circuit_to_kicad_sch(circuit, out)
        content = out.read_text()
        assert '"Reference"' in content


class TestRoundTrip:
    """W6-9: KiCad → SKIDL → KiCad round-trip stability."""

    def test_round_trip_preserves_part_count(self, tmp_path: Path) -> None:
        """KiCad → SKIDL → KiCad preserves component count."""
        if not _LED_FIXTURE.exists():
            pytest.skip(f"Fixture not found: {_LED_FIXTURE}")

        from volta.circuit_ir import build_circuit

        # Original → SKIDL
        circuit, circuit_ir = build_circuit(_LED_FIXTURE)
        original_count = len(circuit_ir.parts)

        # SKIDL → KiCad
        out = tmp_path / "round_trip.kicad_sch"
        circuit_to_kicad_sch(circuit, out)

        # Verify the output has the same number of symbol instances.
        content = out.read_text()
        # Count (symbol (lib_id ... blocks.
        import re
        symbol_count = len(re.findall(r'\(symbol\s+\(lib_id', content))
        assert symbol_count == original_count, (
            f"Round-trip part count mismatch: {original_count} → {symbol_count}"
        )
