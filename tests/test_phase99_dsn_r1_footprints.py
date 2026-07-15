"""R-1: every footprint produces an (image ...) block with (outline ...) in DSN."""
from __future__ import annotations

from pathlib import Path

import pytest

from volta.parser.pcb_native_parser import NativeParser
from volta.routing.dsn_generator import generate_dsn

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "Arduino_Mega" / "Arduino_Mega.kicad_pcb"


def test_r1_every_footprint_produces_image_block() -> None:
    """Every footprint lib_id in the source PCB appears inside an (image "...") block."""
    if not _FIXTURE.exists():
        pytest.skip(f"Fixture missing: {_FIXTURE}")
    content = _FIXTURE.read_text(encoding="utf-8")
    board = NativeParser.parse_pcb_content(content, str(_FIXTURE))
    assert len(board.footprints) > 0, "Fixture must have footprints for R-1"

    dsn = generate_dsn(content, _FIXTURE)

    # Every unique lib_id must appear in an (image "...") block.
    # DSN format is multi-line: (image "NAME"\n  (side ...)\n  ...
    seen_lib_ids = {fp.lib_id for fp in board.footprints if fp.lib_id}
    for lib_id in seen_lib_ids:
        assert f'(image "{lib_id}"' in dsn, (
            f"lib_id {lib_id!r} missing from DSN library (image ...) blocks"
        )


def test_r1_every_image_has_outline() -> None:
    """Every (image ...) block contains at least one (outline ...) element (R-1 truth #2)."""
    if not _FIXTURE.exists():
        pytest.skip(f"Fixture missing: {_FIXTURE}")
    content = _FIXTURE.read_text(encoding="utf-8")
    dsn = generate_dsn(content, _FIXTURE)

    image_count = dsn.count("(image ")
    outline_count = dsn.count("(outline ")
    assert image_count > 0, "No (image ...) blocks emitted"
    assert outline_count >= image_count, (
        f"Every (image ...) must have an (outline ...): "
        f"images={image_count}, outlines={outline_count}"
    )
