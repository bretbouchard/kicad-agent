"""R-5: (control (snap_angle ...)) emission at generate_dsn level."""
from __future__ import annotations

from pathlib import Path

import pytest

from volta.routing.dsn_generator import generate_dsn

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "smd_test_board.kicad_pcb"


def test_r5_fortyfive_degree_emits_control_line() -> None:
    """snap_angle='fortyfive_degree' emits (control (snap_angle fortyfive_degree))."""
    if not _FIXTURE.exists():
        pytest.skip(f"Fixture missing: {_FIXTURE}")
    content = _FIXTURE.read_text(encoding="utf-8")
    dsn = generate_dsn(content, _FIXTURE, snap_angle="fortyfive_degree")
    assert "(control (snap_angle fortyfive_degree))" in dsn, (
        "Expected (control (snap_angle fortyfive_degree)) in DSN structure block"
    )


def test_r5_default_omits_control_line() -> None:
    """Default snap_angle='none' produces NO (snap_angle ...)."""
    if not _FIXTURE.exists():
        pytest.skip(f"Fixture missing: {_FIXTURE}")
    content = _FIXTURE.read_text(encoding="utf-8")
    dsn = generate_dsn(content, _FIXTURE)
    assert "(snap_angle" not in dsn, (
        "Default snap_angle='none' must not emit any snap_angle control line"
    )


def test_r5_ninety_degree_emits_control_line() -> None:
    """snap_angle='ninety_degree' emits (control (snap_angle ninety_degree))."""
    if not _FIXTURE.exists():
        pytest.skip(f"Fixture missing: {_FIXTURE}")
    content = _FIXTURE.read_text(encoding="utf-8")
    dsn = generate_dsn(content, _FIXTURE, snap_angle="ninety_degree")
    assert "(control (snap_angle ninety_degree))" in dsn


def test_r5_invalid_snap_angle_raises_value_error() -> None:
    """T-99-01-04 mitigation: invalid snap_angle raises ValueError."""
    if not _FIXTURE.exists():
        pytest.skip(f"Fixture missing: {_FIXTURE}")
    content = _FIXTURE.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid snap_angle"):
        generate_dsn(content, _FIXTURE, snap_angle="bogus")
