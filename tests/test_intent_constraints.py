"""Natural-language placement-constraint import (volta-24 follow-on).

The LLM fills GenerationIntent.placement_constraints from phrases like
"keep the regulator away from the analog section"; the spec converts to
PlacementRule objects the placement engine enforces.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from volta.generation.intent import GenerationIntent, PlacementConstraintSpec
from volta.placement.constraints import PlacementRule, RuleSource, RuleType


class TestConstraintSpec:
    def test_minimal_avoid_spec(self):
        spec = PlacementConstraintSpec(
            rule_type="avoid",
            refs=["U3"],
            refs_b=["U1"],
            mm=25.0,
            rationale="EMI",
        )
        rule = spec.to_rule()
        assert isinstance(rule, PlacementRule)
        assert rule.rule_type is RuleType.avoid
        assert rule.source is RuleSource.explicit
        assert rule.payload == {"refs_b": ["U1"], "mm": 25.0}
        assert rule.rationale == "EMI"

    def test_edge_spec(self):
        spec = PlacementConstraintSpec(
            rule_type="edge_affinity", refs=["J1"], edge="bottom", mm=4.0
        )
        rule = spec.to_rule()
        assert rule.payload == {"edge": "bottom", "mm": 4.0}

    def test_region_spec(self):
        spec = PlacementConstraintSpec(
            rule_type="region", refs=["U2"],
            region=[0.0, 0.0, 50.0, 40.0], name="analog",
        )
        rule = spec.to_rule()
        assert rule.payload["region"] == [0.0, 0.0, 50.0, 40.0]

    def test_orientation_and_approach_specs(self):
        a = PlacementConstraintSpec(
            rule_type="orientation", refs=["LED1"], rotation=90.0
        ).to_rule()
        b = PlacementConstraintSpec(
            rule_type="approach", refs=["C4"], refs_b=["U3"], mm=5.0
        ).to_rule()
        assert a.payload == {"rotation": 90.0}
        assert b.payload == {"refs_b": ["U3"], "mm": 5.0}

    def test_auto_rule_ids_unique(self):
        specs = [
            PlacementConstraintSpec(rule_type="avoid", refs=["A"], refs_b=["B"], mm=10.0),
            PlacementConstraintSpec(rule_type="avoid", refs=["C"], refs_b=["D"], mm=10.0),
        ]
        rules = [s.to_rule() for s in specs]
        ids = {r.rule_id for r in rules}
        assert len(ids) == 2 and all(i for i in ids)

    def test_invalid_spec_rejected_at_validation(self):
        with pytest.raises(Exception):
            PlacementConstraintSpec(rule_type="avoid", refs=["A"], mm=10.0)  # no refs_b
        with pytest.raises(Exception):
            PlacementConstraintSpec(rule_type="edge_affinity", refs=["J1"], edge="diagonal")

    def test_llm_dict_roundtrip(self):
        intent = GenerationIntent.model_validate({
            "name": "T",
            "placement_constraints": [
                {
                    "rule_type": "avoid",
                    "refs": ["U3"],
                    "refs_b": ["U1"],
                    "mm": 25.0,
                    "rationale": "keep switching noise away from input stage",
                }
            ],
        })
        assert len(intent.placement_constraints) == 1
        assert intent.placement_constraints[0].mm == 25.0


class TestIntentToolSchema:
    def test_tool_schema_includes_constraints(self):
        from volta.llm.tools import INTENT_TOOL

        props = INTENT_TOOL["input_schema"]["properties"]
        assert "placement_constraints" in props
        desc = props["placement_constraints"].get("description", "")
        assert "placement" in desc.lower()


class TestAutoPlaceGate:
    def test_auto_place_accepts_constraints(self, tmp_path):
        """auto_place op parses the constraints field and executes."""
        import shutil

        fixture = Path("tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_pcb")
        work = tmp_path / fixture.name
        shutil.copy(fixture, work)

        from volta.ops.executor import OperationExecutor
        from volta.ops.schema import Operation

        op = Operation.model_validate({
            "root": {
                "op_type": "auto_place",
                "target_file": work.name,
                "component_refs": ["R1", "R2"],
                "constraints": [
                    {
                        "rule_type": "avoid",
                        "refs": ["R1"],
                        "refs_b": ["R2"],
                        "mm": 10.0,
                        "rationale": "test separation",
                    }
                ],
            }
        })
        executor = OperationExecutor(base_dir=tmp_path)
        result = executor.execute(op)
        status = result.get("status", "")
        assert status in ("ok", "partial", "placed", "completed") or not status
        # The op executed with constraints attached without schema rejection
        # (the constraint gate reports via placement_rule violations).
