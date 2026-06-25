"""Native PCB dataclass types for KiCad 10+ .kicad_pcb files.

Replaces kiutils Board objects for PCB reads. Provides typed access to all
board elements (nets, footprints, zones, tracks, vias, net classes, graphic
items, board outline) without kiutils dependency.

All dataclasses are mutable (not frozen) to support the PcbIR adapter pattern
where PcbIR methods append to board.nets, etc.

UUID Preservation Note (Council HIGH-4 / D-07):
  UUIDs are preserved in raw_content (no kiutils round-trip = no UUID loss).
  NativeBoard typed fields only get UUIDs where the parser explicitly extracts
  them (zones.uuid, footprints.uuid). Unparsed elements retain UUIDs in
  raw_content but not in typed fields. PcbRawWriter writes to raw_content
  directly, so UUIDs survive writes.

S-expression Origin:
  Each dataclass maps to a KiCad S-expression element:
  - NativeBoard    -> (kicad_pcb ...)
  - NativeNet      -> (net N "NAME")
  - NativeNetClass -> (net_class "Name" ...)
  - NativeFootprint -> (footprint "lib:fp" ...)
  - NativePad      -> (pad N type shape ...)
  - NativeSegment  -> (segment (start ...) (end ...) ...)
  - NativeVia      -> (via (at ...) (size ...) (drill ...) ...)
  - NativeZone     -> (zone ...)
  - NativeGraphicItem -> (gr_line | gr_arc | gr_circle | gr_rect | gr_poly | gr_curve ...)
  - NativeBoardOutline -> collected Edge.Cuts graphic items
  - NativeGeneral  -> (general ...)
  - NativeSetup    -> (setup ...)
  - NativeStackup  -> (stackup ...)
"""

from dataclasses import dataclass, field
from typing import NamedTuple


class _NativePosition(NamedTuple):
    """2D position supporting both indexing (pos[0]) and attribute access (pos.X).

    NamedTuple IS a tuple, so tuple-based consumers (PcbIR) work unchanged.
    NamedTuple also supports attribute access (pos.X, pos.Y) for consumers
    that expect Position-like objects (board_outline.py, pcb_ops.py).

    Council CRITICAL-2 compatibility: board_outline.py accesses item.start.X,
    item.end.X, item.center.X directly (lines 227-262 of spatial/board_outline.py).
    """

    X: float
    Y: float


# ---------------------------------------------------------------------------
# Leaf dataclasses
# ---------------------------------------------------------------------------


@dataclass
class NativeNet:
    """Board-level net declaration: (net N "NAME")."""

    number: int = 0
    name: str = ""


@dataclass
class NativeNetClass:
    """Net class definition: (net_class "Name" ...).

    Fields map to KiCad net_class children:
      (clearance C) (trace_width W) (via_diameter D) (via_drill DR)
      (add_net "net_name") ...
    """

    name: str = ""
    clearance: float = 0.0
    track_width: float = 0.0
    via_diameter: float = 0.0
    via_drill: float = 0.0
    add_nets: list[str] = field(default_factory=list)


@dataclass
class NativePad:
    """Pad within a footprint: (pad N type shape ...).

    pad_type is the KiCad pad mount type: "smd", "thru_hole", or "np_thru_hole".
    Council HIGH-3: added pinfunction and pintype fields.
    """

    number: str = ""
    net_name: str = ""
    net_number: int = 0
    position: tuple[float, float] = (0.0, 0.0)
    layers: str = ""
    shape: str = ""
    pad_type: str = ""
    pinfunction: str = ""
    pintype: str = ""
    size: tuple[float, float] = (0.0, 0.0)
    drill: float = 0.0


@dataclass
class NativeFootprint:
    """Footprint placement: (footprint "lib:fp" ...).

    position is (x, y, angle). properties dict holds "Reference", "Value", etc.
    with the same interface as kiutils fp.properties.
    """

    lib_id: str = ""
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    pads: list[NativePad] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)
    layer: str = ""
    graphic_items: list = field(default_factory=list)
    uuid: str = ""


@dataclass
class NativeSegment:
    """Copper track segment: (segment (start X Y) (end X Y) (width W) (layer L) (net N))."""

    start: _NativePosition | None = None
    end: _NativePosition | None = None
    width: float = 0.0
    layer: str = ""
    net_number: int = 0
    net_name: str = ""


@dataclass
class NativeVia:
    """Through-hole via: (via (at X Y) (size D) (drill DR) (net N))."""

    position: tuple[float, float] = (0.0, 0.0)
    drill: float = 0.0
    diameter: float = 0.0
    net_number: int = 0
    net_name: str = ""
    layers: tuple[str, str] = ("", "")


@dataclass
class NativeGraphicItem:
    """Board-level graphic element: gr_line, gr_arc, gr_circle, gr_rect, gr_poly, gr_curve,
    gr_text, gr_text_box, dimension, target.

    Council HIGH-2: supports 6 geometric types (line, arc, circle, rect, poly, curve).
    P-BUG-005: adds 4 annotation types (gr_text, gr_text_box, dimension, target).

    start/end/mid/center use _NativePosition (NamedTuple) for both tuple
    indexing and attribute access (pos.X, pos.Y).
    """

    item_type: str = "line"
    start: _NativePosition | None = None
    end: _NativePosition | None = None
    mid: _NativePosition | None = None
    center: _NativePosition | None = None
    radius: float = 0.0
    layer: str = ""
    width: float = 0.0
    filled: str | None = None
    uuid: str = ""
    # P-BUG-005: text annotation fields
    text: str = ""
    font_size: float = 0.0
    rotation: float = 0.0
    # P-BUG-005: dimension/target fields
    target_size: float = 0.0


@dataclass
class NativeZone:
    """Copper zone: (zone ...).

    Council CRITICAL-2 compatibility fields (net, netName, layers, minThickness)
    mirror kiutils Zone attribute names so downstream consumers work unchanged.

    Phase 99 C-1 fix: keepout_* fields capture the (keepout ...) subblock type
    so zones can be classified as copper pour, routing keepout, or placement-only
    keepout. The is_routing_keepout property drives the 3-way classification
    that prevents Freerouting from being told to avoid regions the source PCB
    allows tracks through (the old binary net_name == "" bug).
    """

    net_number: int = 0
    net_name: str = ""
    net: int = 0
    netName: str = ""
    layer: str = ""
    layers: list[str] = field(default_factory=list)
    polygon_points: list[tuple[float, float]] = field(default_factory=list)
    clearance: float = 0.0
    priority: int = 0
    minThickness: float = 0.25
    uuid: str = ""
    # Phase 99 C-1 fix: captures the (keepout ...) subblock type.
    # Defaults of "allowed" mean: zones WITHOUT a keepout subblock are treated
    # as non-routing-restricted (a plain copper pour has no keepout subblock).
    keepout_tracks: str = "allowed"
    keepout_vias: str = "allowed"
    keepout_pads: str = "allowed"
    keepout_copperpour: str = "allowed"
    keepout_footprints: str = "allowed"

    @property
    def tstamp(self) -> str:
        """Kiutils compatibility: returns uuid. Council CRITICAL-2."""
        return self.uuid

    @property
    def is_routing_keepout(self) -> bool:
        """C-1 fix: True if this zone blocks routing (tracks OR vias not allowed).

        Placement-only keepouts (only footprints not_allowed) do NOT block
        routing and must not be emitted as DSN (keepout ...) to Freerouting.
        """
        return self.keepout_tracks == "not_allowed" or self.keepout_vias == "not_allowed"


@dataclass
class NativeBoardOutline:
    """Board outline: all graphic items on Edge.Cuts layer."""

    items: list[NativeGraphicItem] = field(default_factory=list)


@dataclass
class NativeGeneral:
    """General board settings: (general ...).

    Council CRITICAL-2: needed by spatial/layer_stackup.py (board.general.thickness)
    and export/general.py (board.general.layers).
    """

    thickness: float = 1.6
    layers: list = field(default_factory=list)


@dataclass
class NativeStackup:
    """Board stackup definition: (setup (stackup ...)).

    Council CRITICAL-2: needed by spatial/layer_stackup.py (board.setup.stackup.layers).
    Full stackup parsing deferred to future phase.
    """

    layers: list = field(default_factory=list)


@dataclass
class NativeSetup:
    """Board setup section: (setup ...).

    Council CRITICAL-2: needed by spatial/layer_stackup.py (board.setup.stackup).
    """

    stackup: NativeStackup | None = None


# ---------------------------------------------------------------------------
# Top-level board container
# ---------------------------------------------------------------------------


@dataclass
class NativeBoard:
    """Top-level native PCB board: (kicad_pcb ...).

    Replaces kiutils Board for structured PCB reads. Provides typed access
    to all board elements without kiutils dependency.

    Kiutils-compatible properties (Council CRITICAL-2):
      graphicItems -> returns graphic_items (pcb_ops.py, board_outline.py, etc.)
      traceItems   -> returns segments + vias combined (maze_generator.py)
      layers       -> returns general.layers (export/general.py)
    """

    version: str = ""
    generator: str = ""
    nets: list[NativeNet] = field(default_factory=list)
    footprints: list[NativeFootprint] = field(default_factory=list)
    segments: list[NativeSegment] = field(default_factory=list)
    vias: list[NativeVia] = field(default_factory=list)
    zones: list[NativeZone] = field(default_factory=list)
    net_classes: list[NativeNetClass] = field(default_factory=list)
    graphic_items: list[NativeGraphicItem] = field(default_factory=list)
    board_outline: NativeBoardOutline | None = None
    raw_content: str = ""
    file_path: str = ""
    general: NativeGeneral = field(default_factory=NativeGeneral)
    setup: NativeSetup | None = None

    @property
    def graphicItems(self) -> list[NativeGraphicItem]:
        """Kiutils compatibility: pcb_ops.py, board_outline.py, maze_generator.py."""
        return self.graphic_items

    @property
    def traceItems(self) -> list:
        """Kiutils compatibility: maze_generator.py accesses board.traceItems."""
        return list(self.segments) + list(self.vias)

    @property
    def layers(self) -> list:
        """Kiutils compatibility: export/general.py accesses board.layers."""
        return self.general.layers


__all__ = [
    "_NativePosition",
    "NativeNet",
    "NativeNetClass",
    "NativePad",
    "NativeFootprint",
    "NativeSegment",
    "NativeVia",
    "NativeGraphicItem",
    "NativeZone",
    "NativeBoardOutline",
    "NativeGeneral",
    "NativeStackup",
    "NativeSetup",
    "NativeBoard",
]
