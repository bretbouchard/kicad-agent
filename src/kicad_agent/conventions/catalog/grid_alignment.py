"""GRID_ALIGNMENT_01 — components must lie on the 2.54mm KiCad grid (TRANSFORM).

D-01 selection rationale (citing ACTUAL 108-SRS-VERIFICATION.md):
Phase 108 layout_graph.py declares KICAD_GRID_MM = 2.54. Components placed
off-grid break wire connectivity (Phase 26 finding: 3.81mm R/C offset placed
connection points off-grid). TRANSFORM convention — apply() snaps positions
to nearest 2.54mm multiple via dataclasses.replace (Phase 100 CR-01).
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from kicad_agent.conventions.base import Convention, Violation
from kicad_agent.conventions.layout_view import ComponentView, LayoutView


class GRID_ALIGNMENT_01(Convention):
    """Flag and snap components off the 2.54mm grid."""

    rule_id = "GRID_ALIGNMENT_01"
    severity = "warning"
    description = "Components must lie on the 2.54mm KiCad grid for wire connectivity."

    KICAD_GRID_MM = 2.54
    _TOLERANCE_MM = 0.05  # 50 µm tolerance — anything outside is off-grid

    def check(
        self,
        layout: LayoutView,
        config: dict[str, Any] | None = None,
    ) -> list[Violation]:
        violations: list[Violation] = []
        for comp in layout.components:
            if not comp.ref:
                continue
            x, y = comp.position
            nearest_x = round(x / self.KICAD_GRID_MM) * self.KICAD_GRID_MM
            nearest_y = round(y / self.KICAD_GRID_MM) * self.KICAD_GRID_MM
            if abs(x - nearest_x) > self._TOLERANCE_MM or abs(y - nearest_y) > self._TOLERANCE_MM:
                violations.append(
                    Violation(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        message=f"{comp.ref} is off the {self.KICAD_GRID_MM}mm grid",
                        component_refs=(comp.ref,),
                        suggestion_relative=(
                            f"snap {comp.ref} to nearest grid crossing"
                        ),
                    )
                )
        return violations

    def apply(self, layout: LayoutView) -> LayoutView:
        """Phase 100 CR-01: return a NEW LayoutView with snapped positions.

        NEVER mutates the input. Each ComponentView is rebuilt via
        dataclasses.replace(comp, position=(snapped_x, snapped_y)).
        """
        new_components = tuple(self._snap(comp) for comp in layout.components)
        return replace(layout, components=new_components)

    def _snap(self, comp: ComponentView) -> ComponentView:
        x, y = comp.position
        snapped_x = round(x / self.KICAD_GRID_MM) * self.KICAD_GRID_MM
        snapped_y = round(y / self.KICAD_GRID_MM) * self.KICAD_GRID_MM
        if abs(snapped_x - x) < 1e-9 and abs(snapped_y - y) < 1e-9:
            return comp  # already on grid — avoid unnecessary rebuild
        return replace(comp, position=(snapped_x, snapped_y))
