"""Phase 157: Floor plan applier integration tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from kicad_agent.floorplan import (
    FloorPlanSpec,
    PlacementRule,
    RuleType,
    RulePriority,
    apply_floor_plan,
    load_floor_plan,
)


_MINI_PCB = """(kicad_pcb
  (version 20241129)
  (footprint "Resistor_SMD:R_0603" (layer "F.Cu")
    (uuid "fp-001")
    (at 50.0 50.0 0)
    (property "Reference" "R1" (at 0 0 0))
  )
  (footprint "Package_SO:SOIC-8" (layer "F.Cu")
    (uuid "fp-002")
    (at 100.0 60.0 0)
    (property "Reference" "U1" (at 0 0 0))
  )
)
"""


class TestApplyFloorPlan:
    """Applier: spec -> modified PCB content."""

    def test_applies_fixed_positions(self) -> None:
        """Pre-placed components get repositioned."""
        spec = FloorPlanSpec(
            board_width_mm=120, board_height_mm=80,
            pre_placed={"R1": (10.0, 10.0, 0.0)},
        )
        content, result = apply_floor_plan(_MINI_PCB, spec, ["R1", "U1"])
        assert result.applied
        assert result.fixed_count == 1

    def test_injects_keepout_zones(self) -> None:
        """Edge clearance generates keepout rectangles."""
        spec = FloorPlanSpec(
            board_width_mm=120, board_height_mm=80,
            edge_clearance_mm=3.0,
        )
        content, result = apply_floor_plan(_MINI_PCB, spec, ["R1", "U1"])
        assert result.applied
        assert result.keepout_count >= 4
        assert "gr_rect" in content

    def test_hard_rule_violation_recorded(self) -> None:
        """Hard avoid rule records a violation when components overlap."""
        spec = FloorPlanSpec(
            board_width_mm=120, board_height_mm=80,
            pre_placed={
                "R1": (50.0, 50.0, 0.0),
                "U1": (51.0, 50.0, 0.0),
            },
            placement_rules=[
                PlacementRule(
                    subject_ref="U1", rule_type=RuleType.AVOID,
                    target="R1", min_mm=25.0,
                    rationale="EMI", priority=RulePriority.HARD,
                ),
            ],
        )
        content, result = apply_floor_plan(_MINI_PCB, spec, ["R1", "U1"])
        assert result.applied
        assert len(result.violations) > 0

    def test_failure_returns_original(self) -> None:
        """On error, returns original content unmodified."""
        bad_spec = FloorPlanSpec()
        content, result = apply_floor_plan(_MINI_PCB, bad_spec, ["R1"])
        assert isinstance(content, str)
        assert isinstance(result.applied, bool)

    def test_yaml_round_trip(self, tmp_path: Path) -> None:
        """Load YAML -> apply to PCB."""
        yaml_content = """\
board:
  width_mm: 100.0
  height_mm: 80.0
  edge_clearance_mm: 3.0
zones:
  - name: power
    x_range: [0, 20]
    y_range: [0, 80]
    priority_refs: [U1]
pre_placed:
  U1: [10.0, 40.0, 0.0]
placement_rules:
  - subject_ref: U1
    rule_type: edge_affinity
    target: edge
    max_mm: 10.0
    priority: hard
    rationale: "Regulator near power input"
"""
        yaml_path = tmp_path / "test.floorplan.yaml"
        yaml_path.write_text(yaml_content, encoding="utf-8")

        spec = load_floor_plan(yaml_path)
        assert spec.board_width_mm == 100.0
        assert len(spec.zones) == 1
        assert len(spec.placement_rules) == 1

        content, result = apply_floor_plan(_MINI_PCB, spec, ["R1", "U1"])
        assert result.applied
