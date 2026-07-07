"""Phase 204: BOM markdown generation from skidl Circuit."""
from __future__ import annotations

from kicad_agent.sim.bom import circuit_to_bom_markdown
from kicad_agent.sim.eurorack import build_preamp_circuit


def _fixture_circuit():
    return build_preamp_circuit(4.7e3, 68e3, 10e3, 470, 10e-6, 10e-6, 100e-6)


def test_bom_has_title_header() -> None:
    md = circuit_to_bom_markdown(_fixture_circuit())
    assert md.startswith("# Bill of Materials")


def test_bom_has_table_header() -> None:
    md = circuit_to_bom_markdown(_fixture_circuit())
    assert "| Ref | Value | Footprint |" in md
    assert "|-----|-------|-----------|" in md


def test_bom_lists_all_8_parts() -> None:
    md = circuit_to_bom_markdown(_fixture_circuit())
    for ref in ("Q1", "R1", "R2", "R3", "R4", "C1", "C2", "C3"):
        assert ref in md, f"BOM missing {ref}"


def test_bom_total_parts_count() -> None:
    md = circuit_to_bom_markdown(_fixture_circuit())
    assert "Total parts: 8" in md


def test_bom_value_uses_engineering_notation() -> None:
    md = circuit_to_bom_markdown(_fixture_circuit())
    # R1 row should show "4.7k" not "4700.0" or "4700"
    r1_line = next(ln for ln in md.splitlines() if ln.startswith("| R1 "))
    assert "4.7k" in r1_line, f"R1 line not in engineering notation: {r1_line!r}"
