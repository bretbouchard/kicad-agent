"""Contextual placement constraints — model, persistence, enforcement (volta-24).

Three layers, TDD:
1. PlacementRule model + validation
2. constraints.json sidecar round-trip
3. Enforcement: initial snap, SA penalty terms, post-placement gate
"""

from __future__ import annotations

from pathlib import Path

import pytest

from volta.placement.constraints import (
    PlacementRuleSet,
    ConstraintViolation,
    PlacementRule,
    RuleSource,
    RuleType,
    apply_initial_constraints,
    constraint_penalty,
    validate_constraints,
)


def _rule(**kw) -> PlacementRule:
    defaults = dict(
        rule_id="r1",
        rule_type=RuleType.avoid,
        source=RuleSource.explicit,
        refs=["U3"],
        payload={"refs_b": ["U1"], "mm": 25.0},
        rationale="EMI: keep switching regulator away from analog front end",
    )
    defaults.update(kw)
    return PlacementRule(**defaults)


class TestModel:
    def test_rule_is_immutable_with_rationale(self):
        r = _rule()
        assert r.rationale.startswith("EMI")
        with pytest.raises(Exception):
            r.refs.append("X")  # frozen

    def test_avoid_requires_refs_b_and_mm(self):
        with pytest.raises(ValueError):
            _rule(payload={})

    def test_approach_requires_refs_b_and_mm(self):
        with pytest.raises(ValueError):
            _rule(rule_type=RuleType.approach, payload={})
        ok = _rule(
            rule_type=RuleType.approach,
            payload={"refs_b": ["U3"], "mm": 5.0},
        )
        assert ok.payload["mm"] == 5.0

    def test_edge_affinity_requires_edge(self):
        with pytest.raises(ValueError):
            _rule(rule_type=RuleType.edge_affinity, payload={})
        r = _rule(rule_type=RuleType.edge_affinity, payload={"edge": "bottom"})
        assert r.payload["edge"] == "bottom"

    def test_region_requires_bbox(self):
        with pytest.raises(ValueError):
            _rule(rule_type=RuleType.region, payload={})
        r = _rule(
            rule_type=RuleType.region,
            payload={"region": [0.0, 0.0, 50.0, 40.0], "name": "analog"},
        )
        assert r.payload["name"] == "analog"

    def test_orientation_requires_degrees(self):
        with pytest.raises(ValueError):
            _rule(rule_type=RuleType.orientation, payload={})
        _rule(rule_type=RuleType.orientation, payload={"rotation": 90.0})

    def test_mm_must_be_positive(self):
        with pytest.raises(ValueError):
            _rule(payload={"refs_b": ["U1"], "mm": -3.0})


class TestPersistence:
    def test_sidecar_roundtrip(self, tmp_path: Path):
        cs = PlacementRuleSet(
            board_width=100.0,
            board_height=80.0,
            rules=[
                _rule(),
                _rule(
                    rule_id="r2",
                    rule_type=RuleType.approach,
                    refs=["C4"],
                    payload={"refs_b": ["U3"], "mm": 5.0},
                    source=RuleSource.inferred,
                    rationale="decoupling cap near regulator",
                ),
            ],
        )
        path = tmp_path / "constraints.json"
        cs.save(path)
        loaded = PlacementRuleSet.load(path)
        assert loaded.board_width == 100.0
        assert len(loaded.rules) == 2
        assert loaded.rules[1].source == RuleSource.inferred
        assert loaded.rules[0] == cs.rules[0]

    def test_unknown_schema_version_rejected(self, tmp_path: Path):
        path = tmp_path / "constraints.json"
        path.write_text('{"schema_version": 99, "board_width": 1, "board_height": 1, "rules": []}')
        with pytest.raises(ValueError, match="schema"):
            PlacementRuleSet.load(path)


class TestEnforcement:
    POS = {"U1": (10.0, 10.0, 0.0), "U3": (80.0, 60.0, 0.0)}

    def test_avoid_satisfied_zero_penalty(self):
        cs = PlacementRuleSet(100.0, 80.0, [_rule()])
        assert constraint_penalty(cs, self.POS) == 0.0

    def test_avoid_violated_positive_penalty(self):
        cs = PlacementRuleSet(100.0, 80.0, [_rule()])
        pos = {"U1": (10.0, 10.0, 0.0), "U3": (12.0, 10.0, 0.0)}  # 2mm apart
        p = constraint_penalty(cs, pos)
        assert p == pytest.approx((25.0 - 2.0) ** 2)

    def test_approach_violated_when_too_far(self):
        cs = PlacementRuleSet(
            100.0, 80.0,
            [_rule(rule_type=RuleType.approach, refs=["C4"],
                   payload={"refs_b": ["U3"], "mm": 5.0})],
        )
        far = {"C4": (10.0, 10.0, 0.0), "U3": (80.0, 60.0, 0.0)}
        near = {"C4": (40.0, 60.0, 0.0), "U3": (42.0, 60.0, 0.0)}
        assert constraint_penalty(cs, far) > 0.0
        assert constraint_penalty(cs, near) == 0.0

    def test_edge_affinity_penalty_and_snap(self):
        cs = PlacementRuleSet(
            100.0, 80.0,
            [_rule(rule_type=RuleType.edge_affinity, refs=["J1"],
                   payload={"edge": "bottom", "mm": 5.0})],
        )
        pos = {"J1": (50.0, 40.0, 0.0)}
        assert constraint_penalty(cs, pos) > 0.0
        snapped = apply_initial_constraints(cs, pos)
        assert 0.0 <= snapped["J1"][1] <= 5.0  # within 5mm of bottom edge
        assert constraint_penalty(cs, snapped) == 0.0

    def test_region_snap(self):
        cs = PlacementRuleSet(
            100.0, 80.0,
            [_rule(rule_type=RuleType.region, refs=["U2"],
                   payload={"region": [0.0, 0.0, 50.0, 40.0], "name": "analog"})],
        )
        snapped = apply_initial_constraints(cs, {"U2": (90.0, 70.0, 0.0)})
        x, y, _ = snapped["U2"]
        assert 0.0 <= x <= 50.0 and 0.0 <= y <= 40.0

    def test_orientation_penalty(self):
        cs = PlacementRuleSet(
            100.0, 80.0,
            [_rule(rule_type=RuleType.orientation, refs=["LED1"],
                   payload={"rotation": 90.0})],
        )
        wrong = {"LED1": (10.0, 10.0, 0.0)}
        right = {"LED1": (10.0, 10.0, 90.0)}
        assert constraint_penalty(cs, wrong) > 0.0
        assert constraint_penalty(cs, right) == 0.0

    def test_missing_ref_no_crash(self):
        cs = PlacementRuleSet(100.0, 80.0, [_rule()])
        assert constraint_penalty(cs, {"U1": (1.0, 1.0, 0.0)}) == 0.0


class TestGate:
    def test_validate_reports_violations_with_rule_ids(self):
        cs = PlacementRuleSet(100.0, 80.0, [_rule()])
        pos = {"U1": (10.0, 10.0, 0.0), "U3": (12.0, 10.0, 0.0)}
        violations = validate_constraints(cs, pos)
        assert violations and isinstance(violations[0], ConstraintViolation)
        assert violations[0].rule_id == "r1"
        assert "U3" in violations[0].ref
        assert violations[0].actual_mm < 25.0

    def test_validate_clean_returns_empty(self):
        cs = PlacementRuleSet(100.0, 80.0, [_rule()])
        pos = {"U1": (10.0, 10.0, 0.0), "U3": (80.0, 60.0, 0.0)}
        assert validate_constraints(cs, pos) == []


class TestEngineIntegration:
    """End-to-end: rules steer the SA optimizer and the gate reports."""

    def test_avoid_rule_steer_and_gate(self):
        from volta.generation.intent import ComponentSpec
        from volta.placement.engine import HybridPlacementEngine, PlacementRequest
        import math

        comps = [
            ComponentSpec(library_id="Device:R", reference="R1", value="10k",
                          position={"x": 0, "y": 0, "angle": 0.0}, footprint="R_0603"),
            ComponentSpec(library_id="Device:R", reference="R2", value="10k",
                          position={"x": 0, "y": 0, "angle": 0.0}, footprint="R_0603"),
        ]
        rules = [{
            "rule_id": "keep-apart", "rule_type": "avoid",
            "source": "explicit", "refs": ["R1"],
            "payload": {"refs_b": ["R2"], "mm": 30.0},
            "rationale": "EMI separation",
        }]
        req = PlacementRequest(
            components=comps, board_width=100.0, board_height=80.0,
            use_ml=False, refine_sa=True, placement_rules=rules,
            fixed_positions={"R1": (20.0, 40.0, 0.0)},
        )
        out = HybridPlacementEngine().place(req)
        d = math.hypot(
            out.positions["R1"][0] - out.positions["R2"][0],
            out.positions["R1"][1] - out.positions["R2"][1],
        )
        assert d >= 30.0, f"SA must honor avoid rule (got {d:.1f}mm)"
        assert not [v for v in out.violations if v.get("type") == "placement_rule"]

    def test_gate_reports_violation_when_rule_broken(self):
        from volta.generation.intent import ComponentSpec
        from volta.placement.engine import HybridPlacementEngine, PlacementRequest

        comps = [
            ComponentSpec(library_id="Device:R", reference="R1", value="10k",
                          position={"x": 0, "y": 0, "angle": 0.0}, footprint="R_0603"),
            ComponentSpec(library_id="Device:R", reference="R2", value="10k",
                          position={"x": 0, "y": 0, "angle": 0.0}, footprint="R_0603"),
        ]
        rules = [{
            "rule_id": "keep-apart", "rule_type": "avoid",
            "source": "explicit", "refs": ["R1"],
            "payload": {"refs_b": ["R2"], "mm": 30.0},
            "rationale": "EMI separation",
        }]
        req = PlacementRequest(
            components=comps, board_width=100.0, board_height=80.0,
            use_ml=False, refine_sa=False, placement_rules=rules,
        )
        out = HybridPlacementEngine().place(req)  # rule-based path: no SA
        rule_violations = [
            v for v in out.violations if v.get("type") == "placement_rule"
        ]
        assert rule_violations, "gate must flag the broken avoid rule"
        assert rule_violations[0]["rule_id"] == "keep-apart"
