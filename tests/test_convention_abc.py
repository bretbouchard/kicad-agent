"""Plan 01 Task 1: Convention ABC + Violation + LayoutView contract tests.

Verifies:
- P0-3: rule_id and severity are CLASS-LEVEL attributes (no instance-attr anti-pattern)
- P0-3: rule_id regex matches Phase 48 pattern r'^[A-Z][A-Z0-9_]*\\d{2}$'
- D-03: Convention ABC has both check(layout, config=None) and apply(layout)
- D-04: Violation has to_json() and to_markdown() methods
- P1-2 (scoped LO-04): Violation.model_fields has no coordinate-named fields
- Phase 100 CR-01: LayoutView is frozen; apply() returns new instance
- P1-1: LayoutView.from_schematic_ir reads ir.components (no .serialize() called)
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any

import pytest

from kicad_agent.conventions.base import Convention, Severity, Violation
from kicad_agent.conventions.layout_view import (
    ComponentView,
    LabelView,
    LayoutView,
    WireView,
)


# ---------------------------------------------------------------------------
# Test helpers — minimal Convention subclasses for contract verification
# ---------------------------------------------------------------------------


class _ReadOnlyConv(Convention):
    """Read-only convention: overrides check() only; apply() is identity."""

    rule_id = "READONLY_TEST_01"
    severity: Severity = "info"
    description = "test read-only convention"

    def check(self, layout: LayoutView, config: dict[str, Any] | None = None) -> list[Violation]:
        return [
            Violation(
                rule_id=self.rule_id,
                severity=self.severity,
                message="test violation",
                component_refs=("R1",),
                suggestion_relative="move closer",
            )
        ]

    def apply(self, layout: LayoutView) -> LayoutView:
        return layout  # identity contract per D-03


class _TransformConv(Convention):
    """Transform convention: overrides both check() and apply()."""

    rule_id = "TRANSFORM_TEST_01"
    severity: Severity = "warning"
    description = "test transform convention"

    def check(self, layout: LayoutView, config: dict[str, Any] | None = None) -> list[Violation]:
        return [
            Violation(
                rule_id=self.rule_id,
                severity=self.severity,
                message="would-transform",
                component_refs=("R2",),
                suggestion_relative="snap orientation",
            )
        ]

    def apply(self, layout: LayoutView) -> LayoutView:
        # Return a NEW LayoutView with shifted components (Phase 100 CR-01).
        new_comps = tuple(
            dataclasses.replace(c, orientation=(c.orientation + 90.0) % 360.0)
            for c in layout.components
        )
        return dataclasses.replace(layout, components=new_comps)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_rule_id_and_severity_are_class_level_attributes():
    """P0-3: rule_id accessible on the class without instantiation."""
    assert _ReadOnlyConv.rule_id == "READONLY_TEST_01"
    assert _ReadOnlyConv.severity == "info"
    assert _TransformConv.rule_id == "TRANSFORM_TEST_01"
    assert _TransformConv.severity == "warning"
    # Class-level attr equals instance attr
    inst = _ReadOnlyConv()
    assert type(inst).rule_id == inst.rule_id


def test_readonly_apply_is_identity():
    """D-03: read-only convention returns layout unchanged."""
    layout = _empty_layout()
    conv = _ReadOnlyConv()
    result = conv.apply(layout)
    assert result is layout


def test_transform_apply_returns_new_instance():
    """Phase 100 CR-01: apply() returns a NEW LayoutView; input unmutated."""
    layout = _empty_layout()
    assert layout.components == ()
    # Build a layout with one component
    comp = ComponentView(
        ref="R1",
        lib_id="Device:R",
        position=(10.0, 20.0),
        orientation=0.0,
        bounding_box=(8.0, 18.0, 12.0, 22.0),
    )
    layout = dataclasses.replace(layout, components=(comp,))
    conv = _TransformConv()
    result = conv.apply(layout)
    assert result is not layout  # new instance
    assert layout.components[0].orientation == 0.0  # original unchanged
    assert result.components[0].orientation == 90.0  # transformed


def test_violation_rule_id_requires_two_digit_suffix():
    """P0-3: rule_id regex rejects names without _NN suffix."""
    pattern = r"^[A-Z][A-Z0-9_]*\d{2}$"
    # Valid
    Violation(rule_id="SIGNAL_FLOW_DIRECTION_01", severity="warning", message="ok")
    Violation(rule_id="A_99", severity="info", message="ok")
    # Invalid — no digits suffix
    with pytest.raises(Exception):
        Violation(rule_id="SIGNAL_FLOW_DIRECTION", severity="warning", message="ok")
    # Invalid — single digit
    with pytest.raises(Exception):
        Violation(rule_id="RULE_1", severity="warning", message="ok")
    # Invalid — starts with lowercase
    with pytest.raises(Exception):
        Violation(rule_id="lowercase_01", severity="warning", message="ok")
    assert re.match(pattern, "SIGNAL_FLOW_DIRECTION_01")


def test_violation_model_fields_are_exactly_the_five_expected():
    """P1-2 (scoped LO-04): Violation.model_fields contains no coordinate names."""
    forbidden = {"x", "y", "position", "coordinate", "location"}
    fields = set(Violation.model_fields.keys())
    leak = forbidden & fields
    assert not leak, f"LO-04 violation: coordinate names in Violation fields: {leak}"
    expected = {"rule_id", "severity", "message", "component_refs", "suggestion_relative"}
    assert fields == expected, f"Unexpected Violation fields: {fields ^ expected}"


def test_violation_to_json_keys_match_model_fields():
    """D-04: to_json() returns the 5 expected keys."""
    v = Violation(
        rule_id="TEST_RULE_01",
        severity="warning",
        message="bad layout",
        component_refs=("R5", "R6"),
        suggestion_relative="rotate R5",
    )
    j = v.to_json()
    assert set(j.keys()) == {"rule_id", "severity", "message", "component_refs", "suggestion_relative"}
    assert j["component_refs"] == ["R5", "R6"]


def test_violation_to_markdown_format():
    """D-04: to_markdown() returns formatted bullet."""
    v = Violation(
        rule_id="TEST_RULE_01",
        severity="warning",
        message="bad layout",
        component_refs=("R5", "R6"),
        suggestion_relative="rotate R5",
    )
    md = v.to_markdown()
    assert md.startswith("- [WARNING] TEST_RULE_01: bad layout")
    assert "(refs: R5, R6)" in md
    assert md.endswith("rotate R5")


def test_violation_rejects_empty_required_fields():
    """Pydantic min_length enforcement."""
    with pytest.raises(Exception):
        Violation(rule_id="", severity="warning", message="ok")
    with pytest.raises(Exception):
        Violation(rule_id="RULE_01", severity="warning", message="")


def test_violation_severity_literal_enforced():
    """Severity Literal: only error | warning | info."""
    Violation(rule_id="RULE_01", severity="error", message="ok")
    Violation(rule_id="RULE_01", severity="warning", message="ok")
    Violation(rule_id="RULE_01", severity="info", message="ok")
    with pytest.raises(Exception):
        Violation(rule_id="RULE_01", severity="critical", message="ok")  # type: ignore[arg-type]


def test_layout_view_is_frozen():
    """Phase 100 CR-01: LayoutView is a frozen dataclass."""
    layout = _empty_layout()
    with pytest.raises(dataclasses.FrozenInstanceError):
        layout.components = ()  # type: ignore[misc]


def test_layout_view_from_schematic_ir_projects_components():
    """P1-1: from_schematic_ir builds a LayoutView by reading ir.components.

    No .serialize() / .write() / .to_file() method is called (read-only).
    """
    fixture = Path(__file__).parent / "fixtures" / "Arduino_Mega" / "Arduino_Mega.kicad_sch"
    if not fixture.exists():
        pytest.skip("Arduino_Mega fixture not available")
    from kicad_agent.parser.schematic_parser import parse_schematic
    from kicad_agent.ir.schematic_ir import SchematicIR

    parse_result = parse_schematic(fixture)
    ir = SchematicIR(_parse_result=parse_result)
    layout = LayoutView.from_schematic_ir(ir)

    # Components tuple is populated
    assert isinstance(layout.components, tuple)
    assert len(layout.components) > 0
    # Each component is a ComponentView with required fields
    for c in layout.components:
        assert isinstance(c, ComponentView)
        assert isinstance(c.ref, str) and c.ref
        assert isinstance(c.lib_id, str)
        assert isinstance(c.position, tuple) and len(c.position) == 2
        assert isinstance(c.orientation, float)
        assert isinstance(c.bounding_box, tuple) and len(c.bounding_box) == 4
    # schematic_ir reference held (P0-2: NOT serialized)
    assert layout.schematic_ir is ir


def test_layout_view_to_mutations_emits_new_x_new_y_keys():
    """P1-R2-1 (Council Round 2): to_mutations() MUST emit new_x/new_y, NOT x/y.

    SchematicRawWriter.apply_mutation reads `new_x`/`new_y` (NOT `x`/`y`).
    """
    comp = ComponentView(
        ref="R1",
        lib_id="Device:R",
        position=(25.4, 30.0),
        orientation=90.0,
        bounding_box=(20.0, 25.0, 30.0, 35.0),
    )
    layout = _empty_layout()
    layout = dataclasses.replace(layout, components=(comp,))
    mutations = layout.to_mutations()
    assert isinstance(mutations, list)
    assert len(mutations) == 1
    m = mutations[0]
    assert m["op"] == "move_symbol"
    assert m["ref"] == "R1"
    # P1-R2-1: writer reads new_x/new_y, not x/y
    assert "new_x" in m, f"P1-R2-1 FAIL: mutation uses x/y, writer needs new_x/new_y: {m}"
    assert "new_y" in m
    assert m["new_x"] == 25.4
    assert m["new_y"] == 30.0
    # x/y MUST NOT be present (would be silently ignored by writer)
    assert "x" not in m, f"P1-R2-1 FAIL: legacy x key present: {m}"
    assert "y" not in m, f"P1-R2-1 FAIL: legacy y key present: {m}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_layout() -> LayoutView:
    """Build a minimal LayoutView with empty tuples and None schematic_ir.

    Used by tests that exercise Convention.apply() semantics without a real schematic.
    """
    return LayoutView(schematic_ir=None, components=(), wires=(), labels=())  # type: ignore[arg-type]
