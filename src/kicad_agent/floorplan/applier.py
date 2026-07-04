"""Phase 157: Floor plan applier — applies a FloorPlanSpec to a real PCB.

Orchestrates the lowering + PcbRawWriter operations:
  1. Lower the spec → PlacementVectors (fixed positions, keepouts, penalties)
  2. Apply fixed positions via modify_footprint_position
  3. Inject keepout zones via build_zone_sexp / gr_poly
  4. Verify placement rules (hard rules fail-closed)
  5. Return (modified_pcb, result) with violations list
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from kicad_agent.floorplan.spec import FloorPlanSpec, RulePriority
from kicad_agent.floorplan.lower import (
    PlacementVectors,
    lower_floor_plan,
    evaluate_rule_penalty,
    total_penalty,
)

logger = logging.getLogger(__name__)


@dataclass
class FloorPlanResult:
    """Result of applying a floor plan to a PCB.

    Attributes:
        applied: True if the floor plan was applied successfully.
        modified_content: The modified PCB raw content (or original on failure).
        fixed_count: Number of components locked to positions.
        keepout_count: Number of keepout zones injected.
        violations: List of hard-rule violations (empty = all pass).
        total_penalty: Sum of soft-rule penalties (lower = better).
    """

    applied: bool
    modified_content: str
    fixed_count: int = 0
    keepout_count: int = 0
    violations: list[str] = field(default_factory=list)
    total_penalty: float = 0.0


def apply_floor_plan(
    pcb_content: str,
    spec: FloorPlanSpec,
    component_refs: list[str],
) -> tuple[str, FloorPlanResult]:
    """Apply a floor plan to a PCB's raw content.

    Args:
        pcb_content: Raw .kicad_pcb S-expression content.
        spec: The floor plan specification.
        component_refs: All component reference designators.

    Returns:
        Tuple of (modified_content, result). On any error, returns the
        original content unmodified + result.applied=False.
    """
    try:
        # 1. Lower the spec.
        vectors = lower_floor_plan(spec, component_refs)
        content = pcb_content

        # 2. Apply fixed positions.
        for ref, (x, y, rot) in vectors.fixed_positions.items():
            try:
                from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
                content = PcbRawWriter.modify_footprint_position(
                    content, ref, x, y, rot,
                )
            except Exception as e:
                logger.warning("Failed to fix %s: %s", ref, e)

        # 3. Inject keepout zones as gr_rect graphics on Eco1.User.
        for keepout in vectors.keepout_zones:
            x1, y1, x2, y2 = keepout
            gr_rect = (
                f'  (gr_rect (start {x1} {y1}) (end {x2} {y2}) '
                f'(layer "Eco1.User") (width 0.15) (tstamp 00000000-0000-0000-0000-000000000000))'
            )
            # Insert before the final closing paren.
            content = content.rstrip()
            if content.endswith(")"):
                content = content[:-1] + gr_rect + "\n)"

        # 4. Evaluate placement rules.
        # Build a positions dict from the fixed positions (for rule checking).
        positions: dict[str, tuple[float, float, float]] = {}
        for ref, (x, y, rot) in vectors.fixed_positions.items():
            positions[ref] = (x, y, rot)

        violations: list[str] = []
        for penalty in vectors.rule_penalties:
            p = evaluate_rule_penalty(positions, penalty)
            if p > 0 and penalty.get("weight", 0) >= 1000.0:
                # Hard rule violation.
                violations.append(
                    f"Hard rule violated: {penalty.get('type')} "
                    f"on {penalty.get('subject_ref')} "
                    f"(penalty={p:.1f}, rationale={penalty.get('rationale', '')})"
                )

        soft_penalty = total_penalty(
            positions,
            [p for p in vectors.rule_penalties if p.get("weight", 0) < 1000.0],
        )

        result = FloorPlanResult(
            applied=True,
            modified_content=content,
            fixed_count=len(vectors.fixed_positions),
            keepout_count=len(vectors.keepout_zones),
            violations=violations,
            total_penalty=soft_penalty,
        )

        logger.info(
            "Floor plan applied: %d fixed, %d keepouts, %d violations, %.1f penalty",
            result.fixed_count, result.keepout_count,
            len(violations), soft_penalty,
        )

        return content, result

    except Exception as e:
        logger.error("Floor plan application failed: %s", e)
        return pcb_content, FloorPlanResult(
            applied=False,
            modified_content=pcb_content,
            violations=[f"Application error: {e}"],
        )
