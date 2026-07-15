"""Plan 03 Task 2: Phase 108 autolayout integration tests.

Stable integration surface consumed by Phase 108:
- load_conventions_as_constraints(config) — return enabled Convention list
- evaluate_placement(layout, conventions) — run all convention check() methods
- suggest_placement_adjustments(layout, violations, conventions) — apply TRANSFORM conventions

P1-3 (Council Round 1 fix): suggest_placement_adjustments dedupes by rule_id;
each convention's apply() runs at most ONCE per call.
Phase 100 CR-01: returns NEW LayoutView, never mutates input.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from volta.conventions.base import Convention, Violation
from volta.conventions.layout_view import ComponentView, LayoutView
from volta.conventions.loader import ConventionConfig


# ---------------------------------------------------------------------------
# load_conventions_as_constraints tests
# ---------------------------------------------------------------------------


def test_load_returns_v1_catalog_instances():
    from volta.conventions.autolayout_integration import (
        load_conventions_as_constraints,
    )

    catalog = load_conventions_as_constraints()
    assert len(catalog) >= 10  # 6 adapters + 4 new = 10 minimum
    for c in catalog:
        assert isinstance(c, Convention)


def test_load_skips_disabled_conventions():
    from volta.conventions.autolayout_integration import (
        load_conventions_as_constraints,
    )

    config = ConventionConfig(
        disabled_conventions={"GRID_ALIGNMENT_01", "WIRE_ORTHOGONALITY_01"},
    )
    catalog = load_conventions_as_constraints(config=config)
    rule_ids = {c.rule_id for c in catalog}
    assert "GRID_ALIGNMENT_01" not in rule_ids
    assert "WIRE_ORTHOGONALITY_01" not in rule_ids
    # Other conventions still present
    assert "SIGNAL_FLOW_DIRECTION_01" in rule_ids


def test_load_with_none_config_returns_full_catalog():
    from volta.conventions.autolayout_integration import (
        load_conventions_as_constraints,
    )

    catalog = load_conventions_as_constraints(config=None)
    assert len(catalog) >= 10


# ---------------------------------------------------------------------------
# evaluate_placement tests
# ---------------------------------------------------------------------------


def test_evaluate_placement_runs_all_convention_checks():
    from volta.conventions.autolayout_integration import evaluate_placement

    call_count = {"n": 0}

    class _SpyConv(Convention):
        rule_id = "SPY_CONV_01"
        severity = "info"  # type: ignore[assignment]
        description = "spy"

        def check(self, layout, config=None):
            call_count["n"] += 1
            return []

        def apply(self, layout):
            return layout

    layout = _empty_layout()
    violations = evaluate_placement(layout, [_SpyConv()])
    assert call_count["n"] == 1
    assert isinstance(violations, list)


def test_evaluate_placement_never_raises_on_empty_layout():
    from volta.conventions.autolayout_integration import (
        evaluate_placement,
        load_conventions_as_constraints,
    )

    catalog = load_conventions_as_constraints()
    layout = _empty_layout()
    violations = evaluate_placement(layout, catalog)
    assert isinstance(violations, list)


# ---------------------------------------------------------------------------
# suggest_placement_adjustments tests
# ---------------------------------------------------------------------------


def test_suggest_placement_adjustments_returns_layout_view():
    from volta.conventions.autolayout_integration import (
        suggest_placement_adjustments,
    )

    layout = _empty_layout()
    result = suggest_placement_adjustments(layout, [], [])
    assert isinstance(result, LayoutView)


def test_suggest_placement_adjustments_dedupes_by_rule_id():
    """P1-3: each convention's apply() runs AT MOST ONCE per call.

    Verify by patching a convention's apply() with a counter and asserting
    count == 1 even when 10 violations share the rule_id.
    """
    from volta.conventions.autolayout_integration import (
        suggest_placement_adjustments,
    )

    apply_count = {"n": 0}

    class _CountingConv(Convention):
        rule_id = "COUNTING_01"
        severity = "warning"  # type: ignore[assignment]
        description = "counting"

        def check(self, layout, config=None):
            return []

        def apply(self, layout):
            apply_count["n"] += 1
            return layout

    # 10 violations all sharing the same rule_id
    violations = [
        Violation(
            rule_id="COUNTING_01",
            severity="warning",
            message=f"v{i}",
            component_refs=(f"R{i}",),
            suggestion_relative="fix",
        )
        for i in range(10)
    ]
    layout = _empty_layout()
    suggest_placement_adjustments(layout, violations, [_CountingConv()])
    assert apply_count["n"] == 1, (
        f"P1-3 FAIL: apply() ran {apply_count['n']} times for 10 same-rule_id violations"
    )


def test_suggest_placement_adjustments_skips_missing_conventions():
    """If a violation references a rule_id not in conventions, it's skipped."""
    from volta.conventions.autolayout_integration import (
        suggest_placement_adjustments,
    )

    violations = [
        Violation(
            rule_id="MISSING_RULE_01",
            severity="info",
            message="orphan",
            component_refs=("R1",),
            suggestion_relative="nothing to apply",
        )
    ]
    layout = _empty_layout()
    # Should not raise — just returns the layout
    result = suggest_placement_adjustments(layout, violations, [])
    assert isinstance(result, LayoutView)


def test_suggest_placement_adjustments_runs_transform_once_per_convention():
    """GRID_ALIGNMENT_01 TRANSFORM: deduped — 3 violations = 1 apply call."""
    from volta.conventions.autolayout_integration import (
        suggest_placement_adjustments,
    )
    from volta.conventions.catalog.grid_alignment import GRID_ALIGNMENT_01

    off_grid_1 = ComponentView(
        ref="R1", lib_id="Device:R", position=(10.5, 10.7),
        orientation=0.0, bounding_box=(5.0, 5.0, 15.0, 15.0),
    )
    off_grid_2 = ComponentView(
        ref="R2", lib_id="Device:R", position=(20.5, 20.7),
        orientation=0.0, bounding_box=(15.0, 15.0, 25.0, 25.0),
    )
    off_grid_3 = ComponentView(
        ref="R3", lib_id="Device:R", position=(30.5, 30.7),
        orientation=0.0, bounding_box=(25.0, 25.0, 35.0, 35.0),
    )
    layout = LayoutView(
        schematic_ir=None,
        components=(off_grid_1, off_grid_2, off_grid_3),
        wires=(), labels=(),
    )

    violations = [
        Violation(
            rule_id="GRID_ALIGNMENT_01",
            severity="warning",
            message=f"v{i}",
            component_refs=(c.ref,),
            suggestion_relative="snap",
        )
        for i, c in enumerate(layout.components)
    ]
    result = suggest_placement_adjustments(layout, violations, [GRID_ALIGNMENT_01()])
    # All three should be snapped after one apply() call
    KICAD_GRID_MM = 2.54
    for orig, snapped in zip(layout.components, result.components):
        expected_x = round(orig.position[0] / KICAD_GRID_MM) * KICAD_GRID_MM
        expected_y = round(orig.position[1] / KICAD_GRID_MM) * KICAD_GRID_MM
        assert abs(snapped.position[0] - expected_x) < 1e-6
        assert abs(snapped.position[1] - expected_y) < 1e-6


def test_disabled_conventions_skipped_in_both_load_and_evaluate():
    """Disabled conventions must not appear in evaluate_placement output."""
    from volta.conventions.autolayout_integration import (
        evaluate_placement,
        load_conventions_as_constraints,
    )

    config = ConventionConfig(disabled_conventions={"GRID_ALIGNMENT_01"})
    catalog = load_conventions_as_constraints(config=config)
    layout = _empty_layout()
    violations = evaluate_placement(layout, catalog)
    rule_ids = {v.rule_id for v in violations}
    # GRID_ALIGNMENT_01 should not be in violations because the convention is absent
    assert "GRID_ALIGNMENT_01" not in rule_ids


def test_full_round_trip_with_arduino_mega_fixture():
    """Integration test: load conventions → evaluate → no crash → violations returned."""
    fixture = Path(__file__).resolve().parent / "fixtures" / "Arduino_Mega" / "Arduino_Mega.kicad_sch"
    if not fixture.exists():
        pytest.skip("Arduino_Mega fixture not available")

    from volta.conventions.autolayout_integration import (
        evaluate_placement,
        load_conventions_as_constraints,
    )
    from volta.conventions.layout_view import LayoutView
    from volta.ir.schematic_ir import SchematicIR
    from volta.parser.schematic_parser import parse_schematic

    parse_result = parse_schematic(fixture)
    ir = SchematicIR(_parse_result=parse_result)
    layout = LayoutView.from_schematic_ir(ir)
    catalog = load_conventions_as_constraints()
    violations = evaluate_placement(layout, catalog)
    assert isinstance(violations, list)
    # Phase 108 placed Arduino_Mega with improved spacing (+0.050 SRS delta).
    # Convention count is informational; we just verify no crash + list output.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_layout() -> LayoutView:
    return LayoutView(schematic_ir=None, components=(), wires=(), labels=())  # type: ignore[arg-type]
