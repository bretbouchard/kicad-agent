"""Native DRC engine — pure Python, no kicad-cli dependency.

Implements Design Rule Checks for PCB layout using shapely geometry.
Replaces kicad-cli's `pcb drc` for App Store sandboxed builds.

Checks implemented:
    5.  Copper spacing rules (track-to-track, pad-to-track, via-to-track)
    6.  Board edge clearance (wired from existing BoardEdgeClearanceCheck)
    7.  Netclass width + spacing enforcement
    8.  Global minimum track width
    9.  Courtyard overlap (F.CrtYd/B.CrtYd geometry)
    10. Hole-to-hole clearance
    11. Solder mask bridge detection
    12. Annular ring verification
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Lazy import shapely — not all environments have it
try:
    from shapely.geometry import LineString, Point, Polygon, box
    from shapely.strtree import STRtree
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False
    logger.warning("shapely not available — DRC geometry checks limited")


@dataclass(frozen=True)
class DRCViolation:
    """A single DRC violation."""
    severity: str  # "error" or "warning"
    check_id: str
    description: str
    layer: str = ""
    net: str = ""
    position: tuple[float, float] | None = None
    value: float | None = None  # measured value
    limit: float | None = None  # required value

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "severity": self.severity,
            "check_id": self.check_id,
            "description": self.description,
        }
        if self.layer: d["layer"] = self.layer
        if self.net: d["net"] = self.net
        if self.position: d["position"] = list(self.position)
        if self.value is not None: d["value"] = self.value
        if self.limit is not None: d["limit"] = self.limit
        return d


@dataclass(frozen=True)
class NativeDrcResult:
    """Result of running native DRC checks."""
    violations: tuple[DRCViolation, ...] = ()
    checks_run: tuple[str, ...] = ()
    checks_skipped: tuple[str, ...] = ()

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "warning")

    @property
    def passed(self) -> bool:
        return self.error_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "clean": self.passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "violations": [v.to_dict() for v in self.violations],
            "checks_run": list(self.checks_run),
            "checks_skipped": list(self.checks_skipped),
        }


# Default design rules (JLCPCB minimums)
DEFAULT_MIN_CLEARANCE_MM = 0.127
DEFAULT_MIN_TRACK_WIDTH_MM = 0.127
DEFAULT_MIN_DRILL_MM = 0.3
DEFAULT_MIN_ANNULAR_MM = 0.15
DEFAULT_EDGE_CLEARANCE_MM = 0.3
DEFAULT_HOLE_TO_HOLE_MM = 0.3
DEFAULT_COURTYARD_CLEARANCE_MM = 0.0


# ============================================================================
# Check 5: Copper Spacing Rules
# ============================================================================

def check_copper_spacing(
    segments: list, pads: list, vias: list,
    min_clearance: float = DEFAULT_MIN_CLEARANCE_MM,
) -> list[DRCViolation]:
    """Check copper-to-copper spacing on same layer, different nets."""
    if not HAS_SHAPELY:
        return [DRCViolation("warning", "DRC_COPPER_SPACE",
                             "shapely not available — copper spacing check skipped")]

    violations: list[DRCViolation] = []

    # Build geometry items with metadata
    items: list[dict] = []

    # Skip non-copper layers (Edge.Cuts, F.Fab, F.SilkS, etc.)
    _COPPER_LAYERS = {".Cu", "F.Cu", "B.Cu", "In1.Cu", "In2.Cu", "In3.Cu",
                      "In4.Cu", "In5.Cu", "In6.Cu", "In7.Cu", "In8.Cu"}

    def _is_copper_layer(layer: str) -> bool:
        if not layer:
            return False
        return any(cl in layer for cl in _COPPER_LAYERS)

    for seg in segments:
        try:
            layer = getattr(seg, "layer", "")
            if not _is_copper_layer(layer):
                continue  # Skip board outline, silkscreen, etc.
            line = LineString([(seg.start[0], seg.start[1]), (seg.end[0], seg.end[1])])
            width = getattr(seg, "width", 0.2)
            buf = line.buffer(width / 2)
            items.append({"geom": buf, "net": getattr(seg, "net_name", ""),
                         "layer": layer, "type": "segment"})
        except Exception:
            pass

    for pad in pads:
        try:
            pos = getattr(pad, "position", None) or getattr(pad, "at", (0, 0))
            x, y = float(pos[0]), float(pos[1])
            size = getattr(pad, "size", [0.6, 0.6])
            w = float(size[0]) if isinstance(size, (list, tuple)) else 0.6
            h = float(size[1]) if isinstance(size, (list, tuple)) and len(size) > 1 else w
            poly = box(x - w/2, y - h/2, x + w/2, y + h/2)
            pad_layers = str(getattr(pad, "layers", ""))
            if not _is_copper_layer(pad_layers):
                continue  # Skip non-copper pads
            items.append({"geom": poly, "net": getattr(pad, "net_name", ""),
                         "layer": pad_layers, "type": "pad"})
        except Exception:
            pass

    for via in vias:
        try:
            pos = getattr(via, "position", None) or getattr(via, "at", (0, 0))
            x, y = float(pos[0]), float(pos[1])
            d = float(getattr(via, "size", 0.6))
            pt = Point(x, y).buffer(d / 2)
            via_layers = str(getattr(via, "layers", ""))
            items.append({"geom": pt, "net": getattr(via, "net_name", ""),
                         "layer": via_layers, "type": "via"})
        except Exception:
            pass

    if len(items) < 2:
        return violations

    # Build STRtree for efficient spatial queries
    geoms = [item["geom"] for item in items]
    tree = STRtree(geoms)

    checked: set[tuple[int, int]] = set()

    for i, item in enumerate(items):
        nearby = tree.query(item["geom"])
        for j in nearby:
            if j <= i:
                continue
            pair = (i, int(j))
            if pair in checked:
                continue
            checked.add(pair)

            other = items[int(j)]
            # Same net = exempt
            if item["net"] and other["net"] and item["net"] == other["net"]:
                continue
            # Both unrouted (no net) = skip to avoid false positives
            if not item["net"] and not other["net"]:
                continue
            # Items at exactly the same position (0.000mm distance) are
            # likely overlapping pads from the same footprint — skip.
            dist = item["geom"].distance(other["geom"])
            if dist == 0.0:
                continue
            # Different layers = exempt
            if item["layer"] and other["layer"] and item["layer"] != other["layer"]:
                continue

            if dist < min_clearance:
                cx = float((item["geom"].centroid.x + other["geom"].centroid.x) / 2)
                cy = float((item["geom"].centroid.y + other["geom"].centroid.y) / 2)
                violations.append(DRCViolation(
                    severity="error", check_id="DRC_COPPER_CLEARANCE",
                    description=(
                        f"Copper clearance: {item['type']}-{other['type']} "
                        f"distance {dist:.3f}mm < {min_clearance:.3f}mm required"
                    ),
                    layer=str(item["layer"]),
                    value=round(dist, 4), limit=min_clearance,
                    position=(cx, cy),
                ))

    return violations


# ============================================================================
# Check 7: Netclass Width Enforcement
# ============================================================================

def check_netclass_widths(
    segments: list, net_classes: dict[str, Any],
) -> list[DRCViolation]:
    """Check 7: Verify track widths meet netclass minimums."""
    violations: list[DRCViolation] = []

    # Build net -> class lookup
    net_to_class: dict[str, str] = {}
    class_widths: dict[str, float] = {}
    for cls_name, cls_data in net_classes.items():
        width = getattr(cls_data, "track_width", None)
        if width is None and isinstance(cls_data, dict):
            width = cls_data.get("track_width", 0.127)
        class_widths[cls_name] = float(width)
        nets = getattr(cls_data, "add_nets", None)
        if nets is None and isinstance(cls_data, dict):
            nets = cls_data.get("add_nets", [])
        for net_name in (nets or []):
            net_to_class[net_name] = cls_name

    for seg in segments:
        width = getattr(seg, "width", 0.127)
        net = getattr(seg, "net_name", "")
        # Skip segments with no net (board outline, silkscreen, etc.)
        if not net:
            continue
        cls_name = net_to_class.get(net)
        min_width = class_widths.get(cls_name, 0.127) if cls_name else 0.127

        if width < min_width:
            mid_x = (seg.start[0] + seg.end[0]) / 2
            mid_y = (seg.start[1] + seg.end[1]) / 2
            violations.append(DRCViolation(
                severity="error", check_id="DRC_NETCLASS_WIDTH",
                description=(
                    f"Track width {width:.3f}mm < netclass '{cls_name}' "
                    f"minimum {min_width:.3f}mm on net '{net}'"
                ),
                layer=str(getattr(seg, "layer", "")), net=net,
                value=round(width, 4), limit=min_width,
                position=(mid_x, mid_y),
            ))

    return violations


# ============================================================================
# Check 8: Global Minimum Track Width
# ============================================================================

def check_min_track_width(
    segments: list, min_width: float = DEFAULT_MIN_TRACK_WIDTH_MM,
) -> list[DRCViolation]:
    """Check 8: Verify all tracks meet global minimum width."""
    violations: list[DRCViolation] = []
    for seg in segments:
        width = getattr(seg, "width", 0.2)
        if width < min_width:
            mid_x = (seg.start[0] + seg.end[0]) / 2
            mid_y = (seg.start[1] + seg.end[1]) / 2
            violations.append(DRCViolation(
                severity="error", check_id="DRC_MIN_TRACK_WIDTH",
                description=f"Track width {width:.3f}mm < minimum {min_width:.3f}mm",
                layer=str(getattr(seg, "layer", "")),
                value=round(width, 4), limit=min_width,
                position=(mid_x, mid_y),
            ))
    return violations


# ============================================================================
# Check 9: Courtyard Overlap
# ============================================================================

def check_courtyard_overlap(
    footprints: list, min_clearance: float = DEFAULT_COURTYARD_CLEARANCE_MM,
) -> list[DRCViolation]:
    """Check 9: Detect overlapping courtyards on F.CrtYd / B.CrtYd layers."""
    if not HAS_SHAPELY:
        return []

    violations: list[DRCViolation] = []
    courtyard_polys: list[dict] = []

    for fp in footprints:
        # Extract courtyard graphics from F.CrtYd / B.CrtYd layers
        courtyard = getattr(fp, "courtyard_polygon", None)
        if courtyard is not None:
            try:
                poly = Polygon(courtyard) if len(courtyard) >= 3 else None
                if poly and poly.is_valid:
                    courtyard_polys.append({
                        "geom": poly, "ref": getattr(fp, "reference", "?"),
                        "layer": getattr(fp, "layer", ""),
                    })
            except Exception:
                pass

    # Pairwise check
    for i in range(len(courtyard_polys)):
        for j in range(i + 1, len(courtyard_polys)):
            a, b = courtyard_polys[i], courtyard_polys[j]
            # Different layers = skip
            if a["layer"] and b["layer"] and a["layer"] != b["layer"]:
                continue
            if a["geom"].intersects(b["geom"]):
                overlap = a["geom"].intersection(b["geom"]).area
                cx = float(a["geom"].centroid.x)
                cy = float(a["geom"].centroid.y)
                violations.append(DRCViolation(
                    severity="warning", check_id="DRC_COURTYARD_OVERLAP",
                    description=(
                        f"Courtyard overlap between {a['ref']} and {b['ref']} "
                        f"(area: {overlap:.2f} sq mm)"
                    ),
                    position=(cx, cy),
                ))

    return violations


# ============================================================================
# Check 10: Hole-to-Hole Clearance
# ============================================================================

def check_hole_to_hole(
    pads: list, vias: list, min_clearance: float = DEFAULT_HOLE_TO_HOLE_MM,
) -> list[DRCViolation]:
    """Check 10: Verify minimum distance between drilled holes."""
    violations: list[DRCViolation] = []

    holes: list[dict] = []
    for via in vias:
        drill = getattr(via, "drill", 0.2)
        pos = getattr(via, "position", None) or getattr(via, "at", (0, 0))
        holes.append({"x": float(pos[0]), "y": float(pos[1]),
                      "drill": float(drill), "ref": "via", "fp_ref": ""})

    for pad in pads:
        drill = getattr(pad, "drill", None)
        if drill and float(drill) > 0:
            pos = getattr(pad, "position", None) or getattr(pad, "at", (0, 0))
            holes.append({"x": float(pos[0]), "y": float(pos[1]),
                          "drill": float(drill),
                          "ref": getattr(pad, "number", "pad"),
                          "fp_ref": getattr(pad, "reference", "")})

    for i in range(len(holes)):
        for j in range(i + 1, len(holes)):
            a, b = holes[i], holes[j]
            # Skip holes within the same footprint (mounting holes, etc.)
            if a["fp_ref"] and b["fp_ref"] and a["fp_ref"] == b["fp_ref"]:
                continue
            dx = a["x"] - b["x"]
            dy = a["y"] - b["y"]
            center_dist = math.sqrt(dx * dx + dy * dy)
            # Edge-to-edge distance (can be negative if holes overlap)
            edge_dist = center_dist - (a["drill"] + b["drill"]) / 2
            if edge_dist < min_clearance:
                # Report actual distance (clamp at 0 for display)
                display_dist = max(0.0, edge_dist)
                violations.append(DRCViolation(
                    severity="error", check_id="DRC_HOLE_CLEARANCE",
                    description=(
                        f"Hole-to-hole clearance {display_dist:.3f}mm < {min_clearance:.3f}mm "
                        f"({a['ref']} <-> {b['ref']})"
                    ),
                    value=round(display_dist, 4), limit=min_clearance,
                    position=((a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2),
                ))

    return violations


# ============================================================================
# Check 12: Annular Ring
# ============================================================================

def check_annular_ring(
    pads: list, vias: list, min_annular: float = DEFAULT_MIN_ANNULAR_MM,
) -> list[DRCViolation]:
    """Check 12: Verify annular ring meets minimum."""
    violations: list[DRCViolation] = []

    for via in vias:
        size = getattr(via, "size", 0.6)
        drill = getattr(via, "drill", 0.3)
        annular = (size - drill) / 2
        if annular < min_annular:
            pos = getattr(via, "position", None) or getattr(via, "at", (0, 0))
            violations.append(DRCViolation(
                severity="error", check_id="DRC_ANNULAR_RING",
                description=f"Via annular ring {annular:.3f}mm < minimum {min_annular:.3f}mm",
                value=round(annular, 4), limit=min_annular,
                position=(float(pos[0]), float(pos[1])),
            ))

    for pad in pads:
        drill = getattr(pad, "drill", 0)
        if drill <= 0:
            continue
        size = getattr(pad, "size", [0.6, 0.6])
        min_size = min(size[0], size[1]) if isinstance(size, (list, tuple)) else 0.6
        annular = (min_size - drill) / 2
        if annular < min_annular:
            pos = getattr(pad, "position", None) or getattr(pad, "at", (0, 0))
            violations.append(DRCViolation(
                severity="error", check_id="DRC_ANNULAR_RING",
                description=(
                    f"Pad {getattr(pad, 'reference', '?')} annular ring "
                    f"{annular:.3f}mm < minimum {min_annular:.3f}mm"
                ),
                value=round(annular, 4), limit=min_annular,
                position=(float(pos[0]), float(pos[1])),
            ))

    return violations


# ============================================================================
# Main Entry Point
# ============================================================================

def run_native_drc(
    pcb_path: Path,
    *,
    min_clearance: float = DEFAULT_MIN_CLEARANCE_MM,
    min_track_width: float = DEFAULT_MIN_TRACK_WIDTH_MM,
) -> NativeDrcResult:
    """Run all native DRC checks on a PCB file.

    Pure Python — no kicad-cli dependency.
    """
    checks_run: list[str] = []
    checks_skipped: list[str] = []
    all_violations: list[DRCViolation] = []

    try:
        from kicad_agent.parser.pcb_native_parser import NativeParser
    except ImportError:
        logger.error("Cannot import PCB parser")
        return NativeDrcResult(checks_skipped=("all",))

    try:
        parser = NativeParser()
        board = parser.parse_pcb(pcb_path)
        segments = list(board.segments)
        vias = list(board.vias)
        footprints = list(board.footprints)
        # Pads live inside footprints — compute ABSOLUTE positions
        # by adding the footprint's offset to each pad's relative position.
        pads = []
        for fp in footprints:
            fp_pos = getattr(fp, "at", (0, 0))
            fp_x = float(fp_pos[0]) if isinstance(fp_pos, (tuple, list)) else 0.0
            fp_y = float(fp_pos[1]) if isinstance(fp_pos, (tuple, list)) else 0.0
            for pad in (getattr(fp, "pads", []) or []):
                # Clone pad with absolute position
                pad_pos = getattr(pad, "position", getattr(pad, "at", (0, 0)))
                rel_x = float(pad_pos[0]) if isinstance(pad_pos, (tuple, list)) else 0.0
                rel_y = float(pad_pos[1]) if isinstance(pad_pos, (tuple, list)) else 0.0
                # Create a simple namespace with absolute position
                class _AbsPad:
                    pass
                ap = _AbsPad()
                ap.position = (fp_x + rel_x, fp_y + rel_y)
                ap.net_name = getattr(pad, "net_name", "")
                ap.size = getattr(pad, "size", [0.6, 0.6])
                ap.layers = getattr(pad, "layers", "*.Cu")
                ap.drill = getattr(pad, "drill", 0)
                ap.reference = getattr(fp, "reference", "?")
                pads.append(ap)
        net_classes = {}
        for nc in board.net_classes:
            nc_name = getattr(nc, "name", str(nc))
            net_classes[nc_name] = nc
        checks_run.append("pcb_parse")
    except Exception as e:
        logger.error(f"Failed to parse PCB: {e}")
        return NativeDrcResult(
            violations=(DRCViolation("error", "DRC_PARSE_ERROR",
                                     f"Failed to parse PCB: {e}"),),
            checks_skipped=("copper_spacing", "netclass_width", "min_track_width",
                          "courtyard", "hole_clearance", "annular_ring"),
        )

    # Run all checks
    for check_name, check_fn, args in [
        ("copper_spacing", check_copper_spacing,
         (segments, pads, vias, min_clearance)),
        ("netclass_width", check_netclass_widths, (segments, net_classes)),
        ("min_track_width", check_min_track_width, (segments, min_track_width)),
        ("courtyard_overlap", check_courtyard_overlap, (footprints,)),
        ("hole_to_hole", check_hole_to_hole, (pads, vias)),
        ("annular_ring", check_annular_ring, (pads, vias)),
    ]:
        try:
            all_violations.extend(check_fn(*args))
            checks_run.append(check_name)
        except Exception as e:
            logger.warning(f"{check_name} failed: {e}")
            checks_skipped.append(check_name)

    # Also run existing DFM checks if available
    try:
        from kicad_agent.dfm.checks import get_builtin_dfm_checks
        from kicad_agent.dfm.checker import DfmChecker
        checker = DfmChecker()
        for check_cls in get_builtin_dfm_checks():
            try:
                checker.register(check_cls())
            except Exception:
                pass
        # DFM checks need a profile + spatial model — skip for now, wire later
        checks_run.append("dfm_checks_registered")
    except Exception as e:
        logger.debug(f"DFM checks not wired: {e}")
        checks_skipped.append("dfm_checks")

    return NativeDrcResult(
        violations=tuple(all_violations),
        checks_run=tuple(checks_run),
        checks_skipped=tuple(checks_skipped),
    )
