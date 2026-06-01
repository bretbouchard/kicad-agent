"""DFM multi-stage pipeline, panelization scoring, and assembly checks.

DFM-04: Multi-stage DFM analysis (footprint audit, placement check, post-route check).
DFM-05: Panelization readiness scoring and assembly consideration checks.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any

from pydantic import BaseModel, Field

from kicad_agent.dfm.checker import DfmCheck, DfmChecker, DfmReport, DfmFinding, DfmSeverity
from kicad_agent.dfm.checks import get_builtin_dfm_checks
from kicad_agent.dfm.profiles import ManufacturerProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PanelizationScore
# ---------------------------------------------------------------------------


class PanelizationScore(BaseModel):
    """Panelization readiness score for manufacturing.

    Evaluates fiducials, tooling holes, component orientation,
    and edge clearance to produce a 0.0-1.0 readiness score.

    Attributes:
        score: Readiness score 0.0-1.0.
        has_fiducials: At least 3 fiducial marks detected.
        has_tooling_holes: At least 3 tooling holes detected.
        fiducial_count: Number of fiducials found.
        tooling_hole_count: Number of tooling holes found.
        component_orientation_ok: All components at 0/90/180/270 degrees.
        edge_clearance_ok: Components clear of board edge.
        findings: Panelization-specific findings.
        details: Extra context (board dimensions, etc.).
    """

    score: float = Field(ge=0.0, le=1.0)
    has_fiducials: bool = False
    has_tooling_holes: bool = False
    fiducial_count: int = Field(default=0, ge=0)
    tooling_hole_count: int = Field(default=0, ge=0)
    component_orientation_ok: bool = True
    edge_clearance_ok: bool = True
    findings: tuple[DfmFinding, ...] = Field(default_factory=tuple)
    details: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# AssemblyCheckResult
# ---------------------------------------------------------------------------


class AssemblyCheckResult(BaseModel):
    """Assembly consideration check results.

    Evaluates component orientation, spacing for pick-and-place,
    and polarity marking for polarized components.

    Attributes:
        orientation_findings: Components with non-standard rotation.
        spacing_findings: Components too close for pick-and-place.
        polarity_findings: Polarized components missing orientation mark.
        assembly_score: 0.0-1.0 readiness score.
        summary: Human-readable summary.
    """

    orientation_findings: tuple[DfmFinding, ...] = Field(default_factory=tuple)
    spacing_findings: tuple[DfmFinding, ...] = Field(default_factory=tuple)
    polarity_findings: tuple[DfmFinding, ...] = Field(default_factory=tuple)
    assembly_score: float = Field(ge=0.0, le=1.0)
    summary: str = ""


# ---------------------------------------------------------------------------
# MultiStageDfmReport
# ---------------------------------------------------------------------------


class MultiStageDfmReport(BaseModel):
    """Multi-stage DFM analysis report.

    Runs three stages of DFM analysis plus panelization scoring
    and assembly checks, aggregating results into a single report.

    Attributes:
        footprint_audit: Stage 1 results (pre-placement checks).
        placement_check: Stage 2 results (component spacing checks).
        post_route_check: Stage 3 results (manufacturing constraint checks).
        panelization: Panelization readiness score.
        assembly: Assembly check results.
        overall_score: Minimum of all stage scores and panelization score.
        total_findings: Sum of all findings across stages.
        elapsed_ms: Total pipeline execution time.
    """

    footprint_audit: DfmReport
    placement_check: DfmReport
    post_route_check: DfmReport
    panelization: PanelizationScore
    assembly: AssemblyCheckResult
    overall_score: float = Field(ge=0.0, le=1.0)
    total_findings: int = Field(default=0, ge=0)
    elapsed_ms: float = Field(default=0.0, ge=0.0)


# ---------------------------------------------------------------------------
# Panelization readiness scoring (DFM-05)
# ---------------------------------------------------------------------------

_STANDARD_ORIENTATIONS = {0, 90, 180, 270, -90, -180, -270, 360}

_FIDUCIAL_TYPES = {"fiducial", "fiducial_mark"}

_TOOLING_TYPES = {"tooling_hole", "tooling", "mounting_hole"}

_COMPONENT_TYPES = {"footprint", "component"}


def score_panelization_readiness(
    spatial_model: Any,
    profile: ManufacturerProfile,
) -> PanelizationScore:
    """Evaluate board for panelization manufacturing readiness.

    Scans for fiducials, tooling holes, component orientation,
    and edge clearance. Produces a readiness score 0.0-1.0.

    Score formula:
        +0.3 if 3+ fiducials, +0.15 if 1-2 fiducials
        +0.2 if 3+ tooling holes, +0.1 if 1-2 tooling holes
        +0.3 if all components at standard orientations
        +0.2 if edge clearance OK
        Clamped to [0.0, 1.0]

    Args:
        spatial_model: PcbSpatialModel to evaluate.
        profile: ManufacturerProfile with constraints.

    Returns:
        PanelizationScore with readiness assessment.
    """
    findings: list[DfmFinding] = []
    primitives = spatial_model.all_primitives if hasattr(spatial_model, "all_primitives") else []

    # 1. Count fiducials
    fiducial_count = 0
    for p in primitives:
        etype = getattr(p, "entity_type", "")
        if not isinstance(etype, str):
            etype = ""
        ref = getattr(p, "reference", "")
        if not isinstance(ref, str):
            ref = ""
        if etype in _FIDUCIAL_TYPES or "fiducial" in etype.lower():
            fiducial_count += 1
        elif ref.upper().startswith("FID") or "FIDUCIAL" in ref.upper():
            fiducial_count += 1

    has_fiducials = fiducial_count >= 3

    # 2. Count tooling holes
    tooling_count = 0
    for p in primitives:
        etype = getattr(p, "entity_type", "")
        if etype in _TOOLING_TYPES:
            tooling_count += 1

    has_tooling_holes = tooling_count >= 3

    # 3. Check component orientation
    orientation_ok = True
    for p in primitives:
        etype = getattr(p, "entity_type", "")
        if etype not in _COMPONENT_TYPES:
            continue
        rotation = getattr(p, "rotation", None)
        if rotation is None:
            continue
        # Normalize rotation to 0-360
        normalized = rotation % 360
        if normalized not in {0, 90, 180, 270}:
            orientation_ok = False
            eid = getattr(p, "entity_id", "")
            ref = getattr(p, "reference", eid)
            findings.append(DfmFinding(
                check_id="PANELIZE_01",
                description=(
                    f"Component {ref} at non-standard rotation "
                    f"{rotation} degrees (expected 0/90/180/270)"
                ),
                severity=DfmSeverity.WARNING,
                location=ref,
                suggestion="Rotate component to 0, 90, 180, or 270 degrees for panelization",
                affected_entities=(eid,),
                details={"rotation": rotation},
            ))

    # 4. Check edge clearance
    edge_ok = _check_edge_clearance(primitives)
    if not edge_ok:
        findings.append(DfmFinding(
            check_id="PANELIZE_02",
            description="Component(s) may overlap with board edge (Edge.Cuts)",
            severity=DfmSeverity.WARNING,
            location="(edge)",
            suggestion="Move components away from board edge for panelization clearance",
            affected_entities=(),
            details={},
        ))

    # 5. Compute score
    score = 0.0
    if fiducial_count >= 3:
        score += 0.3
    elif fiducial_count >= 1:
        score += 0.15

    if tooling_count >= 3:
        score += 0.2
    elif tooling_count >= 1:
        score += 0.1

    if orientation_ok:
        score += 0.3

    if edge_ok:
        score += 0.2

    score = max(0.0, min(1.0, score))

    return PanelizationScore(
        score=score,
        has_fiducials=has_fiducials,
        has_tooling_holes=has_tooling_holes,
        fiducial_count=fiducial_count,
        tooling_hole_count=tooling_count,
        component_orientation_ok=orientation_ok,
        edge_clearance_ok=edge_ok,
        findings=tuple(findings),
        details={
            "fiducial_count": fiducial_count,
            "tooling_hole_count": tooling_count,
        },
    )


def _check_edge_clearance(primitives: list[Any]) -> bool:
    """Check that components are clear of board edge geometry.

    Args:
        primitives: List of spatial primitives to check.

    Returns:
        True if all components are clear of Edge.Cuts geometry.
    """
    edge_prims = []
    component_prims = []
    for p in primitives:
        layer = getattr(p, "layer", "")
        etype = getattr(p, "entity_type", "")
        if layer == "Edge.Cuts":
            edge_prims.append(p)
        elif etype in _COMPONENT_TYPES:
            component_prims.append(p)

    if not edge_prims or not component_prims:
        # No edge or no components -> OK by default
        return True

    edge_geoms = []
    for ep in edge_prims:
        geom = ep.to_shapely() if hasattr(ep, "to_shapely") else None
        if geom is not None:
            edge_geoms.append(geom)

    if not edge_geoms:
        return True

    # Build a combined edge geometry
    from shapely.ops import unary_union
    try:
        edge_union = unary_union(edge_geoms)
    except Exception:
        return True

    # Buffer edge slightly (0.5mm clearance zone)
    try:
        edge_buffer = edge_union.buffer(0.5)
    except Exception:
        return True

    for comp in component_prims:
        geom = comp.to_shapely() if hasattr(comp, "to_shapely") else None
        if geom is None:
            continue
        try:
            if geom.intersects(edge_buffer):
                return False
        except Exception:
            continue

    return True


# ---------------------------------------------------------------------------
# Assembly checks
# ---------------------------------------------------------------------------

_POLARIZED_PREFIXES = ("C_Pol", "D", "U")


def run_assembly_checks(
    spatial_model: Any,
    profile: ManufacturerProfile,
) -> AssemblyCheckResult:
    """Validate pick-and-place assembly readiness.

    Checks:
    1. Orientation: components at 0/90/180/270 degrees
    2. Spacing: components far enough apart for pick-and-place nozzle
    3. Polarity: polarized components have orientation marks

    Args:
        spatial_model: PcbSpatialModel to check.
        profile: ManufacturerProfile with constraints.

    Returns:
        AssemblyCheckResult with findings and score.
    """
    primitives = spatial_model.all_primitives if hasattr(spatial_model, "all_primitives") else []

    orientation_findings: list[DfmFinding] = []
    spacing_findings: list[DfmFinding] = []
    polarity_findings: list[DfmFinding] = []

    # Collect components
    components: list[Any] = []
    for p in primitives:
        etype = getattr(p, "entity_type", "")
        if etype in _COMPONENT_TYPES:
            components.append(p)

    # 1. Orientation check
    for comp in components:
        rotation = getattr(comp, "rotation", None)
        if rotation is None:
            continue
        normalized = rotation % 360
        if normalized not in {0, 90, 180, 270}:
            eid = getattr(comp, "entity_id", "")
            ref = getattr(comp, "reference", eid)
            orientation_findings.append(DfmFinding(
                check_id="ASSEMBLY_01",
                description=(
                    f"Component {ref} at rotation {rotation} degrees -- "
                    f"pick-and-place prefers 0/90/180/270"
                ),
                severity=DfmSeverity.WARNING,
                location=ref,
                suggestion=f"Rotate {ref} to 0, 90, 180, or 270 degrees",
                affected_entities=(eid,),
                details={"rotation": rotation},
            ))

    # 2. Spacing check (center-to-center distance < clearance * 3)
    min_spacing = profile.min_clearance_mm * 3.0
    for i, comp_a in enumerate(components):
        x1_a = getattr(comp_a, "x1", 0) or 0
        y1_a = getattr(comp_a, "y1", 0) or 0
        x2_a = getattr(comp_a, "x2", 0) or 0
        y2_a = getattr(comp_a, "y2", 0) or 0
        cx_a = (x1_a + x2_a) / 2.0
        cy_a = (y1_a + y2_a) / 2.0
        eid_a = getattr(comp_a, "entity_id", "")
        ref_a = getattr(comp_a, "reference", eid_a)

        for comp_b in components[i + 1:]:
            x1_b = getattr(comp_b, "x1", 0) or 0
            y1_b = getattr(comp_b, "y1", 0) or 0
            x2_b = getattr(comp_b, "x2", 0) or 0
            y2_b = getattr(comp_b, "y2", 0) or 0
            cx_b = (x1_b + x2_b) / 2.0
            cy_b = (y1_b + y2_b) / 2.0

            dist = math.sqrt((cx_b - cx_a) ** 2 + (cy_b - cy_a) ** 2)
            if dist < min_spacing:
                eid_b = getattr(comp_b, "entity_id", "")
                ref_b = getattr(comp_b, "reference", eid_b)
                spacing_findings.append(DfmFinding(
                    check_id="ASSEMBLY_02",
                    description=(
                        f"Components {ref_a} and {ref_b} too close "
                        f"({dist:.2f}mm < {min_spacing:.2f}mm) for pick-and-place"
                    ),
                    severity=DfmSeverity.WARNING,
                    location=f"{ref_a}, {ref_b}",
                    suggestion="Increase spacing between components for pick-and-place clearance",
                    affected_entities=(eid_a, eid_b),
                    details={"distance_mm": round(dist, 4), "minimum_mm": round(min_spacing, 4)},
                ))

    # 3. Polarity check
    for comp in components:
        ref = getattr(comp, "reference", "")
        if not ref:
            continue
        is_polarized = False
        for prefix in _POLARIZED_PREFIXES:
            if ref.startswith(prefix):
                is_polarized = True
                break
        if not is_polarized:
            continue

        # Emit INFO -- we cannot confirm orientation mark from spatial model alone
        eid = getattr(comp, "entity_id", "")
        polarity_findings.append(DfmFinding(
            check_id="ASSEMBLY_03",
            description=(
                f"Polarized component {ref} -- verify orientation mark is correct"
            ),
            severity=DfmSeverity.INFO,
            location=ref,
            suggestion="Ensure polarity/orientation mark is visible on silkscreen",
            affected_entities=(eid,),
            details={"component_ref": ref},
        ))

    # 4. Compute assembly score
    total_warnings = len(orientation_findings) + len(spacing_findings)
    assembly_score = max(0.0, min(1.0, 1.0 - total_warnings * 0.05))

    summary = (
        f"Assembly readiness: {assembly_score:.0%}. "
        f"{len(orientation_findings)} orientation, "
        f"{len(spacing_findings)} spacing, "
        f"{len(polarity_findings)} polarity findings."
    )

    return AssemblyCheckResult(
        orientation_findings=tuple(orientation_findings),
        spacing_findings=tuple(spacing_findings),
        polarity_findings=tuple(polarity_findings),
        assembly_score=assembly_score,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Multi-stage DFM pipeline (DFM-04)
# ---------------------------------------------------------------------------

_FOOTPRINT_AUDIT_CHECKS = {"ANNULAR_RING_01", "MIN_DRILL_01"}
_PLACEMENT_CHECK_CHECKS = {"SOLDER_MASK_01", "THERMAL_RELIEF_01"}
_POST_ROUTE_CHECK_CHECKS = {"MIN_TRACE_01", "MIN_DRILL_01"}


def _filter_checks(names: set[str]) -> list[DfmCheck]:
    """Get builtin checks filtered to only the named subset."""
    return [c for c in get_builtin_dfm_checks() if c.name in names]


def run_multistage_dfm(
    spatial_model: Any,
    profile: ManufacturerProfile,
    config: dict[str, dict[str, Any]] | None = None,
) -> MultiStageDfmReport:
    """Run 3-stage DFM pipeline plus panelization and assembly checks.

    Stages:
    1. Footprint Audit: ANNULAR_RING_01, MIN_DRILL_01
    2. Placement Check: SOLDER_MASK_01, THERMAL_RELIEF_01
    3. Post-Route Check: MIN_TRACE_01, MIN_DRILL_01

    Args:
        spatial_model: PcbSpatialModel to analyze.
        profile: ManufacturerProfile with constraints.
        config: Optional per-check configuration overrides.

    Returns:
        MultiStageDfmReport with all stage results.
    """
    start = time.monotonic()

    # Stage 1: Footprint audit (pre-placement checks)
    checker_1 = DfmChecker(checks=_filter_checks(_FOOTPRINT_AUDIT_CHECKS), config=config)
    footprint_audit = checker_1.run(spatial_model, profile)

    # Stage 2: Placement check (component spacing for assembly)
    checker_2 = DfmChecker(checks=_filter_checks(_PLACEMENT_CHECK_CHECKS), config=config)
    placement_check = checker_2.run(spatial_model, profile)

    # Stage 3: Post-route check (manufacturing constraints)
    checker_3 = DfmChecker(checks=_filter_checks(_POST_ROUTE_CHECK_CHECKS), config=config)
    post_route_check = checker_3.run(spatial_model, profile)

    # Panelization readiness
    panelization = score_panelization_readiness(spatial_model, profile)

    # Assembly checks
    assembly = run_assembly_checks(spatial_model, profile)

    # Overall score is minimum of stage scores and panelization score
    stage_scores = [
        footprint_audit.manufacturability_score,
        placement_check.manufacturability_score,
        post_route_check.manufacturability_score,
        panelization.score,
    ]
    overall_score = min(stage_scores)

    # Total findings across all stages
    total_findings = (
        len(footprint_audit.findings)
        + len(placement_check.findings)
        + len(post_route_check.findings)
    )

    elapsed = (time.monotonic() - start) * 1000

    return MultiStageDfmReport(
        footprint_audit=footprint_audit,
        placement_check=placement_check,
        post_route_check=post_route_check,
        panelization=panelization,
        assembly=assembly,
        overall_score=overall_score,
        total_findings=total_findings,
        elapsed_ms=elapsed,
    )
