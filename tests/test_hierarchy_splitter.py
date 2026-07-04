"""Phase 108 Plan 03 Task 1 — HierarchicalSheetSplitter tests (D-02).

Tests the sub-sheet promotion DECISION logic (v1: decision only, no physical
emission — deferred to Phase 145 follow-up Bead).

Coverage:
  - Tests 1-3: MIN_GROUPS_FOR_SPLIT=3 threshold (D-02 small-board collapse)
  - Test 4: Each SheetPlan has unique sub_sheet_file path (no collisions)
  - Test 5: Inter-group boundary_nets computed correctly (nets in >=2 plans)
  - Test 6: SplitterResult + SheetPlan are frozen dataclasses
  - Test 7: Component-to-sheet assignment covers all refs (no orphans)
  - Test 8 (adversarial): Component in 2 subcircuits raises ValueError

TDD: this file is committed FIRST (RED), then implementation lands (GREEN).
"""
from __future__ import annotations

import dataclasses
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from kicad_agent.analysis.subcircuit_detector import (
    Subcircuit,
    SubcircuitType,
)
from kicad_agent.schematic_autolayout.hierarchy_splitter import (
    MIN_GROUPS_FOR_SPLIT,
    HierarchicalSheetSplitter,
    SheetPlan,
    SplitterResult,
)


# ----------------------------------------------------------------------------
# Fixture builders — Subcircuit inline construction (no KiCad files needed)
# ----------------------------------------------------------------------------


def _make_subcircuit(
    subcircuit_id: str,
    refs: tuple[str, ...],
    boundary_nets: tuple[str, ...],
    subcircuit_type: SubcircuitType = SubcircuitType.UNKNOWN,
    center_component: str = "",
    nets: tuple[str, ...] = (),
) -> Subcircuit:
    """Build a Subcircuit fixture with minimal required fields."""
    return Subcircuit(
        subcircuit_id=subcircuit_id,
        components=refs,
        nets=nets or boundary_nets,
        boundary_nets=boundary_nets,
        subcircuit_type=subcircuit_type,
        confidence=0.9,
        center_component=center_component or (refs[0] if refs else ""),
        features={},
    )


# ============================================================================
# Tests 1-3: MIN_GROUPS_FOR_SPLIT threshold (D-02 small-board collapse)
# ============================================================================


class TestPromotionThreshold:
    """D-02: small boards (<3 groups) collapse to single-sheet."""

    def test_single_group_does_not_promote(self):
        """Test 1: 1 subcircuit -> promote_to_hierarchical=False."""
        scs = [
            _make_subcircuit(
                "SC-001",
                ("U1", "R1", "R2"),
                ("VIN", "VOUT"),
                SubcircuitType.PREAMP,
            ),
        ]
        splitter = HierarchicalSheetSplitter()
        result = splitter.split(scs, "board.kicad_sch")

        assert result.promote_to_hierarchical is False
        assert result.sheet_plans == ()
        assert result.inter_group_nets == ()

    def test_two_groups_do_not_promote(self):
        """Test 2: 2 subcircuits -> still single-sheet (below threshold)."""
        scs = [
            _make_subcircuit(
                "SC-001",
                ("U1", "R1"),
                ("NET_A",),
                SubcircuitType.PREAMP,
            ),
            _make_subcircuit(
                "SC-002",
                ("U2", "R2"),
                ("NET_A",),
                SubcircuitType.COMPRESSOR,
            ),
        ]
        splitter = HierarchicalSheetSplitter()
        result = splitter.split(scs, "board.kicad_sch")

        assert result.promote_to_hierarchical is False
        assert result.sheet_plans == ()
        assert result.inter_group_nets == ()

    def test_three_groups_promote_with_three_plans(self):
        """Test 3: 3 subcircuits -> promote=True, len(sheet_plans)==3 (D-02)."""
        scs = [
            _make_subcircuit(
                "SC-001",
                ("U1", "R1"),
                ("AUDIO_IN", "AUDIO_OUT"),
                SubcircuitType.PREAMP,
            ),
            _make_subcircuit(
                "SC-002",
                ("U2", "R2"),
                ("AUDIO_IN", "AUDIO_MID"),
                SubcircuitType.COMPRESSOR,
            ),
            _make_subcircuit(
                "SC-003",
                ("U3", "R3"),
                ("AUDIO_MID", "AUDIO_OUT"),
                SubcircuitType.OUTPUT_STAGE,
            ),
        ]
        splitter = HierarchicalSheetSplitter()
        result = splitter.split(scs, "board.kicad_sch")

        assert result.promote_to_hierarchical is True
        assert len(result.sheet_plans) == 3


# ============================================================================
# Test 4: Unique sub_sheet_file paths (no collisions)
# ============================================================================


class TestSheetPlanFilenames:
    """Each SheetPlan gets a unique sub_sheet_file path."""

    def test_sheet_plans_have_unique_filenames(self):
        """Test 4: no filename collisions across 4 groups."""
        scs = [
            _make_subcircuit(
                f"SC-00{i}",
                (f"U{i}", f"R{i}"),
                ("SHARED_NET",),
                SubcircuitType.PREAMP if i == 1 else SubcircuitType.COMPRESSOR,
            )
            for i in range(1, 5)  # 4 subcircuits
        ]
        splitter = HierarchicalSheetSplitter()
        result = splitter.split(scs, "mixer_board.kicad_sch")

        filenames = [p.sub_sheet_file for p in result.sheet_plans]
        assert len(filenames) == len(set(filenames)), (
            f"Filename collision in: {filenames}"
        )
        # All filenames should derive from the root stem + subcircuit_id + type
        for fn in filenames:
            assert fn.startswith("mixer_board_")
            assert fn.endswith(".kicad_sch")


# ============================================================================
# Test 5: Inter-group boundary nets (nets shared across >=2 plans)
# ============================================================================


class TestInterGroupNets:
    """Boundary nets appearing in >=2 plans become inter_group_nets."""

    def test_inter_group_nets_detected(self):
        """Test 5: SHARED_NET in 2 plans -> inter_group_nets contains it."""
        scs = [
            _make_subcircuit(
                "SC-001",
                ("U1",),
                ("SHARED_NET", "UNIQUE_1"),
                SubcircuitType.PREAMP,
            ),
            _make_subcircuit(
                "SC-002",
                ("U2",),
                ("SHARED_NET", "UNIQUE_2"),
                SubcircuitType.COMPRESSOR,
            ),
            _make_subcircuit(
                "SC-003",
                ("U3",),
                ("SHARED_NET", "UNIQUE_3"),
                SubcircuitType.EQ,
            ),
        ]
        splitter = HierarchicalSheetSplitter()
        result = splitter.split(scs, "board.kicad_sch")

        # SHARED_NET appears in all 3 plans -> inter_group
        assert "SHARED_NET" in result.inter_group_nets
        # UNIQUE_* appear in only 1 plan -> not inter_group
        assert "UNIQUE_1" not in result.inter_group_nets
        assert "UNIQUE_2" not in result.inter_group_nets
        assert "UNIQUE_3" not in result.inter_group_nets


# ============================================================================
# Test 6: Frozen dataclass invariant (Phase 100 CR-01)
# ============================================================================


class TestFrozenDataclasses:
    """SheetPlan and SplitterResult are frozen (Phase 100 CR-01)."""

    def test_sheet_plan_is_frozen(self):
        """Test 6a: SheetPlan mutation raises FrozenInstanceError."""
        plan = SheetPlan(
            subcircuit_id="SC-001",
            sub_sheet_file="board_sc-001_preamp.kicad_sch",
            sheet_name="PREAMP",
            components=("U1", "R1"),
            boundary_nets=("NET_A",),
        )
        with pytest.raises(FrozenInstanceError):
            plan.subcircuit_id = "SC-999"  # type: ignore[misc]

    def test_splitter_result_is_frozen(self):
        """Test 6b: SplitterResult mutation raises FrozenInstanceError."""
        result = SplitterResult(
            promote_to_hierarchical=False,
            sheet_plans=(),
            inter_group_nets=(),
        )
        with pytest.raises(FrozenInstanceError):
            result.promote_to_hierarchical = True  # type: ignore[misc]

    def test_dataclasses_replace_works(self):
        """Test 6c: dataclasses.replace() is the supported mutation path."""
        plan = SheetPlan(
            subcircuit_id="SC-001",
            sub_sheet_file="board_sc-001_preamp.kicad_sch",
            sheet_name="PREAMP",
            components=("U1",),
            boundary_nets=("NET_A",),
        )
        new_plan = dataclasses.replace(plan, subcircuit_id="SC-002")
        assert new_plan.subcircuit_id == "SC-002"
        assert new_plan.components == plan.components
        # Original unchanged
        assert plan.subcircuit_id == "SC-001"


# ============================================================================
# Test 7: Component-to-sheet coverage (no orphans, no duplicates)
# ============================================================================


class TestComponentCoverage:
    """Every component in the input subcircuits lands in exactly one sheet plan."""

    def test_all_refs_covered_no_orphans(self):
        """Test 7: union(plan.components) == union(sc.components)."""
        scs = [
            _make_subcircuit(
                "SC-001",
                ("U1", "R1", "R2", "C1"),
                ("NET_A",),
                SubcircuitType.PREAMP,
            ),
            _make_subcircuit(
                "SC-002",
                ("U2", "R3", "C2"),
                ("NET_A",),
                SubcircuitType.COMPRESSOR,
            ),
            _make_subcircuit(
                "SC-003",
                ("U3", "R4"),
                ("NET_A",),
                SubcircuitType.EQ,
            ),
        ]
        all_input_refs = set()
        for sc in scs:
            all_input_refs.update(sc.components)

        splitter = HierarchicalSheetSplitter()
        result = splitter.split(scs, "board.kicad_sch")

        all_planned_refs = set()
        for plan in result.sheet_plans:
            all_planned_refs.update(plan.components)

        assert all_input_refs == all_planned_refs, (
            f"Missing refs: {all_input_refs - all_planned_refs}; "
            f"Extra refs: {all_planned_refs - all_input_refs}"
        )


# ============================================================================
# Test 8 (adversarial): Component in 2 subcircuits raises ValueError
# ============================================================================


class TestAdversarialOverlap:
    """T-108 adversarial: overlapping subcircuit assignments must raise."""

    def test_overlapping_assignment_raises_value_error(self):
        """Test 8: U1 in SC-001 AND SC-002 -> ValueError mentions U1."""
        scs = [
            _make_subcircuit(
                "SC-001",
                ("U1", "R1"),
                ("NET_A",),
                SubcircuitType.PREAMP,
            ),
            _make_subcircuit(
                "SC-002",
                ("U1", "R2"),  # U1 overlaps SC-001
                ("NET_A",),
                SubcircuitType.COMPRESSOR,
            ),
            _make_subcircuit(
                "SC-003",
                ("U3", "R3"),
                ("NET_A",),
                SubcircuitType.EQ,
            ),
        ]
        splitter = HierarchicalSheetSplitter()
        with pytest.raises(ValueError) as exc_info:
            splitter.split(scs, "board.kicad_sch")

        # Error message must mention the conflicting ref
        assert "U1" in str(exc_info.value), (
            f"Error message must mention conflicting ref 'U1': {exc_info.value}"
        )


# ============================================================================
# Constant: MIN_GROUPS_FOR_SPLIT threshold
# ============================================================================


class TestMinGroupsConstant:
    """MIN_GROUPS_FOR_SPLIT = 3 (D-02)."""

    def test_min_groups_for_split_is_three(self):
        """The D-02 threshold for hierarchy promotion is exactly 3."""
        assert MIN_GROUPS_FOR_SPLIT == 3
