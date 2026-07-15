"""Schematic IR -- thin wrapper over a kiutils Schematic object with mutation tracking.

D-05: Holds reference to kiutils Schematic (not a copy).
D-06: Tracks mutations, dirty flag.
D-07: Schematic-specific IR.

Usage:
    from volta.ir.schematic_ir import SchematicIR
    from volta.parser import parse_schematic

    result = parse_schematic(Path("my_schematic.kicad_sch"))
    ir = SchematicIR(_parse_result=result)
    component = ir.get_component_by_ref("U1")
"""

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Optional

from kiutils.schematic import Schematic

from volta.ir.base import BaseIR
from volta.parser.types import ParseResult
from volta.parser.uuid_extractor import UUIDMap

# Regex for parsing reference designators: prefix (alpha + optional #) + numeric suffix or '?'
_REF_PATTERN = re.compile(r"^([#A-Za-z]+)(\d+|\?)$")


def _match_lib_symbol(lib_sym, comp_lib_id: str) -> bool:
    """Check if a lib_symbol matches a component's libId.

    Handles Issue #6: when libraryNickname is None on the lib symbol,
    its libId may lack the library prefix (e.g., "AK4619VN" instead of
    "Audio_Codec:AK4619VN"). Falls back to matching on entryName alone.

    Args:
        lib_sym: A kiutils lib symbol object with libId and entryName attrs.
        comp_lib_id: The component's libId (e.g., "Audio_Codec:AK4619VN").

    Returns:
        True if the lib symbol matches the component's libId.
    """
    sym_lib_id = getattr(lib_sym, "libId", "")
    if sym_lib_id == comp_lib_id:
        return True
    # Fallback: match by entryName when lib symbol has no nickname
    if ":" in comp_lib_id:
        comp_entry = comp_lib_id.split(":")[-1]
        sym_entry = getattr(lib_sym, "entryName", None) or (
            sym_lib_id.split(":")[-1] if ":" in sym_lib_id else sym_lib_id
        )
        if sym_entry and sym_entry == comp_entry and ":" not in sym_lib_id:
            return True
    return False


@dataclass
class SchematicIR(BaseIR):
    """Thin wrapper over a kiutils Schematic object with mutation tracking.

    D-05: Holds reference to kiutils Schematic (not a copy).
    D-06: Tracks mutations, dirty flag.
    D-07: Schematic-specific IR.
    """

    def __post_init__(self) -> None:
        """Validate file type matches schematic."""
        super().__post_init__()
        if self.file_type != "schematic":
            raise ValueError(
                f"Expected file_type='schematic', got {self.file_type!r}"
            )

    @property
    def schematic(self) -> Schematic:
        """Direct access to the kiutils Schematic object."""
        return self._parse_result.kiutils_obj

    @property
    def components(self) -> list:
        """Access to schematic symbols (components)."""
        return self._parse_result.kiutils_obj.schematicSymbols

    def get_component_by_ref(self, reference: str) -> Optional[Any]:
        """Find a component by its reference designator.

        Args:
            reference: The reference designator to search for (e.g. "U1", "R3").

        Returns:
            The matching kiutils SchematicSymbol, or None if not found.
        """
        for sym in self._parse_result.kiutils_obj.schematicSymbols:
            for prop in sym.properties:
                if prop.key == "Reference" and prop.value == reference:
                    return sym
        return None

    def get_component_property(self, component: Any, property_key: str) -> Optional[str]:
        """Get a specific property value from a component.

        Args:
            component: A kiutils SchematicSymbol object.
            property_key: The property key to look up (e.g. "Reference", "Value").

        Returns:
            The property value string, or None if not found.
        """
        for prop in component.properties:
            if prop.key == property_key:
                return prop.value
        return None

    def get_labels_by_name(self, name: str) -> list:
        """Find all local labels with matching text.

        Args:
            name: Label text to search for.

        Returns:
            List of kiutils LocalLabel objects with text matching the name.
        """
        return [
            label
            for label in self._parse_result.kiutils_obj.labels
            if label.text == name
        ]

    @property
    def bus_aliases(self) -> list:
        """Access to schematic bus aliases (KiCad 10+)."""
        return self._parse_result.kiutils_obj.busAliases

    def get_all_references(self) -> list[tuple[str, str]]:
        """Get all (reference, libId) pairs from schematic symbols.

        Returns:
            List of (reference, libId) tuples for every component.
        """
        result: list[tuple[str, str]] = []
        for sym in self._parse_result.kiutils_obj.schematicSymbols:
            ref = self.get_component_property(sym, "Reference")
            if ref is None:
                ref = ""
            result.append((ref, sym.libId))
        return result

    def _set_component_reference(self, component: Any, new_ref: str) -> None:
        """Update the Reference property on a schematic symbol.

        Args:
            component: A kiutils SchematicSymbol.
            new_ref: The new reference designator string.
        """
        for prop in component.properties:
            if prop.key == "Reference":
                prop.value = new_ref
                return

    def renumber_references(
        self, prefix: str = "", start_index: int = 1, step: int = 1
    ) -> list[tuple[str, str]]:
        """Renumber component references with configurable prefix and sequencing.

        Args:
            prefix: Only renumber components with this prefix (e.g. "R", "U").
                    Empty string means renumber all components, grouped by prefix.
            start_index: Starting index for numbering (default 1).
            step: Step between indices (default 1).

        Returns:
            List of (old_ref, new_ref) tuples showing what changed.
        """
        # Iterate components directly to avoid index coupling between two lists
        parsed: list[tuple[str, int, Any]] = []
        for comp in self._parse_result.kiutils_obj.schematicSymbols:
            ref = self.get_component_property(comp, "Reference") or ""
            m = _REF_PATTERN.match(ref)
            if m and m.group(2) != "?":
                parsed.append((m.group(1), int(m.group(2)), comp))

        # Group by prefix
        groups: dict[str, list[tuple[int, Any]]] = {}
        for ref_prefix, num, comp in parsed:
            groups.setdefault(ref_prefix, []).append((num, comp))

        # Filter to target prefix if specified
        if prefix:
            groups = {k: v for k, v in groups.items() if k == prefix}

        changes: list[tuple[str, str]] = []
        for grp_prefix, members in groups.items():
            # Sort by current numeric suffix
            members.sort(key=lambda x: x[0])
            for idx, (old_num, comp) in enumerate(members):
                new_num = start_index + idx * step
                old_ref = f"{grp_prefix}{old_num}"
                new_ref = f"{grp_prefix}{new_num}"
                if old_ref != new_ref:
                    self._set_component_reference(comp, new_ref)
                    self._record_mutation(
                        "renumber_reference",
                        {"old_ref": old_ref, "new_ref": new_ref},
                    )
                    changes.append((old_ref, new_ref))

        return changes

    def validate_reference_uniqueness(self) -> list[str]:
        """Check that all references are unique.

        Returns:
            List of reference strings that appear more than once. Empty if all unique.
        """
        all_refs = self.get_all_references()
        ref_strs = [r for r, _ in all_refs]
        counts = Counter(ref_strs)
        return [ref for ref, count in counts.items() if count > 1]

    def annotate_components(self, prefix_filter: str = "") -> list[tuple[str, str]]:
        """Auto-assign references to unannotated components (refs ending in '?').

        Args:
            prefix_filter: Only annotate components with this prefix (e.g. "R").
                           Empty string means annotate all unannotated.

        Returns:
            List of (old_ref, new_ref) tuples showing what was annotated.
        """
        symbols = self._parse_result.kiutils_obj.schematicSymbols

        # Find unannotated refs (ending in '?') by iterating symbols directly
        unannotated: list[tuple[str, Any]] = []
        for comp in symbols:
            ref = self.get_component_property(comp, "Reference") or ""
            if ref.endswith("?"):
                unannotated.append((ref, comp))

        # Apply prefix filter
        if prefix_filter:
            unannotated = [
                (ref, comp)
                for ref, comp in unannotated
                if ref.startswith(prefix_filter)
            ]

        if not unannotated:
            return []

        # Find max existing numeric suffix per prefix across all annotated refs
        max_per_prefix: dict[str, int] = {}
        for comp in symbols:
            ref = self.get_component_property(comp, "Reference") or ""
            m = _REF_PATTERN.match(ref)
            if m and m.group(2) != "?":
                max_per_prefix[m.group(1)] = max(
                    max_per_prefix.get(m.group(1), 0), int(m.group(2))
                )

        changes: list[tuple[str, str]] = []
        # Track per-prefix counter for this annotation pass
        counters: dict[str, int] = {
            p: max_per_prefix.get(p, 0) for p in max_per_prefix
        }
        # Also include prefixes that only appear in unannotated refs
        for ref, _ in unannotated:
            m = _REF_PATTERN.match(ref)
            if m:
                p = m.group(1)
                if p not in counters:
                    counters[p] = 0

        for old_ref, comp in unannotated:
            m = _REF_PATTERN.match(old_ref)
            if not m:
                continue
            p = m.group(1)
            counters[p] = counters.get(p, 0) + 1
            new_ref = f"{p}{counters[p]}"
            self._set_component_reference(comp, new_ref)
            self._record_mutation(
                "annotate_component",
                {"old_ref": old_ref, "new_ref": new_ref},
            )
            changes.append((old_ref, new_ref))

        return changes

    def assign_footprint(self, reference: str, footprint_lib_id: str) -> None:
        """Assign a footprint to a component by updating the Footprint property.

        Args:
            reference: Component reference designator (e.g. "U1").
            footprint_lib_id: Footprint library reference (e.g. "Package_DIP:DIP-8_W7.62mm").

        Raises:
            ValueError: If reference not found.
        """
        comp = self.get_component_by_ref(reference)
        if comp is None:
            raise ValueError(f"Component '{reference}' not found")

        for prop in comp.properties:
            if prop.key == "Footprint":
                prop.value = footprint_lib_id
                self._record_mutation("assign_footprint", {
                    "reference": reference,
                    "footprint_lib_id": footprint_lib_id,
                })
                return

        # No Footprint property exists — create it
        from kiutils.items.common import Property, Position, Effects
        comp.properties.append(Property(
            key="Footprint",
            value=footprint_lib_id,
            id=len(comp.properties),
            position=Position(X=0.0, Y=0.0, angle=0.0),
            effects=Effects(),
        ))
        self._record_mutation("assign_footprint", {
            "reference": reference,
            "footprint_lib_id": footprint_lib_id,
            "created_property": True,
        })

    def get_component_footprint(self, reference: str) -> Optional[str]:
        """Get the current footprint libId for a component.

        Args:
            reference: Component reference designator.

        Returns:
            Footprint library string, or None if not set or component not found.
        """
        comp = self.get_component_by_ref(reference)
        if comp is None:
            return None
        return self.get_component_property(comp, "Footprint")

    def verify_pin_map(self, reference: str, footprint_lib_id: str) -> dict[str, Any]:
        """Verify that symbol pin numbers match footprint pad numbers.

        Checks the component's libId against the embedded libSymbols to find
        pin definitions, then compares against the footprint's pad numbers.

        Args:
            reference: Component reference designator.
            footprint_lib_id: Footprint library reference to verify against.

        Returns:
            Dict with:
            - 'symbol_pins': set of pin numbers from the symbol
            - 'footprint_pads': set of pad numbers (empty if no PCB loaded)
            - 'missing_in_footprint': pin numbers in symbol but not footprint
            - 'extra_in_footprint': pad numbers in footprint but not symbol
            - 'match': bool - True if all symbol pins have corresponding pads
        """
        comp = self.get_component_by_ref(reference)
        symbol_pins: set[str] = set()

        if comp is not None:
            # Look up the component's libId in embedded libSymbols
            comp_lib_id = comp.libId
            lib_symbols = self._parse_result.kiutils_obj.libSymbols
            if lib_symbols:
                for lib_sym in lib_symbols:
                    if _match_lib_symbol(lib_sym, comp_lib_id):
                        # Collect pin numbers from all units
                        for unit in lib_sym.units:
                            for pin in unit.pins:
                                if pin.number:
                                    symbol_pins.add(pin.number)
                        break

        # Footprint pads: without a loaded PCB, we can't check the actual
        # pad numbers. Return empty set for footprint_pads.
        footprint_pads: set[str] = set()

        missing_in_footprint = symbol_pins - footprint_pads
        extra_in_footprint = footprint_pads - symbol_pins

        return {
            "symbol_pins": symbol_pins,
            "footprint_pads": footprint_pads,
            "missing_in_footprint": missing_in_footprint,
            "extra_in_footprint": extra_in_footprint,
            "match": len(missing_in_footprint) == 0,
        }

    def cross_reference_check(self) -> list[tuple[str, str]]:
        """Verify all symbol libIds resolve to entries in the embedded libSymbols.

        Returns:
            List of (reference, libId) tuples for unresolved symbols. Empty if all resolve.
        """
        # Build set of valid libIds from embedded libSymbols
        valid_lib_ids: set[str] = set()
        lib_symbols = self._parse_result.kiutils_obj.libSymbols
        if lib_symbols:
            for sym in lib_symbols:
                if hasattr(sym, "libId") and sym.libId:
                    valid_lib_ids.add(sym.libId)
                # Also check extends chain
                if hasattr(sym, "extends") and sym.extends:
                    # The extending symbol inherits from the parent
                    pass

        # Issue #6: Also check entryName-based matching for nickname-less symbols
        entry_name_map: dict[str, str] = {}
        for sym in lib_symbols or []:
            sym_lib_id = getattr(sym, "libId", "")
            if ":" not in sym_lib_id and sym_lib_id:
                entry_name_map[sym_lib_id] = sym_lib_id

        unresolved: list[tuple[str, str]] = []
        for comp in self._parse_result.kiutils_obj.schematicSymbols:
            ref = self.get_component_property(comp, "Reference") or ""
            lib_id = comp.libId
            if lib_id and lib_id not in valid_lib_ids:
                # Issue #6 fallback: check by entryName
                if ":" in lib_id:
                    entry = lib_id.split(":")[-1]
                    if entry in entry_name_map:
                        continue
                unresolved.append((ref, lib_id))

        return unresolved

    # -------------------------------------------------------------------
    # Net resolution (Phase 129: net-aware wire generation)
    # -------------------------------------------------------------------

    # Tolerance for position matching when resolving nets. KiCad schematics
    # use a 1.27mm grid; 0.5mm is tight enough to avoid cross-grid collisions
    # while tolerating minor float drift from symbol rotation math.
    _NET_POS_TOL: float = 0.5

    # Reference prefix for power symbols. KiCad uses "#PWRxxxx" for invisible
    # power-port references; the rail name lives in the Value property.
    _PWR_REF_PREFIX: str = "#PWR"

    # lib_id prefix for KiCad's standard power library.
    _PWR_LIB_PREFIX: str = "power:"

    def _is_power_symbol(self, component: Any) -> bool:
        """Detect whether a component is a KiCad power symbol.

        Power symbols declare a global net through their Value (e.g. "+5V",
        "GND", "-12V"). They are recognised two ways:
            1. Reference designator starts with "#PWR" (invisible power port)
            2. lib_id starts with "power:" (KiCad's standard power library)

        Args:
            component: A kiutils SchematicSymbol.

        Returns:
            True if the component is a power symbol.
        """
        ref = self.get_component_property(component, "Reference") or ""
        if ref.startswith(self._PWR_REF_PREFIX):
            return True
        lib_id = getattr(component, "libId", "") or ""
        if lib_id.startswith(self._PWR_LIB_PREFIX):
            return True
        return False

    def _resolve_net_at_position(
        self, x: float, y: float, _tol: float | None = None
    ) -> Optional[str]:
        """Determine the net name at a given schematic position.

        Checks (in order of precision):
            1. Labels at this position (local, global, hierarchical) -- a label
               directly at the coordinate wins outright.
            2. Component pins at this position -- if the pin belongs to a power
               symbol, the symbol's Value is the net name.
            3. Wire graph traversal (BFS) -- walk connected wire endpoints up
               to a depth limit looking for a labelled position.

        Args:
            x, y: Position in mm.
            _tol: Position tolerance in mm. Defaults to ``_NET_POS_TOL``
                (0.5mm) which is tighter than the 1.27mm KiCad grid.

        Returns:
            Net name if one can be resolved, ``None`` if the position has no
            determinable net assignment (e.g. empty space or unconnected wire).
        """
        tol = _tol if _tol is not None else self._NET_POS_TOL

        # 1. Labels at position -- direct, most precise.
        for label in self.get_label_positions():
            if abs(label["x"] - x) <= tol and abs(label["y"] - y) <= tol:
                return label["name"]

        # 2. Power-symbol pins at position.
        for pin in self.get_pin_positions():
            if abs(pin["x"] - x) > tol or abs(pin["y"] - y) > tol:
                continue
            comp = self.get_component_by_ref(pin.get("reference", ""))
            if comp is not None and self._is_power_symbol(comp):
                value = self.get_component_property(comp, "Value")
                if value:
                    return value

        # 3. BFS through the wire graph for a labelled position.
        return self._trace_wire_to_net(x, y, tol)

    def _trace_wire_to_net(
        self,
        start_x: float,
        start_y: float,
        tol: float,
        _max_depth: int = 64,
    ) -> Optional[str]:
        """BFS through wire endpoints to find a labelled net.

        Starts at (start_x, start_y) and walks the wire graph (wires sharing
        endpoints within ``tol``) until a position with a label is reached or
        the depth budget is exhausted.

        Args:
            start_x, start_y: Seed position in mm.
            tol: Endpoint matching tolerance in mm.
            _max_depth: Maximum number of wire hops before giving up.

        Returns:
            Net name from the first labelled position reached, or ``None``.
        """
        # Pre-compute label positions once.
        labels = self.get_label_positions()
        if not labels:
            return None

        # Fast exit: if the seed itself is labelled, return it.
        for label in labels:
            if abs(label["x"] - start_x) <= tol and abs(label["y"] - start_y) <= tol:
                return label["name"]

        wires = self.get_wire_endpoints()
        if not wires:
            return None

        def _near(a: tuple[float, float], b: tuple[float, float]) -> bool:
            return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol

        seed = (start_x, start_y)
        # Build an adjacency list keyed by coordinate tuples to avoid O(N^2)
        # scans during BFS. Two wires are "connected" if any of their
        # endpoints match within tolerance.
        endpoints: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for w in wires:
            endpoints.append(((w["start_x"], w["start_y"]), (w["end_x"], w["end_y"])))

        visited_edges: set[int] = set()
        visited_nodes: set[tuple[float, float]] = set()
        # Normalise seed into the visited set using rounding so equivalent
        # float coords collapse together.
        def _key(pt: tuple[float, float]) -> tuple[float, float]:
            return (round(pt[0], 3), round(pt[1], 3))

        frontier: list[tuple[float, float]] = [seed]
        visited_nodes.add(_key(seed))

        for _ in range(_max_depth):
            if not frontier:
                break
            next_frontier: list[tuple[float, float]] = []
            for node in frontier:
                # Check labels at this node.
                for label in labels:
                    if abs(label["x"] - node[0]) <= tol and abs(label["y"] - node[1]) <= tol:
                        return label["name"]
                # Expand to neighbouring wire endpoints.
                for idx, (a, b) in enumerate(endpoints):
                    if idx in visited_edges:
                        continue
                    if _near(a, node) or _near(b, node):
                        visited_edges.add(idx)
                        other = b if _near(a, node) else a
                        if _key(other) not in visited_nodes:
                            visited_nodes.add(_key(other))
                            next_frontier.append(other)
            frontier = next_frontier

        return None

    def add_wire(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        force: bool = False,
    ) -> dict[str, Any]:
        """Add a wire segment between two points.

        Phase 129 -- net-aware wire generation:

            Before creating the wire, the method resolves the net at each
            endpoint (via :meth:`_resolve_net_at_position`). If both
            endpoints resolve to *different* nets, the wire is rejected with
            a :class:`ValueError` because it would short two power rails or
            signals together (the root cause of the backplane +5V/+3V3/GND
            shorts generated in Phase 26).

            Callers who genuinely need to override the check (e.g. to merge
            two ground variants, or to wire an as-yet-unlabelled position)
            may pass ``force=True``. The override is logged in the mutation
            trail for auditability.

        Args:
            start_x: Start X coordinate in mm.
            start_y: Start Y coordinate in mm.
            end_x: End X coordinate in mm.
            end_y: End Y coordinate in mm.
            force: When ``True``, skip net-conflict validation. The conflict
                (if any) is still recorded in the returned dict under
                ``"net_conflict_overridden"`` for traceability. Default
                ``False`` -- validation is ON.

        Returns:
            Dict with wire details. May include:

                - ``"net_conflict_overridden"``: present when ``force=True``
                  bypassed a detected conflict.
                - ``"duplicate"``: ``True`` when an identical wire already
                  exists and creation was skipped.

        Raises:
            ValueError: If the start and end endpoints resolve to different,
                non-empty net names. The error message includes both net
                names and the coordinates so callers can pinpoint the short
                in their generation pipeline.
        """
        import uuid
        from kiutils.items.schitems import Connection
        from kiutils.items.common import Position, Stroke

        # Net-conflict detection (Phase 129). Runs BEFORE the wire object is
        # constructed so we never mutate the schematic on a rejected call.
        start_net = self._resolve_net_at_position(start_x, start_y)
        end_net = self._resolve_net_at_position(end_x, end_y)
        net_conflict: Optional[dict[str, str]] = None
        if (
            start_net is not None
            and end_net is not None
            and start_net != end_net
        ):
            net_conflict = {"start_net": start_net, "end_net": end_net}
            if not force:
                raise ValueError(
                    f"Wire from ({start_x},{start_y}) to ({end_x},{end_y}) "
                    f"would short different nets: '{start_net}' and "
                    f"'{end_net}'. Wire creation rejected to prevent "
                    f"schematic corruption. Pass force=True to override."
                )

        wire = Connection(
            type="wire",
            points=[
                Position(X=start_x, Y=start_y),
                Position(X=end_x, Y=end_y),
            ],
            stroke=Stroke(width=0.0),
            uuid=str(uuid.uuid4()),
        )
        # Duplicate detection: skip if wire already exists at same position
        _tol = 0.01
        for existing in self.get_wire_endpoints():
            if (abs(existing["start_x"] - start_x) <= _tol
                    and abs(existing["start_y"] - start_y) <= _tol
                    and abs(existing["end_x"] - end_x) <= _tol
                    and abs(existing["end_y"] - end_y) <= _tol):
                result: dict[str, Any] = {
                    "start": [start_x, start_y],
                    "end": [end_x, end_y],
                    "duplicate": True,
                }
                if net_conflict is not None:
                    result["net_conflict_overridden"] = net_conflict
                return result

        self._parse_result.kiutils_obj.graphicalItems.append(wire)
        mutation_payload: dict[str, Any] = {
            "start": [start_x, start_y],
            "end": [end_x, end_y],
        }
        if net_conflict is not None:
            mutation_payload["net_conflict_overridden"] = net_conflict
        self._record_mutation("add_wire", mutation_payload)
        result = {
            "start": [start_x, start_y],
            "end": [end_x, end_y],
        }
        if net_conflict is not None:
            result["net_conflict_overridden"] = net_conflict
        return result

    def add_label(
        self,
        name: str,
        label_type: str = "local",
        x: float = 0.0,
        y: float = 0.0,
        angle: float = 0.0,
        shape: str = "input",
    ) -> dict[str, Any]:
        """Add a net label to the schematic.

        Skips creation if a label with the same name and type already exists
        at the same position (within 0.01mm tolerance).

        Args:
            name: Label text.
            label_type: One of "local", "global", "hierarchical".
            x: X coordinate in mm.
            y: Y coordinate in mm.
            angle: Rotation angle in degrees.
            shape: Shape for global/hierarchical labels.

        Returns:
            Dict with label details.
        """
        import uuid
        from kiutils.items.common import Position, Property
        from kiutils.items.schitems import LocalLabel, GlobalLabel, HierarchicalLabel

        # Duplicate detection: skip if same name+type already exists at same position
        tolerance = 0.01
        existing = self._find_existing_label(name, label_type, x, y, tolerance)
        if existing is not None:
            return existing

        pos = Position(X=x, Y=y, angle=angle)

        if label_type == "global":
            label = GlobalLabel(
                text=name,
                shape=shape,
                position=pos,
                uuid=str(uuid.uuid4()),
            )
            label.fieldsAutoplaced = True
            label.properties.append(Property(key="Intersheets", value=""))
            self._parse_result.kiutils_obj.globalLabels.append(label)
        elif label_type == "hierarchical":
            label = HierarchicalLabel(
                text=name,
                shape=shape,
                position=pos,
                uuid=str(uuid.uuid4()),
            )
            label.fieldsAutoplaced = True
            self._parse_result.kiutils_obj.hierarchicalLabels.append(label)
        else:
            label = LocalLabel(
                text=name,
                position=pos,
                uuid=str(uuid.uuid4()),
            )
            self._parse_result.kiutils_obj.labels.append(label)

        self._record_mutation("add_label", {
            "name": name,
            "label_type": label_type,
            "position": [x, y, angle],
            "shape": shape,
        })
        return {
            "name": name,
            "label_type": label_type,
            "position": [x, y],
        }

    def _find_existing_label(
        self, name: str, label_type: str, x: float, y: float, tolerance: float,
    ) -> dict[str, Any] | None:
        """Check if a label with same name and type exists at the given position.

        Returns existing label dict if found, None otherwise.
        """
        sch = self._parse_result.kiutils_obj
        if label_type == "global":
            existing_labels = sch.globalLabels
        elif label_type == "hierarchical":
            existing_labels = sch.hierarchicalLabels
        else:
            existing_labels = sch.labels

        for lbl in existing_labels:
            if hasattr(lbl, 'text') and lbl.text == name:
                lbl_x = lbl.position.X if hasattr(lbl.position, 'X') else 0
                lbl_y = lbl.position.Y if hasattr(lbl.position, 'Y') else 0
                if abs(lbl_x - x) <= tolerance and abs(lbl_y - y) <= tolerance:
                    return {"name": name, "label_type": label_type, "position": [lbl_x, lbl_y]}
        return None

    def _ensure_power_lib_symbol(self, name: str) -> None:
        """Ensure a power symbol lib_symbol with pin definition is embedded.

        Power symbols (PWR_FLAG, GND, +5V, etc.) need an embedded lib_symbol
        entry with a pin definition so that SchematicGraph can resolve pin
        positions for connectivity analysis.

        Args:
            name: Power symbol name (e.g. "PWR_FLAG", "GND", "+3V3").
        """
        lib_id = f"power:{name}"
        lib_symbols = self._parse_result.kiutils_obj.libSymbols
        if lib_symbols is None:
            lib_symbols = []
            self._parse_result.kiutils_obj.libSymbols = lib_symbols

        # Check if already embedded
        for sym in lib_symbols:
            sym_lib_id = getattr(sym, 'libId', '')
            if sym_lib_id == lib_id:
                return  # Already embedded

        from kiutils.symbol import Symbol, SymbolPin
        from kiutils.items.common import Position

        pin = SymbolPin(
            name="1",
            number="1",
            electricalType="power_in",
            position=Position(0, 0),
            length=0,
        )
        stub = Symbol(
            libraryNickname="power",
            entryName=name,
            isPower=True,
        )
        stub.pins.append(pin)
        lib_symbols.append(stub)

    def add_power_symbol(
        self,
        name: str,
        x: float = 0.0,
        y: float = 0.0,
        angle: float = 0.0,
    ) -> dict[str, Any]:
        """Add a power symbol (from the power library) to the schematic.

        Power symbols (e.g. +5V, GND) are placed as SchematicSymbol objects
        with libId ``power:<name>``. They carry a single power-output pin
        that connects to the named net.

        Args:
            name: Power net name (e.g. "+5V", "GND", "+3V3").
            x: X coordinate in mm.
            y: Y coordinate in mm.
            angle: Rotation angle in degrees.

        Returns:
            Dict with the placed power symbol details.
        """
        import uuid
        from kiutils.items.common import Position, Property, Effects, Font
        from kiutils.items.schitems import SchematicSymbol

        lib_id = f"power:{name}"
        pos = Position(X=x, Y=y, angle=angle)
        sym_uuid = str(uuid.uuid4())

        sym = SchematicSymbol(
            libraryNickname="power",
            entryName=name,
            position=pos,
            uuid=sym_uuid,
            properties=[
                Property(
                    key="Reference",
                    value="#PWR?",
                    id=0,
                    position=Position(X=0.0, Y=0.0, angle=0.0),
                    effects=Effects(font=Font()),
                ),
                Property(
                    key="Value",
                    value=name,
                    id=1,
                    position=Position(X=0.0, Y=0.0, angle=0.0),
                    effects=Effects(font=Font()),
                ),
                Property(
                    key="Footprint",
                    value="",
                    id=2,
                    position=Position(X=0.0, Y=0.0, angle=0.0),
                    effects=Effects(font=Font()),
                ),
            ],
        )
        # Ensure the power symbol's lib_symbol definition is embedded
        # with a pin so SchematicGraph can resolve pin positions.
        self._ensure_power_lib_symbol(name)

        self._parse_result.kiutils_obj.schematicSymbols.append(sym)
        self._record_mutation("add_power_symbol", {
            "name": name,
            "lib_id": lib_id,
            "position": [x, y, angle],
        })
        return {
            "name": name,
            "lib_id": lib_id,
            "position": [x, y],
        }

    def add_no_connect(self, x: float = 0.0, y: float = 0.0) -> dict[str, Any]:
        """Add a no-connect flag at a position.

        Args:
            x: X coordinate in mm.
            y: Y coordinate in mm.

        Returns:
            Dict with position details.
        """
        import uuid
        from kiutils.items.common import Position
        from kiutils.items.schitems import NoConnect

        nc = NoConnect(
            position=Position(X=x, Y=y, angle=0),
            uuid=str(uuid.uuid4()),
        )
        self._parse_result.kiutils_obj.noConnects.append(nc)
        self._record_mutation("add_no_connect", {"position": [x, y]})
        return {"position": [x, y]}

    def add_design_note(
        self,
        text: str,
        x: float = 0.0,
        y: float = 0.0,
        angle: float = 0.0,
        note_type: str = "NOTE",
        target_ref: str | None = None,
        font_size_mm: float = 1.27,
    ) -> dict[str, Any]:
        """Add a design-intent annotation to the schematic (kicad-agent-29).

        Inserts a kiutils Text element capturing the WHY/WHAT/HOW of a design
        choice. Unlike net labels or refdes, design notes preserve design
        intent for reviewers and future designers.

        Args:
            text: Annotation content. Multi-line via literal "\\n".
            x: X coordinate in mm.
            y: Y coordinate in mm.
            angle: Text rotation in degrees (default 0).
            note_type: Semantic category. NOTE/REASON/MATH/BLOCK_HEADER.
                Prefixed into text as "[NOTE] " etc. for searchability.
            target_ref: Optional refdes (e.g. "R7") for tooling linkage.
                Stored in text prefix as "@R7" — does NOT affect placement.
            font_size_mm: Text height in mm (default 1.27).

        Returns:
            Dict with placement details + rendered text.
        """
        import uuid
        from kiutils.items.common import Position, Effects, Font, ColorRGBA
        from kiutils.items.schitems import Text as SchText

        # Prefix the note_type + target_ref into the text so it's grep-able.
        # Example: "[MATH] @R7 2.5/55000=45.5 [uA] + 5/1000000=5 [uA]"
        prefix = f"[{note_type}]"
        if target_ref:
            prefix += f" @{target_ref}"
        rendered_text = f"{prefix} {text}" if text else prefix

        text_obj = SchText(
            text=rendered_text,
            position=Position(X=x, Y=y, angle=angle),
            effects=Effects(
                font=Font(height=font_size_mm, width=font_size_mm, color=ColorRGBA(R=0, G=0, B=0, A=0)),
            ),
            uuid=str(uuid.uuid4()),
        )
        # Schematic text elements live in the `texts` collection on the kiutils object.
        if not hasattr(self._parse_result.kiutils_obj, "texts"):
            # Defensive — older kiutils versions may not expose this.
            self._parse_result.kiutils_obj.texts = []
        self._parse_result.kiutils_obj.texts.append(text_obj)

        self._record_mutation("add_design_note", {
            "text": rendered_text,
            "position": [x, y],
            "angle": angle,
            "note_type": note_type,
            "target_ref": target_ref,
            "font_size_mm": font_size_mm,
        })
        return {
            "text": rendered_text,
            "position": [x, y],
            "note_type": note_type,
            "target_ref": target_ref,
        }

    def add_junction(self, x: float = 0.0, y: float = 0.0) -> dict[str, Any]:
        """Add a junction dot at a wire intersection.

        Args:
            x: X coordinate in mm.
            y: Y coordinate in mm.

        Returns:
            Dict with position details.
        """
        import uuid
        from kiutils.items.common import Position
        from kiutils.items.schitems import Junction

        jct = Junction(
            position=Position(X=x, Y=y),
            uuid=str(uuid.uuid4()),
        )
        self._parse_result.kiutils_obj.junctions.append(jct)
        self._record_mutation("add_junction", {"position": [x, y]})
        return {"position": [x, y]}

    # -------------------------------------------------------------------
    # Pin / wire / label position helpers (for repair operations)
    # -------------------------------------------------------------------

    def get_pin_positions(self) -> list[dict[str, Any]]:
        """Return all pin absolute positions with symbol reference and pin name.

        Computes absolute pin positions using the Y-inversion pattern:
            absolute = (sx + rotated_px, sy - rotated_py)
        where (sx, sy) is the symbol placement position and (px, py) is the
        pin offset in the library definition. Rotation is applied to (px, py)
        before translation.

        T-10-11: Explicit Y-inversion via (sx+px, sy-py).

        Returns:
            List of dicts with keys: reference, pin_name, pin_number, x, y,
            electrical_type.
        """
        import math

        sch = self._parse_result.kiutils_obj

        # Build libId -> list of pin definitions from embedded libSymbols.
        # Issue #6: When libraryNickname is None, the lib symbol's libId may
        # not include the library prefix (e.g., "AK4619VN" vs "Audio_Codec:AK4619VN").
        # We build both a primary map (exact libId match) and a fallback map
        # keyed by entryName alone for nickname-less symbols.
        lib_pin_map: dict[str, list] = {}
        fallback_pin_map: dict[str, list] = {}
        for lib_sym in sch.libSymbols:
            lib_id = getattr(lib_sym, "libId", "")
            pins: list = []
            for unit in lib_sym.units:
                pins.extend(unit.pins)
            if pins:
                lib_pin_map[lib_id] = pins
                entry_name = getattr(lib_sym, "entryName", None) or (
                    lib_id.split(":")[-1] if ":" in lib_id else lib_id
                )
                # Only add fallback if libId doesn't already contain a nickname
                if ":" not in lib_id and entry_name:
                    fallback_pin_map[entry_name] = pins

        result: list[dict[str, Any]] = []
        for sym in sch.schematicSymbols:
            ref = self.get_component_property(sym, "Reference") or ""
            lib_id = sym.libId
            sx = sym.position.X
            sy = sym.position.Y
            angle_deg = sym.position.angle or 0.0
            angle_rad = math.radians(angle_deg)

            pin_defs = lib_pin_map.get(lib_id)
            if pin_defs is None:
                # Issue #6 fallback: try matching by entryName when the lib
                # symbol has no libraryNickname (libId lacks the prefix).
                entry = lib_id.split(":")[-1] if ":" in lib_id else lib_id
                pin_defs = fallback_pin_map.get(entry, [])
            for pin_def in pin_defs:
                px = pin_def.position.X
                py = pin_def.position.Y

                # Apply rotation to pin offset, then translate.
                # Y-inversion: KiCad pin Y is inverted relative to sheet coords.
                rot_px = px * math.cos(angle_rad) - py * math.sin(angle_rad)
                rot_py = px * math.sin(angle_rad) + py * math.cos(angle_rad)

                # T-10-11: pin absolute position = (sx + rot_px, sy - rot_py)
                abs_x = sx + rot_px
                abs_y = sy - rot_py

                result.append({
                    "reference": ref,
                    "pin_name": pin_def.name,
                    "pin_number": pin_def.number,
                    "x": abs_x,
                    "y": abs_y,
                    "electrical_type": pin_def.electricalType,
                })

        return result

    def get_wire_endpoints(self) -> list[dict[str, Any]]:
        """Return all wire start/end positions from graphicalItems.

        Wires are Connection objects with type='wire' in graphicalItems.

        Returns:
            List of dicts with keys: start_x, start_y, end_x, end_y, uuid,
            wire_index.
        """
        result: list[dict[str, Any]] = []
        sch = self._parse_result.kiutils_obj
        from kiutils.items.schitems import Connection

        for idx, item in enumerate(sch.graphicalItems):
            if isinstance(item, Connection) and item.type == "wire":
                if len(item.points) >= 2:
                    result.append({
                        "start_x": item.points[0].X,
                        "start_y": item.points[0].Y,
                        "end_x": item.points[1].X,
                        "end_y": item.points[1].Y,
                        "uuid": item.uuid,
                        "wire_index": idx,
                    })
        return result

    def get_label_positions(self) -> list[dict[str, Any]]:
        """Return all label positions with names.

        Includes local labels, global labels, and hierarchical labels.

        Returns:
            List of dicts with keys: name, x, y, label_type.
        """
        result: list[dict[str, Any]] = []
        sch = self._parse_result.kiutils_obj

        for label in sch.labels:
            result.append({
                "name": label.text,
                "x": label.position.X,
                "y": label.position.Y,
                "label_type": "local",
            })

        for label in sch.globalLabels:
            result.append({
                "name": label.text,
                "x": label.position.X,
                "y": label.position.Y,
                "label_type": "global",
            })

        for label in sch.hierarchicalLabels:
            result.append({
                "name": label.text,
                "x": label.position.X,
                "y": label.position.Y,
                "label_type": "hierarchical",
            })

        return result

    # -------------------------------------------------------------------
    # UUID-based lookup helpers (for remove operations)
    # -------------------------------------------------------------------

    def get_wire_by_uuid(self, uuid: str) -> Optional[Any]:
        """Find a wire Connection object by its UUID.

        Wires are Connection objects with type='wire' stored in graphicalItems.

        Args:
            uuid: The UUID string to search for.

        Returns:
            The matching kiutils Connection (wire), or None if not found.
        """
        from kiutils.items.schitems import Connection

        for item in self._parse_result.kiutils_obj.graphicalItems:
            if isinstance(item, Connection) and item.type == "wire":
                if item.uuid == uuid:
                    return item
        return None

    def get_label_by_uuid(self, uuid: str) -> Optional[Any]:
        """Find a label object by its UUID.

        Searches local labels, global labels, and hierarchical labels.

        Args:
            uuid: The UUID string to search for.

        Returns:
            The matching kiutils label object, or None if not found.
        """
        sch = self._parse_result.kiutils_obj

        for label in sch.labels:
            if label.uuid == uuid:
                return label

        for label in sch.globalLabels:
            if label.uuid == uuid:
                return label

        for label in sch.hierarchicalLabels:
            if label.uuid == uuid:
                return label

        return None

    def get_junction_by_uuid(self, uuid: str) -> Optional[Any]:
        """Find a Junction object by its UUID.

        Args:
            uuid: The UUID string to search for.

        Returns:
            The matching kiutils Junction, or None if not found.
        """
        for jct in self._parse_result.kiutils_obj.junctions:
            if jct.uuid == uuid:
                return jct
        return None

    def get_no_connect_by_uuid(self, uuid: str) -> Optional[Any]:
        """Find a NoConnect object by its UUID.

        Args:
            uuid: The UUID string to search for.

        Returns:
            The matching kiutils NoConnect, or None if not found.
        """
        for nc in self._parse_result.kiutils_obj.noConnects:
            if nc.uuid == uuid:
                return nc
        return None

    def get_adjacent_wires(
        self, wire_uuid: str, tolerance: float = 0.0001
    ) -> list:
        """Find wires that share an endpoint with the specified wire.

        Two wires are adjacent when the start or end coordinates of one
        match the start or end coordinates of the other within tolerance.

        Args:
            wire_uuid: UUID of the reference wire.
            tolerance: Maximum coordinate distance to consider as touching
                       (default 0.0001 mm).

        Returns:
            List of kiutils Connection (wire) objects adjacent to the
            reference wire, excluding the reference wire itself.
        """
        from kiutils.items.schitems import Connection

        ref = self.get_wire_by_uuid(wire_uuid)
        if ref is None or len(ref.points) < 2:
            return []

        ref_coords = {
            (ref.points[0].X, ref.points[0].Y),
            (ref.points[1].X, ref.points[1].Y),
        }

        adjacent: list = []
        for item in self._parse_result.kiutils_obj.graphicalItems:
            if not isinstance(item, Connection) or item.type != "wire":
                continue
            if item.uuid == wire_uuid or len(item.points) < 2:
                continue

            item_coords = [
                (item.points[0].X, item.points[0].Y),
                (item.points[1].X, item.points[1].Y),
            ]

            for ix, iy in item_coords:
                for rx, ry in ref_coords:
                    if abs(ix - rx) <= tolerance and abs(iy - ry) <= tolerance:
                        adjacent.append(item)
                        break
                else:
                    continue
                break

        return adjacent
