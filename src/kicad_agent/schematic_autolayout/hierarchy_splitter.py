"""Hierarchical sheet promotion DECISION for D-02 functional-group split.

When SubcircuitDetector finds >= MIN_GROUPS_FOR_SPLIT functional groups, this
module computes the promotion DECISION: which subcircuits become sub-sheets,
what their filenames would be, and which nets become hierarchical pins.

v1 scope (per Phase 108 Council Gate 1 revision — CRITICAL-1 fix):
    The DECISION is computed and reported; physical sub-sheet EMISSION
    (writing new .kicad_sch files, moving components between sheets,
    wiring hierarchical pins via existing add_sheet_pin op) is deferred
    to Phase 145. The follow-up Bead is created by the orchestrator
    (Plan 03 Task 2) under the four-state taxonomy as
    DEFERRED-TO-NAMED-TARGET (Phase 145).

D-02 (CONTEXT.md):
    "Always split by functional group via SubcircuitDetector." Small boards
    (<3 groups) collapse back to single-sheet automatically.

Phase 100 CR-01:
    SheetPlan and SplitterResult are @dataclass(frozen=True). Mutation only
    via dataclasses.replace().
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kicad_agent.analysis.subcircuit_detector import Subcircuit

# D-02: small boards stay single-sheet. Below this threshold, the splitter
# returns a no-promotion result regardless of input topology shape.
MIN_GROUPS_FOR_SPLIT: int = 3


@dataclass(frozen=True)
class SheetPlan:
    """Per-sub-sheet creation plan (advisory in v1).

    Physical emission of these plans (writing the .kicad_sch files, moving
    components, wiring hierarchical sheet pins) is deferred to Phase 145.

    Attributes:
        subcircuit_id: The detector-assigned ID (e.g. "SC-001").
        sub_sheet_file: Filename the sub-sheet WOULD receive. Sanitized
            to lower-case subcircuit_type. Unique across plans.
        sheet_name: Human-readable sheet name from SubcircuitType.value
            (e.g. "PREAMP", "COMPRESSOR").
        components: Refs owned by this sheet (tuple — frozen invariant).
        boundary_nets: Nets crossing the sheet boundary (connecting to
            other groups). These become hierarchical pins in Phase 145.
    """

    subcircuit_id: str
    sub_sheet_file: str
    sheet_name: str
    components: tuple[str, ...]
    boundary_nets: tuple[str, ...]


@dataclass(frozen=True)
class SplitterResult:
    """Outcome of the D-02 promotion decision.

    Attributes:
        promote_to_hierarchical: True when >= MIN_GROUPS_FOR_SPLIT groups
            detected AND no overlapping assignments. The advisory flag —
            v1 orchestrator reports hierarchy_promoted=False honestly
            regardless of this value (physical emission deferred).
        sheet_plans: One SheetPlan per subcircuit when promote_to_hierarchical
            is True; empty tuple otherwise.
        inter_group_nets: Nets appearing in >=2 plans' boundary_nets.
            These are the signals that would cross sheet boundaries
            (hierarchical pins in Phase 145). Sorted lexically for
            determinism.
    """

    promote_to_hierarchical: bool
    sheet_plans: tuple[SheetPlan, ...]
    inter_group_nets: tuple[str, ...]


class HierarchicalSheetSplitter:
    """Compute the D-02 hierarchy-promotion DECISION.

    Pure function over the SubcircuitDetector output — does not touch the
    filesystem. Idempotent: same input -> same output.
    """

    def split(
        self,
        subcircuits: list[Subcircuit],
        root_file: str,
    ) -> SplitterResult:
        """Decide whether hierarchy promotion is warranted (D-02).

        Args:
            subcircuits: Output of SubcircuitDetector.detect(topology).
                May be empty (no ICs found) or below threshold — both
                collapse to single-sheet.
            root_file: Path to the root .kicad_sch. Used only to derive
                sub-sheet filename stems; never read or written.

        Returns:
            SplitterResult. promote_to_hierarchical is True iff:
              1. len(subcircuits) >= MIN_GROUPS_FOR_SPLIT, AND
              2. No component appears in >1 subcircuit (adversarial guard).

        Raises:
            ValueError: When a component is assigned to multiple
                subcircuits. The error message includes the conflicting
                refs and their owning subcircuit IDs for diagnosis.
        """
        # D-02 small-board collapse: below threshold, stay single-sheet.
        if len(subcircuits) < MIN_GROUPS_FOR_SPLIT:
            return SplitterResult(
                promote_to_hierarchical=False,
                sheet_plans=(),
                inter_group_nets=(),
            )

        # T-108 adversarial guard: no component in 2 subcircuits.
        # Physical corruption would result if we emitted sub-sheets with
        # overlapping component ownership (Phase 145 work). Catch now.
        ref_owners: dict[str, list[str]] = {}
        for sc in subcircuits:
            for ref in sc.components:
                ref_owners.setdefault(ref, []).append(sc.subcircuit_id)
        overlaps: dict[str, list[str]] = {
            ref: owners for ref, owners in ref_owners.items() if len(owners) > 1
        }
        if overlaps:
            raise ValueError(
                f"Components assigned to multiple subcircuits: {overlaps}"
            )

        # Build sheet plans: one per subcircuit. Filename derives from the
        # root stem + subcircuit_id + sanitized subcircuit_type. All three
        # segments are required because subcircuit_type alone could collide
        # (two PREAMP groups in a large board) and subcircuit_id alone is
        # opaque to humans reading the directory listing.
        root_stem = Path(root_file).stem
        plans: list[SheetPlan] = []
        for sc in subcircuits:
            safe_name = sc.subcircuit_type.value.lower()
            sub_file = (
                f"{root_stem}_{sc.subcircuit_id.lower()}_{safe_name}.kicad_sch"
            )
            plans.append(
                SheetPlan(
                    subcircuit_id=sc.subcircuit_id,
                    sub_sheet_file=sub_file,
                    sheet_name=sc.subcircuit_type.value,
                    components=sc.components,
                    boundary_nets=sc.boundary_nets,
                )
            )

        # Inter-group nets = boundary_nets appearing in >=2 plans. These
        # are the signals that would become hierarchical sheet pins in
        # Phase 145. Sort lexically for deterministic output.
        net_owners: dict[str, set[str]] = {}
        for plan in plans:
            for net in plan.boundary_nets:
                net_owners.setdefault(net, set()).add(plan.subcircuit_id)
        inter_group = tuple(
            sorted(
                net
                for net, owners in net_owners.items()
                if len(owners) >= 2
            )
        )

        return SplitterResult(
            promote_to_hierarchical=True,
            sheet_plans=tuple(plans),
            inter_group_nets=inter_group,
        )
