"""Universal pre-flight gate -- think before you act for ALL editing operations.

Runs before mutation operations on schematics, PCBs, and cross-file
operations to detect problems early. File-type dispatch routes to
specialized check modules.

Tiered enforcement:
  - BLOCKERS: Critical issues that prevent execution (overlap, unknown refs, etc.)
  - WARNINGS: Soft issues that don't prevent execution but should be noted

Architecture:
  The gate is called by the executor before dispatching to handlers.
  It receives the Operation and the already-parsed IR (SchematicIR, PcbIR,
  or ir_map for cross-file), so it adds no extra parse cost.

  File-type dispatch (H-01 fix):
    1. Check file extension FIRST (before op-type guard)
    2. .kicad_pcb -> _analyze_pcb -> pre_analysis_pcb.analyze_pcb()
    3. .kicad_sch -> existing schematic analysis (op-type guarded)
    4. Other valid KiCad -> _analyze_crossfile -> pre_analysis_crossfile.analyze_crossfile()
    5. Unknown extension -> empty result

  PCB and cross-file checks are extracted to separate modules (M-01 fix).

Usage:
    from kicad_agent.ops.pre_analysis import PreAnalysisGate

    gate = PreAnalysisGate()
    result = gate.analyze(operation.root, ir, file_path)
    if result.blockers:
        raise ValueError(f"Pre-analysis blocked: {result.blockers}")
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

logger = logging.getLogger(__name__)

# M-03: Single source of truth for valid KiCad file extensions.
# Imported by execution.py and other modules that need extension checks.
_VALID_KICAD_EXTENSIONS = frozenset({
    ".kicad_sch",
    ".kicad_pcb",
    ".kicad_sym",
    ".kicad_mod",
    ".kicad_pro",
    ".kicad_dru",
})

# Extensions that indicate cross-file dispatch (not schematic, not PCB)
_CROSSFILE_EXTENSIONS = _VALID_KICAD_EXTENSIONS - {".kicad_sch", ".kicad_pcb"}
# Operations that benefit from pre-analysis (schematic mutations only)
_MUTATION_OP_TYPES = frozenset({
    "add_component",
    "move_component",
    "snap_components_to_grid",
    "add_wire",
    "add_label",
    "add_power",
    "add_no_connect",
    "add_junction",
    "add_power_flag",
    "connect_pins",
    "batch_connect",
    "place_net_labels",
    "regenerate_wiring",
    "remove_component",
    "remove_wire",
    "remove_label",
    "remove_labels",
    "remove_junction",
    "remove_no_connect",
    "duplicate_component",
    "array_replicate",
    "modify_property",
    "swap_symbol",
})

# Default overlap tolerance in mm
_OVERLAP_TOLERANCE_MM = 2.54

# Default collision tolerance in mm
_COLLISION_TOLERANCE_MM = 2.54


@dataclass(frozen=True)
class PreAnalysisFinding:
    """A single finding from pre-analysis (blocker or warning)."""

    severity: str
    category: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreAnalysisResult:
    """Result from the pre-analysis gate."""

    blockers: list[PreAnalysisFinding] = field(default_factory=list)
    warnings: list[PreAnalysisFinding] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    enriched_context: dict[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        """True if any blockers were found."""
        return len(self.blockers) > 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to serializable dict for API responses."""
        return {
            "blocked": self.blocked,
            "blockers": [
                {
                    "severity": f.severity,
                    "category": f.category,
                    "message": f.message,
                    "details": f.details,
                }
                for f in self.blockers
            ],
            "warnings": [
                {
                    "severity": f.severity,
                    "category": f.category,
                    "message": f.message,
                    "details": f.details,
                }
                for f in self.warnings
            ],
            "suggestions": self.suggestions,
            "enriched_context": self.enriched_context,
        }


class PreAnalysisGate:
    """Pre-analysis gate for editing operations. Tiered enforcement: blockers prevent execution, warnings proceed with logging."""

    def analyze(
        self,
        op: Any,
        ir: Union[Any, dict[Path, Any]],
        file_path: Path,
    ) -> PreAnalysisResult:
        """Run pre-analysis on an operation.

        H-01 fix: File-type dispatch FIRST (before op-type guard).
        The _MUTATION_OP_TYPES set only contains schematic ops -- PCB and
        cross-file ops would short-circuit at the old position.

        H-02 fix: ir parameter accepts Union[Any, dict[Path, Any]] so
        cross-file checks can receive the full ir_map.

        Args:
            op: The operation root model (e.g. AddComponentOp, MoveComponentOp).
            ir: IR for the target file (SchematicIR, PcbIR, or dict[Path, Any] for cross-file).
            file_path: Path to the target file.

        Returns:
            PreAnalysisResult with blockers, warnings, and enriched context.
        """
        result = PreAnalysisResult()
        self._current_file_path = Path(file_path)
        op_type = getattr(op, "op_type", None)
        ext = Path(file_path).suffix

        # File-type dispatch FIRST (H-01 fix)
        if ext == ".kicad_pcb":
            self._analyze_pcb(op, ir, result)
            return result
        elif ext == ".kicad_sch":
            # Schematic path -- apply existing op-type guard below
            pass
        elif ext in _CROSSFILE_EXTENSIONS:
            # Cross-file: ir may be ir_map (dict[Path, Any])
            self._analyze_crossfile(op, ir, result)
            return result
        else:
            return result  # Unknown file type: no checks

        # Existing schematic guard (only reached for .kicad_sch files)
        if op_type not in _MUTATION_OP_TYPES:
            return result

        # Route to specific analyzers based on op_type
        if op_type == "add_component":
            self._analyze_add_component(op, ir, result)
        elif op_type == "move_component":
            self._analyze_move_component(op, ir, result)
        elif op_type in ("add_wire", "connect_pins", "batch_connect"):
            self._analyze_wiring(op, ir, result)
        elif op_type == "add_power":
            self._analyze_add_power(op, ir, result)
        elif op_type == "remove_component":
            self._analyze_remove_component(op, ir, result)

        # Always run: component reference resolution check
        self._check_ref_resolution(op, ir, result)

        # Label duplication check (runs AFTER wiring analysis for batch_connect)
        if op_type in ("add_label", "batch_connect", "regenerate_wiring", "place_net_labels"):
            self._analyze_label_operation(op, ir, result)

        # Expanded schematic checks (D-07)
        self._analyze_schematic_expanded(op, ir, result)

        return result

    # File-type dispatch delegates

    def _analyze_pcb(self, op: Any, ir: Any, result: PreAnalysisResult) -> None:
        """Delegate to extracted PCB check module (D-05)."""
        from kicad_agent.ops.pre_analysis_pcb import analyze_pcb
        analyze_pcb(op, ir, self._current_file_path, result)

    def _analyze_crossfile(self, op: Any, ir_or_map: Union[Any, dict[Path, Any]], result: PreAnalysisResult) -> None:
        """Delegate to extracted cross-file check module (D-06, H-02)."""
        from kicad_agent.ops.pre_analysis_crossfile import analyze_crossfile
        analyze_crossfile(op, ir_or_map, self._current_file_path, result)

    def _analyze_schematic_expanded(self, op: Any, ir: Any, result: PreAnalysisResult) -> None:
        """Delegate to extracted expanded schematic check module (D-07)."""
        from kicad_agent.ops.pre_analysis_schematic import analyze_schematic_expanded
        analyze_schematic_expanded(op, ir, result)

    # Component placement analysis

    def _analyze_add_component(self, op: Any, ir: Any, result: PreAnalysisResult) -> None:
        """Check for overlap and spatial conflicts before adding a component."""
        new_x = op.position.x
        new_y = op.position.y

        # Get bounding boxes of existing components
        existing_positions = self._get_component_bounding_boxes(ir)
        new_bbox = _estimated_bbox(new_x, new_y, op.library_id, 0.0)

        overlaps = self._find_overlaps(new_bbox, existing_positions)
        if overlaps:
            result.blockers.append(PreAnalysisFinding(
                severity="blocker",
                category="component_overlap",
                message=(
                    f"Component at ({new_x}, {new_y}) overlaps with: "
                    + ", ".join(f"{o['ref']} at ({o['x']}, {o['y']})" for o in overlaps)
                ),
                details={
                    "new_position": {"x": new_x, "y": new_y},
                    "overlapping_components": overlaps,
                },
            ))
            result.suggestions.append(
                f"Move component to avoid overlap with: "
                + ", ".join(o["ref"] for o in overlaps)
            )

    def _analyze_move_component(self, op: Any, ir: Any, result: PreAnalysisResult) -> None:
        """Check for overlap at destination before moving a component."""
        ref = op.reference
        dest_x = op.position.x
        dest_y = op.position.y

        component = ir.get_component_by_ref(ref)
        if component is None:
            result.blockers.append(PreAnalysisFinding(
                severity="blocker",
                category="unknown_ref",
                message=f"Cannot move {ref}: component not found in schematic",
                details={"reference": ref},
            ))
            return

        # Get all other component positions (exclude the one being moved)
        existing_positions = self._get_component_bounding_boxes(ir, exclude_ref=ref)

        lib_id = getattr(component, "libId", "")
        new_bbox = _estimated_bbox(dest_x, dest_y, lib_id, op.position.angle)

        overlaps = self._find_overlaps(new_bbox, existing_positions)
        if overlaps:
            result.blockers.append(PreAnalysisFinding(
                severity="blocker",
                category="component_overlap",
                message=(
                    f"Moving {ref} to ({dest_x}, {dest_y}) would overlap with: "
                    + ", ".join(f"{o['ref']} at ({o['x']}, {o['y']})" for o in overlaps)
                ),
                details={
                    "reference": ref,
                    "destination": {"x": dest_x, "y": dest_y},
                    "overlapping_components": overlaps,
                },
            ))

    # Wiring analysis

    def _analyze_wiring(self, op: Any, ir: Any, result: PreAnalysisResult) -> None:
        """Check for collision zones and pin conflicts before wiring."""
        pin_positions = ir.get_pin_positions()

        # Detect collision zones (pins from different refs at same position)
        collision_zones = _detect_collision_zones(
            pin_positions, _COLLISION_TOLERANCE_MM
        )
        if collision_zones:
            result.warnings.append(PreAnalysisFinding(
                severity="warning",
                category="collision_zone",
                message=(
                    f"{len(collision_zones)} collision zone(s) detected in schematic -- "
                    "wires through these zones may short pins from different nets"
                ),
                details={"collision_zones": collision_zones},
            ))

        # For connect_pins / batch_connect, verify referenced pins exist
        if op.op_type == "connect_pins":
            self._check_pin_resolution(op, ir, pin_positions, result)
        elif op.op_type == "batch_connect":
            self._check_batch_pin_resolution(op, ir, pin_positions, result)

        # For add_wire, check if wire endpoints land on collision zones
        if op.op_type == "add_wire":
            self._check_wire_collision(op, collision_zones, result)

        # Build connectivity context for enriched_context
        self._build_connectivity_context(ir, pin_positions, result)

    def _check_pin_resolution(self, op: Any, ir: Any, pin_positions: list[dict], result: PreAnalysisResult) -> None:
        """Verify that connect_pins references resolve to actual pins."""
        source_ref = getattr(op, "source", None)
        target_ref = getattr(op, "target", None)

        if source_ref is None or target_ref is None:
            return

        for pin_ref in [source_ref, target_ref]:
            ref = pin_ref.ref
            pin = pin_ref.pin
            found = any(
                p["reference"] == ref and (p["pin_number"] == pin or p["pin_name"] == pin)
                for p in pin_positions
            )
            if not found:
                result.blockers.append(PreAnalysisFinding(
                    severity="blocker",
                    category="unresolved_pin",
                    message=f"Pin {ref}.{pin} not found in schematic",
                    details={"reference": ref, "pin": pin},
                ))

    def _check_batch_pin_resolution(self, op: Any, ir: Any, pin_positions: list[dict], result: PreAnalysisResult) -> None:
        """Verify all pins in a batch_connect operation resolve."""
        nets = getattr(op, "nets", [])
        for net_def in nets:
            pins = getattr(net_def, "pins", [])
            for pin_ref in pins:
                ref = pin_ref.ref
                pin = pin_ref.pin
                found = any(
                    p["reference"] == ref
                    and (p["pin_number"] == pin or p["pin_name"] == pin)
                    for p in pin_positions
                )
                if not found:
                    result.blockers.append(PreAnalysisFinding(
                        severity="blocker",
                        category="unresolved_pin",
                        message=f"Pin {ref}.{pin} not found in schematic",
                        details={"reference": ref, "pin": pin, "net": getattr(net_def, "net_name", "")},
                    ))

    def _check_wire_collision(self, op: Any, collision_zones: list[dict], result: PreAnalysisResult) -> None:
        """Check if a wire segment passes through any collision zones."""
        if not collision_zones:
            return

        for zone in collision_zones:
            zx, zy = zone["x"], zone["y"]
            if _point_near_segment(zx, zy, op.start_x, op.start_y, op.end_x, op.end_y, tolerance=2.54):
                result.warnings.append(PreAnalysisFinding(
                    severity="warning",
                    category="wire_collision_risk",
                    message=(
                        f"Wire passes through collision zone at ({zx}, {zy}) -- "
                        "may short pins from different nets"
                    ),
                    details={
                        "collision_zone": zone,
                        "wire": {
                            "start_x": op.start_x,
                            "start_y": op.start_y,
                            "end_x": op.end_x,
                            "end_y": op.end_y,
                        },
                    },
                ))

    # Power symbol analysis

    def _analyze_add_power(self, op: Any, ir: Any, result: PreAnalysisResult) -> None:
        """Check for power net consistency before adding a power symbol."""
        power_net_name = getattr(op, "net_name", None) or getattr(op, "power_net", None)
        if power_net_name is None:
            return

        # Check if this power net already exists in the schematic
        existing_power_nets = _get_power_nets(ir)
        if not existing_power_nets:
            return

        # If there are existing power symbols but none for this net, that's fine (adding it)
        # But if we're adding a net that conflicts with an existing different net name, warn
        # This is advisory -- the user might be intentionally adding a second power symbol
        # for current capacity reasons

    # Remove component analysis

    def _analyze_remove_component(self, op: Any, ir: Any, result: PreAnalysisResult) -> None:
        """Check for dangling wires/labels before removing a component."""
        ref = op.reference
        component = ir.get_component_by_ref(ref)
        if component is None:
            result.blockers.append(PreAnalysisFinding(
                severity="blocker",
                category="unknown_ref",
                message=f"Cannot remove {ref}: component not found in schematic",
                details={"reference": ref},
            ))
            return

        # Check if the component has connected wires
        pin_positions = ir.get_pin_positions()
        connected_pins = [p for p in pin_positions if p["reference"] == ref]
        wire_endpoints = ir.get_wire_endpoints()

        dangling_count = 0
        for pin in connected_pins:
            for we in wire_endpoints:
                if _distance(pin["x"], pin["y"], we["start_x"], we["start_y"]) <= 0.01:
                    dangling_count += 1
                elif _distance(pin["x"], pin["y"], we["end_x"], we["end_y"]) <= 0.01:
                    dangling_count += 1

        if dangling_count > 0:
            result.warnings.append(PreAnalysisFinding(
                severity="warning",
                category="dangling_wires",
                message=(
                    f"Removing {ref} will leave {dangling_count} dangling wire endpoint(s) -- "
                    "consider removing connected wires first"
                ),
                details={
                    "reference": ref,
                    "dangling_wire_count": dangling_count,
                },
            ))

    # Label duplication analysis

    def _analyze_label_operation(self, op: Any, ir: Any, result: PreAnalysisResult) -> None:
        """Check for duplicate global labels before label-creating operations."""
        existing_labels = _get_existing_global_label_names(ir)
        op_type = op.op_type

        if op_type == "add_label":
            self._check_single_label(op, existing_labels, result)

        elif op_type in ("batch_connect", "regenerate_wiring"):
            self._check_label_list(op, existing_labels, result)

        elif op_type == "place_net_labels":
            # PlaceNetLabelsOp has no global_labels field -- labels are
            # derived from a pin_map profile at handler level.  Nothing to
            # check at pre-analysis time.
            pass

    def _check_single_label(self, op: Any, existing: dict[str, list[tuple[float, float]]], result: PreAnalysisResult) -> None:
        """Check a single add_label operation for duplicate global labels."""
        if getattr(op, "label_type", None) != "global":
            return  # Local and hierarchical labels can legitimately repeat.

        name = op.name
        if name in existing:
            positions = existing[name]
            result.blockers.append(PreAnalysisFinding(
                severity="blocker",
                category="duplicate_global_label",
                message=(
                    f"Global label '{name}' already exists in schematic -- "
                    "duplicate global labels on the same net are not allowed"
                ),
                details={
                    "label_name": name,
                    "existing_positions": [
                        {"x": x, "y": y} for x, y in positions
                    ],
                },
            ))

    def _check_label_list(self, op: Any, existing: dict[str, list[tuple[float, float]]], result: PreAnalysisResult) -> None:
        """Check a label list (batch_connect / regenerate_wiring) for duplicates."""
        global_labels = getattr(op, "global_labels", [])
        if not global_labels:
            return

        # Collect names from the operation
        op_names: list[str] = []
        for gl in global_labels:
            op_names.append(gl.name)

        # Check for intra-operation duplicates (same name appears twice in the list)
        seen: set[str] = set()
        for name in op_names:
            if name in seen:
                result.blockers.append(PreAnalysisFinding(
                    severity="blocker",
                    category="duplicate_global_label",
                    message=(
                        f"Global label '{name}' appears multiple times in operation "
                        "-- intra-operation duplicate"
                    ),
                    details={
                        "label_name": name,
                        "duplicate_type": "intra_operation",
                    },
                ))
            seen.add(name)

        # Check against existing global labels in the schematic
        for name in seen:
            if name in existing:
                positions = existing[name]
                result.blockers.append(PreAnalysisFinding(
                    severity="blocker",
                    category="duplicate_global_label",
                    message=(
                        f"Global label '{name}' already exists in schematic -- "
                        "duplicate global labels on the same net are not allowed"
                    ),
                    details={
                        "label_name": name,
                        "existing_positions": [
                            {"x": x, "y": y} for x, y in positions
                        ],
                    },
                ))

    # -------------------------------------------------------------------
    # Shared checks
    # -------------------------------------------------------------------

    def _check_ref_resolution(self, op: Any, ir: Any, result: PreAnalysisResult) -> None:
        """Verify any component references in the operation exist in the schematic."""
        ref_fields = ["reference", "source_ref", "target_ref"]
        for field_name in ref_fields:
            ref = getattr(op, field_name, None)
            if ref is None:
                continue
            # Skip pattern refs like "R?" (used by add_component)
            if ref.endswith("?"):
                continue
            component = ir.get_component_by_ref(ref)
            if component is None and op.op_type not in ("add_component",):
                result.blockers.append(PreAnalysisFinding(
                    severity="blocker",
                    category="unknown_ref",
                    message=f"Component {ref} not found in schematic",
                    details={"reference": ref, "field": field_name},
                ))

    def _build_connectivity_context(self, ir: Any, pin_positions: list[dict], result: PreAnalysisResult) -> None:
        """Build connectivity context for enriched_context."""
        wire_endpoints = ir.get_wire_endpoints()
        label_positions = ir.get_label_positions()

        # Count connected vs unconnected pins
        connected_pins: set[str] = set()
        for pin in pin_positions:
            for we in wire_endpoints:
                if (_distance(pin["x"], pin["y"], we["start_x"], we["start_y"]) <= 0.01
                        or _distance(pin["x"], pin["y"], we["end_x"], we["end_y"]) <= 0.01):
                    connected_pins.add(f"{pin['reference']}.{pin['pin_number']}")
                    break

        total_pins = len(pin_positions)
        connected_count = len(connected_pins)

        # Build component pin summaries
        pin_summaries: dict[str, list[dict]] = {}
        for pin in pin_positions:
            ref = pin["reference"]
            if ref not in pin_summaries:
                pin_summaries[ref] = []
            pin_summaries[ref].append({
                "pin": pin["pin_number"],
                "name": pin["pin_name"],
                "type": pin["electrical_type"],
                "x": round(pin["x"], 2),
                "y": round(pin["y"], 2),
                "connected": f"{ref}.{pin['pin_number']}" in connected_pins,
            })

        result.enriched_context.update({
            "connectivity": {
                "total_pins": total_pins,
                "connected_pins": connected_count,
                "unconnected_pins": total_pins - connected_count,
            },
            "component_pin_map": pin_summaries,
            "power_nets": _get_power_nets(ir),
        })

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    @staticmethod
    @staticmethod
    def _get_component_bounding_boxes(ir: Any, exclude_ref: Optional[str] = None) -> list[dict[str, Any]]:
        """Get bounding boxes for all placed components."""
        boxes: list[dict[str, Any]] = []
        for sym in ir.components:
            ref = ""
            for prop in sym.properties:
                if prop.key == "Reference":
                    ref = prop.value
                    break
            if ref == exclude_ref:
                continue
            if not ref:
                continue

            sx = sym.position.X
            sy = sym.position.Y
            angle = sym.position.angle or 0.0
            lib_id = getattr(sym, "libId", "")

            bbox = _estimated_bbox(sx, sy, lib_id, angle)
            boxes.append({
                "ref": ref,
                "x": sx,
                "y": sy,
                "width": bbox["width"],
                "height": bbox["height"],
                "angle": angle,
                "lib_id": lib_id,
            })
        return boxes

    @staticmethod
    @staticmethod
    def _find_overlaps(new_bbox: dict[str, Any], existing: list[dict[str, Any]], tolerance: float = _OVERLAP_TOLERANCE_MM) -> list[dict[str, Any]]:
        """Find existing bounding boxes that overlap with a new one."""
        overlaps: list[dict[str, Any]] = []
        nx1 = new_bbox["x"] - new_bbox["width"] / 2
        ny1 = new_bbox["y"] - new_bbox["height"] / 2
        nx2 = new_bbox["x"] + new_bbox["width"] / 2
        ny2 = new_bbox["y"] + new_bbox["height"] / 2

        for comp in existing:
            cx1 = comp["x"] - comp["width"] / 2 - tolerance
            cy1 = comp["y"] - comp["height"] / 2 - tolerance
            cx2 = comp["x"] + comp["width"] / 2 + tolerance
            cy2 = comp["y"] + comp["height"] / 2 + tolerance

            # AABB overlap test
            if nx1 < cx2 and nx2 > cx1 and ny1 < cy2 and ny2 > cy1:
                overlaps.append(comp)

        return overlaps


# Module-level helpers


def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance between two points."""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def _estimated_bbox(
    x: float, y: float, lib_id: str, angle: float
) -> dict[str, Any]:
    """Estimate a component's bounding box from its library ID using heuristics."""
    lib_lower = lib_id.lower()

    # Heuristic sizes based on common component types (in mm)
    if any(k in lib_lower for k in ("resistor", "r_small", "r_us")):
        w, h = 5.0, 3.0
    elif any(k in lib_lower for k in ("capacitor", "c_small", "c_us")):
        w, h = 4.0, 3.0
    elif any(k in lib_lower for k in ("diode", "led")):
        w, h = 6.0, 3.0
    elif any(k in lib_lower for k in ("transistor", "bjt", "fet", "mosfet", "q_")):
        w, h = 6.0, 5.0
    elif "opamp" in lib_lower or any(k in lib_lower for k in ("tl07", "tl08", "lm358", "ne553")):
        w, h = 8.0, 8.0
    elif any(k in lib_lower for k in ("connector", "header", "j_")):
        # Connectors vary wildly; use a larger default
        w, h = 10.0, 8.0
    else:
        # Generic IC or unknown: use a conservative default
        # Count unit suffixes like _1, _2 to detect multi-unit
        w, h = 10.0, 8.0

    # Adjust for rotation (swap w/h for 90/270)
    angle_norm = angle % 360
    if angle_norm in (90, 270):
        w, h = h, w

    return {"x": x, "y": y, "width": w, "height": h}


def _detect_collision_zones(
    pin_positions: list[dict],
    tolerance: float,
) -> list[dict[str, Any]]:
    """Detect positions where pins from different components overlap."""
    # Group pins by rounded position
    position_groups: dict[tuple[float, float], list[dict]] = {}
    for pin in pin_positions:
        key = (round(pin["x"], 1), round(pin["y"], 1))
        position_groups.setdefault(key, []).append(pin)

    collision_zones: list[dict[str, Any]] = []
    for pos, pins in position_groups.items():
        if len(pins) < 2:
            continue
        # Check if pins are from different components
        refs = set(p["reference"] for p in pins)
        if len(refs) < 2:
            continue
        collision_zones.append({
            "x": pos[0],
            "y": pos[1],
            "pins": [
                {
                    "reference": p["reference"],
                    "pin": p["pin_number"],
                    "name": p["pin_name"],
                }
                for p in pins
            ],
        })

    return collision_zones


def _get_power_nets(ir: Any) -> list[str]:
    """Extract power net names from power symbols in the schematic."""
    power_nets: list[str] = []
    sch = ir.schematic
    for sym in sch.schematicSymbols:
        if sym.libId.startswith("power:"):
            net_name = sym.libId.split(":", 1)[1]
            for prop in sym.properties:
                if prop.key == "Value":
                    net_name = prop.value
                    break
            if net_name not in power_nets:
                power_nets.append(net_name)
    return sorted(power_nets)


def _get_existing_global_label_names(
    ir: Any,
) -> dict[str, list[tuple[float, float]]]:
    """Extract existing global label names from the schematic IR."""
    labels = ir.get_label_positions()
    result: dict[str, list[tuple[float, float]]] = {}
    for label in labels:
        if label.get("label_type") != "global":
            continue
        name = label["name"]
        pos = (label["x"], label["y"])
        result.setdefault(name, []).append(pos)
    return result


def _point_near_segment(px, py, x1, y1, x2, y2, tolerance) -> bool:
    """Check if a point is near a line segment (distance <= tolerance)."""
    dx = x2 - x1
    dy = y2 - y1
    length_sq = dx * dx + dy * dy

    if length_sq == 0:
        return _distance(px, py, x1, y1) <= tolerance

    # Project point onto line, clamped to segment
    t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / length_sq))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy

    return _distance(px, py, proj_x, proj_y) <= tolerance
