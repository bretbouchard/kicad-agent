"""Phase 157: Floor planner tests — placement rules + lowering."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from kicad_agent.floorplan import (
    FloorPlanSpec,
    PlacementRule,
    RuleType,
    RulePriority,
    load_floor_plan,
    lower_floor_plan,
    evaluate_rule_penalty,
    total_penalty,
)


class TestPlacementRule:
    """PlacementRule model — the contextual constraint primitive."""

    def test_edge_affinity_rule(self) -> None:
        """edge_affinity: J1 must be on bottom edge."""
        rule = PlacementRule(
            subject_ref="J1",
            rule_type=RuleType.EDGE_AFFINITY,
            target="edge",
            max_mm=3.0,
            edge_sides=("bottom",),
            rationale="USB connector accessible from enclosure",
            priority=RulePriority.HARD,
        )
        assert rule.rule_type == RuleType.EDGE_AFFINITY
        assert rule.max_mm == 3.0
        assert rule.priority == RulePriority.HARD

    def test_avoid_rule(self) -> None:
        """avoid: U3 must be 25mm from U1."""
        rule = PlacementRule(
            subject_ref="U3",
            rule_type=RuleType.AVOID,
            target="U1",
            min_mm=25.0,
            rationale="EMI from switching regulator",
        )
        assert rule.min_mm == 25.0
        assert rule.priority == RulePriority.SOFT  # default

    def test_approach_rule(self) -> None:
        """approach: C4 within 5mm of U3."""
        rule = PlacementRule(
            subject_ref="C4",
            rule_type=RuleType.APPROACH,
            target="U3",
            max_mm=5.0,
            rationale="Decoupling inductance",
        )
        assert rule.max_mm == 5.0

    def test_orientation_rule(self) -> None:
        """orientation: LED1 faces up."""
        rule = PlacementRule(
            subject_ref="LED1",
            rule_type=RuleType.ORIENTATION,
            target="fixed",
            orientation_deg=0.0,
            rationale="Visible from above",
        )
        assert rule.orientation_deg == 0.0


class TestLowerFloorPlan:
    """Lowering: spec → placement vectors."""

    def test_pre_placed_become_fixed(self) -> None:
        """Pre-placed anchors become fixed positions."""
        spec = FloorPlanSpec(
            board_width_mm=100, board_height_mm=80,
            pre_placed={"J1": (5.0, 40.0, 90.0)},
        )
        vectors = lower_floor_plan(spec, ["J1", "R1"])
        assert "J1" in vectors.fixed_positions
        assert vectors.fixed_positions["J1"] == (5.0, 40.0, 90.0)

    def test_edge_clearance_generates_keepouts(self) -> None:
        """Edge clearance generates 4 keepout bands."""
        spec = FloorPlanSpec(
            board_width_mm=100, board_height_mm=80,
            edge_clearance_mm=3.0,
        )
        vectors = lower_floor_plan(spec, [])
        assert len(vectors.keepout_zones) >= 4  # 4 edge bands

    def test_avoid_rule_generates_penalty(self) -> None:
        """avoid rule generates a SA penalty."""
        spec = FloorPlanSpec(
            board_width_mm=100, board_height_mm=80,
            placement_rules=[
                PlacementRule(
                    subject_ref="U3", rule_type=RuleType.AVOID,
                    target="U1", min_mm=25.0,
                    rationale="EMI", priority=RulePriority.HARD,
                ),
            ],
        )
        vectors = lower_floor_plan(spec, ["U1", "U3"])
        avoid_penalties = [p for p in vectors.rule_penalties if p["type"] == "avoid"]
        assert len(avoid_penalties) == 1
        assert avoid_penalties[0]["min_mm"] == 25.0


class TestEvaluateRulePenalty:
    """Penalty evaluation — the SA objective integration."""

    def test_avoid_satisfied(self) -> None:
        """Components far apart → 0 penalty."""
        positions = {"U1": (0, 0, 0), "U3": (50, 50, 0)}
        penalty = {"type": "avoid", "subject_ref": "U3", "target_ref": "U1",
                    "min_mm": 25.0, "weight": 1000.0}
        assert evaluate_rule_penalty(positions, penalty) == 0.0

    def test_avoid_violated(self) -> None:
        """Components too close → positive penalty."""
        positions = {"U1": (10, 10, 0), "U3": (15, 10, 0)}  # 5mm apart
        penalty = {"type": "avoid", "subject_ref": "U3", "target_ref": "U1",
                    "min_mm": 25.0, "weight": 1000.0}
        p = evaluate_rule_penalty(positions, penalty)
        assert p > 0.0

    def test_approach_satisfied(self) -> None:
        """Components close → 0 penalty."""
        positions = {"C4": (10, 10, 0), "U3": (12, 10, 0)}  # 2mm apart
        penalty = {"type": "approach", "subject_ref": "C4", "target_ref": "U3",
                    "max_mm": 5.0, "weight": 10.0}
        assert evaluate_rule_penalty(positions, penalty) == 0.0

    def test_approach_violated(self) -> None:
        """Components too far → positive penalty."""
        positions = {"C4": (0, 0, 0), "U3": (50, 50, 0)}  # 70mm apart
        penalty = {"type": "approach", "subject_ref": "C4", "target_ref": "U3",
                    "max_mm": 5.0, "weight": 10.0}
        p = evaluate_rule_penalty(positions, penalty)
        assert p > 0.0

    def test_edge_affinity_satisfied(self) -> None:
        """Component near edge → 0 penalty."""
        positions = {"J1": (50, 78, 0)}  # 2mm from bottom edge
        penalty = {"type": "edge_affinity", "subject_ref": "J1",
                    "max_mm": 3.0, "edge_sides": ["bottom"],
                    "board_bounds": (0, 0, 100, 80), "weight": 1000.0}
        assert evaluate_rule_penalty(positions, penalty) == 0.0

    def test_edge_affinity_violated(self) -> None:
        """Component in center → positive penalty."""
        positions = {"J1": (50, 40, 0)}  # center of board
        penalty = {"type": "edge_affinity", "subject_ref": "J1",
                    "max_mm": 3.0, "edge_sides": ["bottom"],
                    "board_bounds": (0, 0, 100, 80), "weight": 1000.0}
        p = evaluate_rule_penalty(positions, penalty)
        assert p > 0.0

    def test_total_penalty_sums_all(self) -> None:
        """total_penalty sums multiple rules."""
        positions = {"U1": (0, 0, 0), "U3": (5, 0, 0)}
        penalties = [
            {"type": "avoid", "subject_ref": "U3", "target_ref": "U1",
             "min_mm": 25.0, "weight": 100.0},
            {"type": "avoid", "subject_ref": "U1", "target_ref": "U3",
             "min_mm": 25.0, "weight": 100.0},
        ]
        total = total_penalty(positions, penalties)
        assert total > 0.0
