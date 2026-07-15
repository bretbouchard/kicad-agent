"""Tests for DFM multi-stage pipeline, panelization scoring, and assembly checks.

Covers:
- MultiStageDfmReport (3-stage pipeline, score aggregation)
- PanelizationScore (fiducials, tooling holes, orientation, edge clearance)
- AssemblyCheckResult (orientation, spacing, polarity findings)
- run_multistage_dfm() pipeline
- score_panelization_readiness() scoring
- run_assembly_checks() validation
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from volta.dfm.checker import (
    DfmCheck,
    DfmChecker,
    DfmFinding,
    DfmReport,
    DfmSeverity,
)
from volta.dfm.profiles import (
    ManufacturerProfile,
    get_builtin_profiles,
    load_profile,
)


# ===========================================================================
# Helpers
# ===========================================================================


class _MockSpatialModel:
    """Minimal spatial model mock for scoring tests."""

    def __init__(self, primitives=None):
        self._primitives = primitives or []

    @property
    def all_primitives(self):
        return list(self._primitives)

    def layer_primitives(self, layer_name: str):
        return [p for p in self._primitives if getattr(p, "layer", "") == layer_name]


def _make_box(
    x1=0, y1=0, x2=1, y2=1,
    entity_type="pad", entity_id="p1",
    layer="F.Cu", reference="U1",
    rotation=None, net="",
):
    """Create a mock SpatialBox primitive."""
    from shapely.geometry import box as shapely_box

    box = MagicMock()
    box.x1 = x1
    box.y1 = y1
    box.x2 = x2
    box.y2 = y2
    box.entity_type = entity_type
    box.entity_id = entity_id
    box.layer = layer
    box.reference = reference
    box.rotation = rotation
    box.net = net
    box.to_shapely.return_value = shapely_box(x1, y1, x2, y2)
    return box


def _make_point(
    x=0, y=0,
    entity_type="via_drill", entity_id="v1",
    layer="", net="",
    drill_diameter=None,
):
    """Create a mock SpatialPoint primitive."""
    from shapely.geometry import Point

    pt = MagicMock()
    pt.x = x
    pt.y = y
    pt.entity_type = entity_type
    pt.entity_id = entity_id
    pt.layer = layer
    pt.net = net
    pt.drill_diameter = drill_diameter
    pt.to_shapely.return_value = Point(x, y)
    return pt


def _make_path(
    points=((0, 0), (10, 0)),
    entity_type="trace", entity_id="t1",
    layer="F.Cu", net="", width=0.2,
):
    """Create a mock SpatialPath primitive."""
    from shapely.geometry import LineString

    path = MagicMock()
    path.points = points
    path.entity_type = entity_type
    path.entity_id = entity_id
    path.layer = layer
    path.net = net
    path.width = width
    path.to_shapely.return_value = LineString(points)
    return path


def _make_region(
    boundary=((0, 0), (10, 0), (10, 10), (0, 10)),
    entity_type="zone", entity_id="z1",
    layer="F.Cu", net="GND",
):
    """Create a mock region/zone primitive."""
    from shapely.geometry import Polygon

    region = MagicMock()
    region.boundary = boundary
    region.entity_type = entity_type
    region.entity_id = entity_id
    region.layer = layer
    region.net = net
    region.to_shapely.return_value = Polygon(boundary)
    return region


# ===========================================================================
# TestPanelizationScore
# ===========================================================================


class TestPanelizationScore:
    """Panelization readiness scoring: fiducials, tooling holes, orientation, edge clearance."""

    def test_no_fiducials_low_score(self):
        """Board with no fiducials, no tooling holes, non-standard orientation has low score."""
        from volta.dfm.scoring import score_panelization_readiness

        primitives = [
            _make_box(x1=0, y1=0, x2=10, y2=10,
                      entity_type="footprint", entity_id="U1", reference="U1",
                      rotation=45),  # Non-standard orientation reduces score
        ]
        model = _MockSpatialModel(primitives=primitives)
        profile = get_builtin_profiles()["generic"]

        score = score_panelization_readiness(model, profile)
        assert score.score < 0.5
        assert score.has_fiducials is False
        assert score.fiducial_count == 0

    def test_three_fiducials_high_score(self):
        """Board with 3 fiducials and tooling holes has high panelization score."""
        from volta.dfm.scoring import score_panelization_readiness

        primitives = [
            # 3 fiducials
            _make_box(x1=0, y1=0, x2=1, y2=1,
                      entity_type="fiducial", entity_id="FID1", reference="FID1",
                      rotation=0),
            _make_box(x1=50, y1=0, x2=51, y2=1,
                      entity_type="fiducial", entity_id="FID2", reference="FID2",
                      rotation=0),
            _make_box(x1=0, y1=50, x2=1, y2=51,
                      entity_type="fiducial", entity_id="FID3", reference="FID3",
                      rotation=0),
            # 3 tooling holes
            _make_point(x=2, y=2, entity_type="tooling_hole",
                        entity_id="TH1", drill_diameter=3.0),
            _make_point(x=48, y=2, entity_type="tooling_hole",
                        entity_id="TH2", drill_diameter=3.0),
            _make_point(x=2, y=48, entity_type="tooling_hole",
                        entity_id="TH3", drill_diameter=3.0),
            # Standard orientation component
            _make_box(x1=10, y1=10, x2=15, y2=15,
                      entity_type="footprint", entity_id="U1", reference="U1",
                      rotation=0),
            # Edge cuts (far from components)
            _make_path(
                points=((0, 0), (60, 0), (60, 60), (0, 60), (0, 0)),
                entity_type="line", entity_id="edge1",
                layer="Edge.Cuts", width=0.15,
            ),
        ]
        model = _MockSpatialModel(primitives=primitives)
        profile = get_builtin_profiles()["generic"]

        score = score_panelization_readiness(model, profile)
        assert score.score >= 0.7
        assert score.has_fiducials is True
        assert score.fiducial_count == 3
        assert score.has_tooling_holes is True
        assert score.tooling_hole_count == 3

    def test_tooling_holes_contribute(self):
        """Adding tooling holes improves the score."""
        from volta.dfm.scoring import score_panelization_readiness

        # No tooling holes
        primitives_no_th = [
            _make_box(x1=10, y1=10, x2=15, y2=15,
                      entity_type="footprint", entity_id="U1", reference="U1",
                      rotation=0),
        ]
        model_no_th = _MockSpatialModel(primitives=primitives_no_th)
        profile = get_builtin_profiles()["generic"]
        score_no_th = score_panelization_readiness(model_no_th, profile)

        # With tooling holes
        primitives_with_th = primitives_no_th + [
            _make_point(x=2, y=2, entity_type="tooling_hole",
                        entity_id="TH1", drill_diameter=3.0),
            _make_point(x=48, y=2, entity_type="tooling_hole",
                        entity_id="TH2", drill_diameter=3.0),
            _make_point(x=2, y=48, entity_type="tooling_hole",
                        entity_id="TH3", drill_diameter=3.0),
        ]
        model_with_th = _MockSpatialModel(primitives=primitives_with_th)
        score_with_th = score_panelization_readiness(model_with_th, profile)

        assert score_with_th.score > score_no_th.score

    def test_non_standard_orientation_flags(self):
        """Component at non-standard rotation (45 degrees) is flagged."""
        from volta.dfm.scoring import score_panelization_readiness

        primitives = [
            _make_box(x1=10, y1=10, x2=15, y2=15,
                      entity_type="footprint", entity_id="U1", reference="U1",
                      rotation=45),  # Non-standard
        ]
        model = _MockSpatialModel(primitives=primitives)
        profile = get_builtin_profiles()["generic"]

        score = score_panelization_readiness(model, profile)
        assert score.component_orientation_ok is False
        # Should have a finding about the non-standard orientation
        assert any("orientation" in f.description.lower() or "rotation" in f.description.lower()
                   for f in score.findings)

    def test_edge_clearance_checked(self):
        """Panelization score reflects edge clearance status."""
        from volta.dfm.scoring import score_panelization_readiness

        # Component well inside board
        primitives_safe = [
            _make_box(x1=10, y1=10, x2=15, y2=15,
                      entity_type="footprint", entity_id="U1", reference="U1",
                      rotation=0),
            _make_path(
                points=((0, 0), (50, 0), (50, 50), (0, 50), (0, 0)),
                entity_type="line", entity_id="edge1",
                layer="Edge.Cuts", width=0.15,
            ),
        ]
        model_safe = _MockSpatialModel(primitives=primitives_safe)
        profile = get_builtin_profiles()["generic"]
        score_safe = score_panelization_readiness(model_safe, profile)

        assert score_safe.edge_clearance_ok is True


class TestAssemblyChecks:
    """Assembly consideration checks: orientation, spacing, polarity."""

    def test_standard_orientation_passes(self):
        """Components at 0/90/180/270 degrees have no orientation findings."""
        from volta.dfm.scoring import run_assembly_checks

        primitives = [
            _make_box(x1=10, y1=10, x2=15, y2=15,
                      entity_type="footprint", entity_id="U1", reference="U1",
                      rotation=0),
            _make_box(x1=20, y1=10, x2=25, y2=15,
                      entity_type="footprint", entity_id="U2", reference="U2",
                      rotation=90),
            _make_box(x1=30, y1=10, x2=35, y2=15,
                      entity_type="footprint", entity_id="U3", reference="U3",
                      rotation=180),
            _make_box(x1=40, y1=10, x2=45, y2=15,
                      entity_type="footprint", entity_id="U4", reference="U4",
                      rotation=270),
        ]
        model = _MockSpatialModel(primitives=primitives)
        profile = get_builtin_profiles()["generic"]

        result = run_assembly_checks(model, profile)
        assert len(result.orientation_findings) == 0

    def test_non_standard_rotation_flagged(self):
        """Component at 45 degrees produces orientation finding."""
        from volta.dfm.scoring import run_assembly_checks

        primitives = [
            _make_box(x1=10, y1=10, x2=15, y2=15,
                      entity_type="footprint", entity_id="U1", reference="U1",
                      rotation=45),
        ]
        model = _MockSpatialModel(primitives=primitives)
        profile = get_builtin_profiles()["generic"]

        result = run_assembly_checks(model, profile)
        assert len(result.orientation_findings) >= 1
        assert any("45" in f.description or "rotation" in f.description.lower()
                   for f in result.orientation_findings)

    def test_close_components_flagged(self):
        """Components too close for pick-and-place produce spacing findings."""
        from volta.dfm.scoring import run_assembly_checks

        # Two components very close together (< clearance * 3)
        # generic min_clearance is 0.2mm, so threshold is 0.6mm
        # Centers at (0.5, 0.5) and (0.8, 0.5) -> distance 0.3mm < 0.6mm
        primitives = [
            _make_box(x1=0, y1=0, x2=1, y2=1,
                      entity_type="footprint", entity_id="U1", reference="U1",
                      rotation=0),
            _make_box(x1=0.3, y1=0, x2=1.3, y2=1,
                      entity_type="footprint", entity_id="U2", reference="U2",
                      rotation=0),
        ]
        model = _MockSpatialModel(primitives=primitives)
        profile = get_builtin_profiles()["generic"]

        result = run_assembly_checks(model, profile)
        assert len(result.spacing_findings) >= 1

    def test_polarized_component_info(self):
        """Polarized components (electrolytic caps, diodes) emit INFO findings."""
        from volta.dfm.scoring import run_assembly_checks

        primitives = [
            _make_box(x1=10, y1=10, x2=15, y2=15,
                      entity_type="footprint", entity_id="C1", reference="C_Pol1",
                      rotation=0),
        ]
        model = _MockSpatialModel(primitives=primitives)
        profile = get_builtin_profiles()["generic"]

        result = run_assembly_checks(model, profile)
        # Polarity findings are INFO (cannot confirm, not a violation)
        assert len(result.polarity_findings) >= 1

    def test_assembly_score_range(self):
        """Assembly score is clamped to [0.0, 1.0]."""
        from volta.dfm.scoring import run_assembly_checks

        primitives = [
            _make_box(x1=10, y1=10, x2=15, y2=15,
                      entity_type="footprint", entity_id="U1", reference="U1",
                      rotation=0),
        ]
        model = _MockSpatialModel(primitives=primitives)
        profile = get_builtin_profiles()["generic"]

        result = run_assembly_checks(model, profile)
        assert 0.0 <= result.assembly_score <= 1.0


class TestMultiStageDfm:
    """Multi-stage DFM pipeline: footprint audit, placement check, post-route check."""

    def test_three_stages_run(self):
        """run_multistage_dfm returns MultiStageDfmReport with 3 stage reports."""
        from volta.dfm.scoring import run_multistage_dfm

        primitives = [
            _make_path(
                points=((0, 0), (10, 0)),
                entity_type="trace", entity_id="t1", layer="F.Cu",
                net="SIG", width=0.5,
            ),
        ]
        model = _MockSpatialModel(primitives=primitives)
        profile = get_builtin_profiles()["generic"]

        report = run_multistage_dfm(model, profile)
        assert report.footprint_audit is not None
        assert report.placement_check is not None
        assert report.post_route_check is not None
        assert isinstance(report.footprint_audit, DfmReport)
        assert isinstance(report.placement_check, DfmReport)
        assert isinstance(report.post_route_check, DfmReport)

    def test_footprint_audit_subset(self):
        """Footprint audit stage runs only ANNULAR_RING_01 and MIN_DRILL_01 checks."""
        from volta.dfm.scoring import run_multistage_dfm

        primitives = [
            _make_box(x1=-1, y1=-1, x2=1, y2=1,
                      entity_type="pad", entity_id="p1", reference="P1"),
            _make_point(x=0, y=0, entity_type="drill", entity_id="p1_drill",
                        drill_diameter=0.5),
            _make_point(x=5, y=5, entity_type="via_drill", entity_id="v1",
                        drill_diameter=0.5),
        ]
        model = _MockSpatialModel(primitives=primitives)
        profile = get_builtin_profiles()["generic"]

        report = run_multistage_dfm(model, profile)
        # Footprint audit should have run 2 checks (ANNULAR_RING_01, MIN_DRILL_01)
        assert report.footprint_audit.checks_run == 2

    def test_placement_check_subset(self):
        """Placement check stage runs SOLDER_MASK_01 and THERMAL_RELIEF_01 checks."""
        from volta.dfm.scoring import run_multistage_dfm

        primitives = [
            _make_box(x1=-1, y1=-1, x2=1, y2=1,
                      entity_type="pad", entity_id="p1", reference="P1"),
        ]
        model = _MockSpatialModel(primitives=primitives)
        profile = get_builtin_profiles()["generic"]

        report = run_multistage_dfm(model, profile)
        # Placement check should have run 2 checks (SOLDER_MASK_01, THERMAL_RELIEF_01)
        assert report.placement_check.checks_run == 2

    def test_post_route_check_subset(self):
        """Post-route stage runs MIN_TRACE_01 and MIN_DRILL_01 checks."""
        from volta.dfm.scoring import run_multistage_dfm

        primitives = [
            _make_path(
                points=((0, 0), (10, 0)),
                entity_type="trace", entity_id="t1", layer="F.Cu",
                net="SIG", width=0.5,
            ),
            _make_point(x=5, y=5, entity_type="via_drill", entity_id="v1",
                        drill_diameter=0.5),
        ]
        model = _MockSpatialModel(primitives=primitives)
        profile = get_builtin_profiles()["generic"]

        report = run_multistage_dfm(model, profile)
        # Post-route should have run 2 checks (MIN_TRACE_01, MIN_DRILL_01)
        assert report.post_route_check.checks_run == 2

    def test_overall_score_is_minimum(self):
        """MultiStageDfmReport overall_score is minimum of stage scores and panelization."""
        from volta.dfm.scoring import run_multistage_dfm

        primitives = [
            _make_path(
                points=((0, 0), (10, 0)),
                entity_type="trace", entity_id="t1", layer="F.Cu",
                net="SIG", width=0.5,
            ),
        ]
        model = _MockSpatialModel(primitives=primitives)
        profile = get_builtin_profiles()["generic"]

        report = run_multistage_dfm(model, profile)
        stage_scores = [
            report.footprint_audit.manufacturability_score,
            report.placement_check.manufacturability_score,
            report.post_route_check.manufacturability_score,
            report.panelization.score,
        ]
        assert report.overall_score == pytest.approx(min(stage_scores))

    def test_total_findings_aggregated(self):
        """MultiStageDfmReport total_findings sums findings from all 3 stages."""
        from volta.dfm.scoring import run_multistage_dfm

        primitives = [
            _make_path(
                points=((0, 0), (10, 0)),
                entity_type="trace", entity_id="t1", layer="F.Cu",
                net="SIG", width=0.5,
            ),
        ]
        model = _MockSpatialModel(primitives=primitives)
        profile = get_builtin_profiles()["generic"]

        report = run_multistage_dfm(model, profile)
        expected_total = (
            len(report.footprint_audit.findings)
            + len(report.placement_check.findings)
            + len(report.post_route_check.findings)
        )
        assert report.total_findings == expected_total
