"""Schematic routing operation schemas -- pin resolution, collision detection, wire routing.

Schemas for the schematic routing engine (Phase 38). These operations read
schematic files to resolve pin positions, detect collisions, and plan wire
routes -- they are analysis/query operations, not mutations.

Security (threat model):
  T-38-01-01: target_file validated via TargetFile type (inherited H-01)
  T-38-01-02: ref field bounded to max_length=16 (component refs are short)
  T-38-02-01: target_file validated via TargetFile type (inherited H-01)
  T-38-02-02: collision_tolerance validated: gt=0, le=10 prevents extreme values
  T-38-03-01: net_name, ref, pin fields validated with _validate_sexpr_safe_string
  T-38-03-02: pins list bounded to max_length=100 (prevents DoS)
  T-38-03-04: collision_zones list bounded to max_length=50
  T-38-04-01: net names in NetDef/GlobalLabelSpec validated with _validate_sexpr_safe_string
  T-38-04-03: nets list bounded to max_length=200 (prevents DoS)
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from volta.ops.schema import PositionSpec, TargetFile, _validate_sexpr_safe_string


class ResolvePinPositionsOp(BaseModel):
    """Resolve absolute pin positions for schematic components.

    Reads a .kicad_sch file, parses lib_symbols and placed symbol instances,
    and returns absolute coordinates for every pin of every (or filtered)
    component, including multi-unit ICs and rotation transforms.

    Attributes:
        op_type: Discriminator literal ``"resolve_pin_positions"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        ref: Optional component reference filter (e.g. ``"R55"``, ``"U21"``).
    """

    op_type: Literal["resolve_pin_positions"] = "resolve_pin_positions"
    target_file: TargetFile
    ref: Optional[str] = Field(
        default=None,
        max_length=16,
        description="Filter to a single component reference (e.g. 'R55')",
    )


class DetectRoutingCollisionsOp(BaseModel):
    """Detect collision zones in a schematic where wires would short pins.

    Identifies vertical columns and horizontal rows where pins from different
    components share the same coordinate. Any wire drawn through these zones
    would create unintended short circuits between the overlapping pins.

    Attributes:
        op_type: Discriminator literal ``"detect_routing_collisions"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        collision_tolerance: Max distance (mm) to group pins into a collision column.
    """

    op_type: Literal["detect_routing_collisions"] = "detect_routing_collisions"
    target_file: TargetFile
    collision_tolerance: float = Field(
        default=2.54,
        gt=0,
        le=10,
        description="Max distance (mm) to group pins into a collision column",
    )


class DetectPinOverlapsOp(BaseModel):
    """Detect pins from different nets at the exact same position.

    Finds layout bugs like R55/R56 where pins from different nets share
    coordinates. Any label or wire at that position applies to both pins,
    creating an unintended short.

    Attributes:
        op_type: Discriminator literal ``"detect_pin_overlaps"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        tolerance: Position tolerance (mm) for overlap detection.
    """

    op_type: Literal["detect_pin_overlaps"] = "detect_pin_overlaps"
    target_file: TargetFile
    tolerance: float = Field(
        default=0.01,
        gt=0,
        le=1.0,
        description="Position tolerance (mm) for overlap detection",
    )


class PinRef(BaseModel):
    """Reference to a component pin for net connection.

    Attributes:
        ref: Component reference designator (e.g. ``"R55"``, ``"U21"``).
        pin: Pin number or name (e.g. ``"1"``, ``"VCA_IN"``).
    """

    ref: str = Field(
        min_length=1, max_length=16,
        description="Component reference (e.g. 'R55', 'U21')",
    )
    pin: str = Field(
        min_length=1, max_length=32,
        description="Pin number or name (e.g. '1', 'VCA_IN')",
    )

    @field_validator("ref", "pin")
    @classmethod
    def _validate_sexpr(cls, v: str) -> str:
        """T-38-03-01: Reject S-expression injection in pin references."""
        return _validate_sexpr_safe_string(v)


class CollisionZone(BaseModel):
    """A collision zone to avoid during wire routing.

    Attributes:
        direction: Whether this is a vertical or horizontal zone.
        coordinate: X coordinate (vertical) or Y coordinate (horizontal).
        tolerance: Range around coordinate to avoid (default 2.54mm).
    """

    direction: Literal["vertical", "horizontal"] = Field(
        description="Collision zone direction",
    )
    coordinate: float = Field(description="X coordinate (vertical) or Y coordinate (horizontal)")
    tolerance: float = Field(
        default=2.54, gt=0,
        description="Range around coordinate to avoid",
    )

    @field_validator("coordinate", "tolerance")
    @classmethod
    def _reject_non_finite(cls, v: float) -> float:
        import math
        if math.isnan(v) or math.isinf(v):
            raise ValueError("Coordinate values must be finite (not NaN or Infinity)")
        return v


class ConnectPinsOp(BaseModel):
    """Connect pins into a net with wire/label generation.

    Generates net labels at every pin body_position for guaranteed KiCad
    connectivity. Optionally generates wires for nearby same-axis pins,
    respecting collision zones and max wire length.

    Three strategies:
      - ``wire_first``: Generate wires for connected pins, labels for unreached.
      - ``label_only``: No wires, just labels at every pin.
      - ``hybrid``: Short/clean wires where possible, labels everywhere.

    Attributes:
        op_type: Discriminator literal ``"connect_pins"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        net_name: Net name for generated labels.
        pins: List of pin references to connect.
        strategy: Routing strategy (default ``"hybrid"``).
        collision_zones: Zones to avoid during wire routing (max 50, T-38-03-04).
        max_wire_length: Skip wires longer than this in mm (default 40.0).
    """

    op_type: Literal["connect_pins"] = "connect_pins"
    target_file: TargetFile
    net_name: str = Field(
        min_length=1, max_length=128,
        description="Net name for labels",
    )
    pins: list[PinRef] = Field(
        min_length=1, max_length=100,
        description="Pins to connect (T-38-03-02: max 100)",
    )
    strategy: Literal["wire_first", "label_only", "hybrid"] = Field(
        default="hybrid",
    )
    collision_zones: list[CollisionZone] = Field(
        default_factory=list, max_length=50,
        description="Collision zones to avoid (T-38-03-04: max 50)",
    )
    max_wire_length: float = Field(
        default=40.0, gt=0,
        description="Skip wires longer than this (mm)",
    )

    @field_validator("net_name")
    @classmethod
    def _validate_name_sexpr(cls, v: str) -> str:
        """T-38-03-01: Reject S-expression injection in net name."""
        return _validate_sexpr_safe_string(v)


class NetDef(BaseModel):
    """A net definition: name and the pins that belong to it.

    Attributes:
        name: Net name (e.g. ``"VCC"``, ``"COMP_IN"``).
        pins: List of pin references on this net.
    """

    name: str = Field(min_length=1, max_length=128)
    pins: list[PinRef] = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _validate_name_sexpr(cls, v: str) -> str:
        """T-38-04-01: Reject S-expression injection in net name."""
        return _validate_sexpr_safe_string(v)


class GlobalLabelSpec(BaseModel):
    """A global label to place for cross-sheet connectivity.

    Attributes:
        name: Global label text.
        position: Position on the schematic.
        shape: Label shape (default ``"bidirectional"``).
    """

    name: str = Field(min_length=1, max_length=128)
    position: "PositionSpec" = Field(description="Label position on schematic")
    shape: str = Field(default="bidirectional")

    @field_validator("name")
    @classmethod
    def _validate_name_sexpr(cls, v: str) -> str:
        """T-38-04-01: Reject S-expression injection in global label name."""
        return _validate_sexpr_safe_string(v)


class BatchConnectOp(BaseModel):
    """Batch-connect multiple nets in a single call.

    Processes a list of net definitions, optionally auto-detecting collision
    zones and generating global labels for cross-sheet connectivity.

    Attributes:
        op_type: Discriminator literal ``"batch_connect"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        nets: List of net definitions (T-38-04-03: max 200).
        global_labels: Global labels to place for cross-sheet connectivity.
        strategy: Routing strategy (default ``"hybrid"``).
        collision_zones: Zones to avoid during wire routing (max 50).
        auto_detect_collisions: Auto-detect collision zones when none provided.
        max_wire_length: Skip wires longer than this in mm (default 40.0).
    """

    op_type: Literal["batch_connect"] = "batch_connect"
    target_file: TargetFile
    nets: list[NetDef] = Field(min_length=1, max_length=200)
    global_labels: list[GlobalLabelSpec] = Field(default_factory=list)
    strategy: Literal["wire_first", "label_only", "hybrid"] = Field(default="hybrid")
    collision_zones: list[CollisionZone] = Field(default_factory=list, max_length=50)
    auto_detect_collisions: bool = Field(default=True)
    max_wire_length: float = Field(default=40.0, gt=0)


class RegenerateWiringOp(BaseModel):
    """Strip all wires/labels/no_connects and regenerate from netlist definition.

    Removes all existing wiring elements from a schematic body, then reconnects
    all nets using the provided net definitions, global labels, and no-connect
    markers.

    Attributes:
        op_type: Discriminator literal ``"regenerate_wiring"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        nets: List of net definitions (T-38-04-03: max 200).
        global_labels: Global labels to place for cross-sheet connectivity.
        no_connect_positions: Positions for no-connect markers.
        strategy: Routing strategy (default ``"hybrid"``).
        collision_zones: Zones to avoid during wire routing (max 50).
        auto_detect_collisions: Auto-detect collision zones when none provided.
        max_wire_length: Skip wires longer than this in mm (default 40.0).
    """

    op_type: Literal["regenerate_wiring"] = "regenerate_wiring"
    target_file: TargetFile
    nets: list[NetDef] = Field(min_length=1, max_length=200)
    global_labels: list[GlobalLabelSpec] = Field(default_factory=list)
    no_connect_positions: list["PositionSpec"] = Field(default_factory=list)
    strategy: Literal["wire_first", "label_only", "hybrid"] = Field(default="hybrid")
    collision_zones: list[CollisionZone] = Field(default_factory=list, max_length=50)
    auto_detect_collisions: bool = Field(default=True)
    max_wire_length: float = Field(default=40.0, gt=0)


class PlaceNetLabelsOp(BaseModel):
    """Place net labels on IC pins based on a pin-to-net mapping.

    Issue #8: Takes a pin_map (built-in profile or user-provided JSON) and
    places global labels at IC pin positions that already have wire connections.
    Critical safety: labels are ONLY placed at positions with wire endpoints,
    preventing label_dangling violations.

    Pins mapped to None receive no_connect flags (only if no wire exists).

    Attributes:
        op_type: Discriminator literal ``"place_net_labels"``.
        target_file: Relative path to the .kicad_sch file.
        pin_map: Built-in profile name (e.g. "backplane") or path to JSON mapping file.
        references: Optional list of specific component references. None = all matching.
        dry_run: If True, report what would be placed without modifying.
    """

    op_type: Literal["place_net_labels"] = "place_net_labels"
    target_file: TargetFile
    pin_map: str = Field(
        default="auto",
        description="Built-in profile name or path to JSON pin_map file",
    )
    references: Optional[list[str]] = Field(
        default=None,
        description="Specific component references to process, or None for all",
    )
    dry_run: bool = Field(
        default=False,
        description="Report placements without modifying the file",
    )
