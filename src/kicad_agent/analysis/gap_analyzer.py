"""Deterministic gap analysis for partially-routed PCBs.

Analyzes a .kicad_pcb file and produces a GapReport identifying:
- Unrouted nets (no copper segments at all)
- Incomplete nets (some but not all pins connected)
- DRC violations (enriched via IntelligentDrcAnalyzer)
- Net naming issues (N0xxx nets with suggested functional names)

Purely deterministic — no AI required. The GapReport is the input to
Phase 82's AI gap-filling engine.

Usage:
    from kicad_agent.analysis.gap_analyzer import GapAnalyzer

    analyzer = GapAnalyzer()
    report = analyzer.analyze("path/to/board.kicad_pcb")
    print(report.to_markdown())
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kicad_agent.validation.drc_intel import EnrichedViolation

logger = logging.getLogger(__name__)

# Tolerance for endpoint matching (mm).
_ENDPOINT_TOLERANCE = 0.01
# Tolerance for pad-to-segment proximity check (mm).
_PAD_PROXIMITY_TOLERANCE = 0.5


# ---------------------------------------------------------------------------
# Frozen data schemas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BoardInfo:
    """Metadata about the analyzed PCB."""

    file_path: str
    component_count: int
    net_count: int
    layer_count: int
    bounds: tuple[float, float, float, float] | None

    def to_json(self) -> dict:
        return {
            "file_path": self.file_path,
            "component_count": self.component_count,
            "net_count": self.net_count,
            "layer_count": self.layer_count,
            "bounds": list(self.bounds) if self.bounds else None,
        }


@dataclass(frozen=True)
class RoutingStats:
    """Summary counts for net routing coverage."""

    total_nets: int
    routed_nets: int
    unrouted_nets: int
    incomplete_nets: int
    route_percentage: float

    def to_json(self) -> dict:
        return {
            "total_nets": self.total_nets,
            "routed_nets": self.routed_nets,
            "unrouted_nets": self.unrouted_nets,
            "incomplete_nets": self.incomplete_nets,
            "route_percentage": self.route_percentage,
        }


@dataclass(frozen=True)
class UnroutedNet:
    """A net with zero copper segments."""

    net_name: str
    pad_count: int
    pin_positions: tuple[tuple[float, float], ...]
    nearest_obstacle_distance: float  # mm, -1.0 if no obstacles

    def to_json(self) -> dict:
        return {
            "net_name": self.net_name,
            "pad_count": self.pad_count,
            "pin_positions": [list(p) for p in self.pin_positions],
            "nearest_obstacle_distance": self.nearest_obstacle_distance,
        }


@dataclass(frozen=True)
class IncompleteNet:
    """A net with some but not all pins connected by copper."""

    net_name: str
    routed_pins: tuple[tuple[float, float], ...]
    unrouted_pins: tuple[tuple[float, float], ...]
    gap_distance: float  # Euclidean distance from last routed point to nearest unrouted pin

    def to_json(self) -> dict:
        return {
            "net_name": self.net_name,
            "routed_pins": [list(p) for p in self.routed_pins],
            "unrouted_pins": [list(p) for p in self.unrouted_pins],
            "gap_distance": self.gap_distance,
        }


@dataclass(frozen=True)
class NetNamingIssue:
    """A net whose name is auto-generated (N0xxx) and could be more descriptive."""

    current_name: str
    suggested_name: str
    connected_components: tuple[str, ...]
    reason: str

    def to_json(self) -> dict:
        return {
            "current_name": self.current_name,
            "suggested_name": self.suggested_name,
            "connected_components": list(self.connected_components),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class GapReport:
    """Complete gap analysis report for a PCB."""

    board_info: BoardInfo
    routing_stats: RoutingStats
    unrouted_nets: tuple[UnroutedNet, ...]
    incomplete_nets: tuple[IncompleteNet, ...]
    drc_violations: tuple  # tuple[EnrichedViolation, ...]
    net_naming_issues: tuple[NetNamingIssue, ...]

    def to_json(self) -> dict:
        return {
            "board_info": self.board_info.to_json(),
            "routing_stats": self.routing_stats.to_json(),
            "unrouted_nets": [n.to_json() for n in self.unrouted_nets],
            "incomplete_nets": [n.to_json() for n in self.incomplete_nets],
            "drc_violations": [v.to_json() for v in self.drc_violations],
            "net_naming_issues": [n.to_json() for n in self.net_naming_issues],
        }

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append("# Gap Analysis Report")
        lines.append("")
        lines.append(f"**File:** {self.board_info.file_path}")
        lines.append(
            f"**Components:** {self.board_info.component_count} | "
            f"**Nets:** {self.board_info.net_count} | "
            f"**Layers:** {self.board_info.layer_count}"
        )
        if self.board_info.bounds:
            b = self.board_info.bounds
            lines.append(f"**Bounds:** ({b[0]:.2f}, {b[1]:.2f}) - ({b[2]:.2f}, {b[3]:.2f}) mm")
        lines.append("")

        # Routing stats
        rs = self.routing_stats
        lines.append("## Routing Summary")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Total nets | {rs.total_nets} |")
        lines.append(f"| Routed | {rs.routed_nets} ({rs.route_percentage:.1f}%) |")
        lines.append(f"| Unrouted | {rs.unrouted_nets} |")
        lines.append(f"| Incomplete | {rs.incomplete_nets} |")
        lines.append("")

        # Unrouted nets
        if self.unrouted_nets:
            lines.append(f"## Unrouted Nets ({len(self.unrouted_nets)})")
            lines.append("")
            lines.append("| Net | Pads | Nearest Obstacle |")
            lines.append("|-----|------|-------------------|")
            for un in self.unrouted_nets:
                obs = f"{un.nearest_obstacle_distance:.2f}mm" if un.nearest_obstacle_distance >= 0 else "N/A"
                lines.append(f"| {un.net_name} | {un.pad_count} | {obs} |")
            lines.append("")

        # Incomplete nets
        if self.incomplete_nets:
            lines.append(f"## Incomplete Nets ({len(self.incomplete_nets)})")
            lines.append("")
            lines.append("| Net | Routed Pins | Unrouted Pins | Gap Distance |")
            lines.append("|-----|-------------|---------------|--------------|")
            for inc in self.incomplete_nets:
                lines.append(
                    f"| {inc.net_name} | {len(inc.routed_pins)} | "
                    f"{len(inc.unrouted_pins)} | {inc.gap_distance:.2f}mm |"
                )
            lines.append("")

        # DRC violations
        if self.drc_violations:
            lines.append(f"## DRC Violations ({len(self.drc_violations)})")
            lines.append("")
            for v in self.drc_violations:
                sev = getattr(v, "severity", "unknown")
                desc = getattr(v, "description", str(v))
                lines.append(f"- **[{sev}]** {desc}")
            lines.append("")

        # Naming issues
        if self.net_naming_issues:
            lines.append(f"## Net Naming Issues ({len(self.net_naming_issues)})")
            lines.append("")
            lines.append("| Current Name | Suggested | Components | Reason |")
            lines.append("|-------------|-----------|------------|--------|")
            for ni in self.net_naming_issues:
                comps = ", ".join(ni.connected_components[:5])
                if len(ni.connected_components) > 5:
                    comps += f" +{len(ni.connected_components) - 5} more"
                lines.append(f"| {ni.current_name} | {ni.suggested_name} | {comps} | {ni.reason} |")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Net classification types
# ---------------------------------------------------------------------------

class _NetClass(str):
    ROUTED = "routed"
    UNROUTED = "unrouted"
    INCOMPLETE = "incomplete"


# ---------------------------------------------------------------------------
# GapAnalyzer
# ---------------------------------------------------------------------------


class GapAnalyzer:
    """Deterministic analysis of partially-routed PCBs.

    Reads a .kicad_pcb file, classifies nets as routed/unrouted/incomplete,
    runs DRC, and produces a structured GapReport.

    Args:
        run_drc: Whether to run kicad-cli DRC. Defaults to True.
                 Set to False for fast analysis without DRC.
    """

    def __init__(self, *, run_drc: bool = True) -> None:
        self._run_drc = run_drc

    def analyze(self, pcb_path: str | Path) -> GapReport:
        """Analyze a PCB and produce a gap report.

        Args:
            pcb_path: Path to a .kicad_pcb file.

        Returns:
            GapReport with all gap data.

        Raises:
            FileNotFoundError: If pcb_path does not exist.
        """
        pcb_path = Path(pcb_path)
        if not pcb_path.exists():
            raise FileNotFoundError(f"PCB file not found: {pcb_path}")

        # 1. Parse PCB via NativeParser
        from kicad_agent.parser.pcb_native_parser import NativeParser

        board = NativeParser.parse_pcb(pcb_path)

        # 2. Create PcbIR for netlist/obstacle extraction
        from kicad_agent.ir.pcb_ir import PcbIR

        ir = PcbIR.from_native(board)

        # 3. Extract data from PcbIR
        netlist = ir.extract_netlist()
        bounds = ir.get_board_bounds()
        obstacles = ir.extract_obstacles()

        # 4. Classify nets
        net_classifications = self._classify_nets(board, netlist)

        # 5. Analyze unrouted nets
        unrouted = self._analyze_unrouted_nets_with_netlist(
            net_classifications, netlist, obstacles
        )

        # 6. Analyze incomplete nets
        incomplete = self._analyze_incomplete_nets(board, net_classifications, netlist)

        # 7. DRC (optional)
        drc_violations = self._run_drc_analysis(pcb_path)

        # 8. Net naming issues
        naming_issues = self._detect_naming_issues(board)

        # 9. Board info
        board_info = BoardInfo(
            file_path=str(pcb_path),
            component_count=len(board.footprints),
            net_count=len([n for n in board.nets if n.number > 0]),
            layer_count=len(board.general.layers) if board.general.layers else 2,
            bounds=bounds,
        )

        # 10. Routing stats
        routed_count = sum(1 for v in net_classifications.values() if v == _NetClass.ROUTED)
        unrouted_count = sum(1 for v in net_classifications.values() if v == _NetClass.UNROUTED)
        incomplete_count = sum(1 for v in net_classifications.values() if v == _NetClass.INCOMPLETE)
        total = routed_count + unrouted_count + incomplete_count
        route_pct = (routed_count / total * 100) if total > 0 else 0.0

        routing_stats = RoutingStats(
            total_nets=total,
            routed_nets=routed_count,
            unrouted_nets=unrouted_count,
            incomplete_nets=incomplete_count,
            route_percentage=route_pct,
        )

        return GapReport(
            board_info=board_info,
            routing_stats=routing_stats,
            unrouted_nets=tuple(unrouted),
            incomplete_nets=tuple(incomplete),
            drc_violations=tuple(drc_violations),
            net_naming_issues=tuple(naming_issues),
        )

    # -----------------------------------------------------------------------
    # Net classification
    # -----------------------------------------------------------------------

    def _classify_nets(
        self,
        board,
        netlist: dict[str, list[tuple[float, float]]],
    ) -> dict[str, str]:
        """Classify each net as routed, unrouted, or incomplete.

        Args:
            board: NativeBoard with segments list.
            netlist: Mapping of net name to pad positions.

        Returns:
            Dict mapping net name to classification string.
        """
        # Build segment graph per net: map net_name -> list of (start, end) tuples
        net_segments: dict[str, list[tuple[tuple[float, float], tuple[float, float]]]] = {}
        for seg in board.segments:
            net_name = seg.net_name
            if not net_name:
                continue
            if seg.start is None or seg.end is None:
                continue
            start = (float(seg.start.X), float(seg.start.Y))
            end = (float(seg.end.X), float(seg.end.Y))
            net_segments.setdefault(net_name, []).append((start, end))

        # Collect all via positions per net for connectivity
        net_via_positions: dict[str, list[tuple[float, float]]] = {}
        for via in board.vias:
            if via.net_name:
                net_via_positions.setdefault(via.net_name, []).append(
                    (float(via.position[0]), float(via.position[1]))
                )

        classifications: dict[str, str] = {}

        for net_name, pads in netlist.items():
            # Skip net 0 (unconnected)
            if net_name == "" or net_name == "0":
                continue

            segs = net_segments.get(net_name, [])

            if not segs:
                classifications[net_name] = _NetClass.UNROUTED
                continue

            # Build connectivity from segments: union-find of endpoints
            connected_points = self._build_segment_graph(segs)

            # Add via positions to connected set
            for vp in net_via_positions.get(net_name, []):
                self._add_to_connected_set(connected_points, vp)

            # Check if each pad is within proximity of any connected point
            all_connected = True
            for px, py in pads:
                if not self._point_near_set(px, py, connected_points, _PAD_PROXIMITY_TOLERANCE):
                    all_connected = False
                    break

            classifications[net_name] = (
                _NetClass.ROUTED if all_connected else _NetClass.INCOMPLETE
            )

        return classifications

    @staticmethod
    def _build_segment_graph(
        segs: list[tuple[tuple[float, float], tuple[float, float]]],
    ) -> list[list[tuple[float, float]]]:
        """Build connected components from segment endpoints.

        Returns list of connected point groups.
        """
        # Collect all unique points
        all_points: list[tuple[float, float]] = []
        for start, end in segs:
            all_points.append(start)
            all_points.append(end)

        # Union-find
        parent: dict[tuple[float, float], tuple[float, float]] = {p: p for p in all_points}

        def find(pt: tuple[float, float]) -> tuple[float, float]:
            while parent[pt] != pt:
                parent[pt] = parent[parent[pt]]
                pt = parent[pt]
            return pt

        def union(a: tuple[float, float], b: tuple[float, float]) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for start, end in segs:
            # Connect start to nearest existing point
            for pt in all_points:
                if pt != start and abs(pt[0] - start[0]) < _ENDPOINT_TOLERANCE and abs(pt[1] - start[1]) < _ENDPOINT_TOLERANCE:
                    union(pt, start)
                    break
            # Connect end to nearest existing point
            for pt in all_points:
                if pt != end and abs(pt[0] - end[0]) < _ENDPOINT_TOLERANCE and abs(pt[1] - end[1]) < _ENDPOINT_TOLERANCE:
                    union(pt, end)
                    break

        # Group by root
        groups: dict[tuple[float, float], list[tuple[float, float]]] = {}
        for pt in all_points:
            root = find(pt)
            groups.setdefault(root, []).append(pt)

        return list(groups.values())

    @staticmethod
    def _add_to_connected_set(
        groups: list[list[tuple[float, float]]],
        point: tuple[float, float],
    ) -> None:
        """Add a point to the connected set, merging with nearby groups."""
        for group in groups:
            for pt in group:
                if abs(pt[0] - point[0]) < _ENDPOINT_TOLERANCE and abs(pt[1] - point[1]) < _ENDPOINT_TOLERANCE:
                    group.append(point)
                    return
        # Not near any group — add as new singleton
        groups.append([point])

    @staticmethod
    def _point_near_set(
        x: float,
        y: float,
        groups: list[list[tuple[float, float]]],
        tolerance: float,
    ) -> bool:
        """Check if a point is within tolerance of any point in the connected set."""
        for group in groups:
            for gx, gy in group:
                if math.hypot(gx - x, gy - y) < tolerance:
                    return True
        return False

    # -----------------------------------------------------------------------
    # Unrouted net analysis
    # -----------------------------------------------------------------------

    def _analyze_unrouted_nets(
        self,
        classifications: dict[str, str],
        obstacles: list,
    ) -> list[UnroutedNet]:
        """Build UnroutedNet entries for all unclassified nets.

        Args:
            classifications: Net name -> classification.
            obstacles: List of SpatialBox obstacles from PcbIR.

        Returns:
            List of UnroutedNet data objects.
        """
        from shapely.geometry import Point as ShapelyPoint

        # Pre-build obstacle geometries for distance queries
        obs_geoms = []
        for obs in obstacles:
            try:
                obs_geoms.append(obs.to_shapely())
            except (AttributeError, Exception):
                pass

        result: list[UnroutedNet] = []

        for net_name, cls in classifications.items():
            if cls != _NetClass.UNROUTED:
                continue

            # We need pad positions — extract from the netlist later via caller
            # For now, build from what we have
            pin_positions: tuple[tuple[float, float], ...] = ()
            nearest_dist = -1.0

            result.append(UnroutedNet(
                net_name=net_name,
                pad_count=0,
                pin_positions=pin_positions,
                nearest_obstacle_distance=nearest_dist,
            ))

        return result

    def _analyze_unrouted_nets_with_netlist(
        self,
        classifications: dict[str, str],
        netlist: dict[str, list[tuple[float, float]]],
        obstacles: list,
    ) -> list[UnroutedNet]:
        """Build UnroutedNet entries with full pad positions and obstacle distances.

        Args:
            classifications: Net name -> classification.
            netlist: Mapping of net name to pad positions.
            obstacles: List of SpatialBox obstacles from PcbIR.

        Returns:
            List of UnroutedNet data objects.
        """
        from shapely.geometry import Point as ShapelyPoint

        result: list[UnroutedNet] = []

        for net_name, cls in classifications.items():
            if cls != _NetClass.UNROUTED:
                continue

            pads = netlist.get(net_name, [])
            pin_positions = tuple(pads)
            pad_count = len(pin_positions)

            # Compute nearest obstacle distance from any pin
            nearest_dist = -1.0
            for obs in obstacles:
                try:
                    obs_geom = obs.to_shapely()
                except (AttributeError, Exception):
                    continue
                for px, py in pin_positions:
                    d = ShapelyPoint(px, py).distance(obs_geom)
                    if nearest_dist < 0 or d < nearest_dist:
                        nearest_dist = d

            result.append(UnroutedNet(
                net_name=net_name,
                pad_count=pad_count,
                pin_positions=pin_positions,
                nearest_obstacle_distance=round(nearest_dist, 4) if nearest_dist >= 0 else -1.0,
            ))

        return result

    # -----------------------------------------------------------------------
    # Incomplete net analysis
    # -----------------------------------------------------------------------

    def _analyze_incomplete_nets(
        self,
        board,
        classifications: dict[str, str],
        netlist: dict[str, list[tuple[float, float]]],
    ) -> list[IncompleteNet]:
        """Build IncompleteNet entries for partially routed nets.

        Args:
            board: NativeBoard with segments and vias.
            classifications: Net name -> classification.
            netlist: Mapping of net name to pad positions.

        Returns:
            List of IncompleteNet data objects.
        """
        result: list[IncompleteNet] = []

        for net_name, cls in classifications.items():
            if cls != _NetClass.INCOMPLETE:
                continue

            pads = netlist.get(net_name, [])
            if not pads:
                continue

            # Collect all segment/via endpoints for this net
            connected_points: list[tuple[float, float]] = []
            for seg in board.segments:
                if seg.net_name == net_name and seg.start is not None and seg.end is not None:
                    connected_points.append((float(seg.start.X), float(seg.start.Y)))
                    connected_points.append((float(seg.end.X), float(seg.end.Y)))
            for via in board.vias:
                if via.net_name == net_name:
                    connected_points.append((float(via.position[0]), float(via.position[1])))

            routed_pins: list[tuple[float, float]] = []
            unrouted_pins: list[tuple[float, float]] = []

            for px, py in pads:
                if self._point_near_any(px, py, connected_points, _PAD_PROXIMITY_TOLERANCE):
                    routed_pins.append((px, py))
                else:
                    unrouted_pins.append((px, py))

            # Gap distance: minimum Euclidean from any routed point to any unrouted point
            gap = float("inf")
            if routed_pins and unrouted_pins:
                for rx, ry in routed_pins:
                    for ux, uy in unrouted_pins:
                        d = math.hypot(rx - ux, ry - uy)
                        if d < gap:
                            gap = d

            result.append(IncompleteNet(
                net_name=net_name,
                routed_pins=tuple(routed_pins),
                unrouted_pins=tuple(unrouted_pins),
                gap_distance=round(gap, 4) if gap != float("inf") else -1.0,
            ))

        return result

    @staticmethod
    def _point_near_any(
        x: float, y: float,
        points: list[tuple[float, float]],
        tolerance: float,
    ) -> bool:
        """Check if (x, y) is within tolerance of any point in the list."""
        for px, py in points:
            if math.hypot(px - x, py - y) < tolerance:
                return True
        return False

    # -----------------------------------------------------------------------
    # DRC analysis
    # -----------------------------------------------------------------------

    def _run_drc_analysis(self, pcb_path: Path) -> list:
        """Run kicad-cli DRC and enrich violations.

        Returns empty list if kicad-cli is unavailable or fails.
        """
        if not self._run_drc:
            return []

        try:
            from kicad_agent.validation.drc_intel import IntelligentDrcAnalyzer
            from kicad_agent.validation.erc_drc import run_drc

            drc_result = run_drc(pcb_path, timeout=30)
            analyzer = IntelligentDrcAnalyzer()
            report = analyzer.analyze(drc_result)
            return list(report.enriched_violations)
        except FileNotFoundError:
            logger.debug("kicad-cli not found, skipping DRC analysis")
            return []
        except Exception as exc:
            logger.warning("DRC analysis failed: %s", exc)
            return []

    # -----------------------------------------------------------------------
    # Net naming
    # -----------------------------------------------------------------------

    _AUTO_NET_PATTERN = re.compile(r"^N_\d+$")

    def _detect_naming_issues(self, board) -> list[NetNamingIssue]:
        """Detect auto-generated net names and suggest functional alternatives.

        Scans nets with names matching N_<number> pattern, finds connected
        component references and pin functions, and generates suggestions.

        Args:
            board: NativeBoard with nets and footprints.

        Returns:
            List of NetNamingIssue objects.
        """
        issues: list[NetNamingIssue] = []

        for net in board.nets:
            if net.number == 0:
                continue
            if not self._AUTO_NET_PATTERN.match(net.name):
                continue

            # Find connected components
            connected_refs: list[str] = []
            pin_functions: list[str] = []

            for fp in board.footprints:
                ref = fp.properties.get("Reference", "")
                for pad in fp.pads:
                    if pad.net_name == net.name:
                        if ref and ref not in connected_refs:
                            connected_refs.append(ref)
                        if pad.pinfunction and pad.pinfunction not in pin_functions:
                            pin_functions.append(pad.pinfunction)

            if not connected_refs:
                continue

            # Suggest name based on pin functions
            suggested = self._suggest_net_name(net.name, connected_refs, pin_functions)
            reason = self._naming_reason(connected_refs, pin_functions)

            issues.append(NetNamingIssue(
                current_name=net.name,
                suggested_name=suggested,
                connected_components=tuple(connected_refs),
                reason=reason,
            ))

        return issues

    @staticmethod
    def _suggest_net_name(
        current_name: str,
        refs: list[str],
        pin_functions: list[str],
    ) -> str:
        """Generate a suggested net name from connected components and pin functions."""
        # Power pins
        power_keywords = {"VCC", "VDD", "V+", "+3V3", "+5V", "+12V", "VBUS"}
        gnd_keywords = {"GND", "VSS", "V-", "DGND", "AGND"}

        for pf in pin_functions:
            pf_upper = pf.upper()
            if any(kw in pf_upper for kw in power_keywords):
                return pf_upper
            if any(kw in pf_upper for kw in gnd_keywords):
                return pf_upper

        # Named signals: if all pins share a function name
        if pin_functions and len(set(pin_functions)) == 1:
            pf = pin_functions[0]
            if pf and not pf.startswith("~"):  # skip inverted pins
                return f"{pf}_NET"

        # Fall back to component reference pattern
        if len(refs) <= 3:
            return "_".join(refs) + "_NET"
        return f"{refs[0]}_{refs[1]}_NET"

    @staticmethod
    def _naming_reason(refs: list[str], pin_functions: list[str]) -> str:
        """Generate a human-readable reason for the naming suggestion."""
        if not pin_functions:
            return f"Connected to {', '.join(refs[:3])}"

        # Check for power/ground
        power_kw = {"VCC", "VDD", "V+", "+3V3", "+5V", "+12V", "VBUS"}
        gnd_kw = {"GND", "VSS", "V-", "DGND", "AGND"}
        for pf in pin_functions:
            pf_upper = pf.upper()
            if any(kw in pf_upper for kw in power_kw):
                return f"Power net (pinfunction={pf})"
            if any(kw in pf_upper for kw in gnd_kw):
                return f"Ground net (pinfunction={pf})"

        return f"Connected to {', '.join(refs[:3])} via pins {', '.join(pin_functions[:3])}"
