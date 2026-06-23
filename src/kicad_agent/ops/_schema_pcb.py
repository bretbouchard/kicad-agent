"""PCB-specific operation schemas -- net class, design rule, copper zone, board outline, auto-route."""

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from pydantic import BaseModel, Field, field_validator, model_validator

from kicad_agent.ops.schema import (
    TargetFile,
    _validate_sexpr_safe_string,
)


class AddNetClassOp(BaseModel):
    """Add a net class with track/via/clearance dimensions.

    Attributes:
        op_type: Discriminator literal ``"add_net_class"``.
        target_file: Relative path to the .kicad_dru file.
        name: Net class name.
        clearance: Clearance in mm (must be > 0).
        track_width: Track width in mm (must be > 0).
        via_diameter: Via diameter in mm (must be > 0).
        via_drill: Via drill in mm (must be > 0).
    """

    op_type: Literal["add_net_class"] = "add_net_class"
    target_file: TargetFile
    name: str = Field(
        min_length=1,
        max_length=64,
        description="Net class name",
    )
    clearance: float = Field(gt=0, description="Clearance in mm")
    track_width: float = Field(gt=0, description="Track width in mm")
    via_diameter: float = Field(gt=0, description="Via diameter in mm")
    via_drill: float = Field(gt=0, description="Via drill in mm")


class AddDesignRuleOp(BaseModel):
    """Add a custom DRC rule to .kicad_dru.

    Attributes:
        op_type: Discriminator literal ``"add_design_rule"``.
        target_file: Relative path to the .kicad_dru file.
        name: Rule name.
        constraint_type: Constraint type (e.g. ``"clearance"``, ``"width"``).
        constraint_values: Key-value constraint parameters.
        condition: KiCad condition expression string.
    """

    op_type: Literal["add_design_rule"] = "add_design_rule"
    target_file: TargetFile
    name: str = Field(
        min_length=1,
        max_length=128,
        description="Rule name",
    )
    constraint_type: str = Field(
        min_length=1,
        max_length=64,
        description="Constraint type (e.g. 'clearance', 'width')",
    )
    constraint_values: dict[str, str] = Field(default_factory=dict)
    condition: str = Field(default="", max_length=512)

    @field_validator("condition")
    @classmethod
    def _validate_condition_sexpr(cls, v: str) -> str:
        return _validate_sexpr_safe_string(v)


class AddCopperZoneOp(BaseModel):
    """Add a copper zone/ground pour to a PCB.

    Attributes:
        op_type: Discriminator literal ``"add_copper_zone"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        net_name: Net name for the zone (e.g. "GND").
        layer: Copper layer (e.g. "F.Cu", "B.Cu").
        clearance: Zone clearance in mm.
        min_width: Minimum fill width in mm.
        priority: Zone priority (higher = filled first).
    """

    op_type: Literal["add_copper_zone"] = "add_copper_zone"
    target_file: TargetFile
    net_name: str = Field(min_length=1, max_length=64, description="Net name for the zone")
    layer: str = Field(
        default="F.Cu", max_length=32, pattern=r"^(?:[FB]\.Cu|In[1-9]\d*\.Cu)$",
        description="Copper layer",
    )
    clearance: float = Field(default=0.5, gt=0, description="Clearance in mm")
    min_width: float = Field(default=0.25, gt=0, description="Minimum fill width in mm")
    priority: int = Field(default=0, ge=0, description="Zone priority")


class SetBoardOutlineOp(BaseModel):
    """Define PCB board shape as a rectangle on Edge.Cuts.

    Attributes:
        op_type: Discriminator literal ``"set_board_outline"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        width: Board width in mm.
        height: Board height in mm.
    """

    op_type: Literal["set_board_outline"] = "set_board_outline"
    target_file: TargetFile
    width: float = Field(gt=0, le=1000, description="Board width in mm")
    height: float = Field(gt=0, le=1000, description="Board height in mm")


class AssignNetClassOp(BaseModel):
    """Assign a net class to a specific net in the PCB.

    Attributes:
        op_type: Discriminator literal ``"assign_net_class"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        net_name: Name of the net to assign.
        net_class_name: Name of the net class to assign.
    """

    op_type: Literal["assign_net_class"] = "assign_net_class"
    target_file: TargetFile
    net_name: str = Field(min_length=1, max_length=64, description="Net name")
    net_class_name: str = Field(min_length=1, max_length=64, description="Net class name")


class AutoRouteOp(BaseModel):
    """Auto-route nets on a PCB using A* pathfinding.

    Supports single-layer and multi-layer routing with optional impedance
    control and length matching for differential pairs.

    Attributes:
        op_type: Discriminator literal ``"auto_route"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        nets: Optional list of specific net names to route. Routes all nets if empty.
        layer: Copper layer for single-layer routed traces. Default "F.Cu".
        layers: Target copper layers for multi-layer routing. Empty list uses
            the ``layer`` field for backward-compatible single-layer mode.
        impedance_target: Target impedance in ohms (e.g. 50.0). None = skip.
        length_match_pairs: Net pairs for sawtooth length matching as
            ``[(net_a, net_b, tolerance_mm), ...]``. None = skip.
    """

    op_type: Literal["auto_route"] = "auto_route"
    target_file: TargetFile
    nets: list[str] = Field(default_factory=list, description="Net names to route (empty = all)")
    layer: str = Field(
        default="F.Cu", pattern=r"^(?:[FB]\.Cu|In[1-9]\d*\.Cu)$",
        description="Target copper layer (single-layer mode)",
    )
    layers: list[str] = Field(
        default_factory=list,
        description="Target copper layers for multi-layer routing. "
                    "Empty = use 'layer' field (single-layer mode).",
    )
    impedance_target: Optional[float] = Field(
        default=None, gt=0, le=200,
        description="Target impedance in ohms (e.g., 50.0 for controlled impedance). "
                    "None = no impedance calculation.",
    )
    length_match_pairs: Optional[list[tuple[str, str, float]]] = Field(
        default=None,
        description="Net pairs for length matching: "
                    "[(net_a, net_b, tolerance_mm), ...]. "
                    "Sawtooth pattern applied to shorter net. None = no matching.",
    )
    strategy: str = Field(
        default="auto",
        pattern=r"^(?:auto|freerouting|single_pass|multi_pass)$",
        description="Routing strategy: 'auto' (use Freerouting if available, else A*), "
                    "'freerouting' (Freerouting Java router for dense boards), "
                    "'single_pass' (A* single pass), "
                    "'multi_pass' (A* 3-pass with rip-up). "
                    "Council C-03: max 3 passes for A*, Freerouting has its own pass control.",
    )

    @field_validator("layers")
    @classmethod
    def _validate_layer_names(cls, v: list[str]) -> list[str]:
        """Validate that all layer names match KiCad copper layer naming."""
        pattern = r"^(?:[FB]\.Cu|In[1-9]\d*\.Cu)$"
        for layer_name in v:
            if not re.match(pattern, layer_name):
                raise ValueError(f"Invalid layer name: {layer_name}")
        return v


class ModifyNetClassOp(BaseModel):
    """Modify an existing net class in .kicad_dru.

    Only specified (non-None) fields are updated; None means keep existing value.

    Attributes:
        op_type: Discriminator literal ``"modify_net_class"``.
        target_file: Relative path to the .kicad_dru file.
        name: Net class name to modify.
        clearance: New clearance in mm (optional, keep existing if None).
        track_width: New track width in mm (optional, keep existing if None).
        via_diameter: New via diameter in mm (optional, keep existing if None).
        via_drill: New via drill in mm (optional, keep existing if None).
        uvia_diameter: New micro-via diameter in mm (optional).
        uvia_drill: New micro-via drill in mm (optional).
        diff_pair_width: New diff pair width in mm (optional).
        diff_pair_gap: New diff pair gap in mm (optional).
    """

    op_type: Literal["modify_net_class"] = "modify_net_class"
    target_file: TargetFile
    name: str = Field(min_length=1, max_length=64, description="Net class name to modify")
    clearance: Optional[float] = Field(default=None, gt=0, description="Clearance in mm")
    track_width: Optional[float] = Field(default=None, gt=0, description="Track width in mm")
    via_diameter: Optional[float] = Field(default=None, gt=0, description="Via diameter in mm")
    via_drill: Optional[float] = Field(default=None, gt=0, description="Via drill in mm")
    uvia_diameter: Optional[float] = Field(default=None, gt=0, description="Micro-via diameter in mm")
    uvia_drill: Optional[float] = Field(default=None, gt=0, description="Micro-via drill in mm")
    diff_pair_width: Optional[float] = Field(default=None, gt=0, description="Diff pair width in mm")
    diff_pair_gap: Optional[float] = Field(default=None, gt=0, description="Diff pair gap in mm")


class RemoveNetClassOp(BaseModel):
    """Remove a net class from .kicad_dru.

    Attributes:
        op_type: Discriminator literal ``"remove_net_class"``.
        target_file: Relative path to the .kicad_dru file.
        name: Net class name to remove.
    """

    op_type: Literal["remove_net_class"] = "remove_net_class"
    target_file: TargetFile
    name: str = Field(min_length=1, max_length=64, description="Net class name to remove")


class ListNetClassesOp(BaseModel):
    """List all net classes in a .kicad_dru file.

    Read-only operation -- returns all net classes without modifying the file.

    Attributes:
        op_type: Discriminator literal ``"list_net_classes"``.
        target_file: Relative path to the .kicad_dru file.
    """

    op_type: Literal["list_net_classes"] = "list_net_classes"
    target_file: TargetFile


class ModifyDesignRuleOp(BaseModel):
    """Modify an existing custom DRC rule in .kicad_dru.

    Only specified (non-None) fields are updated.

    Attributes:
        op_type: Discriminator literal ``"modify_design_rule"``.
        target_file: Relative path to the .kicad_dru file.
        name: Rule name to modify.
        constraint_type: New constraint type (optional).
        constraint_values: New constraint parameters (optional).
        condition: New condition expression (optional).
        layer: New layer restriction (optional).
    """

    op_type: Literal["modify_design_rule"] = "modify_design_rule"
    target_file: TargetFile
    name: str = Field(min_length=1, max_length=128, description="Rule name to modify")
    constraint_type: Optional[str] = Field(default=None, min_length=1, max_length=64)
    constraint_values: Optional[dict[str, str]] = Field(default=None)
    condition: Optional[str] = Field(default=None, max_length=512)
    layer: Optional[str] = Field(default=None, max_length=64)

    @field_validator("condition")
    @classmethod
    def _validate_condition_sexpr(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _validate_sexpr_safe_string(v)


class RemoveDesignRuleOp(BaseModel):
    """Remove a custom DRC rule from .kicad_dru.

    Attributes:
        op_type: Discriminator literal ``"remove_design_rule"``.
        target_file: Relative path to the .kicad_dru file.
        name: Rule name to remove.
    """

    op_type: Literal["remove_design_rule"] = "remove_design_rule"
    target_file: TargetFile
    name: str = Field(min_length=1, max_length=128, description="Rule name to remove")


class ListDesignRulesOp(BaseModel):
    """List all custom DRC rules in a .kicad_dru file.

    Read-only operation -- returns all rules without modifying the file.

    Attributes:
        op_type: Discriminator literal ``"list_design_rules"``.
        target_file: Relative path to the .kicad_dru file.
    """

    op_type: Literal["list_design_rules"] = "list_design_rules"
    target_file: TargetFile


class ModifyProjectSettingsOp(BaseModel):
    """Modify settings in a .kicad_pro project file.

    Deep-merges the updates dict into the existing JSON, preserving unknown keys.

    Attributes:
        op_type: Discriminator literal ``"modify_project_settings"``.
        target_file: Relative path to the .kicad_pro file.
        updates: JSON sections to merge into the project file.
    """

    op_type: Literal["modify_project_settings"] = "modify_project_settings"
    target_file: TargetFile
    updates: dict[str, Any] = Field(
        max_length=50,
        description="JSON sections to merge into the project file (max 50 keys)",
    )


class ModifyCopperZoneOp(BaseModel):
    """Modify an existing copper zone on a PCB.

    Only specified (non-None) fields are updated; None means keep existing value.
    Zone is identified by its UUID (tstamp).

    Attributes:
        op_type: Discriminator literal ``"modify_copper_zone"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        zone_uuid: Zone UUID (tstamp) to identify the zone to modify.
        net_name: New net name (optional).
        layer: New copper layer (optional).
        clearance: New clearance in mm (optional).
        min_width: New minimum fill width in mm (optional).
        priority: New priority (optional).
    """

    op_type: Literal["modify_copper_zone"] = "modify_copper_zone"
    target_file: TargetFile
    zone_uuid: str = Field(min_length=1, max_length=64, description="Zone UUID (tstamp)")
    net_name: Optional[str] = Field(default=None, max_length=64, description="New net name")
    layer: Optional[str] = Field(
        default=None, max_length=32, pattern=r"^(?:[FB]\.Cu|In[1-9]\d*\.Cu)$",
        description="New layer (e.g. F.Cu, B.Cu, In1.Cu)",
    )
    clearance: Optional[float] = Field(default=None, gt=0, description="New clearance in mm")
    min_width: Optional[float] = Field(default=None, gt=0, description="New minimum fill width")
    priority: Optional[int] = Field(default=None, ge=0, description="New priority")


class RemoveCopperZoneOp(BaseModel):
    """Remove a copper zone from a PCB.

    Zone is identified by UUID (preferred) or index (fallback).

    Attributes:
        op_type: Discriminator literal ``"remove_copper_zone"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        zone_uuid: Zone UUID (tstamp) to identify the zone (preferred).
        zone_index: Zone index as fallback when UUID is not available.
    """

    op_type: Literal["remove_copper_zone"] = "remove_copper_zone"
    target_file: TargetFile
    zone_uuid: Optional[str] = Field(default=None, max_length=64, description="Zone UUID (tstamp)")
    zone_index: Optional[int] = Field(default=None, ge=0, description="Zone index fallback")

    @model_validator(mode="after")
    def _check_identifier_provided(self) -> "RemoveCopperZoneOp":
        if self.zone_uuid is None and self.zone_index is None:
            raise ValueError("Must specify at least one of zone_uuid or zone_index")
        return self


class RefillCopperZoneOp(BaseModel):
    """Strip filled polygon data from a zone so KiCad refills on next save.

    Attributes:
        op_type: Discriminator literal ``"refill_copper_zone"``.
        target_file: Relative path to the target KiCad PCB file.
        zone_uuid: Zone UUID (tstamp) to identify the zone (preferred).
        zone_index: Zone index as fallback.
    """

    op_type: Literal["refill_copper_zone"] = "refill_copper_zone"
    target_file: TargetFile
    zone_uuid: Optional[str] = Field(default=None, max_length=64, description="Zone UUID (tstamp)")
    zone_index: Optional[int] = Field(default=None, ge=0, description="Zone index fallback")

    @model_validator(mode="after")
    def _check_identifier_provided(self) -> "RefillCopperZoneOp":
        if self.zone_uuid is None and self.zone_index is None:
            raise ValueError("Must specify at least one of zone_uuid or zone_index")
        return self


class ModifyZonePolygonOp(BaseModel):
    """Replace the outline polygon of an existing copper zone.

    Attributes:
        op_type: Discriminator literal ``"modify_zone_polygon"``.
        target_file: Relative path to the target KiCad PCB file.
        zone_uuid: Zone UUID (tstamp) to identify the zone.
        polygon: New polygon outline points (minimum 3).
    """

    op_type: Literal["modify_zone_polygon"] = "modify_zone_polygon"
    target_file: TargetFile
    zone_uuid: str = Field(min_length=1, max_length=64, description="Zone UUID (tstamp)")
    polygon: list[tuple[float, float]] = Field(
        min_length=3, description="New polygon outline points",
    )


class AddKeepoutAreaOp(BaseModel):
    """Add a keepout area to a PCB.

    Keepout areas prevent copper, vias, pads, or tracks from being placed
    in the defined polygon region.

    Attributes:
        op_type: Discriminator literal ``"add_keepout_area"``.
        target_file: Relative path to the target KiCad PCB file.
        layer: Layer restriction (``"*"`` = all layers).
        keepout_type: Type of keepout restriction.
        polygon: Keepout area outline points (minimum 3).
    """

    op_type: Literal["add_keepout_area"] = "add_keepout_area"
    target_file: TargetFile
    layer: str = Field(default="*", max_length=32, description="Layer restriction (* = all)")
    keepout_type: str = Field(
        default="through_hole",
        pattern=r"^(?:through_hole|via|tracks|pads)$",
        description="Type of keepout restriction",
    )
    polygon: list[tuple[float, float]] = Field(
        min_length=3, description="Keepout area outline points",
    )


class RemoveKeepoutAreaOp(BaseModel):
    """Remove a keepout area from a PCB.

    Attributes:
        op_type: Discriminator literal ``"remove_keepout_area"``.
        target_file: Relative path to the target KiCad PCB file.
        zone_uuid: Zone UUID (tstamp) to identify the keepout (preferred).
        zone_index: Zone index as fallback.
    """

    op_type: Literal["remove_keepout_area"] = "remove_keepout_area"
    target_file: TargetFile
    zone_uuid: Optional[str] = Field(default=None, max_length=64, description="Zone UUID (tstamp)")
    zone_index: Optional[int] = Field(default=None, ge=0, description="Zone index fallback")

    @model_validator(mode="after")
    def _check_identifier_provided(self) -> "RemoveKeepoutAreaOp":
        if self.zone_uuid is None and self.zone_index is None:
            raise ValueError("Must specify at least one of zone_uuid or zone_index")
        return self


class RouteDiffPairOp(BaseModel):
    """Route a differential pair with impedance-controlled spacing.

    Routes both nets of a differential pair (e.g. USB D+/D-) using the A*
    pathfinder with coupled spacing, then equalizes lengths via accordion
    serpentining. Optionally computes trace width from IPC-2141 impedance
    target.

    Attributes:
        op_type: Discriminator literal ``"route_diff_pair"``.
        target_file: Relative path to the target KiCad PCB file.
        net_positive: Positive net name (e.g. ``"USB_D+"``).
        net_negative: Negative net name (e.g. ``"USB_D-"``).
        spacing_mm: Coupled pair edge-to-edge spacing in mm.
        impedance_target: Target characteristic impedance in ohms (optional).
        layer: Primary copper layer for routing.
        via_layers: Layer pair for via transitions (e.g. ``["F.Cu", "B.Cu"]``).
        max_length_mismatch_mm: Acceptable length mismatch after tuning.
        dielectric_height_mm: Substrate dielectric height for impedance calc.
        dielectric_er: Relative permittivity for impedance calc.
        copper_thickness_mm: Copper foil thickness for impedance calc.
        trace_width_mm: Override trace width (skip impedance calc if set).
    """

    op_type: Literal["route_diff_pair"] = "route_diff_pair"
    target_file: TargetFile
    net_positive: str = Field(min_length=1, max_length=64, description="Positive net name")
    net_negative: str = Field(min_length=1, max_length=64, description="Negative net name")
    spacing_mm: float = Field(default=0.15, gt=0.05, le=2.0, description="Pair spacing in mm")
    impedance_target: Optional[float] = Field(
        default=None, gt=10, le=200,
        description="Target impedance in ohms (IPC-2141 calc). None = skip.",
    )
    layer: str = Field(
        default="F.Cu", pattern=r"^(?:[FB]\.Cu|In[1-9]\d*\.Cu)$",
        description="Primary copper layer",
    )
    via_layers: Optional[list[str]] = Field(
        default=None, description="Layer pair for via transitions",
    )
    max_length_mismatch_mm: float = Field(
        default=0.5, ge=0.0, description="Max acceptable length mismatch in mm",
    )
    dielectric_height_mm: float = Field(default=0.2, gt=0.01, description="Dielectric height mm")
    dielectric_er: float = Field(default=4.5, gt=1.0, le=12.0, description="Relative permittivity")
    copper_thickness_mm: float = Field(default=0.035, gt=0.001, description="Copper thickness mm")
    trace_width_mm: Optional[float] = Field(
        default=None, gt=0.05, le=5.0, description="Override trace width mm",
    )

    @field_validator("via_layers")
    @classmethod
    def _validate_via_layers(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is not None:
            pattern = r"^(?:[FB]\.Cu|In[1-9]\d*\.Cu)$"
            for layer_name in v:
                if not re.match(pattern, layer_name):
                    raise ValueError(f"Invalid layer name: {layer_name}")
        return v


class MatchLengthsOp(BaseModel):
    """Match route lengths between net pairs via serpentine tuning.

    Reads existing routes from the PCB and adds sawtooth or accordion bumps
    to the shorter net until both nets are within tolerance.

    Attributes:
        op_type: Discriminator literal ``"match_lengths"``.
        target_file: Relative path to the target KiCad PCB file.
        net_pairs: Net pairs with tolerance in mm.
        max_detour_ratio: Maximum detour amplitude as ratio of half-pitch.
        pattern: Serpentine pattern type.
        half_pitch_mm: Spacing between bumps in mm.
    """

    op_type: Literal["match_lengths"] = "match_lengths"
    target_file: TargetFile
    net_pairs: list["NetLengthPair"] = Field(
        min_length=1, description="Net pairs to length-match",
    )
    max_detour_ratio: float = Field(
        default=3.0, ge=1.0, le=10.0,
        description="Max detour amplitude as ratio of half-pitch",
    )
    pattern: Literal["sawtooth", "accordion"] = Field(
        default="sawtooth", description="Serpentine pattern type",
    )
    half_pitch_mm: float = Field(default=1.0, gt=0.1, description="Bump spacing in mm")


class NetLengthPair(BaseModel):
    """A pair of nets to length-match with tolerance."""

    net_a: str = Field(min_length=1, max_length=64, description="First net name")
    net_b: str = Field(min_length=1, max_length=64, description="Second net name")
    tolerance_mm: float = Field(default=0.25, ge=0.0, description="Max allowed mismatch mm")


class AnalyzeSplitPlaneOp(BaseModel):
    """Analyze split power/ground planes for boundary crossings.

    Detects gaps between zones on the same layer/net and flags signals
    on adjacent layers that cross those gaps. Read-only operation.

    Attributes:
        op_type: Discriminator literal ``"analyze_split_plane"``.
        target_file: Relative path to the target KiCad PCB file.
        layer: Net name to analyze (e.g. ``"GND"``).
        min_gap_mm: Minimum gap width to consider a split.
    """

    op_type: Literal["analyze_split_plane"] = "analyze_split_plane"
    target_file: TargetFile
    layer: str = Field(default="GND", min_length=1, max_length=64, description="Net name to analyze")
    min_gap_mm: float = Field(default=0.0, ge=0.0, description="Min gap mm to flag")


class FixSilkscreenOverCopperOp(BaseModel):
    """Detect and optionally relocate silkscreen text overlapping copper.

    Checks reference designators and values on silkscreen layers for
    clearance violations against copper features (pads, traces, zones).

    Attributes:
        op_type: Discriminator literal ``"fix_silkscreen_over_copper"``.
        target_file: Relative path to the target KiCad PCB file.
        clearance_mm: Required clearance between silkscreen and copper.
        action: ``"report"`` for detection only, ``"relocate"`` to fix.
        copper_layers: Copper layers to check against.
        silk_layers: Silkscreen layers to check.
    """

    op_type: Literal["fix_silkscreen_over_copper"] = "fix_silkscreen_over_copper"
    target_file: TargetFile
    clearance_mm: float = Field(default=0.15, gt=0.0, description="Required clearance mm")
    action: Literal["report", "relocate"] = Field(
        default="report", description="report = detection only, relocate = fix positions",
    )
    copper_layers: list[str] = Field(
        default=["F.Cu"], description="Copper layers to check against",
    )
    silk_layers: list[str] = Field(
        default=["F.SilkS", "B.SilkS"], description="Silkscreen layers to check",
    )


class MoveFootprintOp(BaseModel):
    """Move a footprint to a new position on the PCB.

    Uses PcbRawWriter for raw S-expression manipulation (Council C-01).
    The handler calls PcbRawWriter.modify_footprint_position which returns
    modified content, then the executor writes via atomic temp+rename.

    Attributes:
        op_type: Discriminator literal ``"move_footprint"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        reference: Reference designator of the footprint to move.
        x: New X position in mm.
        y: New Y position in mm.
        angle: New rotation angle in degrees.
    """

    op_type: Literal["move_footprint"] = "move_footprint"
    target_file: TargetFile
    reference: str = Field(min_length=1, max_length=32, description="Reference designator")
    x: float = Field(description="New X position in mm")
    y: float = Field(description="New Y position in mm")
    angle: float = Field(default=0.0, description="New rotation angle in degrees")


class BatchExpandFootprintsOp(BaseModel):
    """Expand all synthetic (geometry-less) footprints from their libraries.

    Scans all footprint blocks in the PCB, identifies those without pad geometry
    (synthetic footprints), resolves their lib_id to .kicad_mod files, and
    replaces them with full geometry from the library.

    Attributes:
        op_type: Discriminator literal ``"batch_expand_footprints"``.
        target_file: Relative path to the target KiCad PCB file.
        dry_run: If True, report counts without modifying the file.
    """

    op_type: Literal["batch_expand_footprints"] = "batch_expand_footprints"
    target_file: TargetFile
    dry_run: bool = Field(
        default=False,
        description="Report counts without modifying the file",
    )


class ImportSesOp(BaseModel):
    """Import a Freerouting SES routing result into a KiCad PCB.

    Parses an existing .ses file produced by Freerouting (or compatible
    Specctra autorouter), converts wire/via data to KiCad (segment ...)
    and (via ...) S-expressions, and inserts them into the PCB content.

    Hierarchical net names encoded as ``{slash}`` in the SES file are
    automatically decoded to ``/`` for PCB net matching.

    Attributes:
        op_type: Discriminator literal ``"import_ses"``.
        target_file: Relative path to the target KiCad PCB file.
        ses_file: Path to the .ses file (relative to the PCB directory).
        clean_nets_with_shorts: If True, skip nets whose names match
            generic patterns that may indicate DRC shorts.
    """

    op_type: Literal["import_ses"] = "import_ses"
    target_file: TargetFile
    ses_file: str = Field(
        min_length=1, max_length=256,
        description="Path to .ses file relative to PCB directory",
    )
    clean_nets_with_shorts: bool = Field(
        default=False,
        description="Skip nets with generic Nxxx names that may indicate shorts",
    )


class AutoRouteManhattanOp(BaseModel):
    """Generate Manhattan-style L-shaped routing segments for a PCB.

    For each net with 2+ pads, pads are sorted by (x, y) and consecutive
    pads connected via horizontal-then-vertical L-segments. This is a
    fallback router when Freerouting is unavailable or produces incomplete
    results. Does NOT account for component obstacles or perform clearance
    checking. Run DRC after use.

    Attributes:
        op_type: Discriminator literal ``"auto_route_manhattan"``.
        target_file: Relative path to the target KiCad PCB file.
        nets: Optional list of specific net names to route. Empty = all.
        layer: Default copper layer for signal routing.
        track_width: Default trace width in mm.
        net_overrides: Per-net layer/width overrides as dict mapping net
            name to ``{"layer": "...", "width": ...}``.
        strip_existing: Remove all existing segments before routing.
    """

    op_type: Literal["auto_route_manhattan"] = "auto_route_manhattan"
    target_file: TargetFile
    nets: list[str] = Field(
        default_factory=list,
        description="Net names to route (empty = all)",
    )
    layer: str = Field(
        default="F.Cu",
        description="Default copper layer for signal routing",
    )
    track_width: float = Field(
        default=0.15, gt=0.01,
        description="Default trace width in mm",
    )
    net_overrides: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Per-net overrides: {net_name: {layer, width}}",
    )
    strip_existing: bool = Field(
        default=True,
        description="Remove all existing segments before routing",
    )


class AddTrackOp(BaseModel):
    """Add a single straight track segment to a PCB (Phase 101-01).

    Generates a KiCad 10 ``(segment ...)`` S-expression with the string-only
    ``(net "NAME")`` net reference and inserts it before the closing paren.

    Attributes:
        op_type: Discriminator literal ``"add_track"``.
        target_file: Relative path to the target KiCad PCB file.
        net: Net name (e.g. "GND", "/SIG1").
        start: (x, y) start coordinates in mm.
        end: (x, y) end coordinates in mm.
        width: Trace width in mm.
        layer: Copper layer name (e.g. "F.Cu").
    """

    op_type: Literal["add_track"] = "add_track"
    target_file: TargetFile
    net: str = Field(min_length=1, max_length=128, description="Net name")
    start: tuple[float, float] = Field(description="(x, y) start in mm")
    end: tuple[float, float] = Field(description="(x, y) end in mm")
    width: float = Field(default=0.2, gt=0.01, description="Trace width in mm")
    layer: str = Field(default="F.Cu", description="Copper layer name")


class AddArcTrackOp(BaseModel):
    """Add a single arc track segment to a PCB (Phase 101-01).

    Generates a KiCad 10 ``(arc ...)`` S-expression with start/mid/end
    control points and the string-only ``(net "NAME")`` net reference.

    Attributes:
        op_type: Discriminator literal ``"add_arc_track"``.
        target_file: Relative path to the target KiCad PCB file.
        net: Net name.
        start: (x, y) arc start coordinates in mm.
        mid: (x, y) arc midpoint coordinates in mm.
        end: (x, y) arc end coordinates in mm.
        width: Trace width in mm.
        layer: Copper layer name.
    """

    op_type: Literal["add_arc_track"] = "add_arc_track"
    target_file: TargetFile
    net: str = Field(min_length=1, max_length=128, description="Net name")
    start: tuple[float, float] = Field(description="(x, y) start in mm")
    mid: tuple[float, float] = Field(description="(x, y) midpoint in mm")
    end: tuple[float, float] = Field(description="(x, y) end in mm")
    width: float = Field(default=0.2, gt=0.01, description="Trace width in mm")
    layer: str = Field(default="F.Cu", description="Copper layer name")


class AddViaOp(BaseModel):
    """Add a single via to a PCB (Phase 101-01).

    Generates a KiCad 10 ``(via ...)`` S-expression with the string-only
    ``(net "NAME")`` net reference. Default size=0.7 / drill=0.3 matches
    the JLC 4-layer floor (H2: stackup constraints).

    Attributes:
        op_type: Discriminator literal ``"add_via"``.
        target_file: Relative path to the target KiCad PCB file.
        net: Net name.
        at: (x, y) via center coordinates in mm.
        size: Via pad diameter in mm.
        drill: Via drill hole diameter in mm.
        layers: List of layer names the via connects (default F.Cu + B.Cu).
    """

    op_type: Literal["add_via"] = "add_via"
    target_file: TargetFile
    net: str = Field(min_length=1, max_length=128, description="Net name")
    at: tuple[float, float] = Field(description="(x, y) via center in mm")
    size: float = Field(default=0.7, gt=0.01, description="Via pad diameter in mm")
    drill: float = Field(default=0.3, gt=0.01, description="Via drill diameter in mm")
    layers: list[str] = Field(
        default_factory=lambda: ["F.Cu", "B.Cu"],
        description="Layers the via connects",
    )


class DeleteTrackOp(BaseModel):
    """Delete a straight track segment from a PCB by UUID (Phase 101-02).

    Locates the ``(segment ...)`` block whose ``(uuid "...")`` field matches
    and removes it entirely, including its trailing newline.

    Attributes:
        op_type: Discriminator literal ``"delete_track"``.
        target_file: Relative path to the target KiCad PCB file.
        uuid: UUID of the segment to delete.
    """

    op_type: Literal["delete_track"] = "delete_track"
    target_file: TargetFile
    uuid: str = Field(min_length=1, description="UUID of the segment to delete")


class DeleteViaOp(BaseModel):
    """Delete a via from a PCB by UUID (Phase 101-02).

    Attributes:
        op_type: Discriminator literal ``"delete_via"``.
        target_file: Relative path to the target KiCad PCB file.
        uuid: UUID of the via to delete.
    """

    op_type: Literal["delete_via"] = "delete_via"
    target_file: TargetFile
    uuid: str = Field(min_length=1, description="UUID of the via to delete")


class MoveTrackEndpointOp(BaseModel):
    """Move the start or end point of a track segment (Phase 101-02).

    Locates the ``(segment ...)`` block by UUID and rewrites either its
    ``(start X Y)`` or ``(end X Y)`` field with the new coordinates.

    Attributes:
        op_type: Discriminator literal ``"move_track_endpoint"``.
        target_file: Relative path to the target KiCad PCB file.
        uuid: UUID of the segment to modify.
        end: Which endpoint to move -- ``"start"`` or ``"end"``.
        to: New ``(x, y)`` coordinates in mm.
    """

    op_type: Literal["move_track_endpoint"] = "move_track_endpoint"
    target_file: TargetFile
    uuid: str = Field(min_length=1, description="UUID of the segment to modify")
    end: Literal["start", "end"] = Field(
        description="Which endpoint to move: 'start' or 'end'",
    )
    to: tuple[float, float] = Field(description="New (x, y) coordinates in mm")


class LockTrackOp(BaseModel):
    """Lock a straight track segment by UUID (Phase 101-03).

    Injects ``(locked)`` as the first property of the matching
    ``(segment ...)`` block so pcbnew treats the track as immovable.
    Idempotent -- locking an already-locked segment is a no-op.

    Attributes:
        op_type: Discriminator literal ``"lock_track"``.
        target_file: Relative path to the target KiCad PCB file.
        uuid: UUID of the segment to lock.
    """

    op_type: Literal["lock_track"] = "lock_track"
    target_file: TargetFile
    uuid: str = Field(min_length=1, description="UUID of the segment to lock")


class LockViaOp(BaseModel):
    """Lock a via by UUID (Phase 101-03).

    Same algorithm as ``LockTrackOp`` but for ``(via ...)`` blocks.

    Attributes:
        op_type: Discriminator literal ``"lock_via"``.
        target_file: Relative path to the target KiCad PCB file.
        uuid: UUID of the via to lock.
    """

    op_type: Literal["lock_via"] = "lock_via"
    target_file: TargetFile
    uuid: str = Field(min_length=1, description="UUID of the via to lock")


class AddStitchingViaPatternOp(BaseModel):
    """Add a grid of stitching vias to a PCB (Phase 101-03).

    Generates vias on a regular grid bounded by ``region`` using
    ``PcbRawWriter.build_via_sexp(...)`` from Phase 101-01 and inserts them
    before the closing paren via ``insert_segments``.

    Attributes:
        op_type: Discriminator literal ``"add_stitching_via_pattern"``.
        target_file: Relative path to the target KiCad PCB file.
        net: Net name for all vias (e.g. "GND").
        grid_spacing_mm: Spacing between adjacent vias in mm.
        region: ``((x_min, y_min), (x_max, y_max))`` defining the bounding
            rectangle of the via grid in mm.
        size: Via pad diameter in mm (default 0.4 for JLC stitching).
        drill: Via drill hole diameter in mm (default 0.2 for JLC stitching).
        layers: List of layer names the vias connect (default F.Cu + B.Cu).
    """

    op_type: Literal["add_stitching_via_pattern"] = "add_stitching_via_pattern"
    target_file: TargetFile
    net: str = Field(min_length=1, max_length=128, description="Net name")
    grid_spacing_mm: float = Field(gt=0.01, description="Via-to-via spacing in mm")
    region: tuple[tuple[float, float], tuple[float, float]] = Field(
        description="((x_min, y_min), (x_max, y_max)) bounding box in mm",
    )
    size: float = Field(default=0.4, gt=0.01, description="Via pad diameter in mm")
    drill: float = Field(default=0.2, gt=0.01, description="Via drill diameter in mm")
    layers: list[str] = Field(
        default_factory=lambda: ["F.Cu", "B.Cu"],
        description="Layers the vias connect",
    )


class PlaceComponentOp(BaseModel):
    """Place a component (footprint) on a PCB (Phase 101-05).

    Generates a KiCad 10 ``(footprint ...)`` S-expression using a parametric
    SMD library (Option A) for common 0402/0603/0805 cap and resistor
    packages, and inserts it before the closing paren. Pad nets use the
    KiCad 10 string-only ``(net "NAME")`` format.

    Supported footprints (parametric, IPC-7351 nominal pad geometry):
        - Capacitor_SMD:C_0402_1005Metric
        - Capacitor_SMD:C_0603_1608Metric
        - Capacitor_SMD:C_0805_2012Metric
        - Resistor_SMD:R_0402_1005Metric
        - Resistor_SMD:R_0603_1608Metric
        - Resistor_SMD:R_0805_2012Metric

    Unsupported IDs raise ValueError at handler time. Loading footprints
    from an installed KiCad library (Option B) is a future enhancement.

    Attributes:
        op_type: Discriminator literal ``"place_component"``.
        target_file: Relative path to the target KiCad PCB file.
        ref: Reference designator (e.g. "C42", "R15").
        footprint: Footprint library ID (e.g. "Capacitor_SMD:C_0402_1005Metric").
        library: Optional symbol library name (reserved for future use).
        at: (x, y) position in mm.
        layer: "F.Cu" (default) or "B.Cu".
        rotation: Rotation in degrees (default 0).
        net_pad_map: Dict mapping pad number to net name. Pads not in map
            are emitted without a ``(net ...)`` field (unconnected).
    """

    op_type: Literal["place_component"] = "place_component"
    target_file: TargetFile
    ref: str = Field(min_length=1, max_length=16, description="Reference designator")
    footprint: str = Field(
        min_length=1, max_length=128,
        description='Footprint library ID, e.g. "Capacitor_SMD:C_0402_1005Metric"',
    )
    library: Optional[str] = Field(
        default=None, max_length=64,
        description="Optional symbol library name (reserved for future use)",
    )
    at: tuple[float, float] = Field(description="(x, y) position in mm")
    layer: str = Field(default="F.Cu", description='Copper layer ("F.Cu" or "B.Cu")')
    rotation: float = Field(default=0.0, description="Rotation in degrees")
    net_pad_map: dict[str, str] = Field(
        default_factory=dict,
        description='Mapping of pad number to net name, e.g. {"1": "+3V3", "2": "GND"}',
    )

    @field_validator("ref")
    @classmethod
    def _validate_ref_safe(cls, v: str) -> str:
        return _validate_sexpr_safe_string(v)

    @field_validator("footprint")
    @classmethod
    def _validate_footprint_safe(cls, v: str) -> str:
        # Footprint IDs contain a colon which is in the safe-id pattern
        if not re.match(r'^[A-Za-z0-9_\-:.]+$', v):
            raise ValueError(
                "footprint contains unsafe characters. "
                "Allowed: alphanumeric, underscore, dash, colon, dot."
            )
        return v

    @field_validator("layer")
    @classmethod
    def _validate_layer(cls, v: str) -> str:
        if v not in ("F.Cu", "B.Cu"):
            raise ValueError('layer must be "F.Cu" or "B.Cu"')
        return v

    @field_validator("net_pad_map")
    @classmethod
    def _validate_net_pad_map(cls, v: dict[str, str]) -> dict[str, str]:
        for pad_num, net_name in v.items():
            _validate_sexpr_safe_string(net_name)
        return v
