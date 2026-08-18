"""Contextual placement constraints (volta-24).

Experienced designers carry implicit placement intent that schematics do
not capture: "the connector must sit on the board edge", "keep the
switching regulator away from the analog section", "the decoupling cap
goes within 5mm of its IC". This module gives that intent a first-class
model, persists it as a project sidecar, and enforces it at three
touchpoints:

1. ``apply_initial_constraints`` — hard snap for region/edge rules
   before optimization.
2. ``constraint_penalty`` — differentiable-ish penalty terms for the
   SA objective (avoid / approach / orientation / edge / region).
3. ``validate_constraints`` — post-placement gate producing structured
   violations for the validation pipeline.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

Position = dict[str, tuple[float, float, float]]  # ref -> (x, y, rot)

SCHEMA_VERSION = 1


class RuleType(str, Enum):
    edge_affinity = "edge_affinity"   # component within mm of a board edge
    region = "region"                 # component inside a named bbox
    avoid = "avoid"                   # pairwise min distance (mm)
    approach = "approach"             # pairwise max distance (mm)
    orientation = "orientation"       # component rotation (degrees)


class RuleSource(str, Enum):
    explicit = "explicit"   # user-authored
    inferred = "inferred"   # derived from netlist (e.g. decoupling pairs)
    learned = "learned"     # model suggestion accepted by user
    imported = "imported"   # from another project / rule set


_EDGES = {"top", "bottom", "left", "right"}


@dataclass(frozen=True)
class PlacementRule:
    """One placement intent, carried with its provenance and rationale.

    The rationale is surfaced to the LLM and the UI — placement rules are
    design *conversation*, not just geometry.
    """

    rule_id: str
    rule_type: RuleType
    source: RuleSource
    refs: tuple[str, ...]
    payload: dict
    rationale: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "refs", tuple(self.refs))
        p = self.payload
        if self.rule_type in (RuleType.avoid, RuleType.approach):
            if "refs_b" not in p or "mm" not in p:
                raise ValueError(f"{self.rule_type.value}: requires refs_b and mm")
            if float(p["mm"]) <= 0:
                raise ValueError(f"{self.rule_type.value}: mm must be positive")
        elif self.rule_type is RuleType.edge_affinity:
            if p.get("edge") not in _EDGES:
                raise ValueError(f"edge_affinity: edge must be one of {sorted(_EDGES)}")
            if float(p.get("mm", 5.0)) <= 0:
                raise ValueError("edge_affinity: mm must be positive")
        elif self.rule_type is RuleType.region:
            region = p.get("region")
            if (
                not isinstance(region, (list, tuple))
                or len(region) != 4
            ):
                raise ValueError("region: requires [x1, y1, x2, y2]")
            x1, y1, x2, y2 = (float(v) for v in region)
            if x2 <= x1 or y2 <= y1:
                raise ValueError("region: x2/y2 must exceed x1/y1")
        elif self.rule_type is RuleType.orientation:
            if "rotation" not in p:
                raise ValueError("orientation: requires rotation (degrees)")


@dataclass(frozen=True)
class PlacementRuleSet:
    """All placement rules for a board plus its dimensions."""

    board_width: float
    board_height: float
    rules: tuple[PlacementRule, ...] = field(default_factory=tuple)

    # -- persistence ------------------------------------------------------

    def save(self, path: Path) -> None:
        data = {
            "schema_version": SCHEMA_VERSION,
            "board_width": self.board_width,
            "board_height": self.board_height,
            "rules": [
                {
                    "rule_id": r.rule_id,
                    "rule_type": r.rule_type.value,
                    "source": r.source.value,
                    "refs": list(r.refs),
                    "payload": r.payload,
                    "rationale": r.rationale,
                }
                for r in self.rules
            ],
        }
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "PlacementRuleSet":
        data = json.loads(path.read_text(encoding="utf-8"))
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"constraints schema version {version!r} unsupported "
                f"(expected {SCHEMA_VERSION})"
            )
        rules = tuple(
            PlacementRule(
                rule_id=r["rule_id"],
                rule_type=RuleType(r["rule_type"]),
                source=RuleSource(r["source"]),
                refs=tuple(r["refs"]),
                payload=r["payload"],
                rationale=r.get("rationale", ""),
            )
            for r in data["rules"]
        )
        return cls(
            board_width=float(data["board_width"]),
            board_height=float(data["board_height"]),
            rules=rules,
        )


@dataclass(frozen=True)
class ConstraintViolation:
    """One failed rule at gate time — structured for the pipeline/UI."""

    rule_id: str
    rule_type: RuleType
    ref: str
    description: str
    actual_mm: float | None = None
    required_mm: float | None = None


# -- helpers ---------------------------------------------------------------


def _distance(
    positions: Position, a: str, b: str
) -> float | None:
    pa, pb = positions.get(a), positions.get(b)
    if pa is None or pb is None:
        return None
    return math.hypot(pa[0] - pb[0], pa[1] - pb[1])


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# -- touchpoint 1: initial hard snap ----------------------------------------


def apply_initial_constraints(cs: PlacementRuleSet, positions: Position) -> Position:
    """Snap positions to satisfy hard-assignable rules (region, edge).

    Returns a new dict; inputs are not mutated. Rules that are purely
    penalty-shaped (avoid/approach/orientation) are left to the SA stage.
    """
    out = dict(positions)
    for rule in cs.rules:
        for ref in rule.refs:
            if ref not in out:
                continue
            x, y, rot = out[ref]
            if rule.rule_type is RuleType.region:
                x1, y1, x2, y2 = (float(v) for v in rule.payload["region"])
                out[ref] = (_clamp(x, x1, x2), _clamp(y, y1, y2), rot)
            elif rule.rule_type is RuleType.edge_affinity:
                mm = float(rule.payload.get("mm", 5.0))
                edge = rule.payload["edge"]
                if edge == "bottom":
                    out[ref] = (x, _clamp(y, 0.0, mm), rot)
                elif edge == "top":
                    out[ref] = (x, _clamp(y, cs.board_height - mm, cs.board_height), rot)
                elif edge == "left":
                    out[ref] = (_clamp(x, 0.0, mm), y, rot)
                elif edge == "right":
                    out[ref] = (
                        _clamp(x, cs.board_width - mm, cs.board_width), y, rot,
                    )
    return out


# -- touchpoint 2: SA objective penalty -------------------------------------


def constraint_penalty(cs: PlacementRuleSet, positions: Position) -> float:
    """Sum of squared constraint shortfalls (mm^2) — add to SA objective.

    avoid:    max(0, mm - d)^2      (too close hurts)
    approach: max(0, d - mm)^2      (too far hurts)
    edge:     distance beyond the edge band, squared
    region:   distance outside the bbox, squared (per axis)
    orientation: squared degree mismatch
    """
    total = 0.0
    for rule in cs.rules:
        p = rule.payload
        if rule.rule_type in (RuleType.avoid, RuleType.approach):
            mm = float(p["mm"])
            for a in rule.refs:
                for b in p["refs_b"]:
                    d = _distance(positions, a, b)
                    if d is None:
                        continue
                    if rule.rule_type is RuleType.avoid:
                        total += max(0.0, mm - d) ** 2
                    else:
                        total += max(0.0, d - mm) ** 2
        elif rule.rule_type is RuleType.edge_affinity:
            mm = float(p.get("mm", 5.0))
            for ref in rule.refs:
                pos = positions.get(ref)
                if pos is None:
                    continue
                x, y, _ = pos
                edge = p["edge"]
                if edge == "bottom":
                    total += max(0.0, y - mm) ** 2
                elif edge == "top":
                    total += max(0.0, (cs.board_height - mm) - y) ** 2
                elif edge == "left":
                    total += max(0.0, x - mm) ** 2
                elif edge == "right":
                    total += max(0.0, (cs.board_width - mm) - x) ** 2
        elif rule.rule_type is RuleType.region:
            x1, y1, x2, y2 = (float(v) for v in p["region"])
            for ref in rule.refs:
                pos = positions.get(ref)
                if pos is None:
                    continue
                x, y, _ = pos
                total += max(0.0, x1 - x, x - x2, 0.0) ** 2
                total += max(0.0, y1 - y, y - y2, 0.0) ** 2
        elif rule.rule_type is RuleType.orientation:
            want = float(p["rotation"])
            for ref in rule.refs:
                pos = positions.get(ref)
                if pos is None:
                    continue
                diff = abs((pos[2] - want + 180.0) % 360.0 - 180.0)
                total += diff ** 2
    return total


# -- touchpoint 3: post-placement gate --------------------------------------


def validate_constraints(
    cs: PlacementRuleSet, positions: Position
) -> list[ConstraintViolation]:
    """Report every violated rule with concrete numbers."""
    violations: list[ConstraintViolation] = []
    for rule in cs.rules:
        p = rule.payload
        if rule.rule_type in (RuleType.avoid, RuleType.approach):
            mm = float(p["mm"])
            for a in rule.refs:
                for b in p["refs_b"]:
                    d = _distance(positions, a, b)
                    if d is None:
                        continue
                    bad = d < mm if rule.rule_type is RuleType.avoid else d > mm
                    if bad:
                        word = "closer" if rule.rule_type is RuleType.avoid else "further"
                        violations.append(
                            ConstraintViolation(
                                rule_id=rule.rule_id,
                                rule_type=rule.rule_type,
                                ref=a,
                                description=(
                                    f"{a} is {d:.1f}mm from {b} — rule requires "
                                    f"{word} than {mm:.1f}mm"
                                ),
                                actual_mm=d,
                                required_mm=mm,
                            )
                        )
        elif rule.rule_type is RuleType.edge_affinity:
            mm = float(p.get("mm", 5.0))
            for ref in rule.refs:
                pos = positions.get(ref)
                if pos is None:
                    continue
                x, y, _ = pos
                edge = p["edge"]
                dist = {
                    "bottom": y,
                    "top": cs.board_height - y,
                    "left": x,
                    "right": cs.board_width - x,
                }[edge]
                if dist > mm:
                    violations.append(
                        ConstraintViolation(
                            rule_id=rule.rule_id,
                            rule_type=rule.rule_type,
                            ref=ref,
                            description=(
                                f"{ref} is {dist:.1f}mm from the {edge} edge "
                                f"— rule allows {mm:.1f}mm"
                            ),
                            actual_mm=dist,
                            required_mm=mm,
                        )
                    )
        elif rule.rule_type is RuleType.region:
            x1, y1, x2, y2 = (float(v) for v in p["region"])
            name = p.get("name", "region")
            for ref in rule.refs:
                pos = positions.get(ref)
                if pos is None:
                    continue
                x, y, _ = pos
                if not (x1 <= x <= x2 and y1 <= y <= y2):
                    violations.append(
                        ConstraintViolation(
                            rule_id=rule.rule_id,
                            rule_type=rule.rule_type,
                            ref=ref,
                            description=(
                                f"{ref} at ({x:.1f}, {y:.1f}) is outside "
                                f"region '{name}'"
                            ),
                        )
                    )
        elif rule.rule_type is RuleType.orientation:
            want = float(p["rotation"])
            for ref in rule.refs:
                pos = positions.get(ref)
                if pos is None:
                    continue
                diff = abs((pos[2] - want + 180.0) % 360.0 - 180.0)
                if diff > 1e-6:
                    violations.append(
                        ConstraintViolation(
                            rule_id=rule.rule_id,
                            rule_type=rule.rule_type,
                            ref=ref,
                            description=(
                                f"{ref} rotated {pos[2]:.0f}° — rule requires "
                                f"{want:.0f}°"
                            ),
                        )
                    )
    return violations
