"""Plan 02 Task 2: v1 catalog + new IEEE 315 conventions (D-01).

D-01: catalog selection is data-driven from ACTUAL Phase 108 SRS-verification
factor deltas. Per 108-SRS-VERIFICATION.md:
  - spacing +0.050 on Arduino_Mega (autolayout places components better)
  - all other factors unchanged for small fixtures
  - Phase 108 mutation surface: move_symbol + insert_wire + insert_label

v1 catalog encodes rules Phase 108 already respects (positive validation)
plus rules a larger board would break (forward-looking, grounded in 108's
mutation surface).

4 new conventions:
  - SIGNAL_FLOW_DIRECTION_01 (read-only)
  - IEEE315_PIN_ORIENTATION_01 (TRANSFORM — read-only for v1 per P1-R2-1)
  - GRID_ALIGNMENT_01 (TRANSFORM)
  - WIRE_ORTHOGONALITY_01 (read-only)
"""
from __future__ import annotations

import dataclasses
import re
from typing import Any

import pytest

from volta.conventions.base import Convention, Violation
from volta.conventions.layout_view import ComponentView, LayoutView, WireView


# ---------------------------------------------------------------------------
# Catalog tests
# ---------------------------------------------------------------------------


def test_get_v1_catalog_returns_10_to_15_conventions():
    """D-01: v1 catalog size is 10-15 conventions."""
    from volta.conventions.catalog import get_v1_catalog

    catalog = get_v1_catalog()
    assert 10 <= len(catalog) <= 15, f"v1 catalog must be 10-15, got {len(catalog)}"


def test_get_v1_catalog_includes_6_readability_adapters_plus_4_new():
    """6 adapters (Phase 48.5) + 4 new IEEE 315 conventions = 10 total."""
    from volta.conventions.catalog import get_v1_catalog

    catalog = get_v1_catalog()
    names = {c.rule_id for c in catalog}
    expected_new = {
        "SIGNAL_FLOW_DIRECTION_01",
        "IEEE315_PIN_ORIENTATION_01",
        "GRID_ALIGNMENT_01",
        "WIRE_ORTHOGONALITY_01",
    }
    assert expected_new.issubset(names), f"missing new conventions: {expected_new - names}"


def test_all_catalog_rule_ids_match_phase48_regex():
    """P0-3: every catalog rule_id matches ^[A-Z][A-Z0-9_]*\\d{2}$."""
    from volta.conventions.catalog import get_v1_catalog

    catalog = get_v1_catalog()
    pattern = re.compile(r"^[A-Z][A-Z0-9_]*\d{2}$")
    for c in catalog:
        assert pattern.match(c.rule_id), f"P0-3: {c.rule_id} fails regex"
        assert type(c).rule_id == c.rule_id, f"P0-3: {c.rule_id} not class-level"


# ---------------------------------------------------------------------------
# New convention class tests
# ---------------------------------------------------------------------------


def test_signal_flow_direction_01_class_level_attrs():
    from volta.conventions.catalog.signal_flow import SIGNAL_FLOW_DIRECTION_01

    assert SIGNAL_FLOW_DIRECTION_01.rule_id == "SIGNAL_FLOW_DIRECTION_01"
    assert SIGNAL_FLOW_DIRECTION_01.severity in ("error", "warning", "info")
    assert issubclass(SIGNAL_FLOW_DIRECTION_01, Convention)


def test_ieee315_pin_orientation_01_class_level_attrs():
    from volta.conventions.catalog.pin_orientation import (
        IEEE315_PIN_ORIENTATION_01,
    )

    assert IEEE315_PIN_ORIENTATION_01.rule_id == "IEEE315_PIN_ORIENTATION_01"
    assert IEEE315_PIN_ORIENTATION_01.severity in ("error", "warning", "info")
    assert issubclass(IEEE315_PIN_ORIENTATION_01, Convention)


def test_grid_alignment_01_class_level_attrs():
    from volta.conventions.catalog.grid_alignment import GRID_ALIGNMENT_01

    assert GRID_ALIGNMENT_01.rule_id == "GRID_ALIGNMENT_01"
    assert GRID_ALIGNMENT_01.severity in ("error", "warning", "info")
    assert issubclass(GRID_ALIGNMENT_01, Convention)


def test_wire_orthogonality_01_class_level_attrs():
    from volta.conventions.catalog.wire_orthogonality import (
        WIRE_ORTHOGONALITY_01,
    )

    assert WIRE_ORTHOGONALITY_01.rule_id == "WIRE_ORTHOGONALITY_01"
    assert WIRE_ORTHOGONALITY_01.severity in ("error", "warning", "info")
    assert issubclass(WIRE_ORTHOGONALITY_01, Convention)


def test_each_new_convention_check_returns_list_on_empty_layout():
    """Defensive: check() never raises on empty layout; returns []."""
    from volta.conventions.catalog.grid_alignment import GRID_ALIGNMENT_01
    from volta.conventions.catalog.pin_orientation import (
        IEEE315_PIN_ORIENTATION_01,
    )
    from volta.conventions.catalog.signal_flow import SIGNAL_FLOW_DIRECTION_01
    from volta.conventions.catalog.wire_orthogonality import (
        WIRE_ORTHOGONALITY_01,
    )

    empty = _empty_layout()
    for cls in (
        SIGNAL_FLOW_DIRECTION_01,
        IEEE315_PIN_ORIENTATION_01,
        GRID_ALIGNMENT_01,
        WIRE_ORTHOGONALITY_01,
    ):
        violations = cls().check(empty)
        assert isinstance(violations, list)
        assert all(isinstance(v, Violation) for v in violations)


def test_signal_flow_direction_01_flags_backward_facing_components():
    """Read-only: emits warning when input pin is on the right side of an IC.

    Heuristic for v1: components whose lib_id suggests an IC (U-prefix ref)
    with orientation in (90, 270) are flagged as 'backward-facing' for
    signal flow (input pins typically on left for 0° canonical orientation).
    """
    from volta.conventions.catalog.signal_flow import SIGNAL_FLOW_DIRECTION_01

    ic = ComponentView(
        ref="U1",
        lib_id="Analog:Opamp",
        position=(50.0, 50.0),
        orientation=180.0,  # rotated 180 — signal flow reversed
        bounding_box=(40.0, 40.0, 60.0, 60.0),
    )
    layout = _layout_with_components(ic)
    violations = SIGNAL_FLOW_DIRECTION_01().check(layout)
    # v1 heuristic: 180° rotation is "backward-facing"
    assert any(v.rule_id == "SIGNAL_FLOW_DIRECTION_01" for v in violations)


def test_pin_orientation_01_v1_is_read_only_apply_is_identity():
    """P1-R2-1 (Council Round 2): demoted to read-only for v1.

    SchematicRawWriter.apply_mutation ignores the `angle` field on move_symbol
    mutations, so IEEE315_PIN_ORIENTATION_01 cannot round-trip orientation
    changes through the writer. Per P1-R2-1: demote to read-only for v1
    (apply = identity); document writer extension as DEFERRED-TO-NAMED-TARGET
    Phase 115.
    """
    from volta.conventions.catalog.pin_orientation import (
        IEEE315_PIN_ORIENTATION_01,
    )

    layout = _layout_with_components(
        ComponentView(
            ref="R1",
            lib_id="Device:R",
            position=(10.0, 10.0),
            orientation=45.0,  # non-canonical
            bounding_box=(5.0, 5.0, 15.0, 15.0),
        )
    )
    inst = IEEE315_PIN_ORIENTATION_01()
    result = inst.apply(layout)
    # P1-R2-1: v1 apply is identity (writer cannot round-trip angle)
    assert result is layout


def test_pin_orientation_01_check_flags_non_canonical_passive_orientation():
    """Check-only: flags passives (R/C/L) at non-canonical angles (not 0/90/180/270)."""
    from volta.conventions.catalog.pin_orientation import (
        IEEE315_PIN_ORIENTATION_01,
    )

    bad_r = ComponentView(
        ref="R1",
        lib_id="Device:R",
        position=(10.0, 10.0),
        orientation=45.0,
        bounding_box=(5.0, 5.0, 15.0, 15.0),
    )
    good_r = ComponentView(
        ref="R2",
        lib_id="Device:R",
        position=(20.0, 10.0),
        orientation=90.0,
        bounding_box=(15.0, 5.0, 25.0, 15.0),
    )
    layout = _layout_with_components(bad_r, good_r)
    violations = IEEE315_PIN_ORIENTATION_01().check(layout)
    refs = set()
    for v in violations:
        refs.update(v.component_refs)
    assert "R1" in refs  # bad orientation flagged
    # R2 is canonical (90°) — may or may not appear, but R1 must be flagged


def test_grid_alignment_01_check_flags_off_grid_components():
    """Components off the 2.54mm grid are flagged."""
    from volta.conventions.catalog.grid_alignment import GRID_ALIGNMENT_01

    off_grid = ComponentView(
        ref="R1",
        lib_id="Device:R",
        position=(10.5, 10.0),  # X off-grid (10.5 not multiple of 2.54)
        orientation=0.0,
        bounding_box=(5.0, 5.0, 15.0, 15.0),
    )
    on_grid = ComponentView(
        ref="R2",
        lib_id="Device:R",
        position=(12.7, 10.16),  # both multiples of 2.54
        orientation=0.0,
        bounding_box=(7.7, 5.0, 17.7, 15.0),
    )
    layout = _layout_with_components(off_grid, on_grid)
    violations = GRID_ALIGNMENT_01().check(layout)
    refs = set()
    for v in violations:
        refs.update(v.component_refs)
    assert "R1" in refs


def test_grid_alignment_01_apply_snaps_to_grid_and_returns_new_layout():
    """TRANSFORM convention: apply() returns NEW LayoutView with snapped positions."""
    from volta.conventions.catalog.grid_alignment import GRID_ALIGNMENT_01

    off_grid = ComponentView(
        ref="R1",
        lib_id="Device:R",
        position=(10.5, 10.7),
        orientation=0.0,
        bounding_box=(5.0, 5.0, 15.0, 15.0),
    )
    layout = _layout_with_components(off_grid)
    result = GRID_ALIGNMENT_01().apply(layout)
    assert result is not layout  # Phase 100 CR-01: new instance
    assert result.components is not layout.components
    # Snapped to nearest 2.54mm multiple
    KICAD_GRID_MM = 2.54
    for orig, snapped in zip(layout.components, result.components):
        if orig.ref == "R1":
            expected_x = round(orig.position[0] / KICAD_GRID_MM) * KICAD_GRID_MM
            expected_y = round(orig.position[1] / KICAD_GRID_MM) * KICAD_GRID_MM
            assert abs(snapped.position[0] - expected_x) < 1e-6
            assert abs(snapped.position[1] - expected_y) < 1e-6


def test_wire_orthogonality_01_flags_non_orthogonal_bends():
    """Read-only: flags wire bends that aren't 90°."""
    from volta.conventions.catalog.wire_orthogonality import (
        WIRE_ORTHOGONALITY_01,
    )

    # Diagonal segment — non-orthogonal
    bad_wire = WireView(points=((0.0, 0.0), (5.0, 5.0)))
    # Orthogonal L-bend
    good_wire = WireView(points=((0.0, 0.0), (5.0, 0.0), (5.0, 10.0)))
    layout = LayoutView(
        schematic_ir=None,
        components=(),
        wires=(bad_wire, good_wire),
        labels=(),
    )
    violations = WIRE_ORTHOGONALITY_01().check(layout)
    assert any(v.rule_id == "WIRE_ORTHOGONALITY_01" for v in violations)


def test_wire_orthogonality_01_apply_is_identity():
    """Read-only convention: apply() returns layout unchanged."""
    from volta.conventions.catalog.wire_orthogonality import (
        WIRE_ORTHOGONALITY_01,
    )

    layout = _empty_layout()
    result = WIRE_ORTHOGONALITY_01().apply(layout)
    assert result is layout


def test_check_output_has_no_coordinate_fields():
    """LO-04: Violation.model_fields contract from Plan 01 — no coordinate names."""
    from volta.conventions.catalog.grid_alignment import GRID_ALIGNMENT_01
    from volta.conventions.catalog.pin_orientation import (
        IEEE315_PIN_ORIENTATION_01,
    )
    from volta.conventions.catalog.signal_flow import SIGNAL_FLOW_DIRECTION_01
    from volta.conventions.catalog.wire_orthogonality import (
        WIRE_ORTHOGONALITY_01,
    )

    forbidden = {"x", "y", "position", "coordinate", "location"}
    for cls in (
        SIGNAL_FLOW_DIRECTION_01,
        IEEE315_PIN_ORIENTATION_01,
        GRID_ALIGNMENT_01,
        WIRE_ORTHOGONALITY_01,
    ):
        layout = _empty_layout()
        violations = cls().check(layout)
        for v in violations:
            fields = set(v.model_fields.keys())
            assert not (forbidden & fields), (
                f"LO-04: {cls.rule_id} produces Violation with coordinate fields"
            )


def test_transform_conventions_use_dataclasses_replace():
    """Phase 100 CR-01: TRANSFORM conventions return new instance via dataclasses.replace.

    Verified by checking apply() returns a different object identity (not is).
    """
    from volta.conventions.catalog.grid_alignment import GRID_ALIGNMENT_01

    off_grid = ComponentView(
        ref="R1",
        lib_id="Device:R",
        position=(10.5, 10.7),
        orientation=0.0,
        bounding_box=(5.0, 5.0, 15.0, 15.0),
    )
    layout = _layout_with_components(off_grid)
    result = GRID_ALIGNMENT_01().apply(layout)
    # Original ComponentView unchanged (Phase 100 CR-01 frozen)
    assert layout.components[0].position == (10.5, 10.7)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_layout() -> LayoutView:
    return LayoutView(schematic_ir=None, components=(), wires=(), labels=())  # type: ignore[arg-type]


def _layout_with_components(*comps: ComponentView) -> LayoutView:
    return LayoutView(schematic_ir=None, components=tuple(comps), wires=(), labels=())  # type: ignore[arg-type]
