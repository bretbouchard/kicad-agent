"""PCB spatial model with per-layer Shapely geometry and STRtree indexing.

SI-01: Read-only derived view from PcbIR. Builds per-layer geometry
collections and STRtree spatial index for fast spatial queries.

SI-05: Uses _CLEARANCE_TOLERANCE_MM = 1e-4 for all distance comparisons
to prevent floating-point false positives.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from shapely import STRtree
from shapely.geometry import GeometryCollection

from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.spatial.board_outline import extract_board_outline
from kicad_agent.spatial.extractor import extract_all
from kicad_agent.spatial.layer_classifier import LayerClassifier
from kicad_agent.spatial.layer_stackup import LayerStackup
from kicad_agent.spatial.net_class_geometry import (
    NetClassGeometry,
    build_net_class_map,
)
from kicad_agent.spatial.query import SpatialQueryEngine

_CLEARANCE_TOLERANCE_MM: float = 1e-4  # SI-05: 0.1 micrometers


class PcbSpatialModel:
    """Read-only spatial model derived from PcbIR.

    Builds per-layer Shapely geometry collections and an STRtree spatial
    index from PcbIR data. Provides query methods for layer-based filtering,
    spatial indexing, and clearance computation.

    NOT a BaseIR subclass -- this is a derived view that holds a reference
    to the source PcbIR without copying it.

    Usage:
        from kicad_agent.spatial.pcb_model import PcbSpatialModel

        model = PcbSpatialModel.build_from_pcb_ir(pcb_ir)
        print(model.primitive_count)
        for layer_name in model.layer_names:
            print(layer_name, len(model.layer_primitives(layer_name)))
    """

    def __init__(self, pcb_ir: PcbIR, net_classes: list | None = None) -> None:
        """Initialize PcbSpatialModel from PcbIR.

        Args:
            pcb_ir: Source PCB intermediate representation.
            net_classes: Optional list of NetClassDef objects for per-net geometry params.
        """
        self._pcb_ir: PcbIR = pcb_ir
        self._net_classes_input: list | None = net_classes
        self._dirty: bool = False
        # These are populated by _build()
        self._layer_primitives: dict[str, list] = {}
        self._layer_geometry: dict[str, GeometryCollection] = {}
        self._tree: STRtree | None = None
        self._stackup: LayerStackup = LayerStackup(layers=(), total_thickness_mm=0.0)
        self._net_class_map: dict[str, NetClassGeometry] = {}
        self._all_primitives: list = []
        self._board_outline: Any = None
        self._query_engine: SpatialQueryEngine | None = None
        self._build()

    def _build(self) -> None:
        """Build per-layer geometry, STRtree index, and metadata from PcbIR.

        Called during __init__ and during rebuild() after mutations.
        """
        # Step 1: Extract all spatial primitives
        extracted = extract_all(self._pcb_ir)
        all_primitives: list = []
        for primitive_list in extracted.values():
            all_primitives.extend(primitive_list)
        self._all_primitives = all_primitives

        # Step 2: Group primitives by layer
        layer_map: dict[str, list] = defaultdict(list)
        for prim in all_primitives:
            layer_attr = getattr(prim, "layer", "")
            # Handle comma-separated layers (e.g. vias with multiple layers)
            if layer_attr:
                first_layer = layer_attr.split(",")[0]
                layer_map[first_layer].append(prim)

        self._layer_primitives = dict(layer_map)

        # Step 3: Build per-layer Shapely geometry collections
        self._layer_geometry = {}
        for layer_name, prims in layer_map.items():
            geometries = [p.to_shapely() for p in prims]
            self._layer_geometry[layer_name] = GeometryCollection(geometries)

        # Step 4: Build STRtree from all primitives
        if all_primitives:
            geometries = [p.to_shapely() for p in all_primitives]
            self._tree = STRtree(geometries)
        else:
            self._tree = None

        # Step 5: Build LayerStackup from board
        self._stackup = LayerStackup.from_board(self._pcb_ir.board)

        # Step 6: Build net class geometry map
        if self._net_classes_input is not None:
            self._net_class_map = build_net_class_map(self._net_classes_input)
        else:
            self._net_class_map = {}

        # Step 7: Extract board outline from Edge.Cuts
        self._board_outline = extract_board_outline(self._pcb_ir.board)

        # Step 8: Invalidate query engine (rebuilt lazily on access)
        self._query_engine = None

        # Step 9: Clear dirty flag
        self._dirty = False

    # ------------------------------------------------------------------
    # Public read-only properties
    # ------------------------------------------------------------------

    @property
    def stackup(self) -> LayerStackup:
        """Layer stackup metadata."""
        return self._stackup

    @property
    def net_class_map(self) -> dict[str, NetClassGeometry]:
        """Per-net-class geometry parameters."""
        return dict(self._net_class_map)

    @property
    def layer_names(self) -> list[str]:
        """Sorted list of layer names with geometry."""
        return sorted(self._layer_primitives.keys())

    @property
    def layer_geometry(self) -> dict[str, GeometryCollection]:
        """Per-layer Shapely GeometryCollection (copy)."""
        return dict(self._layer_geometry)

    @property
    def all_primitives(self) -> list:
        """All spatial primitives."""
        return list(self._all_primitives)

    @property
    def primitive_count(self) -> int:
        """Total number of spatial primitives."""
        return len(self._all_primitives)

    @property
    def is_dirty(self) -> bool:
        """Whether the model needs rebuilding after mutations."""
        return self._dirty

    @property
    def clearance_tolerance(self) -> float:
        """Clearance tolerance constant for distance comparisons."""
        return _CLEARANCE_TOLERANCE_MM

    @property
    def board_outline(self) -> Any:
        """Board outline polygon extracted from Edge.Cuts layer.

        Returns:
            Shapely Polygon for single outlines, MultiPolygon for
            disjoint outlines, or None if no Edge.Cuts items.
        """
        return self._board_outline

    @property
    def board_bounds(self) -> tuple[float, float, float, float] | None:
        """Board bounding box (minx, miny, maxx, maxy) or None if no outline."""
        return tuple(self._board_outline.bounds) if self._board_outline else None

    @property
    def query_engine(self) -> SpatialQueryEngine:
        """SpatialQueryEngine backed by current primitives.

        Rebuilds engine if dirty. Returned engine is consistent with
        current spatial model state.
        """
        if self._dirty:
            self.rebuild()
        if self._query_engine is None:
            self._query_engine = SpatialQueryEngine(self._all_primitives)
        return self._query_engine

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    def layer_primitives(self, layer_name: str) -> list:
        """Return primitives on a specific layer.

        Args:
            layer_name: KiCad layer name to filter by.

        Returns:
            List of spatial primitives on that layer (empty list if none).
        """
        return list(self._layer_primitives.get(layer_name, []))

    def geometry_for_layer(self, layer_name: str) -> GeometryCollection | None:
        """Return Shapely geometry for a specific layer.

        Args:
            layer_name: KiCad layer name.

        Returns:
            GeometryCollection for the layer, or None if no geometry exists.
        """
        return self._layer_geometry.get(layer_name)

    def copper_layer_primitives(self) -> dict[str, list]:
        """Return dict of primitives on copper layers only.

        Uses LayerClassifier.is_copper to filter layer names.

        Returns:
            Dict mapping copper layer names to their primitive lists.
        """
        return {
            name: list(prims)
            for name, prims in self._layer_primitives.items()
            if LayerClassifier.is_copper(name)
        }

    def get_net_class_geometry(self, net_name: str) -> NetClassGeometry:
        """Return geometry parameters for a net class name.

        Falls back to NetClassGeometry.default() if the net class
        is not found in the map.

        Args:
            net_name: Net class name to look up.

        Returns:
            NetClassGeometry with parameters for that class, or defaults.
        """
        return self._net_class_map.get(net_name, NetClassGeometry.default())

    def effective_clearance(self, entity_a_id: str, entity_b_id: str) -> float:
        """Compute effective clearance between two entities.

        Computes Shapely distance between the geometries of two entities
        identified by entity_id, then subtracts the clearance tolerance.

        Args:
            entity_a_id: Entity ID of the first entity.
            entity_b_id: Entity ID of the second entity.

        Returns:
            Effective clearance in mm: max(0.0, distance - tolerance).
            Returns 0.0 if entities overlap or either is not found.
        """
        prim_a = None
        prim_b = None
        for prim in self._all_primitives:
            if prim.entity_id == entity_a_id and prim_a is None:
                prim_a = prim
            if prim.entity_id == entity_b_id and prim_b is None:
                prim_b = prim
            if prim_a is not None and prim_b is not None:
                break

        if prim_a is None or prim_b is None:
            return 0.0

        geom_a = prim_a.to_shapely()
        geom_b = prim_b.to_shapely()
        distance = geom_a.distance(geom_b)

        return max(0.0, distance - _CLEARANCE_TOLERANCE_MM)

    def find_near(self, x: float, y: float, radius_mm: float) -> list:
        """Find all primitives within radius of point.

        Delegates to SpatialQueryEngine.proximity.

        Args:
            x: Query point X coordinate (mm).
            y: Query point Y coordinate (mm).
            radius_mm: Search radius in mm.

        Returns:
            List of primitives whose geometry intersects the query buffer.
        """
        return self.query_engine.proximity(x, y, radius_mm)

    def find_in_box(self, x1: float, y1: float, x2: float, y2: float) -> list:
        """Find all primitives fully contained within bounding box.

        Delegates to SpatialQueryEngine.containment.

        Args:
            x1: Min X of query box (mm).
            y1: Min Y of query box (mm).
            x2: Max X of query box (mm).
            y2: Max Y of query box (mm).

        Returns:
            List of primitives fully contained within the query box.
        """
        return self.query_engine.containment(x1, y1, x2, y2)

    def find_clearance(
        self, entity_id: str, search_radius_mm: float = 10.0
    ) -> list[tuple[Any, float]]:
        """Find nearby primitives with distances for a given entity.

        Delegates to SpatialQueryEngine.clearance.

        Args:
            entity_id: The entity_id of the target primitive.
            search_radius_mm: How far to search around the target (mm).

        Returns:
            List of (primitive, distance) tuples sorted by distance ascending.
        """
        return self.query_engine.clearance(entity_id, search_radius_mm)

    # ------------------------------------------------------------------
    # Dirty-flag methods (SI-07 preparation)
    # ------------------------------------------------------------------

    def mark_dirty(self) -> None:
        """Mark the model as needing rebuild after mutations."""
        self._dirty = True
        self._query_engine = None

    def rebuild(self) -> None:
        """Rebuild geometry and index if dirty; no-op if clean."""
        if self._dirty:
            self._build()

    def batch_update(self, update_fn: Any) -> None:
        """Apply a mutation to the underlying PcbIR and rebuild.

        Marks dirty, executes the update function, then rebuilds.

        Args:
            update_fn: Callable that takes a PcbIR as its argument.
                Used to mutate the underlying PCB data.
        """
        self.mark_dirty()
        update_fn(self._pcb_ir)
        self.rebuild()

    # ------------------------------------------------------------------
    # Factory method
    # ------------------------------------------------------------------

    @staticmethod
    def build_from_pcb_ir(
        pcb_ir: PcbIR,
        net_classes: list | None = None,
    ) -> PcbSpatialModel:
        """Construct a PcbSpatialModel from a PcbIR.

        Args:
            pcb_ir: Source PCB intermediate representation.
            net_classes: Optional list of NetClassDef objects.

        Returns:
            Fully-built PcbSpatialModel instance.
        """
        return PcbSpatialModel(pcb_ir=pcb_ir, net_classes=net_classes)
