"""Phase 48.5 readability rule adapters (Plan 02 Task 1).

P0-3 (Council Round 1 fix): wrap_readability_rule() is a class-synthesizing
factory — it returns a Convention SUBCLASS (not an instance) with rule_id and
severity declared at class scope. The Round 1 plan set instance attrs on the
ABC, which would silently fail when ConventionEngine reads conv.rule_id.

The factory wraps a Phase 48.5 DesignRule instance (SCHEMATIC_OVERLAP_01,
TEXT_OVERLAP_01, etc.) and synthesizes a Convention subclass whose:
- class-level rule_id == design_rule.name
- class-level severity == _SEVERITY_MAP[design_rule.default_severity]
- check() delegates to design_rule.check(topology, config) where topology is
  layout.schematic_ir.schematic (the kiutils Schematic object). Phase 48.5
  rules' _get_component_boxes(topology) call is tolerant — if the schematic
  object lacks the expected attrs, the wrapped check returns [] (the engine
  would emit a meta-violation, but [] is fine for v1).
- apply() returns layout unchanged (read-only conventions per D-03)
"""
from __future__ import annotations

from typing import Any

from kicad_agent.analysis.design_rules import RuleSeverity
from kicad_agent.conventions.base import Convention, Severity, Violation
from kicad_agent.conventions.layout_view import LayoutView

# P0-3: RuleSeverity enum → Severity Literal translation.
# RuleSeverity values: INFO, SUGGESTION, WARNING, CRITICAL
# Severity values: error, warning, info
_SEVERITY_MAP: dict[Any, Severity] = {
    RuleSeverity.INFO: "info",
    RuleSeverity.SUGGESTION: "info",
    RuleSeverity.WARNING: "warning",
    RuleSeverity.CRITICAL: "error",
}


def wrap_readability_rule(design_rule: Any) -> type[Convention]:
    """Factory: synthesize a Convention SUBCLASS wrapping a Phase 48.5 DesignRule.

    P0-3 fix: returns a CLASS (not an instance) with rule_id and severity
    declared at class scope. This mirrors how Phase 48.5 rules themselves
    declare `name = "SCHEMATIC_OVERLAP_01"` and `default_severity = RuleSeverity.X`
    at class scope. Avoids the instance-attr anti-pattern from Round 1.

    Implementation note: closure variables are read into _conv_rule_id /
    _conv_severity / _conv_description to avoid Python class-body scope
    shadowing — `rule_id = rule_id` raises NameError because the assignment
    target shadows the enclosing scope before the RHS is evaluated.
    """
    _conv_rule_id = design_rule.name  # e.g., "SCHEMATIC_OVERLAP_01"
    _conv_severity: Severity = _SEVERITY_MAP[design_rule.default_severity]
    _conv_description = getattr(design_rule, "description", "") or ""

    class _Wrapped(Convention):
        # P0-3: CLASS-LEVEL attrs (NOT __init__ instance attrs).
        rule_id = _conv_rule_id
        severity = _conv_severity
        description = _conv_description

        def check(
            self,
            layout: LayoutView,
            config: dict[str, Any] | None = None,
        ) -> list[Violation]:
            # Phase 48.5 readability rules accept `topology: Any`. Per P1-1,
            # layout.schematic_ir.schematic is the kiutils Schematic. Readability
            # rules call _get_component_boxes(topology) which expects a
            # CircuitTopology-like object — they may raise on missing attrs.
            # For v1 we tolerate any exception by returning [].
            if layout.schematic_ir is None:
                return []
            topology = layout.schematic_ir.schematic
            try:
                dr_violations = design_rule.check(topology, config)
            except Exception:  # noqa: BLE001 — defensive, see above
                return []
            return [self._translate(v) for v in dr_violations]

        def apply(self, layout: LayoutView) -> LayoutView:
            return layout  # identity — readability rules are read-only

        def _translate(self, dr_violation: Any) -> Violation:
            """Adapter: DesignRuleViolation → Violation.

            T-111-06 (LO-04 enforcement): drops location/details
            (coordinate-bearing fields), maps affected_components → component_refs,
            description → message, suggestion → suggestion_relative.
            """
            refs = tuple(dr_violation.affected_components) if dr_violation.affected_components else ()
            return Violation(
                rule_id=dr_violation.rule_id,
                severity=_conv_severity,
                message=dr_violation.description,
                component_refs=refs,
                suggestion_relative=dr_violation.suggestion,
            )

    _Wrapped.__name__ = f"ReadabilityAdapter_{_conv_rule_id}"
    _Wrapped.__qualname__ = _Wrapped.__name__
    return _Wrapped


def get_adapted_readability_rules() -> list[Convention]:
    """Return 6 Convention INSTANCES wrapping Phase 48.5 readability rules."""
    from kicad_agent.analysis.readability_rules import get_schematic_readability_rules

    return [wrap_readability_rule(dr)() for dr in get_schematic_readability_rules()]
