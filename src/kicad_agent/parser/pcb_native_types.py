"""Native PCB dataclass types for KiCad 10+ .kicad_pcb files.

Replaces kiutils Board objects for PCB reads. Provides typed access to all
board elements (nets, footprints, zones, tracks, vias, net classes, graphic
items, board outline) without kiutils dependency.

All 14 dataclasses are FROZEN (Phase 100 CR-01 closure — Council Exec Review 99
§7.7-deferred critical finding). Mutation is only possible via
``dataclasses.replace()``, which produces a new instance and leaves the
original intact. This satisfies the project CRITICAL immutability rule
(``~/.claude/rules/coding-style.md``) and provides the snapshot semantics
required by the Phase 100 RoutingOrchestrator rollback mechanism (Plan 02).

Collection-typed fields default to ``tuple`` (not ``list``) — tuples are
immutable, so the board cannot be corrupted by ``board.nets.append(...)``.
``NativeFootprint.properties`` is exposed as a ``MappingProxyType`` view over
an internal tuple of ``(key, value)`` pairs: readers
(``fp.properties.get("Reference")``) work unchanged, while writers
(``fp.properties["x"] = "y"``) raise ``TypeError``.

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
from types import MappingProxyType
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


@dataclass(frozen=True)
class NativeNet:
    """Board-level net declaration: (net N "NAME")."""

    number: int = 0
    name: str = ""


@dataclass(frozen=True)
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
    add_nets: tuple[str, ...] = ()


@dataclass(frozen=True)
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


@dataclass(frozen=True)
class NativeFootprint:
    """Footprint placement: (footprint "lib:fp" ...).

    position is (x, y, angle). ``properties`` is exposed as a read-only
    ``MappingProxyType`` view (CR-01): readers work unchanged, writers raise
    ``TypeError``. The underlying storage is ``_properties_tuple`` of
    ``(key, value)`` pairs; mutation must go through ``dataclasses.replace``.

    MD-04/IN-01: the MappingProxyType view is materialized ONCE in
    ``__post_init__`` (via the frozen-safe ``object.__setattr__`` pattern)
    and cached in ``_properties_view``. Previously every ``fp.properties``
    access rebuilt the dict from the tuple — O(n) per access, noticeable
    when Phase 98 strategies iterate thousands of footprints.
    """

    lib_id: str = ""
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    pads: tuple["NativePad", ...] = ()
    _properties_tuple: tuple[tuple[str, str], ...] = ()
    layer: str = ""
    graphic_items: tuple = ()
    uuid: str = ""
    # MD-04: cached view, populated in __post_init__. Defaults to an empty
    # view so that any code path that bypasses __init__ still works.
    _properties_view: MappingProxyType[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        # MD-04: materialize the read-only view once. Frozen dataclasses
        # cannot assign in __init__, so we use object.__setattr__.
        # The view must always reflect _properties_tuple. We rebuild it
        # whenever _properties_tuple is non-empty OR _properties_view is
        # stale (empty while tuple is non-empty). dataclasses.replace copies
        # both fields, so after a replace that changed _properties_tuple we
        # must rebuild the view to stay consistent.
        object.__setattr__(
            self,
            "_properties_view",
            MappingProxyType(dict(self._properties_tuple)),
        )

    @property
    def properties(self) -> MappingProxyType[str, str]:
        """Read-only dict view over the internal properties tuple.

        Readers (``fp.properties.get("Reference")``) work unchanged.
        Writers (``fp.properties["x"] = "y"``) raise ``TypeError`` — use
        ``dataclasses.replace`` to update.

        MD-04: returns the cached view materialized in __post_init__ —
        no dict rebuild on every access.
        """
        return self._properties_view


@dataclass(frozen=True)
class NativeSegment:
    """Copper track segment: (segment (start X Y) (end X Y) (width W) (layer L) (net N)).

    CR-01: carries its KiCad uuid so callers can join on the stable UUID value
    rather than on a positional index. The UUID extractor and the parser use
    different traversal orders, so positional indices diverge on real boards
    (nested segments inside groups, mixed parent types). UUID is the identity
    the UUID system was designed to provide.
    """

    start: _NativePosition | None = None
    end: _NativePosition | None = None
    width: float = 0.0
    layer: str = ""
    net_number: int = 0
    net_name: str = ""
    uuid: str = ""


@dataclass(frozen=True)
class NativeVia:
    """Through-hole via: (via (at X Y) (size D) (drill DR) (net N)).

    CR-01: carries its KiCad uuid (same rationale as NativeSegment).
    """

    position: tuple[float, float] = (0.0, 0.0)
    drill: float = 0.0
    diameter: float = 0.0
    net_number: int = 0
    net_name: str = ""
    layers: tuple[str, str] = ("", "")
    uuid: str = ""


@dataclass(frozen=True)
class NativeGraphicItem:
    """Board-level graphic element: gr-line, gr-arc, gr-circle, gr-rect, gr-poly, gr-curve,
    gr-text, gr-text-box, dimension, target.

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


@dataclass(frozen=True)
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
    layers: tuple[str, ...] = ()
    polygon_points: tuple[tuple[float, float], ...] = ()
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


@dataclass(frozen=True)
class NativeBoardOutline:
    """Board outline: all graphic items on Edge.Cuts layer."""

    items: tuple[NativeGraphicItem, ...] = ()


@dataclass(frozen=True)
class NativeGeneral:
    """General board settings: (general ...).

    Council CRITICAL-2: needed by spatial/layer_stackup.py (board.general.thickness)
    and export/general.py (board.general.layers).
    """

    thickness: float = 1.6
    layers: tuple = ()


@dataclass(frozen=True)
class NativeStackupLayer:
    """Single layer in a stackup: (layer "F.Cu" (type "copper")) or (layer "dielectric 1" (type "core")).

    Phase 99 R-4: minimal typed representation for stackup-based via padstack
    emission. Only `name` and `type` are consumed by dsn_generator (to distinguish
    copper signal layers from dielectric cores). `thickness` is captured for
    future use but not yet read by any consumer.
    """

    name: str = ""
    type: str = ""
    thickness: float = 0.0


@dataclass(frozen=True)
class NativeStackup:
    """Board stackup definition: (setup (stackup ...)).

    Council CRITICAL-2: needed by spatial/layer_stackup.py (board.setup.stackup.layers).
    Phase 99 R-4: `layers` is now tuple[NativeStackupLayer, ...] (typed, frozen).
    """

    layers: tuple = ()


@dataclass(frozen=True)
class NativeSetup:
    """Board setup section: (setup ...).

    Council CRITICAL-2: needed by spatial/layer_stackup.py (board.setup.stackup).
    """

    stackup: NativeStackup | None = None


# ---------------------------------------------------------------------------
# Top-level board container
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NativeBoard:
    """Top-level native PCB board: (kicad_pcb ...).

    Replaces kiutils Board for structured PCB reads. Provides typed access
    to all board elements without kiutils dependency. Frozen (CR-01).

    Kiutils-compatible properties (Council CRITICAL-2):
      graphicItems -> returns list(graphic_items) (pcb_ops.py, board_outline.py)
      traceItems   -> returns list(segments) + list(vias) (maze_generator.py)
      layers       -> returns list(general.layers) (export/general.py)
    """

    version: str = ""
    generator: str = ""
    nets: tuple[NativeNet, ...] = ()
    footprints: tuple[NativeFootprint, ...] = ()
    segments: tuple[NativeSegment, ...] = ()
    vias: tuple[NativeVia, ...] = ()
    zones: tuple[NativeZone, ...] = ()
    net_classes: tuple[NativeNetClass, ...] = ()
    graphic_items: tuple[NativeGraphicItem, ...] = ()
    board_outline: NativeBoardOutline | None = None
    raw_content: str = ""
    file_path: str = ""
    # MD-03/WR-06: use default_factory instead of None + __post_init__ patch.
    # Cleanly type-safe, no # type: ignore, works on frozen dataclasses.
    general: NativeGeneral = field(default_factory=NativeGeneral)
    setup: NativeSetup | None = None

    @property
    def graphicItems(self) -> list[NativeGraphicItem]:
        """Kiutils compatibility: pcb_ops.py, board_outline.py, maze_generator.py."""
        return list(self.graphic_items)

    @property
    def traceItems(self) -> list:
        """Kiutils compatibility: maze_generator.py accesses board.traceItems."""
        return list(self.segments) + list(self.vias)

    @property
    def layers(self) -> list:
        """Kiutils compatibility: export/general.py accesses board.layers."""
        return list(self.general.layers)


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
    "NativeStackupLayer",
    "NativeSetup",
    "NativeBoard",
]
