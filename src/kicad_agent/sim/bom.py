"""Phase 204: BOM markdown generator for skidl Circuit.

skidl 2.2.3 does NOT have circuit.BOM() — hand-rolled from circuit.parts.
F-string template is sufficient for a 7-8 component BOM (no Jinja2 needed).
"""
from __future__ import annotations

from typing import Any

from kicad_agent.sim.eurorack import _sci


def circuit_to_bom_markdown(circuit: Any) -> str:
    """Generate BOM markdown from a skidl.Circuit.

    Walks circuit.parts (each has .ref, .value, .footprint). Passives get
    engineering-formatted values (4.7k, 10u); transistors keep model name.

    Args:
        circuit: Live skidl.Circuit.

    Returns:
        Markdown string with a table of all parts.
    """
    lines = [
        "# Bill of Materials",
        "",
        "| Ref | Value | Footprint |",
        "|-----|-------|-----------|",
    ]

    def _sort_key(part: Any) -> tuple[int, int]:
        # Group: Q first, then R, then C, then alpha within group
        ref_letter = part.ref[0]
        group_order = {"Q": 0, "R": 1, "C": 2}.get(ref_letter, 9)
        try:
            num = int(part.ref[1:])
        except ValueError:
            num = 0
        return (group_order, num)

    parts_list = list(circuit.parts)
    for part in sorted(parts_list, key=_sort_key):
        ref = part.ref
        # Passives: format numerically; everything else: stringify.
        raw = part.value if part.value is not None else ""
        try:
            val = _sci(float(raw)) if ref[0] in ("R", "C", "L") else str(raw)
        except (TypeError, ValueError):
            val = str(raw)
        fp = getattr(part, "footprint", "") or "—"
        lines.append(f"| {ref} | {val} | {fp} |")

    lines.append("")
    lines.append(f"_Total parts: {len(parts_list)}_")
    return "\n".join(lines)
