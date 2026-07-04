"""WIRE_ORTHOGONALITY_01 — wires must use 90° bends (read-only).

D-01 selection rationale (citing ACTUAL 108-SRS-VERIFICATION.md):
Phase 108 emits `insert_wire` mutations; the wire_router produces orthogonal
segments. This convention validates that real-board wires (which may have been
hand-routed before autolayout) use 90° bends. Read-only (identity apply).
"""
from __future__ import annotations

import math
from typing import Any

from kicad_agent.conventions.base import Convention, Violation
from kicad_agent.conventions.layout_view import LayoutView


class WIRE_ORTHOGONALITY_01(Convention):
    """Flag wire segments that are not horizontal or vertical (non-90° bends)."""

    rule_id = "WIRE_ORTHOGONALITY_01"
    severity = "info"
    description = "Wires should use 90° bends (horizontal or vertical segments only)."

    _TOLERANCE_DEG = 1.0

    def check(
        self,
        layout: LayoutView,
        config: dict[str, Any] | None = None,
    ) -> list[Violation]:
        violations: list[Violation] = []
        for wire in layout.wires:
            pts = wire.points
            for i in range(len(pts) - 1):
                x1, y1 = pts[i]
                x2, y2 = pts[i + 1]
                dx = x2 - x1
                dy = y2 - y1
                if abs(dx) < 1e-9 and abs(dy) < 1e-9:
                    continue  # zero-length segment
                angle_deg = math.degrees(math.atan2(dy, dx)) % 90.0
                # If the segment angle modulo 90 is not ~0, it's non-orthogonal
                if angle_deg > self._TOLERANCE_DEG and angle_deg < (90.0 - self._TOLERANCE_DEG):
                    violations.append(
                        Violation(
                            rule_id=self.rule_id,
                            severity=self.severity,
                            message=(
                                f"wire segment {i + 1} of label-less wire is non-orthogonal "
                                f"(angle {(math.degrees(math.atan2(dy, dx))):.1f}°)"
                            ),
                            component_refs=(),
                            suggestion_relative=(
                                "reroute wire using only horizontal/vertical segments"
                            ),
                        )
                    )
                    break  # one violation per wire is enough
        return violations

    def apply(self, layout: LayoutView) -> LayoutView:
        return layout  # read-only
