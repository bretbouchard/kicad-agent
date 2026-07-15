"""Coordinate-grounded report generation for Rick agent domains.

VP-08: Produces spatially-grounded analysis reports for SI (Signal Integrity),
PI (Power Integrity), EMC (Electromagnetic Compatibility), and DFM (Design for
Manufacturing) Rick domains. Each finding maps domain-specific concerns to
precise PCB coordinates with nearby primitive context.

Replaces text-only Rick findings with coordinate-grounded spatial references
using the <point> [x, y] notation and nearby entity context.

Usage:
    from volta.spatial.rick_integration import generate_all_reports

    reports = generate_all_reports(pcb_primitives)
    for domain, report in reports.items():
        print(report.format_report())
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

from volta.spatial.primitives import (
    SpatialBox,
    SpatialPath,
    SpatialPoint,
    SpatialRegion,
)
from volta.spatial.query import SpatialQueryEngine
from volta.validation.spatial_drc import SpatialViolation


class RickDomain(str, Enum):
    """Rick analysis domain identifiers."""

    SI = "si"  # Signal Integrity
    PI = "pi"  # Power Integrity
    EMC = "emc"  # Electromagnetic Compatibility
    DFM = "dfm"  # Design for Manufacturing


@dataclass(frozen=True)
class RickFinding:
    """Single coordinate-grounded finding from a Rick domain analysis."""

    domain: str  # "si", "pi", "emc", "dfm"
    category: str  # Domain-specific category (e.g., "crosstalk", "decoupling")
    severity: str  # "critical", "warning", "info"
    description: str  # Human-readable finding description
    coordinates: tuple[tuple[float, float], ...]  # Affected coordinate positions
    affected_entities: tuple[dict, ...]  # JSON of nearby spatial primitives
    spatial_context: str  # Coordinate-grounded context string
    recommendation: str  # Fix recommendation

    def to_json(self) -> dict:
        """Serialize to a plain dict for JSON consumption."""
        return {
            "domain": self.domain,
            "category": self.category,
            "severity": self.severity,
            "description": self.description,
            "coordinates": list(self.coordinates),
            "affected_entities": list(self.affected_entities),
            "spatial_context": self.spatial_context,
            "recommendation": self.recommendation,
        }

    def format_finding(self) -> str:
        """Format as coordinate-grounded finding string."""
        parts = [
            f"[{self.domain.upper()}] [{self.severity.upper()}] "
            f"{self.category}: {self.description}",
        ]
        for x, y in self.coordinates:
            parts.append(f"  at <point> [{x:.4f}, {y:.4f}]")
        if self.affected_entities:
            parts.append(
                f"  Affected entities: {len(self.affected_entities)} primitives nearby"
            )
        parts.append(f"  {self.spatial_context}")
        parts.append(f"  Recommendation: {self.recommendation}")
        return "\n".join(parts)


@dataclass(frozen=True)
class SpatialRickReport:
    """Coordinate-grounded report for a specific Rick analysis domain."""

    domain: str
    board_path: str
    findings: tuple[RickFinding, ...]
    summary: str  # One-line summary of findings count and severity distribution

    def to_json(self) -> dict:
        """Serialize to a plain dict for JSON consumption."""
        return {
            "domain": self.domain,
            "board_path": self.board_path,
            "findings": [f.to_json() for f in self.findings],
            "summary": self.summary,
        }

    def format_report(self) -> str:
        """Format as coordinate-grounded report string."""
        lines = [f"=== {self.domain.upper()} Rick Report ===", self.summary, ""]
        for finding in self.findings:
            lines.append(finding.format_finding())
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _calculate_path_length(points: tuple[tuple[float, float], ...]) -> float:
    """Sum of Euclidean distances between consecutive points in a path.

    Args:
        points: Ordered (x, y) coordinate tuples.

    Returns:
        Total path length in mm. Returns 0.0 for fewer than 2 points.
    """
    if len(points) < 2:
        return 0.0
    total = 0.0
    for i in range(len(points) - 1):
        dx = points[i + 1][0] - points[i][0]
        dy = points[i + 1][1] - points[i][1]
        total += math.sqrt(dx * dx + dy * dy)
    return total


def _classify_net_type(net_name: str) -> str:
    """Classify a net name as power, signal, or unknown.

    Args:
        net_name: KiCad net name string.

    Returns:
        "power" for VCC/VDD/+3V3/+5V/GND/VIN nets,
        "signal" for non-empty non-power nets,
        "unknown" for empty strings.
    """
    if not net_name:
        return "unknown"
    power_prefixes = ("VCC", "VDD", "+3V3", "+5V", "GND", "VIN")
    for prefix in power_prefixes:
        if net_name.startswith(prefix):
            return "power"
    return "signal"


def _format_coords(coords: tuple[tuple[float, float], ...]) -> str:
    """Format coordinates as <point> [x, y] notation string."""
    if not coords:
        return "No coordinate data"
    parts = [f"<point> [{x:.4f}, {y:.4f}]" for x, y in coords]
    return "; ".join(parts)


def _build_summary(findings: tuple[RickFinding, ...]) -> str:
    """Build a one-line summary from findings."""
    if not findings:
        return "0 findings: 0 critical, 0 warning, 0 info"
    critical = sum(1 for f in findings if f.severity == "critical")
    warning = sum(1 for f in findings if f.severity == "warning")
    info = sum(1 for f in findings if f.severity == "info")
    return f"{len(findings)} findings: {critical} critical, {warning} warning, {info} info"


# ---------------------------------------------------------------------------
# Per-domain analysis helpers
# ---------------------------------------------------------------------------


def _analyze_si(
    engine: SpatialQueryEngine,
    primitives: list,
    spatial_violations: list[SpatialViolation] | None,
) -> list[RickFinding]:
    """Signal Integrity analysis: crosstalk, trace impedance, stub traces."""
    findings: list[RickFinding] = []

    # Gather all trace paths
    trace_paths = [p for p in primitives if isinstance(p, SpatialPath)]

    # --- Crosstalk: parallel traces on same layer within 2mm ---
    # Group paths by layer for pairwise comparison
    layers_seen: dict[str, list[SpatialPath]] = {}
    for tp in trace_paths:
        layers_seen.setdefault(tp.layer, []).append(tp)

    for layer, paths in layers_seen.items():
        for i, p1 in enumerate(paths):
            for p2 in paths[i + 1 :]:
                # Check if paths run parallel within 2mm
                # Simplified: compute minimum distance between the two LineStrings
                g1 = p1.to_shapely()
                g2 = p2.to_shapely()
                min_dist = g1.distance(g2)
                if 0 < min_dist <= 2.0:
                    # Check parallel run length (simplified: overlap length)
                    # Use the shorter path length as proxy for overlap
                    parallel_len = min(
                        _calculate_path_length(p1.points),
                        _calculate_path_length(p2.points),
                    )
                    if parallel_len > 5.0:
                        severity = "critical" if parallel_len > 10.0 else "warning"
                        # Midpoint coordinates of each path
                        mid1_x = (
                            p1.points[0][0] + p1.points[-1][0]
                        ) / 2
                        mid1_y = (
                            p1.points[0][1] + p1.points[-1][1]
                        ) / 2
                        mid2_x = (
                            p2.points[0][0] + p2.points[-1][0]
                        ) / 2
                        mid2_y = (
                            p2.points[0][1] + p2.points[-1][1]
                        ) / 2
                        coords = (
                            (mid1_x, mid1_y),
                            (mid2_x, mid2_y),
                        )
                        nearby = [
                            n.to_json()
                            for n in engine.proximity(mid1_x, mid1_y, 5.0)
                            if n.entity_id not in (p1.entity_id, p2.entity_id)
                        ]
                        findings.append(
                            RickFinding(
                                domain="si",
                                category="crosstalk",
                                severity=severity,
                                description=(
                                    f"Parallel traces {p1.entity_id} ({p1.net}) and "
                                    f"{p2.entity_id} ({p2.net}) on {layer}: "
                                    f"{min_dist:.2f}mm apart, ~{parallel_len:.1f}mm run"
                                ),
                                coordinates=coords,
                                affected_entities=tuple(nearby),
                                spatial_context=(
                                    f"Parallel traces at {_format_coords(coords)} "
                                    f"on layer {layer}"
                                ),
                                recommendation=(
                                    "Increase spacing to >2mm or add ground guard "
                                    "trace between signal pairs"
                                ),
                            )
                        )

    # --- Trace impedance: anomalous widths ---
    for tp in trace_paths:
        if tp.width > 0.5:
            mid_x = (tp.points[0][0] + tp.points[-1][0]) / 2
            mid_y = (tp.points[0][1] + tp.points[-1][1]) / 2
            findings.append(
                RickFinding(
                    domain="si",
                    category="trace_impedance",
                    severity="warning",
                    description=(
                        f"Trace {tp.entity_id} ({tp.net}) has anomalous width "
                        f"{tp.width:.2f}mm (expected < 0.5mm)"
                    ),
                    coordinates=((mid_x, mid_y),),
                    affected_entities=(),
                    spatial_context=f"Anomalous width at {_format_coords(((mid_x, mid_y),))}",
                    recommendation="Review trace width for impedance matching",
                )
            )
        elif tp.width < 0.1 and tp.width > 0:
            mid_x = (tp.points[0][0] + tp.points[-1][0]) / 2
            mid_y = (tp.points[0][1] + tp.points[-1][1]) / 2
            findings.append(
                RickFinding(
                    domain="si",
                    category="trace_impedance",
                    severity="warning",
                    description=(
                        f"Trace {tp.entity_id} ({tp.net}) has very narrow width "
                        f"{tp.width:.3f}mm (expected >= 0.1mm)"
                    ),
                    coordinates=((mid_x, mid_y),),
                    affected_entities=(),
                    spatial_context=f"Narrow trace at {_format_coords(((mid_x, mid_y),))}",
                    recommendation="Increase trace width for reliable manufacturing",
                )
            )

    # --- Stub traces: paths ending at a single point not connected to pad/via ---
    via_points = [p for p in primitives if isinstance(p, SpatialPoint)]
    for tp in trace_paths:
        end_point = tp.points[-1]
        # Check if end point is near any via/pad
        near_end = engine.proximity(end_point[0], end_point[1], 0.5)
        connected_at_end = any(
            isinstance(n, SpatialPoint) or isinstance(n, SpatialBox)
            for n in near_end
        )
        start_point = tp.points[0]
        near_start = engine.proximity(start_point[0], start_point[1], 0.5)
        connected_at_start = any(
            isinstance(n, SpatialPoint) or isinstance(n, SpatialBox)
            for n in near_start
        )
        # Stub = only one end connected
        if connected_at_start != connected_at_end:
            findings.append(
                RickFinding(
                    domain="si",
                    category="stub_traces",
                    severity="info",
                    description=(
                        f"Trace {tp.entity_id} ({tp.net}) may be a stub -- "
                        f"only one end appears connected"
                    ),
                    coordinates=(start_point, end_point),
                    affected_entities=(),
                    spatial_context=(
                        f"Potential stub at {_format_coords((start_point, end_point))}"
                    ),
                    recommendation="Review trace routing for stub removal",
                )
            )

    # --- Include relevant spatial violations ---
    if spatial_violations:
        for sv in spatial_violations:
            if "clearance" in sv.violation_type.lower() or "courtyard" in sv.violation_type.lower():
                coords = tuple((p.x, p.y) for p in sv.items)
                findings.append(
                    RickFinding(
                        domain="si",
                        category="clearance",
                        severity=sv.severity,
                        description=sv.description,
                        coordinates=coords,
                        affected_entities=(),
                        spatial_context=sv.spatial_context,
                        recommendation="Address clearance violation for signal integrity",
                    )
                )

    return findings


def _analyze_pi(
    engine: SpatialQueryEngine,
    primitives: list,
    spatial_violations: list[SpatialViolation] | None,
) -> list[RickFinding]:
    """Power Integrity analysis: decoupling, power plane continuity."""
    findings: list[RickFinding] = []

    # Find power net primitives
    power_nets: set[str] = set()
    for p in primitives:
        if hasattr(p, "net") and _classify_net_type(p.net) == "power":
            power_nets.add(p.net)

    if not power_nets:
        return findings

    # --- Decoupling: check caps near IC power pins ---
    # Find footprints that look like decoupling caps (reference starts with "C")
    footprints = [p for p in primitives if isinstance(p, SpatialBox)]
    cap_footprints = [fp for fp in footprints if fp.reference.startswith("C")]
    ic_footprints = [
        fp
        for fp in footprints
        if fp.reference
        and fp.reference[0] in ("U", "IC")
        and not fp.reference.startswith("C")
    ]

    for ic in ic_footprints:
        ic_x = (ic.x1 + ic.x2) / 2
        ic_y = (ic.y1 + ic.y2) / 2
        # Check for decoupling cap within 10mm
        has_nearby_cap = False
        for cap in cap_footprints:
            cap_x = (cap.x1 + cap.x2) / 2
            cap_y = (cap.y1 + cap.y2) / 2
            dist = math.sqrt((ic_x - cap_x) ** 2 + (ic_y - cap_y) ** 2)
            if dist <= 10.0:
                has_nearby_cap = True
                break
        if not has_nearby_cap and cap_footprints:
            findings.append(
                RickFinding(
                    domain="pi",
                    category="decoupling",
                    severity="warning",
                    description=(
                        f"IC {ic.reference} has no decoupling capacitor within 10mm"
                    ),
                    coordinates=((ic_x, ic_y),),
                    affected_entities=(),
                    spatial_context=(
                        f"IC at {_format_coords(((ic_x, ic_y),))} lacks nearby "
                        f"decoupling capacitor"
                    ),
                    recommendation=(
                        "Place a 100nF decoupling capacitor within 10mm of IC "
                        "power pins"
                    ),
                )
            )

    # --- Power primitives found (informational) ---
    for net in power_nets:
        net_prims = engine.find_by_net(net)
        if net_prims:
            # Get representative coordinate from first primitive
            first = net_prims[0]
            if isinstance(first, SpatialPoint):
                coords = ((first.x, first.y),)
            elif isinstance(first, SpatialBox):
                coords = (((first.x1 + first.x2) / 2, (first.y1 + first.y2) / 2),)
            elif isinstance(first, SpatialPath):
                coords = (first.points[0],)
            else:
                coords = ((0.0, 0.0),)
            findings.append(
                RickFinding(
                    domain="pi",
                    category="power_net",
                    severity="info",
                    description=(
                        f"Power net '{net}' has {len(net_prims)} "
                        f"spatial primitives"
                    ),
                    coordinates=coords,
                    affected_entities=tuple(p.to_json() for p in net_prims[:5]),
                    spatial_context=(
                        f"Power net '{net}' primitives near {_format_coords(coords)}"
                    ),
                    recommendation="Verify power plane coverage and decoupling strategy",
                )
            )

    # --- Power plane continuity: check for zones on power layers ---
    regions = [p for p in primitives if isinstance(p, SpatialRegion)]
    power_regions = [
        r for r in regions if _classify_net_type(r.net) == "power"
    ]
    if not power_regions and power_nets:
        for net in power_nets:
            findings.append(
                RickFinding(
                    domain="pi",
                    category="power_plane_continuity",
                    severity="warning",
                    description=(
                        f"No copper zone/region found for power net '{net}'"
                    ),
                    coordinates=((0.0, 0.0),),
                    affected_entities=(),
                    spatial_context=(
                        f"No power plane region for net '{net}'"
                    ),
                    recommendation=(
                        "Add a copper zone on the power layer for "
                        f"net '{net}' to ensure plane continuity"
                    ),
                )
            )

    return findings


def _analyze_emc(
    engine: SpatialQueryEngine,
    primitives: list,
    spatial_violations: list[SpatialViolation] | None,
) -> list[RickFinding]:
    """EMC analysis: trace length, clearance, ground plane coverage."""
    findings: list[RickFinding] = []

    # --- Trace length: flag long traces as potential antennas ---
    trace_paths = [p for p in primitives if isinstance(p, SpatialPath)]
    for tp in trace_paths:
        length = _calculate_path_length(tp.points)
        if length > 50.0:
            severity = "critical" if length > 100.0 else "warning"
            mid_x = (tp.points[0][0] + tp.points[-1][0]) / 2
            mid_y = (tp.points[0][1] + tp.points[-1][1]) / 2
            coords = (tp.points[0], tp.points[-1])
            findings.append(
                RickFinding(
                    domain="emc",
                    category="trace_length",
                    severity=severity,
                    description=(
                        f"Trace {tp.entity_id} ({tp.net}) is {length:.1f}mm long -- "
                        f"potential antenna"
                    ),
                    coordinates=coords,
                    affected_entities=(),
                    spatial_context=(
                        f"Long trace from {_format_coords(coords)} on {tp.layer}"
                    ),
                    recommendation=(
                        "Route with controlled impedance or add series termination"
                    ),
                )
            )

    # --- Clearance: use spatial violations if provided ---
    if spatial_violations:
        for sv in spatial_violations:
            if "clearance" in sv.violation_type.lower():
                coords = tuple((p.x, p.y) for p in sv.items)
                findings.append(
                    RickFinding(
                        domain="emc",
                        category="clearance",
                        severity=sv.severity,
                        description=(
                            f"Clearance violation: {sv.description}"
                        ),
                        coordinates=coords,
                        affected_entities=(),
                        spatial_context=sv.spatial_context,
                        recommendation=(
                            "Increase trace spacing to meet EMC clearance "
                            "requirements"
                        ),
                    )
                )

    # --- Ground plane coverage: check for ground primitives ---
    ground_prims = engine.find_by_net("GND")
    if not ground_prims:
        findings.append(
            RickFinding(
                domain="emc",
                category="ground_plane_coverage",
                severity="warning",
                description="No ground net primitives found -- ground plane may be missing",
                coordinates=((0.0, 0.0),),
                affected_entities=(),
                spatial_context="No GND primitives detected on board",
                recommendation=(
                    "Add a ground plane on inner layer or bottom layer for "
                    "EMC compliance"
                ),
            )
        )

    return findings


def _analyze_dfm(
    engine: SpatialQueryEngine,
    primitives: list,
    spatial_violations: list[SpatialViolation] | None,
) -> list[RickFinding]:
    """DFM analysis: component density, minimum feature size, board edge clearance."""
    findings: list[RickFinding] = []

    # --- Minimum feature size: traces narrower than 0.15mm ---
    trace_paths = [p for p in primitives if isinstance(p, SpatialPath)]
    for tp in trace_paths:
        if 0 < tp.width < 0.15:
            mid_x = (tp.points[0][0] + tp.points[-1][0]) / 2
            mid_y = (tp.points[0][1] + tp.points[-1][1]) / 2
            findings.append(
                RickFinding(
                    domain="dfm",
                    category="minimum_feature_size",
                    severity="warning",
                    description=(
                        f"Trace {tp.entity_id} ({tp.net}) width {tp.width:.3f}mm "
                        f"below DFM minimum 0.15mm"
                    ),
                    coordinates=((mid_x, mid_y),),
                    affected_entities=(),
                    spatial_context=(
                        f"Narrow trace at {_format_coords(((mid_x, mid_y),))} "
                        f"on {tp.layer}"
                    ),
                    recommendation="Increase trace width to at least 0.15mm",
                )
            )

    # --- Component density: check 10mm x 10mm windows ---
    footprints = [p for p in primitives if isinstance(p, SpatialBox)]
    if footprints:
        # Determine board bounding box from all footprints
        all_x1 = [fp.x1 for fp in footprints]
        all_y1 = [fp.y1 for fp in footprints]
        all_x2 = [fp.x2 for fp in footprints]
        all_y2 = [fp.y2 for fp in footprints]
        board_x_min = min(all_x1) - 5.0
        board_y_min = min(all_y1) - 5.0
        board_x_max = max(all_x2) + 5.0
        board_y_max = max(all_y2) + 5.0

        # Slide 10mm window
        step = 10.0
        x = board_x_min
        while x < board_x_max:
            y = board_y_min
            while y < board_y_max:
                contained = engine.containment(x, y, x + step, y + step)
                fp_count = sum(1 for p in contained if isinstance(p, SpatialBox))
                if fp_count > 20:
                    center_x = x + step / 2
                    center_y = y + step / 2
                    findings.append(
                        RickFinding(
                            domain="dfm",
                            category="component_density",
                            severity="warning",
                            description=(
                                f"Dense region: {fp_count} components in "
                                f"10mm x 10mm window"
                            ),
                            coordinates=((center_x, center_y),),
                            affected_entities=tuple(
                                p.to_json()
                                for p in contained
                                if isinstance(p, SpatialBox)
                            ),
                            spatial_context=(
                                f"Dense area at {_format_coords(((center_x, center_y),))}"
                            ),
                            recommendation=(
                                "Reduce component density for assembly reliability"
                            ),
                        )
                    )
                y += step
            x += step

    # --- Board edge clearance: primitives near board edges ---
    # Simplified: check primitives near (0, y), (x, 0) assuming board
    # origin is near (0,0). More accurate would need board outline data.
    if footprints:
        edge_margin = 3.0
        for fp in footprints:
            fp_min_x = min(fp.x1, fp.x2)
            fp_min_y = min(fp.y1, fp.y2)
            if fp_min_x < edge_margin or fp_min_y < edge_margin:
                cx = (fp.x1 + fp.x2) / 2
                cy = (fp.y1 + fp.y2) / 2
                findings.append(
                    RickFinding(
                        domain="dfm",
                        category="board_edge_clearance",
                        severity="info",
                        description=(
                            f"Footprint {fp.reference} is within {edge_margin}mm "
                            f"of board edge"
                        ),
                        coordinates=((cx, cy),),
                        affected_entities=(),
                        spatial_context=(
                            f"Component near board edge at {_format_coords(((cx, cy),))}"
                        ),
                        recommendation=(
                            "Ensure adequate board edge clearance for assembly"
                        ),
                    )
                )

    return findings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_spatial_report(
    domain: RickDomain,
    pcb_primitives: list,
    spatial_violations: list[SpatialViolation] | None = None,
    board_path: str = "",
) -> SpatialRickReport:
    """Generate a coordinate-grounded report for a specific Rick domain.

    Each domain maps its specific concerns to PCB coordinates with nearby
    primitive context using the SpatialQueryEngine.

    Args:
        domain: The Rick analysis domain (SI, PI, EMC, DFM).
        pcb_primitives: List of spatial primitives extracted from PCB data.
        spatial_violations: Optional spatially-grounded DRC violations to
            include in domain analysis.
        board_path: Path to the board file for report metadata.

    Returns:
        SpatialRickReport with coordinate-grounded findings.

    Raises:
        ValueError: If domain is not a valid RickDomain.
    """
    if not isinstance(domain, RickDomain):
        raise ValueError(f"domain must be a RickDomain, got {type(domain)}")

    engine = SpatialQueryEngine(pcb_primitives)

    domain_analyzers = {
        RickDomain.SI: _analyze_si,
        RickDomain.PI: _analyze_pi,
        RickDomain.EMC: _analyze_emc,
        RickDomain.DFM: _analyze_dfm,
    }

    analyzer = domain_analyzers[domain]
    findings_list = analyzer(engine, pcb_primitives, spatial_violations)
    findings = tuple(findings_list)
    summary = _build_summary(findings)

    return SpatialRickReport(
        domain=domain.value,
        board_path=board_path,
        findings=findings,
        summary=summary,
    )


def generate_all_reports(
    pcb_primitives: list,
    spatial_violations: list[SpatialViolation] | None = None,
    board_path: str = "",
) -> dict[str, SpatialRickReport]:
    """Generate reports for all four Rick domains.

    Args:
        pcb_primitives: List of spatial primitives extracted from PCB data.
        spatial_violations: Optional spatially-grounded DRC violations.
        board_path: Path to the board file for report metadata.

    Returns:
        Dict mapping domain string ("si", "pi", "emc", "dfm") to
        SpatialRickReport objects.
    """
    reports: dict[str, SpatialRickReport] = {}
    for domain in RickDomain:
        reports[domain.value] = generate_spatial_report(
            domain, pcb_primitives, spatial_violations, board_path
        )
    return reports
