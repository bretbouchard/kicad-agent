"""Plan 02 Task 1: Phase 48.5 readability rule adapters + ConventionEngine tests.

P0-3 fix: wrap_readability_rule() returns a Convention SUBCLASS (not an instance),
          with rule_id and severity declared at class scope. The Round 1 plan set
          instance attrs on the ABC, which would silently fail engine.run().

ConventionEngine mirrors Phase 48 DesignRuleEngine:
- Error-tolerant (broken convention → meta-Violation, continue)
- Skips disabled conventions
- Passes per-convention config via check(layout, config) signature (P2-1)
- Sorts by severity (error → warning → info)
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from kicad_agent.conventions.base import Convention, Violation
from kicad_agent.conventions.layout_view import ComponentView, LayoutView
from kicad_agent.conventions.loader import ConventionConfig


# ---------------------------------------------------------------------------
# Adapter factory tests (P0-3 class-synthesizing factory)
# ---------------------------------------------------------------------------


def test_wrap_readability_rule_returns_convention_subclass_with_class_level_attrs():
    """P0-3: factory returns a CLASS with class-level rule_id accessible pre-instantiation."""
    from kicad_agent.conventions.catalog.readability_adapters import wrap_readability_rule

    # Build a stub DesignRule mimicking Phase 48.5 class-level attrs.
    class _StubRule:
        name = "STUB_RULE_01"
        default_severity = "WARNING"  # RuleSeverity.WARNING value
        description = "stub"

        def check(self, topology: Any, config: Any = None) -> list:
            return []

    wrapped_cls = wrap_readability_rule(_StubRule())
    # P0-3: accessible on the class without instantiation
    assert wrapped_cls.rule_id == "STUB_RULE_01"
    assert wrapped_cls.severity in ("error", "warning", "info")
    assert wrapped_cls.description == "stub"
    # It's a Convention subclass
    assert issubclass(wrapped_cls, Convention)
    # Class-level attr equals instance attr
    inst = wrapped_cls()
    assert type(inst).rule_id == inst.rule_id


def test_wrapped_rule_check_calls_underlying_design_rule_check():
    """Adapter's check() delegates to the wrapped Phase 48.5 rule.

    P1-1: layout.schematic_ir.schematic is passed as topology to the wrapped rule.
    """
    from kicad_agent.conventions.catalog.readability_adapters import wrap_readability_rule

    call_log: list[Any] = []

    class _StubRule:
        name = "STUB_RULE_01"
        default_severity = "WARNING"
        description = "stub"

        def check(self, topology: Any, config: Any = None) -> list:
            call_log.append((topology, config))
            return []

    wrapped_cls = wrap_readability_rule(_StubRule())
    # Build a layout with a non-None schematic_ir so the early-return guard is skipped.
    layout = _layout_with_stub_ir()
    inst = wrapped_cls()
    inst.check(layout, config={"iou_threshold": 0.1})
    assert len(call_log) == 1
    assert call_log[0][0] is "stub-schematic"  # layout.schematic_ir.schematic
    assert call_log[0][1] == {"iou_threshold": 0.1}


def test_wrapped_rule_check_returns_empty_when_schematic_ir_is_none():
    """When layout.schematic_ir is None (synthetic test layout), check() returns []."""
    from kicad_agent.conventions.catalog.readability_adapters import wrap_readability_rule

    class _StubRule:
        name = "STUB_RULE_01"
        default_severity = "WARNING"
        description = "stub"

        def check(self, topology: Any, config: Any = None) -> list:
            raise AssertionError("should not be called when schematic_ir is None")

    inst = wrap_readability_rule(_StubRule())()
    layout = _empty_layout()  # schematic_ir=None
    result = inst.check(layout)
    assert result == []


def test_wrapped_rule_apply_is_identity():
    """Read-only conventions: apply() returns layout unchanged."""
    from kicad_agent.conventions.catalog.readability_adapters import wrap_readability_rule

    class _StubRule:
        name = "STUB_RULE_01"
        default_severity = "WARNING"
        description = "stub"

        def check(self, topology: Any, config: Any = None) -> list:
            return []

    inst = wrap_readability_rule(_StubRule())()
    layout = _empty_layout()
    result = inst.apply(layout)
    assert result is layout  # identity


def test_get_adapted_readability_rules_returns_six_convention_instances():
    """Phase 48.5 has 6 readability rules; all wrapped as Convention subclasses."""
    from kicad_agent.conventions.catalog.readability_adapters import (
        get_adapted_readability_rules,
    )

    rules = get_adapted_readability_rules()
    assert len(rules) == 6
    pattern = re.compile(r"^[A-Z][A-Z0-9_]*\d{2}$")
    for r in rules:
        assert isinstance(r, Convention)
        assert pattern.match(r.rule_id), f"P0-3: {r.rule_id} fails regex"
        # class-level attr (P0-3)
        assert type(r).rule_id == r.rule_id, f"P0-3: {r.rule_id} not class-level"


def test_adapter_rule_ids_match_phase48_readability_names():
    """All 6 Phase 48.5 names preserved through the adapter."""
    from kicad_agent.conventions.catalog.readability_adapters import (
        get_adapted_readability_rules,
    )

    rules = get_adapted_readability_rules()
    names = {r.rule_id for r in rules}
    expected = {
        "SCHEMATIC_OVERLAP_01",
        "TEXT_OVERLAP_01",
        "DUPLICATE_LABEL_01",
        "LABEL_SPACING_01",
        "COMPONENT_SPACING_01",
        "WIRE_CLUTTER_01",
    }
    assert names == expected


# ---------------------------------------------------------------------------
# ConventionEngine tests
# ---------------------------------------------------------------------------


class _StubConvention(Convention):
    """Test stub — emits N violations, configurable severity."""

    rule_id = "STUB_CONV_01"
    severity = "warning"  # type: ignore[assignment]
    description = "stub"

    def __init__(self, n: int = 1, severity: str = "warning", raise_on_call: bool = False):
        self._n = n
        self._severity = severity  # type: ignore[assignment]
        self._raise = raise_on_call

    def check(self, layout: LayoutView, config: dict[str, Any] | None = None) -> list[Violation]:
        if self._raise:
            raise RuntimeError("synthetic crash")
        return [
            Violation(
                rule_id=self.rule_id,
                severity=self._severity,  # type: ignore[arg-type]
                message=f"v{i}",
                component_refs=("R1",),
                suggestion_relative="fix",
            )
            for i in range(self._n)
        ]

    def apply(self, layout: LayoutView) -> LayoutView:
        return layout


def test_engine_runs_all_enabled_conventions():
    from kicad_agent.conventions.engine import ConventionEngine

    convs = [_StubConvention(n=2, severity="warning"), _StubConvention(n=1, severity="info")]
    engine = ConventionEngine(conventions=convs)
    violations = engine.run(_empty_layout())
    assert len(violations) == 3


def test_engine_skips_disabled_conventions():
    from kicad_agent.conventions.engine import ConventionEngine

    a = _StubConvention(n=1, severity="warning")
    # rule_id collision is fine for this test — both use STUB_CONV_01
    config = ConventionConfig(disabled_conventions={"STUB_CONV_01"})
    engine = ConventionEngine(conventions=[a], config=config)
    violations = engine.run(_empty_layout())
    assert violations == []


def test_engine_passes_per_convention_thresholds_via_config():
    """P2-1: engine looks up per-convention thresholds in config.convention_configs."""
    from kicad_agent.conventions.engine import ConventionEngine

    received_configs: list[Any] = []

    class _Recording(Convention):
        rule_id = "RECORDING_01"
        severity = "info"  # type: ignore[assignment]
        description = "records config"

        def check(self, layout: LayoutView, config: dict[str, Any] | None = None) -> list[Violation]:
            received_configs.append(config)
            return []

        def apply(self, layout: LayoutView) -> LayoutView:
            return layout

    cfg = ConventionConfig(
        convention_configs={"RECORDING_01": {"iou_threshold": 0.42}},
    )
    engine = ConventionEngine(conventions=[_Recording()], config=cfg)
    engine.run(_empty_layout())
    assert received_configs == [{"iou_threshold": 0.42}]


def test_engine_catches_broken_convention_and_emits_meta_violation():
    """Broken convention → meta-Violation (severity=warning); engine continues."""
    from kicad_agent.conventions.engine import ConventionEngine

    broken = _StubConvention(raise_on_call=True)
    good = _StubConvention(n=1, severity="info")
    engine = ConventionEngine(conventions=[broken, good])
    violations = engine.run(_empty_layout())
    # Broken emits 1 meta-violation; good emits 1
    assert len(violations) == 2
    meta = next(v for v in violations if "execution failed" in v.message.lower())
    assert meta.rule_id == "STUB_CONV_01"
    assert meta.severity == "warning"


def test_engine_sorts_violations_by_severity():
    """error → warning → info ordering."""
    from kicad_agent.conventions.engine import ConventionEngine

    convs = [
        _StubConvention(n=1, severity="info"),
        _StubConvention(n=1, severity="error"),
        _StubConvention(n=1, severity="warning"),
    ]
    engine = ConventionEngine(conventions=convs)
    violations = engine.run(_empty_layout())
    severities = [v.severity for v in violations]
    assert severities == ["error", "warning", "info"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubIR:
    """Minimal SchematicIR stub — exposes .schematic as a sentinel."""

    @property
    def schematic(self):
        return "stub-schematic"


def _empty_layout() -> LayoutView:
    return LayoutView(schematic_ir=None, components=(), wires=(), labels=())  # type: ignore[arg-type]


def _layout_with_stub_ir() -> LayoutView:
    """Layout whose schematic_ir is a stub returning a sentinel schematic object."""
    return LayoutView(schematic_ir=_StubIR(), components=(), wires=(), labels=())  # type: ignore[arg-type]
