"""IEEE315_PIN_ORIENTATION_01 — canonical pin orientation convention.

D-01 selection rationale (citing ACTUAL 108-SRS-VERIFICATION.md):
Phase 108 emits `move_symbol` mutations with `angle` field; if a real board
(beyond Arduino_Mega's 6 subcircuits) has passives at non-canonical angles,
autolayout should snap them.

P1-R2-1 (Council Round 2 fix): DEMOTED TO READ-ONLY for v1.
SchematicRawWriter.apply_mutation ignores the `angle` field on move_symbol
mutations (only new_x/new_y are honored — see schematic_raw_writer.py lines
420-422). This convention's apply() cannot round-trip orientation changes
through the writer. Resolution per Bureaucracy §7 four-state taxonomy:

  - State: SUPERSEDED-BY-ALTERNATIVE for the TRANSFORM semantics.
  - v1 implementation: read-only (apply = identity). check() still flags
    non-canonical orientations.
  - Alternative: extend SchematicRawWriter to honor `angle` field.
  - Evidence: writer source (lines 420-422) confirms angle is dropped.
  - Trigger for auto-promotion back to TRANSFORM: when Phase 115 lands the
    writer angle extension, restore apply() to dataclasses.replace-snapped
    orientations. Tracked in ROADMAP "## Deferred" section.
"""
from __future__ import annotations

from typing import Any

from kicad_agent.conventions.base import Convention, Violation
from kicad_agent.conventions.layout_view import LayoutView


class IEEE315_PIN_ORIENTATION_01(Convention):
    """Flag passives (R/C/L/D) at non-canonical orientations (not 0/90/180/270).

    P1-R2-1: For v1, apply() is identity (read-only). The check() still
    reports non-canonical orientations. Writer angle support deferred to
    Phase 115.
    """

    rule_id = "IEEE315_PIN_ORIENTATION_01"
    severity = "info"
    description = (
        "Passive components (R/C/L/D) should use canonical orientations "
        "(0°/90°/180°/270°) per IEEE 315."
    )

    _PASSIVE_REF_PREFIXES = ("R", "C", "L", "D")
    _CANONICAL_ORIENTATIONS = (0.0, 90.0, 180.0, 270.0)
    _TOLERANCE_DEG = 0.5

    def check(
        self,
        layout: LayoutView,
        config: dict[str, Any] | None = None,
    ) -> list[Violation]:
        violations: list[Violation] = []
        for comp in layout.components:
            if not comp.ref:
                continue
            if not any(comp.ref.startswith(p) for p in self._PASSIVE_REF_PREFIXES):
                continue
            orientation = comp.orientation % 360.0
            if not any(
                abs(orientation - canonical) < self._TOLERANCE_DEG
                for canonical in self._CANONICAL_ORIENTATIONS
            ):
                violations.append(
                    Violation(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        message=(
                            f"{comp.ref} orientation {orientation:.1f}° is non-canonical "
                            "(should be 0°/90°/180°/270°)"
                        ),
                        component_refs=(comp.ref,),
                        suggestion_relative=(
                            f"rotate {comp.ref} to nearest 90° multiple"
                        ),
                    )
                )
        return violations

    def apply(self, layout: LayoutView) -> LayoutView:
        # P1-R2-1: identity for v1. Writer cannot round-trip angle.
        # DEFERRED-TO-NAMED-TARGET: Phase 115 writer angle extension will
        # restore TRANSFORM semantics here.
        return layout
