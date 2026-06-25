"""R-1: (outline ...) dimensions match courtyard or fall back to pad bbox."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from kicad_agent.routing.dsn_generator import generate_dsn

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "smd_test_board.kicad_pcb"


def test_r1_outline_nonzero_dimensions() -> None:
    """Each (image ...) has an (outline (rect ...)) with non-zero dimensions."""
    if not _FIXTURE.exists():
        pytest.skip(f"Fixture missing: {_FIXTURE}")
    content = _FIXTURE.read_text(encoding="utf-8")
    dsn = generate_dsn(content, _FIXTURE)

    # Parse every (outline (rect LAYER X1 Y1 X2 Y2)) and assert non-zero area.
    import re

    outlines = re.findall(r"\(outline \(rect \S+ (-?\d+) (-?\d+) (-?\d+) (-?\d+)\)", dsn)
    assert outlines, "No (outline (rect ...)) emitted"
    for x1, y1, x2, y2 in outlines:
        dx = abs(int(x2) - int(x1))
        dy = abs(int(y2) - int(y1))
        assert dx > 0 and dy > 0, (
            f"Outline rect has zero dimensions: ({x1},{y1})-({x2},{y2})"
        )


def test_r1_pad_bbox_fallback_when_no_crtyd(monkeypatch, tmp_path) -> None:
    """Footprint without F.CrtYd falls back to pad bounding box (non-zero)."""
    if not _FIXTURE.exists():
        pytest.skip(f"Fixture missing: {_FIXTURE}")
    from kicad_agent.parser import pcb_native_parser as pnp_mod
    from kicad_agent.parser.pcb_native_types import NativeFootprint
    import dataclasses

    content = _FIXTURE.read_text(encoding="utf-8")
    board = pnp_mod.NativeParser.parse_pcb_content(content, str(_FIXTURE))
    assert board.footprints, "Fixture needs footprints"

    # Force every footprint to have zero CrtYd graphics -> fallback path.
    # Phase 100 CR-01: NativeFootprint is frozen — use dataclasses.replace, not in-place mutation.
    original_parse = pnp_mod.NativeParser.parse_pcb_content

    def _stripped_parse(text: str, file_path: str = ""):
        b = original_parse(text, file_path)
        new_footprints = []
        for fp in b.footprints:
            stripped = tuple(
                g for g in fp.graphic_items if not getattr(g.layer, "", "").endswith(".CrtYd")
            )
            new_footprints.append(dataclasses.replace(fp, graphic_items=stripped))
        return dataclasses.replace(b, footprints=tuple(new_footprints))

    monkeypatch.setattr(pnp_mod.NativeParser, "parse_pcb_content", _stripped_parse)

    dsn = generate_dsn(content, _FIXTURE)
    import re

    outlines = re.findall(r"\(outline \(rect \S+ (-?\d+) (-?\d+) (-?\d+) (-?\d+)\)", dsn)
    assert outlines, "Fallback path emitted no outlines"
    for x1, y1, x2, y2 in outlines:
        dx = abs(int(x2) - int(x1))
        dy = abs(int(y2) - int(y1))
        assert dx > 0 and dy > 0, (
            f"Fallback outline rect has zero dimensions: ({x1},{y1})-({x2},{y2})"
        )
