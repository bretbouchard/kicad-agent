"""R2-01: _handle_auto_route threads snap_angle and caps max_passes via op.max_iterations.

Council Round 2 finding: WR-01/CR-02/WR-02 fixes wired snap_angle through the
auto_route handler and capped max_passes to op.max_iterations, but no test
exercised the op-handler layer. This file closes that coverage gap.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "smd_test_board.kicad_pcb"
_FIXTURE_REL = "tests/fixtures/smd_test_board.kicad_pcb"


def _make_op(**overrides):
    """Build a minimal AutoRouteOp-like object for handler invocation.

    Schema rejects absolute paths, so target_file is relative to repo root.
    Tests must chdir to repo root before invoking the handler.
    """
    from kicad_agent.ops._schema_pcb import AutoRouteOp

    fields = {
        "target_file": _FIXTURE_REL,
        "strategy": "freerouting",
        "snap_angle": None,
        "max_iterations": 5,
    }
    fields.update(overrides)
    return AutoRouteOp(**fields)


import os
import pytest


@pytest.fixture(autouse=True)
def _chdir_to_repo_root(monkeypatch):
    """Run all tests in this file from repo root so relative fixture paths resolve."""
    monkeypatch.chdir(_REPO_ROOT)


def _make_ir():
    """Build a minimal IR mock for handler invocation.

    Handler reads ir.raw_content and calls ir.commit_raw_content(new_content)
    on Freerouting success path. MagicMock handles both.
    """
    from unittest.mock import MagicMock

    ir = MagicMock()
    ir.raw_content = "(kicad_pcb ...)"

    def _commit(new_content):
        ir.raw_content = new_content

    ir.commit_raw_content.side_effect = _commit
    return ir


def _patch_freerouting(monkeypatch, captured, *, available=True, success=True):
    """Patch freerouting module so handler runs without external deps."""
    import kicad_agent.routing.freerouting as fr_module

    monkeypatch.setattr(fr_module, "is_freerouting_available", lambda: available)

    def _fake_route_with_freerouting(file_path, *, max_passes=5, snap_angle="none"):
        captured["file_path"] = file_path
        captured["max_passes"] = max_passes
        captured["snap_angle"] = snap_angle
        return SimpleNamespace(
            success=success,
            stderr="" if success else "patched failure",
            stdout="",
            dsn_path=Path("/tmp/fake.dsn"),
            ses_path=Path("/tmp/fake.ses"),
            exit_code=0 if success else 1,
        )

    monkeypatch.setattr(fr_module, "route_with_freerouting", _fake_route_with_freerouting)

    def _fake_import_ses(ses_path, raw_content):
        return ("(kicad_pcb ... routed ...)", {"nets_routed": 1, "segments": 1, "vias": 0, "skipped": 0})

    monkeypatch.setattr(fr_module, "import_ses_into_pcb", _fake_import_ses)


def test_auto_route_threads_snap_angle_to_freerouting(monkeypatch, tmp_path):
    """auto_route op with snap_angle='fortyfive_degree' reaches route_with_freerouting."""
    if not _FIXTURE.exists():
        import pytest
        pytest.skip(f"Fixture missing: {_FIXTURE}")

    from kicad_agent.ops.handlers.pcb import _handle_auto_route

    captured: dict = {}
    _patch_freerouting(monkeypatch, captured)

    op = _make_op(snap_angle="fortyfive_degree")
    ir = _make_ir()
    _handle_auto_route(op, ir, Path(op.target_file))

    assert captured.get("snap_angle") == "fortyfive_degree", (
        "snap_angle='fortyfive_degree' must reach route_with_freerouting "
        f"(got: {captured.get('snap_angle')!r})"
    )


def test_auto_route_defaults_snap_angle_to_none(monkeypatch):
    """auto_route op without snap_angle threads 'none' (no 45° mode)."""
    if not _FIXTURE.exists():
        import pytest
        pytest.skip(f"Fixture missing: {_FIXTURE}")

    from kicad_agent.ops.handlers.pcb import _handle_auto_route

    captured: dict = {}
    _patch_freerouting(monkeypatch, captured)

    op = _make_op()  # snap_angle defaults to None
    ir = _make_ir()
    _handle_auto_route(op, ir, Path(op.target_file))

    assert captured.get("snap_angle") == "none", (
        "Default snap_angle must be 'none' when op.snap_angle is None "
        f"(got: {captured.get('snap_angle')!r})"
    )


def test_auto_route_caps_max_passes_to_five(monkeypatch):
    """max_iterations > 5 is capped to 5 (schema safety cap, Council WR-02)."""
    if not _FIXTURE.exists():
        import pytest
        pytest.skip(f"Fixture missing: {_FIXTURE}")

    from kicad_agent.ops.handlers.pcb import _handle_auto_route

    captured: dict = {}
    _patch_freerouting(monkeypatch, captured)

def test_auto_route_schema_caps_max_iterations():
    """Schema rejects max_iterations > 5 (Council WR-02 primary enforcement)."""
    from kicad_agent.ops._schema_pcb import AutoRouteOp
    import pytest

    with pytest.raises(ValueError):
        AutoRouteOp(target_file="test.kicad_pcb", max_iterations=10)

    op = AutoRouteOp(target_file="test.kicad_pcb", max_iterations=5)
    assert op.max_iterations == 5


def test_auto_route_handler_defensive_min_clamp(monkeypatch):
    """Handler's min(getattr(op, 'max_iterations', 5), 5) clamps bypassed schema.

    Council WR-02 fix is belt-and-suspenders: schema caps max_iterations<=5,
    but handler also clamps in case op object doesn't go through validation
    (e.g., constructed via dict unpacking in batch executor).
    """
    if not _FIXTURE.exists():
        import pytest
        pytest.skip(f"Fixture missing: {_FIXTURE}")

    from kicad_agent.ops.handlers.pcb import _handle_auto_route

    captured: dict = {}
    _patch_freerouting(monkeypatch, captured)

    # Bypass schema validation — simulate a malformed op reaching the handler
    op = SimpleNamespace(
        target_file=_FIXTURE_REL,
        strategy="freerouting",
        snap_angle=None,
        max_iterations=10,  # over-cap (would fail schema validation)
        layers=[],
        layer="F.Cu",
    )
    ir = _make_ir()
    _handle_auto_route(op, ir, Path(op.target_file))

    assert captured.get("max_passes") == 5, (
        "Handler's defensive min() must clamp max_iterations=10 to max_passes=5 "
        f"even when schema validation is bypassed (got: {captured.get('max_passes')!r})"
    )


def test_auto_route_passes_max_iterations_below_cap(monkeypatch):
    """max_iterations <= 5 is honored as max_passes (not inflated)."""
    if not _FIXTURE.exists():
        import pytest
        pytest.skip(f"Fixture missing: {_FIXTURE}")

    from kicad_agent.ops.handlers.pcb import _handle_auto_route

    captured: dict = {}
    _patch_freerouting(monkeypatch, captured)

    op = _make_op(max_iterations=3)
    ir = _make_ir()
    _handle_auto_route(op, ir, Path(op.target_file))

    assert captured.get("max_passes") == 3, (
        "max_iterations=3 must pass through as max_passes=3 "
        f"(got: {captured.get('max_passes')!r})"
    )


def test_auto_route_op_schema_accepts_snap_angle():
    """AutoRouteOp schema accepts snap_angle with enum validation."""
    from kicad_agent.ops._schema_pcb import AutoRouteOp

    op = AutoRouteOp(target_file="test.kicad_pcb", snap_angle="fortyfive_degree")
    assert op.snap_angle == "fortyfive_degree"

    op_default = AutoRouteOp(target_file="test.kicad_pcb")
    assert op_default.snap_angle is None

    import pytest
    with pytest.raises(ValueError):
        AutoRouteOp(target_file="test.kicad_pcb", snap_angle="bogus")


def test_auto_route_uses_freerouting_strategy(monkeypatch):
    """strategy='freerouting' triggers the Freerouting path even if unavailable."""
    if not _FIXTURE.exists():
        import pytest
        pytest.skip(f"Fixture missing: {_FIXTURE}")

    from kicad_agent.ops.handlers.pcb import _handle_auto_route

    captured: dict = {}
    _patch_freerouting(monkeypatch, captured, available=False)  # not auto-available

    op = _make_op(strategy="freerouting")  # explicit
    ir = _make_ir()
    _handle_auto_route(op, ir, Path(op.target_file))

    assert "snap_angle" in captured, (
        "strategy='freerouting' must invoke route_with_freerouting even when "
        "is_freerouting_available() returns False"
    )
