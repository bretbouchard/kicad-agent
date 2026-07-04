"""Phase 157: Floor plan specification + contextual placement rules.

The PlacementRule model captures implicit PCB design knowledge — the
"stupid requirements" that experienced designers carry in their heads
and that cause board respins when violated (Bead kicad-agent-24).

Rule types:
  edge_affinity: component must be on/near the board edge
  avoid: two components must not be near each other (EMI, noise)
  approach: two components must be near each other (decoupling)
  orientation: component must face a specific direction
  region: component must be in a named zone
  alignment: group of components must be aligned

Each rule carries a rationale field — the "why" — that becomes training
data for the AI (Phase 159).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class RuleType(str, Enum):
    """Contextual placement rule types."""
    EDGE_AFFINITY = "edge_affinity"
    AVOID = "avoid"
    APPROACH = "approach"
    ORIENTATION = "orientation"
    REGION = "region"
    ALIGNMENT = "alignment"


class RulePriority(str, Enum):
    """Rule enforcement priority."""
    HARD = "hard"   # Gate-enforced (fail-closed)
    SOFT = "soft"   # SA objective penalty only


@dataclass(frozen=True)
class PlacementRule:
    """A contextual placement rule for a component.

    Attributes:
        subject_ref: Component reference(s) the rule applies to.
        rule_type: Type of rule (edge_affinity, avoid, approach, etc.).
        target: What to relate to ("edge", "corner:TL", "U1", zone name).
        min_mm: Minimum distance (for avoid).
        max_mm: Maximum distance (for approach, edge_affinity).
        orientation_deg: Required rotation (for orientation).
        edge_sides: Which board edges are valid (for edge_affinity).
        rationale: WHY this rule exists — training data for AI.
        priority: "hard" (gate-enforced) or "soft" (SA penalty).
    """

    subject_ref: str
    rule_type: RuleType
    target: str
    min_mm: float | None = None
    max_mm: float | None = None
    orientation_deg: float | None = None
    edge_sides: tuple[str, ...] = ()
    rationale: str = ""
    priority: RulePriority = RulePriority.SOFT


@dataclass(frozen=True)
class ZoneSpec:
    """A functional zone on the board.

    Attributes:
        name: Zone name (e.g. "power", "analog", "digital").
        x_range: (x_min, x_max) in mm.
        y_range: (y_min, y_max) in mm.
        fill_order: Component fill direction ("top-to-bottom", "left-to-right").
        priority_refs: Components that MUST be in this zone.
    """

    name: str
    x_range: tuple[float, float]
    y_range: tuple[float, float]
    fill_order: str = "top-to-bottom"
    priority_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class KeepoutSpec:
    """A keepout zone where components/traces can't go.

    Attributes:
        bounds: (x1, y1, x2, y2) in mm.
        name: Human-readable name.
        zone_type: "copper", "via", "track", or "all".
    """

    bounds: tuple[float, float, float, float]
    name: str = ""
    zone_type: str = "all"


@dataclass
class FloorPlanSpec:
    """Complete floor plan specification.

    Loaded from a .floorplan.yaml file. Contains zones, keepouts,
    pre-placed anchors, and contextual placement rules.
    """

    board_width_mm: float = 0.0
    board_height_mm: float = 0.0
    layers: list[str] = field(default_factory=lambda: ["F.Cu", "B.Cu"])
    edge_clearance_mm: float = 3.0
    zones: list[ZoneSpec] = field(default_factory=list)
    keepouts: list[KeepoutSpec] = field(default_factory=list)
    pre_placed: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    placement_rules: list[PlacementRule] = field(default_factory=list)
    ground_pour_net: str | None = None
    source_file: str = ""


def load_floor_plan(yaml_path: Path | str) -> FloorPlanSpec:
    """Load a floor plan specification from a YAML file.

    Args:
        yaml_path: Path to the .floorplan.yaml file.

    Returns:
        FloorPlanSpec with all zones, keepouts, and placement rules.
    """
    yaml_path = Path(yaml_path)
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

    spec = FloorPlanSpec(source_file=str(yaml_path))

    # Board section.
    board = raw.get("board", {})
    spec.board_width_mm = float(board.get("width_mm", 0))
    spec.board_height_mm = float(board.get("height_mm", 0))
    spec.layers = board.get("layers", ["F.Cu", "B.Cu"])
    spec.edge_clearance_mm = float(board.get("edge_clearance_mm", 3.0))

    # Zones.
    for z in raw.get("zones", []):
        spec.zones.append(ZoneSpec(
            name=z["name"],
            x_range=tuple(z.get("x_range", [0, 0])),
            y_range=tuple(z.get("y_range", [0, 0])),
            fill_order=z.get("fill_order", "top-to-bottom"),
            priority_refs=tuple(z.get("priority_refs", [])),
        ))

    # Keepouts.
    for k in raw.get("keepouts", []):
        spec.keepouts.append(KeepoutSpec(
            bounds=tuple(k[:4]),
            name=k[4] if len(k) > 4 else "",
            zone_type=k[5] if len(k) > 5 else "all",
        ))

    # Pre-placed anchors.
    for ref, coords in raw.get("pre_placed", {}).items():
        spec.pre_placed[ref] = tuple(coords)

    # Contextual placement rules (Bead kicad-agent-24).
    for r in raw.get("placement_rules", []):
        subject = r["subject_ref"]
        # Handle list subjects (for alignment rules).
        if isinstance(subject, list):
            subject = ",".join(subject)

        rule = PlacementRule(
            subject_ref=subject,
            rule_type=RuleType(r["rule_type"]),
            target=r.get("target", ""),
            min_mm=float(r["min_mm"]) if "min_mm" in r else None,
            max_mm=float(r["max_mm"]) if "max_mm" in r else None,
            orientation_deg=float(r["orientation_deg"]) if "orientation_deg" in r else None,
            edge_sides=tuple(r.get("edge_sides", ())),
            rationale=r.get("rationale", ""),
            priority=RulePriority(r.get("priority", "soft")),
        )
        spec.placement_rules.append(rule)

    # Ground pour.
    gp = raw.get("ground_pour", {})
    if gp:
        spec.ground_pour_net = gp.get("net", "GND")

    return spec
