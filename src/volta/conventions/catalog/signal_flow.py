"""SIGNAL_FLOW_DIRECTION_01 — signal-flow left-to-right convention (read-only).

D-01 selection rationale (citing ACTUAL 108-SRS-VERIFICATION.md):
Phase 108 Sugiyama stage 1 reverses feedback edges and lays out signal flow
left-to-right. This convention validates that the OUTPUT respects signal flow
(no ICs facing backward). Read-only (identity apply).

v1 heuristic: flags ICs (refs starting with U, IC) whose orientation is 180°
(canonical signal-flow reversed). Future phases can refine via lib_symbol pin
analysis once a richer LayoutView is available.
"""
from __future__ import annotations

from typing import Any

from volta.conventions.base import Convention, Violation
from volta.conventions.layout_view import LayoutView


class SIGNAL_FLOW_DIRECTION_01(Convention):
    """Flag ICs whose orientation suggests backward signal flow (180° rotation)."""

    rule_id = "SIGNAL_FLOW_DIRECTION_01"
    severity = "warning"
    description = (
        "ICs should face canonical signal-flow direction (left-to-right). "
        "Components rotated 180° may reverse signal flow."
    )

    _IC_REF_PREFIXES = ("U", "IC", "Q", "M")

    def check(
        self,
        layout: LayoutView,
        config: dict[str, Any] | None = None,
    ) -> list[Violation]:
        violations: list[Violation] = []
        for comp in layout.components:
            if not comp.ref:
                continue
            if not any(comp.ref.startswith(p) for p in self._IC_REF_PREFIXES):
                continue
            # Normalize orientation to [0, 360)
            orientation = comp.orientation % 360.0
            if abs(orientation - 180.0) < 0.5:
                violations.append(
                    Violation(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        message=f"IC {comp.ref} is rotated 180° — signal flow may be reversed",
                        component_refs=(comp.ref,),
                        suggestion_relative=(
                            f"rotate {comp.ref} to 0° to align signal flow left-to-right"
                        ),
                    )
                )
        return violations

    def apply(self, layout: LayoutView) -> LayoutView:
        return layout  # read-only
