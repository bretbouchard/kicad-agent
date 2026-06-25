"""BLOCKER-1 contract: snap_angle threads route_with_freerouting -> export_dsn -> generate_dsn."""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from kicad_agent.routing.dsn_generator import generate_dsn
from kicad_agent.routing.freerouting import export_dsn, route_with_freerouting

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "smd_test_board.kicad_pcb"


def test_export_dsn_accepts_snap_angle_kwarg() -> None:
    """export_dsn signature must accept snap_angle (BLOCKER-1)."""
    sig = inspect.signature(export_dsn)
    assert "snap_angle" in sig.parameters, (
        "export_dsn must accept snap_angle kwarg — Plan 99-03 SC-5 test depends on it"
    )
    assert sig.parameters["snap_angle"].default == "none", (
        "export_dsn snap_angle default must be 'none'"
    )


def test_route_with_freerouting_accepts_snap_angle_kwarg() -> None:
    """route_with_freerouting signature must accept snap_angle (BLOCKER-1)."""
    sig = inspect.signature(route_with_freerouting)
    assert "snap_angle" in sig.parameters, (
        "route_with_freerouting must accept snap_angle kwarg — Plan 99-03 SC-5 test depends on it"
    )
    assert sig.parameters["snap_angle"].default == "none", (
        "route_with_freerouting snap_angle default must be 'none'"
    )


def test_export_dsn_threads_snap_angle_to_generate_dsn(tmp_path: Path) -> None:
    """export_dsn(snap_angle=...) reaches generate_dsn (end-to-end DSN content check)."""
    if not _FIXTURE.exists():
        pytest.skip(f"Fixture missing: {_FIXTURE}")
    dsn_path = export_dsn(_FIXTURE, tmp_path, snap_angle="fortyfive_degree")
    dsn_text = dsn_path.read_text(encoding="utf-8")
    assert "(control (snap_angle fortyfive_degree))" in dsn_text, (
        "snap_angle='fortyfive_degree' did not reach generate_dsn via export_dsn"
    )


def test_export_dsn_default_omits_snap_angle(tmp_path: Path) -> None:
    """export_dsn(snap_angle='none') (default) produces no snap_angle control line."""
    if not _FIXTURE.exists():
        pytest.skip(f"Fixture missing: {_FIXTURE}")
    dsn_path = export_dsn(_FIXTURE, tmp_path)  # default snap_angle
    dsn_text = dsn_path.read_text(encoding="utf-8")
    assert "(snap_angle" not in dsn_text, (
        "Default snap_angle='none' should NOT emit any snap_angle control line"
    )
