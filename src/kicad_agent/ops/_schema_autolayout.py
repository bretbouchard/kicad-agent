"""Pydantic schemas for autolayout ops (Phase 108 Plan 02, D-04).

Three independently-callable ops:
  - PlaceComponentsSchOp  : Sugiyama placement → raw S-expr (at X Y) edits
  - RouteWiresSchOp       : Phase 38 wire_router reuse → raw S-expr (wire ...) inserts
  - ApplyLabelsSchOp      : Phase 38 net_namer reuse → raw S-expr (label ...) inserts

Council Gate 1 fixes honored:
  - HIGH-1: TargetFile imported from kicad_agent.ops.schema (NOT _schema_common)
  - HIGH-4: mutation dicts in handlers use "op" discriminator (handlers module)
  - D-02:  subcircuit_split defaults True (functional-group split per CONTEXT.md)

All writes go through SchematicRawWriter + atomic_write (P101-INV-01).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# HIGH-1 fix (Council Gate 1): TargetFile lives in kicad_agent.ops.schema.
# Cross-confirmed: 8 existing schemas (_schema_component.py, _schema_footprint.py,
# _schema_net.py, _schema_create.py, _schema_reference.py, etc.) all import
# TargetFile from this exact location. _schema_common.py does NOT exist.
from kicad_agent.ops.schema import TargetFile


class PlaceComponentsSchOp(BaseModel):
    """Sugiyama-based component placement on a KiCad 10 schematic.

    Computes (x, y) coordinates via SugiyamaLayout from CircuitTopology,
    writes new positions via SchematicRawWriter (P101-INV-01: never
    kiutils.to_file()).

    Attributes:
        op_type: Discriminator literal "place_components_sch".
        target_file: Relative path to .kicad_sch (H-01 validated).
        subcircuit_split: When True (default, D-02), split by
            SubcircuitDetector groups; each group gets independent
            Sugiyama pass with X-offset between groups.
        layer_spacing_mm: Vertical spacing between layers (default 25.4).
        node_spacing_mm: Horizontal spacing between nodes (default 12.7).
        dry_run: Return computed positions without writing files.
    """

    op_type: Literal["place_components_sch"] = "place_components_sch"
    target_file: TargetFile
    subcircuit_split: bool = Field(
        default=True,
        description="D-02: split by functional group via SubcircuitDetector.",
    )
    layer_spacing_mm: float = Field(default=25.4, ge=2.54, le=127.0)
    node_spacing_mm: float = Field(default=12.7, ge=2.54, le=127.0)
    dry_run: bool = Field(
        default=False,
        description="Return positions without writing files.",
    )


class RouteWiresSchOp(BaseModel):
    """Collision-aware wire routing between placed components.

    Reuses Phase 38 wire_router.generate_fixes. Generates L-shaped
    wires between pins; skips wires >max_wire_length_mm (labels from
    apply_labels_sch provide connectivity for long runs per Phase 38
    finding: net labels are primary connection mechanism in KiCad 10).

    Attributes:
        op_type: Discriminator literal "route_wires_sch".
        target_file: Relative path to .kicad_sch.
        max_wire_length_mm: Skip wires longer than this (default 40mm,
            per Phase 38 CONTEXT §Pain Point 2).
        collision_zones: Optional list of (x_min, x_max, reason) tuples
            to avoid. Auto-detected if empty.
        dry_run: Return computed wires without writing.
    """

    op_type: Literal["route_wires_sch"] = "route_wires_sch"
    target_file: TargetFile
    max_wire_length_mm: float = Field(default=40.0, ge=5.0, le=200.0)
    collision_zones: list[tuple[float, float, str]] = Field(default_factory=list)
    dry_run: bool = Field(default=False)


class ApplyLabelsSchOp(BaseModel):
    """Net label generation at pin body positions.

    Per Phase 38 finding: net labels are primary connection mechanism
    in KiCad 10 (wires unreliable for programmatic connections).
    Generates one label per net at pin body_position using net_namer
    canonical names.

    Attributes:
        op_type: Discriminator literal "apply_labels_sch".
        target_file: Relative path to .kicad_sch.
        label_size_mm: Font size in mm (default 1.27 — KiCad default).
        global_labels: Net names that should be global (cross-sheet).
            Default: nets in topology.power_nets + nets starting with
            "+", "-", or matching interface pattern.
        dry_run: Return computed labels without writing.
    """

    op_type: Literal["apply_labels_sch"] = "apply_labels_sch"
    target_file: TargetFile
    label_size_mm: float = Field(default=1.27, ge=0.5, le=5.0)
    global_labels: list[str] = Field(default_factory=list)
    dry_run: bool = Field(default=False)
