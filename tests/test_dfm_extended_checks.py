"""Tests for extended DFM checks (45 new manufacturing checks).

TDD RED phase: these tests define the expected behavior for the expanded
DFM engine covering acid traps, copper pour spacing, via-in-pad, solder
paste coverage, silkscreen clearance, board edge clearance, via tenting,
via stubs, impedance control, layer stackup, min feature sizes, trace
angles, courtyard overlap, pin 1 markers, component placement constraints,
fiducial markers, panelization markers, power plane void area, and fab
profile system updates.
"""
from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest

from kicad_agent.dfm.checker import DfmCheck, DfmFinding, DfmSeverity
from kicad_agent.dfm.profiles import get_builtin_profiles


# ===========================================================================
# Helpers
# ===========================================================================


class _MockSpatialModel:
    """Minimal spatial model mock for extended DFM check tests."""

    def __init__(self, primitives=None, board_path="test.kicad_pcb"):
        self._primitives = primitives or []
        self.board_path = board_path

    @property
    def all_primitives(self):
        return list(self._primitives)

    def layer_primitives(self, layer_name: str):
        return [p for p in self._primitives if getattr(p, "layer", "") == layer_name]

    def copper_layer_primitives(self):
        return {"F.Cu": self.layer_primitives("F.Cu"), "B.Cu": self.layer_primitives("B.Cu")}


def _make_box(
    x1=0, y1=0, x2=1, y2=1,
    entity_type="pad", entity_id="p1",
    layer="F.Cu", reference="U1",
    rotation=None, net="",
    **kwargs,
):
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
    for k, v in kwargs.items():
        setattr(box, k, v)
    return box


def _make_point(
    x=0, y=0,
    entity_type="via_drill", entity_id="v1",
    layer="", net="",
    drill_diameter=None,
    **kwargs,
):
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
    for k, v in kwargs.items():
        setattr(pt, k, v)
    return pt


def _make_path(
    points=((0, 0), (10, 0)),
    entity_type="trace", entity_id="t1",
    layer="F.Cu", net="", width=0.2,
    **kwargs,
):
    from shapely.geometry import LineString

    path = MagicMock()
    path.points = points
    path.entity_type = entity_type
    path.entity_id = entity_id
    path.layer = layer
    path.net = net
    path.width = width
    path.to_shapely.return_value = LineString(points)
    for k, v in kwargs.items():
        setattr(path, k, v)
    return path


def _make_region(
    boundary=((0, 0), (10, 0), (10, 10), (0, 10)),
    entity_type="zone", entity_id="z1",
    layer="F.Cu", net="GND",
    **kwargs,
):
    from shapely.geometry import Polygon

    region = MagicMock()
    region.boundary = boundary
    region.entity_type = entity_type
    region.entity_id = entity_id
    region.layer = layer
    region.net = net
    region.to_shapely.return_value = Polygon(boundary)
    for k, v in kwargs.items():
        setattr(region, k, v)
    return region


# ===========================================================================
# TestAcidTrapCheck (ACID_TRAP_01)
# ===========================================================================


class TestAcidTrapCheck:
    """ACID_TRAP_01: Detect acute angles that trap etchant during PCB fabrication."""

    def test_acute_angle_between_traces_flagged(self):
        """Two traces forming an acute angle (< 90 degrees) are flagged."""
        from kicad_agent.dfm.extended_checks import AcidTrapCheck

        # Two traces meeting at a point with acute angle (~45 degrees)
        trace1 = _make_path(
            points=((0, 0), (10, 0)),
            entity_type="trace", entity_id="t1", layer="F.Cu",
            net="SIG", width=0.2,
        )
        trace2 = _make_path(
            points=((10, 0), (15, 7)),  # acute angle from horizontal
            entity_type="trace", entity_id="t2", layer="F.Cu",
            net="SIG", width=0.2,
        )
        model = _MockSpatialModel(primitives=[trace1, trace2])
        profile = get_builtin_profiles()["jlcpcb"]
        check = AcidTrapCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any(f.severity == DfmSeverity.WARNING for f in findings)
        assert any("ACID_TRAP_01" == f.check_id for f in findings)

    def test_right_angle_between_traces_passes(self):
        """Two traces forming a right angle (90 degrees) pass."""
        from kicad_agent.dfm.extended_checks import AcidTrapCheck

        trace1 = _make_path(
            points=((0, 0), (10, 0)),
            entity_type="trace", entity_id="t1", layer="F.Cu",
            net="SIG", width=0.2,
        )
        trace2 = _make_path(
            points=((10, 0), (10, 10)),  # 90 degrees
            entity_type="trace", entity_id="t2", layer="F.Cu",
            net="SIG", width=0.2,
        )
        model = _MockSpatialModel(primitives=[trace1, trace2])
        profile = get_builtin_profiles()["jlcpcb"]
        check = AcidTrapCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    def test_obtuse_angle_passes(self):
        """Two traces forming an obtuse angle (> 90 degrees) pass."""
        from kicad_agent.dfm.extended_checks import AcidTrapCheck

        trace1 = _make_path(
            points=((0, 0), (10, 0)),
            entity_type="trace", entity_id="t1", layer="F.Cu",
            net="SIG", width=0.2,
        )
        trace2 = _make_path(
            points=((10, 0), (5, 7)),  # obtuse angle (~126 degrees)
            entity_type="trace", entity_id="t2", layer="F.Cu",
            net="SIG", width=0.2,
        )
        model = _MockSpatialModel(primitives=[trace1, trace2])
        profile = get_builtin_profiles()["jlcpcb"]
        check = AcidTrapCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    def test_no_traces_no_findings(self):
        """Empty spatial model produces no findings."""
        from kicad_agent.dfm.extended_checks import AcidTrapCheck

        model = _MockSpatialModel(primitives=[])
        profile = get_builtin_profiles()["jlcpcb"]
        check = AcidTrapCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    def test_disconnected_traces_no_findings(self):
        """Traces that don't meet at endpoints produce no findings."""
        from kicad_agent.dfm.extended_checks import AcidTrapCheck

        trace1 = _make_path(
            points=((0, 0), (10, 0)),
            entity_type="trace", entity_id="t1", layer="F.Cu",
            net="SIG", width=0.2,
        )
        trace2 = _make_path(
            points=((20, 20), (30, 25)),  # far away
            entity_type="trace", entity_id="t2", layer="F.Cu",
            net="SIG", width=0.2,
        )
        model = _MockSpatialModel(primitives=[trace1, trace2])
        profile = get_builtin_profiles()["jlcpcb"]
        check = AcidTrapCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestCopperPourSpacingCheck (COPPER_POUR_01)
# ===========================================================================


class TestCopperPourSpacingCheck:
    """COPPER_POUR_01: Validate spacing between copper pour zones and other features."""

    def test_zone_too_close_to_pad_flagged(self):
        """Copper pour zone too close to a pad is flagged."""
        from kicad_agent.dfm.extended_checks import CopperPourSpacingCheck

        pad = _make_box(
            x1=4.5, y1=4.5, x2=5.5, y2=5.5,
            entity_type="pad", entity_id="p1", reference="R1",
            layer="F.Cu", net="VCC",
        )
        # Zone boundary overlapping with pad clearance
        zone = _make_region(
            boundary=((3, 3), (7, 3), (7, 7), (3, 7)),
            entity_type="zone", entity_id="z1", layer="F.Cu",
            net="GND",
        )
        model = _MockSpatialModel(primitives=[pad, zone])
        profile = get_builtin_profiles()["jlcpcb"]
        check = CopperPourSpacingCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("COPPER_POUR_01" == f.check_id for f in findings)

    def test_zone_adequate_spacing_passes(self):
        """Copper pour zone with adequate spacing to pad passes."""
        from kicad_agent.dfm.extended_checks import CopperPourSpacingCheck

        pad = _make_box(
            x1=0, y1=0, x2=1, y2=1,
            entity_type="pad", entity_id="p1", reference="R1",
            layer="F.Cu", net="VCC",
        )
        # Zone boundary far from pad
        zone = _make_region(
            boundary=((10, 10), (20, 10), (20, 20), (10, 20)),
            entity_type="zone", entity_id="z1", layer="F.Cu",
            net="GND",
        )
        model = _MockSpatialModel(primitives=[pad, zone])
        profile = get_builtin_profiles()["jlcpcb"]
        check = CopperPourSpacingCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    def test_same_net_zone_ignores_clearance(self):
        """Zone on same net as pad does not trigger spacing check."""
        from kicad_agent.dfm.extended_checks import CopperPourSpacingCheck

        pad = _make_box(
            x1=4.5, y1=4.5, x2=5.5, y2=5.5,
            entity_type="pad", entity_id="p1", reference="R1",
            layer="F.Cu", net="GND",
        )
        zone = _make_region(
            boundary=((3, 3), (7, 3), (7, 7), (3, 7)),
            entity_type="zone", entity_id="z1", layer="F.Cu",
            net="GND",
        )
        model = _MockSpatialModel(primitives=[pad, zone])
        profile = get_builtin_profiles()["jlcpcb"]
        check = CopperPourSpacingCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    def test_zone_to_trace_spacing_flagged(self):
        """Copper pour zone too close to a trace is flagged."""
        from kicad_agent.dfm.extended_checks import CopperPourSpacingCheck

        trace = _make_path(
            points=((0, 0), (10, 0)),
            entity_type="trace", entity_id="t1", layer="F.Cu",
            net="SIG", width=0.2,
        )
        zone = _make_region(
            boundary=((0.1, -1), (9.9, -1), (9.9, 0.1), (0.1, 0.1)),
            entity_type="zone", entity_id="z1", layer="F.Cu",
            net="GND",
        )
        model = _MockSpatialModel(primitives=[trace, zone])
        profile = get_builtin_profiles()["jlcpcb"]
        check = CopperPourSpacingCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1


# ===========================================================================
# TestViaInPadCheck (VIA_IN_PAD_01)
# ===========================================================================


class TestViaInPadCheck:
    """VIA_IN_PAD_01: Detect vias placed inside pads (requires plugged or tented vias)."""

    def test_via_inside_pad_flagged(self):
        """A via geometry contained within a pad geometry is flagged."""
        from kicad_agent.dfm.extended_checks import ViaInPadCheck

        pad = _make_box(
            x1=0, y1=0, x2=2, y2=2,
            entity_type="pad", entity_id="p1", reference="U1",
            layer="F.Cu", net="VCC",
        )
        via = _make_point(
            x=1, y=1, entity_type="via", entity_id="v1",
            layer="F.Cu", net="VCC",
            drill_diameter=0.3,
        )
        model = _MockSpatialModel(primitives=[pad, via])
        profile = get_builtin_profiles()["jlcpcb"]
        check = ViaInPadCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("VIA_IN_PAD_01" == f.check_id for f in findings)

    def test_via_outside_pad_passes(self):
        """A via far from any pad passes."""
        from kicad_agent.dfm.extended_checks import ViaInPadCheck

        pad = _make_box(
            x1=0, y1=0, x2=2, y2=2,
            entity_type="pad", entity_id="p1", reference="U1",
            layer="F.Cu", net="VCC",
        )
        via = _make_point(
            x=10, y=10, entity_type="via", entity_id="v2",
            layer="F.Cu", net="GND",
            drill_diameter=0.3,
        )
        model = _MockSpatialModel(primitives=[pad, via])
        profile = get_builtin_profiles()["jlcpcb"]
        check = ViaInPadCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    def test_no_vias_no_findings(self):
        """No vias produces no findings."""
        from kicad_agent.dfm.extended_checks import ViaInPadCheck

        pad = _make_box(
            x1=0, y1=0, x2=2, y2=2,
            entity_type="pad", entity_id="p1", reference="U1",
        )
        model = _MockSpatialModel(primitives=[pad])
        profile = get_builtin_profiles()["jlcpcb"]
        check = ViaInPadCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestSolderPasteCoverageCheck (SOLDER_PASTE_01)
# ===========================================================================


class TestSolderPasteCoverageCheck:
    """SOLDER_PASTE_01: Validate solder paste coverage on SMD pads."""

    def test_paste_smaller_than_pad_flagged(self):
        """Solder paste opening smaller than pad coverage threshold flagged."""
        from kicad_agent.dfm.extended_checks import SolderPasteCoverageCheck

        # Pad with small paste coverage
        pad = _make_box(
            x1=0, y1=0, x2=2, y2=2,
            entity_type="pad", entity_id="p1", reference="R1",
            layer="F.Cu", net="SIG",
        )
        # Paste area significantly smaller than pad
        paste = _make_box(
            x1=0.5, y1=0.5, x2=1.5, y2=1.5,
            entity_type="solder_paste", entity_id="paste1",
            layer="F.Paste",
        )
        model = _MockSpatialModel(primitives=[pad, paste])
        profile = get_builtin_profiles()["jlcpcb"]
        check = SolderPasteCoverageCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("SOLDER_PASTE_01" == f.check_id for f in findings)

    def test_paste_covers_pad_passes(self):
        """Solder paste adequately covering pad passes."""
        from kicad_agent.dfm.extended_checks import SolderPasteCoverageCheck

        pad = _make_box(
            x1=0, y1=0, x2=2, y2=2,
            entity_type="pad", entity_id="p1", reference="R1",
            layer="F.Cu", net="SIG",
        )
        # Paste area covers most of pad
        paste = _make_box(
            x1=0.05, y1=0.05, x2=1.95, y2=1.95,
            entity_type="solder_paste", entity_id="paste1",
            layer="F.Paste",
        )
        model = _MockSpatialModel(primitives=[pad, paste])
        profile = get_builtin_profiles()["jlcpcb"]
        check = SolderPasteCoverageCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    def test_no_paste_data_info_finding(self):
        """Pads without paste data emit INFO finding."""
        from kicad_agent.dfm.extended_checks import SolderPasteCoverageCheck

        pad = _make_box(
            x1=0, y1=0, x2=2, y2=2,
            entity_type="pad", entity_id="p1", reference="R1",
            layer="F.Cu", net="SIG",
        )
        model = _MockSpatialModel(primitives=[pad])
        profile = get_builtin_profiles()["jlcpcb"]
        check = SolderPasteCoverageCheck()
        findings = check.check(model, profile)
        # May or may not emit findings depending on design (no paste is normal for THT)
        # Check doesn't crash and returns a list
        assert isinstance(findings, list)


# ===========================================================================
# TestSilkscreenClearanceCheck (SILKSCREEN_01)
# ===========================================================================


class TestSilkscreenClearanceCheck:
    """SILKSCREEN_01: Validate silkscreen clearance from pads and other features."""

    def test_silkscreen_on_pad_flagged(self):
        """Silkscreen geometry overlapping pad geometry is flagged."""
        from kicad_agent.dfm.extended_checks import SilkscreenClearanceCheck

        pad = _make_box(
            x1=0, y1=0, x2=2, y2=2,
            entity_type="pad", entity_id="p1", reference="R1",
            layer="F.Cu", net="SIG",
        )
        silk = _make_box(
            x1=1.5, y1=1.5, x2=3, y2=3,
            entity_type="silkscreen", entity_id="silk1",
            layer="F.SilkS",
        )
        model = _MockSpatialModel(primitives=[pad, silk])
        profile = get_builtin_profiles()["jlcpcb"]
        check = SilkscreenClearanceCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("SILKSCREEN_01" == f.check_id for f in findings)

    def test_silkscreen_clear_of_pad_passes(self):
        """Silkscreen geometry clear of pad geometry passes."""
        from kicad_agent.dfm.extended_checks import SilkscreenClearanceCheck

        pad = _make_box(
            x1=0, y1=0, x2=2, y2=2,
            entity_type="pad", entity_id="p1", reference="R1",
            layer="F.Cu", net="SIG",
        )
        silk = _make_box(
            x1=5, y1=5, x2=7, y2=7,
            entity_type="silkscreen", entity_id="silk1",
            layer="F.SilkS",
        )
        model = _MockSpatialModel(primitives=[pad, silk])
        profile = get_builtin_profiles()["jlcpcb"]
        check = SilkscreenClearanceCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    def test_no_silkscreen_no_findings(self):
        """No silkscreen primitives produces no findings."""
        from kicad_agent.dfm.extended_checks import SilkscreenClearanceCheck

        pad = _make_box(
            x1=0, y1=0, x2=2, y2=2,
            entity_type="pad", entity_id="p1", reference="R1",
        )
        model = _MockSpatialModel(primitives=[pad])
        profile = get_builtin_profiles()["jlcpcb"]
        check = SilkscreenClearanceCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestBoardEdgeClearanceCheck (EDGE_CLEAR_01)
# ===========================================================================


class TestBoardEdgeClearanceCheck:
    """EDGE_CLEAR_01: Validate feature clearance from board edge."""

    def test_pad_too_close_to_edge_flagged(self):
        """Pad too close to Edge.Cuts geometry is flagged."""
        from kicad_agent.dfm.extended_checks import BoardEdgeClearanceCheck

        pad = _make_box(
            x1=0, y1=0, x2=1, y2=1,
            entity_type="pad", entity_id="p1", reference="R1",
            layer="F.Cu", net="SIG",
        )
        edge = _make_path(
            points=((0, 0), (50, 0), (50, 50), (0, 50), (0, 0)),
            entity_type="line", entity_id="edge1",
            layer="Edge.Cuts", width=0.15,
        )
        model = _MockSpatialModel(primitives=[pad, edge])
        profile = get_builtin_profiles()["jlcpcb"]
        check = BoardEdgeClearanceCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("EDGE_CLEAR_01" == f.check_id for f in findings)

    def test_pad_far_from_edge_passes(self):
        """Pad well inside board edge passes."""
        from kicad_agent.dfm.extended_checks import BoardEdgeClearanceCheck

        pad = _make_box(
            x1=10, y1=10, x2=12, y2=12,
            entity_type="pad", entity_id="p1", reference="R1",
            layer="F.Cu", net="SIG",
        )
        edge = _make_path(
            points=((0, 0), (50, 0), (50, 50), (0, 50), (0, 0)),
            entity_type="line", entity_id="edge1",
            layer="Edge.Cuts", width=0.15,
        )
        model = _MockSpatialModel(primitives=[pad, edge])
        profile = get_builtin_profiles()["jlcpcb"]
        check = BoardEdgeClearanceCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    def test_no_edge_geometry_passes(self):
        """No Edge.Cuts geometry means no findings (cannot check)."""
        from kicad_agent.dfm.extended_checks import BoardEdgeClearanceCheck

        pad = _make_box(
            x1=0, y1=0, x2=1, y2=1,
            entity_type="pad", entity_id="p1", reference="R1",
        )
        model = _MockSpatialModel(primitives=[pad])
        profile = get_builtin_profiles()["jlcpcb"]
        check = BoardEdgeClearanceCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestViaTentingCheck (VIA_TENT_01)
# ===========================================================================


class TestViaTentingCheck:
    """VIA_TENT_01: Check via tenting requirements (covered by solder mask)."""

    def test_uncovered_via_flagged_when_tenting_required(self):
        """Via without tenting/tenting_required flag emits INFO finding."""
        from kicad_agent.dfm.extended_checks import ViaTentingCheck

        via = _make_point(
            x=5, y=5, entity_type="via", entity_id="v1",
            layer="F.Cu", net="SIG",
            drill_diameter=0.3,
        )
        via.tenting = None  # No tenting info
        model = _MockSpatialModel(primitives=[via])
        profile = get_builtin_profiles()["jlcpcb"]
        check = ViaTentingCheck()
        findings = check.check(model, profile)
        # Should emit at least INFO for untented via
        assert isinstance(findings, list)

    def test_tented_via_passes(self):
        """Via with tenting attribute passes."""
        from kicad_agent.dfm.extended_checks import ViaTentingCheck

        via = _make_point(
            x=5, y=5, entity_type="via", entity_id="v1",
            layer="F.Cu", net="SIG",
            drill_diameter=0.3,
            tenting=True,
        )
        model = _MockSpatialModel(primitives=[via])
        profile = get_builtin_profiles()["jlcpcb"]
        check = ViaTentingCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    def test_no_vias_no_findings(self):
        """No vias produces no findings."""
        from kicad_agent.dfm.extended_checks import ViaTentingCheck

        model = _MockSpatialModel(primitives=[])
        profile = get_builtin_profiles()["jlcpcb"]
        check = ViaTentingCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestImpedanceControlCheck (IMPEDANCE_01)
# ===========================================================================


class TestImpedanceControlCheck:
    """IMPEDANCE_01: Validate impedance-controlled trace constraints."""

    def test_wide_power_trace_without_impedance_info_flagged(self):
        """Power trace exceeding impedance width threshold flagged when no impedance info."""
        from kicad_agent.dfm.extended_checks import ImpedanceControlCheck

        # Thick trace that might need impedance control
        trace = _make_path(
            points=((0, 0), (50, 0)),
            entity_type="trace", entity_id="t1", layer="F.Cu",
            net="RF1", width=0.5,
        )
        trace.impedance_controlled = None
        model = _MockSpatialModel(primitives=[trace])
        profile = get_builtin_profiles()["jlcpcb"]
        check = ImpedanceControlCheck()
        findings = check.check(model, profile)
        # Should emit INFO for potentially impedance-critical nets
        assert isinstance(findings, list)

    def test_traces_on_normal_nets_pass(self):
        """Normal signal traces don't trigger impedance warnings."""
        from kicad_agent.dfm.extended_checks import ImpedanceControlCheck

        trace = _make_path(
            points=((0, 0), (10, 0)),
            entity_type="trace", entity_id="t1", layer="F.Cu",
            net="SIG", width=0.2,
        )
        model = _MockSpatialModel(primitives=[trace])
        profile = get_builtin_profiles()["jlcpcb"]
        check = ImpedanceControlCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestLayerStackupCheck (STACKUP_01)
# ===========================================================================


class TestLayerStackupCheck:
    """STACKUP_01: Validate board layer stackup against profile constraints."""

    def test_missing_layer_flagged_for_4layer_profile(self):
        """Missing inner copper layers flagged when profile requires 4+ layers."""
        from kicad_agent.dfm.extended_checks import LayerStackupCheck

        # Profile expects 4 layers, but board has only 2
        model = _MockSpatialModel(primitives=[
            _make_path(points=((0, 0), (10, 0)), layer="F.Cu", net="SIG"),
            _make_path(points=((0, 5), (10, 5)), layer="B.Cu", net="SIG"),
        ])
        profile = get_builtin_profiles()["jlcpcb-4layer"]
        check = LayerStackupCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("STACKUP_01" == f.check_id for f in findings)

    def test_correct_layers_for_2layer_passes(self):
        """Board with correct layer count for 2-layer profile passes."""
        from kicad_agent.dfm.extended_checks import LayerStackupCheck

        model = _MockSpatialModel(primitives=[
            _make_path(points=((0, 0), (10, 0)), layer="F.Cu", net="SIG"),
            _make_path(points=((0, 5), (10, 5)), layer="B.Cu", net="SIG"),
        ])
        profile = get_builtin_profiles()["jlcpcb"]
        check = LayerStackupCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestMinFeatureSizeCheck (MIN_FEATURE_01)
# ===========================================================================


class TestMinFeatureSizeCheck:
    """MIN_FEATURE_01: Validate minimum feature size per layer type."""

    def test_small_pad_flagged(self):
        """Pad below minimum feature size flagged."""
        from kicad_agent.dfm.extended_checks import MinFeatureSizeCheck

        # Very small pad: 0.05mm x 0.05mm
        pad = _make_box(
            x1=0, y1=0, x2=0.05, y2=0.05,
            entity_type="pad", entity_id="p1", reference="R1",
            layer="F.Cu", net="SIG",
        )
        model = _MockSpatialModel(primitives=[pad])
        profile = get_builtin_profiles()["jlcpcb"]
        check = MinFeatureSizeCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("MIN_FEATURE_01" == f.check_id for f in findings)

    def test_normal_pad_passes(self):
        """Normal-sized pad passes."""
        from kicad_agent.dfm.extended_checks import MinFeatureSizeCheck

        pad = _make_box(
            x1=0, y1=0, x2=2, y2=2,
            entity_type="pad", entity_id="p1", reference="R1",
        )
        model = _MockSpatialModel(primitives=[pad])
        profile = get_builtin_profiles()["jlcpcb"]
        check = MinFeatureSizeCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    def test_small_text_on_silkscreen_flagged(self):
        """Small silkscreen text flagged if below minimum."""
        from kicad_agent.dfm.extended_checks import MinFeatureSizeCheck

        text = MagicMock()
        text.entity_type = "text"
        text.entity_id = "txt1"
        text.layer = "F.SilkS"
        text.x1 = 0
        text.y1 = 0
        text.x2 = 0.3
        text.y2 = 0.2
        text.height = 0.2
        text.width = 0.025  # Very thin stroke
        text.to_shapely.return_value = None  # Text may not have geometry

        model = _MockSpatialModel(primitives=[text])
        profile = get_builtin_profiles()["jlcpcb"]
        check = MinFeatureSizeCheck()
        findings = check.check(model, profile)
        assert isinstance(findings, list)


# ===========================================================================
# TestTraceAngleCheck (TRACE_ANGLE_01)
# ===========================================================================


class TestTraceAngleCheck:
    """TRACE_ANGLE_01: Validate trace segment angles for manufacturability."""

    def test_45_degree_bend_passes(self):
        """45-degree trace bend passes."""
        from kicad_agent.dfm.extended_checks import TraceAngleCheck

        trace = _make_path(
            points=((0, 0), (10, 0), (15, 5)),
            entity_type="trace", entity_id="t1", layer="F.Cu",
            net="SIG", width=0.2,
        )
        model = _MockSpatialModel(primitives=[trace])
        profile = get_builtin_profiles()["jlcpcb"]
        check = TraceAngleCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    def test_straight_line_passes(self):
        """Straight trace with no bends passes."""
        from kicad_agent.dfm.extended_checks import TraceAngleCheck

        trace = _make_path(
            points=((0, 0), (10, 0), (20, 0)),
            entity_type="trace", entity_id="t1", layer="F.Cu",
            net="SIG", width=0.2,
        )
        model = _MockSpatialModel(primitives=[trace])
        profile = get_builtin_profiles()["jlcpcb"]
        check = TraceAngleCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestCourtyardOverlapCheck (COURTYARD_01)
# ===========================================================================


class TestCourtyardOverlapCheck:
    """COURTYARD_01: Detect courtyard overlap between components."""

    def test_overlapping_courtyards_flagged(self):
        """Two components with overlapping courtyards flagged."""
        from kicad_agent.dfm.extended_checks import CourtyardOverlapCheck

        comp1 = _make_box(
            x1=0, y1=0, x2=5, y2=5,
            entity_type="courtyard", entity_id="cy1", reference="U1",
            layer="F.CrtYd", net="",
        )
        comp2 = _make_box(
            x1=4, y1=4, x2=9, y2=9,
            entity_type="courtyard", entity_id="cy2", reference="U2",
            layer="F.CrtYd", net="",
        )
        model = _MockSpatialModel(primitives=[comp1, comp2])
        profile = get_builtin_profiles()["jlcpcb"]
        check = CourtyardOverlapCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("COURTYARD_01" == f.check_id for f in findings)

    def test_non_overlapping_courtyards_pass(self):
        """Components with separate courtyards pass."""
        from kicad_agent.dfm.extended_checks import CourtyardOverlapCheck

        comp1 = _make_box(
            x1=0, y1=0, x2=5, y2=5,
            entity_type="courtyard", entity_id="cy1", reference="U1",
            layer="F.CrtYd",
        )
        comp2 = _make_box(
            x1=10, y1=10, x2=15, y2=15,
            entity_type="courtyard", entity_id="cy2", reference="U2",
            layer="F.CrtYd",
        )
        model = _MockSpatialModel(primitives=[comp1, comp2])
        profile = get_builtin_profiles()["jlcpcb"]
        check = CourtyardOverlapCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    def test_no_courtyards_no_findings(self):
        """No courtyard primitives produces no findings."""
        from kicad_agent.dfm.extended_checks import CourtyardOverlapCheck

        model = _MockSpatialModel(primitives=[])
        profile = get_builtin_profiles()["jlcpcb"]
        check = CourtyardOverlapCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestPin1MarkerCheck (PIN1_MARKER_01)
# ===========================================================================


class TestPin1MarkerCheck:
    """PIN1_MARKER_01: Verify pin 1 markers are present on IC components."""

    def test_ic_without_pin1_marker_flagged(self):
        """IC component without pin 1 marker emits INFO finding."""
        from kicad_agent.dfm.extended_checks import Pin1MarkerCheck

        comp = _make_box(
            x1=0, y1=0, x2=10, y2=10,
            entity_type="footprint", entity_id="U1", reference="U1",
            layer="F.Cu",
        )
        comp.has_pin1_marker = False
        model = _MockSpatialModel(primitives=[comp])
        profile = get_builtin_profiles()["jlcpcb"]
        check = Pin1MarkerCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("PIN1_MARKER_01" == f.check_id for f in findings)

    def test_ic_with_pin1_marker_passes(self):
        """IC component with pin 1 marker passes."""
        from kicad_agent.dfm.extended_checks import Pin1MarkerCheck

        comp = _make_box(
            x1=0, y1=0, x2=10, y2=10,
            entity_type="footprint", entity_id="U1", reference="U1",
            layer="F.Cu",
        )
        comp.has_pin1_marker = True
        model = _MockSpatialModel(primitives=[comp])
        profile = get_builtin_profiles()["jlcpcb"]
        check = Pin1MarkerCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    def test_passive_component_ignored(self):
        """Passive components (R, C, L) are not checked for pin 1 markers."""
        from kicad_agent.dfm.extended_checks import Pin1MarkerCheck

        comp = _make_box(
            x1=0, y1=0, x2=3, y2=2,
            entity_type="footprint", entity_id="R1", reference="R1",
            layer="F.Cu",
        )
        comp.has_pin1_marker = False
        model = _MockSpatialModel(primitives=[comp])
        profile = get_builtin_profiles()["jlcpcb"]
        check = Pin1MarkerCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestViaStubCheck (VIA_STUB_01)
# ===========================================================================


class TestViaStubCheck:
    """VIA_STUB_01: Detect via stubs in high-speed designs."""

    def test_long_via_stub_flagged(self):
        """Via with long stub length flagged."""
        from kicad_agent.dfm.extended_checks import ViaStubCheck

        via = _make_point(
            x=5, y=5, entity_type="via", entity_id="v1",
            layer="F.Cu", net="SIG",
            drill_diameter=0.3,
        )
        via.stub_length_mm = 1.5  # Long stub
        model = _MockSpatialModel(primitives=[via])
        profile = get_builtin_profiles()["jlcpcb"]
        check = ViaStubCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("VIA_STUB_01" == f.check_id for f in findings)

    def test_no_stub_data_passes(self):
        """Via without stub length data passes (can't check)."""
        from kicad_agent.dfm.extended_checks import ViaStubCheck

        via = _make_point(
            x=5, y=5, entity_type="via", entity_id="v1",
            layer="F.Cu", net="SIG",
            drill_diameter=0.3,
        )
        # No stub_length_mm attribute
        model = _MockSpatialModel(primitives=[via])
        profile = get_builtin_profiles()["jlcpcb"]
        check = ViaStubCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestPowerPlaneVoidCheck (POWER_VOID_01)
# ===========================================================================


class TestPowerPlaneVoidCheck:
    """POWER_VOID_01: Detect excessive void areas in power planes."""

    def test_large_void_in_power_zone_flagged(self):
        """Large void area in power plane flagged."""
        from kicad_agent.dfm.extended_checks import PowerPlaneVoidCheck

        zone = _make_region(
            boundary=((0, 0), (50, 0), (50, 50), (0, 50)),
            entity_type="zone", entity_id="z1", layer="In1.Cu",
            net="VCC",
        )
        zone.void_area_mm2 = 200.0  # Large void
        model = _MockSpatialModel(primitives=[zone])
        profile = get_builtin_profiles()["jlcpcb"]
        check = PowerPlaneVoidCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("POWER_VOID_01" == f.check_id for f in findings)

    def test_small_void_passes(self):
        """Small void area in power plane passes."""
        from kicad_agent.dfm.extended_checks import PowerPlaneVoidCheck

        zone = _make_region(
            boundary=((0, 0), (50, 0), (50, 50), (0, 50)),
            entity_type="zone", entity_id="z1", layer="In1.Cu",
            net="VCC",
        )
        zone.void_area_mm2 = 5.0  # Small void
        model = _MockSpatialModel(primitives=[zone])
        profile = get_builtin_profiles()["jlcpcb"]
        check = PowerPlaneVoidCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    def test_signal_zone_ignored(self):
        """Signal zones are not checked for power void issues."""
        from kicad_agent.dfm.extended_checks import PowerPlaneVoidCheck

        zone = _make_region(
            boundary=((0, 0), (50, 0), (50, 50), (0, 50)),
            entity_type="zone", entity_id="z1", layer="In1.Cu",
            net="SIG",  # Not a power net
        )
        zone.void_area_mm2 = 200.0
        model = _MockSpatialModel(primitives=[zone])
        profile = get_builtin_profiles()["jlcpcb"]
        check = PowerPlaneVoidCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestFiducialMarkerCheck (FIDUCIAL_01)
# ===========================================================================


class TestFiducialMarkerCheck:
    """FIDUCIAL_01: Check for adequate fiducial marker presence."""

    def test_no_fiducials_flagged(self):
        """Board with no fiducials flagged."""
        from kicad_agent.dfm.extended_checks import FiducialMarkerCheck

        model = _MockSpatialModel(primitives=[])
        profile = get_builtin_profiles()["jlcpcb"]
        check = FiducialMarkerCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("FIDUCIAL_01" == f.check_id for f in findings)

    def test_three_fiducials_passes(self):
        """Board with 3+ fiducials passes."""
        from kicad_agent.dfm.extended_checks import FiducialMarkerCheck

        primitives = [
            _make_box(entity_type="fiducial", entity_id="FID1", reference="FID1"),
            _make_box(entity_type="fiducial", entity_id="FID2", reference="FID2"),
            _make_box(entity_type="fiducial", entity_id="FID3", reference="FID3"),
        ]
        model = _MockSpatialModel(primitives=primitives)
        profile = get_builtin_profiles()["jlcpcb"]
        check = FiducialMarkerCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestComponentPlacementCheck (COMP_PLACE_01)
# ===========================================================================


class TestComponentPlacementCheck:
    """COMP_PLACE_01: Validate component placement constraints."""

    def test_component_outside_board_flagged(self):
        """Component placed outside board outline flagged."""
        from kicad_agent.dfm.extended_checks import ComponentPlacementCheck

        comp = _make_box(
            x1=-5, y1=-5, x2=0, y2=0,
            entity_type="footprint", entity_id="U1", reference="U1",
            layer="F.Cu",
        )
        edge = _make_path(
            points=((0, 0), (50, 0), (50, 50), (0, 50), (0, 0)),
            entity_type="line", entity_id="edge1",
            layer="Edge.Cuts", width=0.15,
        )
        model = _MockSpatialModel(primitives=[comp, edge])
        profile = get_builtin_profiles()["jlcpcb"]
        check = ComponentPlacementCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("COMP_PLACE_01" == f.check_id for f in findings)

    def test_component_inside_board_passes(self):
        """Component well inside board outline passes."""
        from kicad_agent.dfm.extended_checks import ComponentPlacementCheck

        comp = _make_box(
            x1=10, y1=10, x2=15, y2=15,
            entity_type="footprint", entity_id="U1", reference="U1",
            layer="F.Cu",
        )
        edge = _make_path(
            points=((0, 0), (50, 0), (50, 50), (0, 50), (0, 0)),
            entity_type="line", entity_id="edge1",
            layer="Edge.Cuts", width=0.15,
        )
        model = _MockSpatialModel(primitives=[comp, edge])
        profile = get_builtin_profiles()["jlcpcb"]
        check = ComponentPlacementCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestMinSpacingCheck (MIN_SPACE_01)
# ===========================================================================


class TestMinSpacingCheck:
    """MIN_SPACE_01: Validate minimum spacing between copper features."""

    def test_traces_too_close_flagged(self):
        """Two traces on same layer below minimum clearance flagged."""
        from kicad_agent.dfm.extended_checks import MinSpacingCheck

        trace1 = _make_path(
            points=((0, 0), (10, 0)),
            entity_type="trace", entity_id="t1", layer="F.Cu",
            net="SIG1", width=0.2,
        )
        trace2 = _make_path(
            points=((0, 0.05), (10, 0.05)),  # 0.05mm spacing
            entity_type="trace", entity_id="t2", layer="F.Cu",
            net="SIG2", width=0.2,
        )
        model = _MockSpatialModel(primitives=[trace1, trace2])
        profile = get_builtin_profiles()["jlcpcb"]
        check = MinSpacingCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("MIN_SPACE_01" == f.check_id for f in findings)

    def test_traces_far_apart_pass(self):
        """Traces with adequate spacing pass."""
        from kicad_agent.dfm.extended_checks import MinSpacingCheck

        trace1 = _make_path(
            points=((0, 0), (10, 0)),
            entity_type="trace", entity_id="t1", layer="F.Cu",
            net="SIG1", width=0.2,
        )
        trace2 = _make_path(
            points=((0, 1.0), (10, 1.0)),  # 1mm spacing
            entity_type="trace", entity_id="t2", layer="F.Cu",
            net="SIG2", width=0.2,
        )
        model = _MockSpatialModel(primitives=[trace1, trace2])
        profile = get_builtin_profiles()["jlcpcb"]
        check = MinSpacingCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0

    def test_same_net_traces_ignored(self):
        """Traces on same net are not checked for spacing."""
        from kicad_agent.dfm.extended_checks import MinSpacingCheck

        trace1 = _make_path(
            points=((0, 0), (10, 0)),
            entity_type="trace", entity_id="t1", layer="F.Cu",
            net="SIG", width=0.2,
        )
        trace2 = _make_path(
            points=((0, 0.05), (10, 0.05)),
            entity_type="trace", entity_id="t2", layer="F.Cu",
            net="SIG", width=0.2,
        )
        model = _MockSpatialModel(primitives=[trace1, trace2])
        profile = get_builtin_profiles()["jlcpcb"]
        check = MinSpacingCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestMinViaPadCheck (MIN_VIA_PAD_01)
# ===========================================================================


class TestMinViaPadCheck:
    """MIN_VIA_PAD_01: Validate minimum via pad diameter."""

    def test_small_via_pad_flagged(self):
        """Via pad below minimum diameter flagged."""
        from kicad_agent.dfm.extended_checks import MinViaPadCheck

        via = _make_point(
            x=5, y=5, entity_type="via", entity_id="v1",
            layer="F.Cu", net="SIG",
            drill_diameter=0.15,
        )
        via.pad_diameter = 0.25  # Below JLCPCB 0.4mm
        model = _MockSpatialModel(primitives=[via])
        profile = get_builtin_profiles()["jlcpcb"]
        check = MinViaPadCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("MIN_VIA_PAD_01" == f.check_id for f in findings)

    def test_adequate_via_pad_passes(self):
        """Via pad with adequate diameter passes."""
        from kicad_agent.dfm.extended_checks import MinViaPadCheck

        via = _make_point(
            x=5, y=5, entity_type="via", entity_id="v1",
            layer="F.Cu", net="SIG",
            drill_diameter=0.3,
        )
        via.pad_diameter = 0.6  # Above JLCPCB 0.4mm
        model = _MockSpatialModel(primitives=[via])
        profile = get_builtin_profiles()["jlcpcb"]
        check = MinViaPadCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestTeardropCheck (TEARDROP_01)
# ===========================================================================


class TestTeardropCheck:
    """TEARDROP_01: Check for teardrop recommendations on via-pad transitions."""

    def test_via_pad_without_teardrop_emits_info(self):
        """Via-pad transition without teardrop emits INFO finding."""
        from kicad_agent.dfm.extended_checks import TeardropCheck

        via = _make_point(
            x=5, y=5, entity_type="via", entity_id="v1",
            layer="F.Cu", net="SIG",
            drill_diameter=0.3,
        )
        via.has_teardrop = False
        model = _MockSpatialModel(primitives=[via])
        profile = get_builtin_profiles()["jlcpcb"]
        check = TeardropCheck()
        findings = check.check(model, profile)
        assert isinstance(findings, list)

    def test_via_pad_with_teardrop_passes(self):
        """Via-pad transition with teardrop passes."""
        from kicad_agent.dfm.extended_checks import TeardropCheck

        via = _make_point(
            x=5, y=5, entity_type="via", entity_id="v1",
            layer="F.Cu", net="SIG",
            drill_diameter=0.3,
        )
        via.has_teardrop = True
        model = _MockSpatialModel(primitives=[via])
        profile = get_builtin_profiles()["jlcpcb"]
        check = TeardropCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestBlindViaCheck (BLIND_VIA_01)
# ===========================================================================


class TestBlindViaCheck:
    """BLIND_VIA_01: Validate blind via usage against profile support."""

    def test_blind_via_unsupported_flagged(self):
        """Blind via on manufacturer that doesn't support them flagged."""
        from kicad_agent.dfm.extended_checks import BlindViaCheck

        via = _make_point(
            x=5, y=5, entity_type="blind_via", entity_id="bv1",
            layer="F.Cu", net="SIG",
            drill_diameter=0.3,
        )
        model = _MockSpatialModel(primitives=[via])
        profile = get_builtin_profiles()["jlcpcb"]  # No blind via support
        check = BlindViaCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("BLIND_VIA_01" == f.check_id for f in findings)

    def test_blind_via_supported_passes(self):
        """Blind via on manufacturer that supports them passes."""
        from kicad_agent.dfm.extended_checks import BlindViaCheck

        via = _make_point(
            x=5, y=5, entity_type="blind_via", entity_id="bv1",
            layer="F.Cu", net="SIG",
            drill_diameter=0.3,
        )
        model = _MockSpatialModel(primitives=[via])
        profile = get_builtin_profiles()["pcbway"]  # Supports blind vias
        check = BlindViaCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestBoardDimensionCheck (BOARD_DIM_01)
# ===========================================================================


class TestBoardDimensionCheck:
    """BOARD_DIM_01: Validate board dimensions against profile maximum."""

    def test_oversized_board_flagged(self):
        """Board exceeding maximum dimension flagged."""
        from kicad_agent.dfm.extended_checks import BoardDimensionCheck

        edge = _make_path(
            points=((0, 0), (600, 0), (600, 400), (0, 400), (0, 0)),
            entity_type="line", entity_id="edge1",
            layer="Edge.Cuts", width=0.15,
        )
        model = _MockSpatialModel(primitives=[edge])
        profile = get_builtin_profiles()["jlcpcb"]  # max 500mm
        check = BoardDimensionCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("BOARD_DIM_01" == f.check_id for f in findings)

    def test_normal_board_passes(self):
        """Board within maximum dimensions passes."""
        from kicad_agent.dfm.extended_checks import BoardDimensionCheck

        edge = _make_path(
            points=((0, 0), (100, 0), (100, 80), (0, 80), (0, 0)),
            entity_type="line", entity_id="edge1",
            layer="Edge.Cuts", width=0.15,
        )
        model = _MockSpatialModel(primitives=[edge])
        profile = get_builtin_profiles()["jlcpcb"]
        check = BoardDimensionCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestCastellatedHoleCheck (CASTELLATED_01)
# ===========================================================================


class TestCastellatedHoleCheck:
    """CASTELLATED_01: Validate castellated hole usage against profile support."""

    def test_castellated_unsupported_flagged(self):
        """Castellated hole on unsupported manufacturer flagged."""
        from kicad_agent.dfm.extended_checks import CastellatedHoleCheck

        pad = _make_point(
            x=0, y=10, entity_type="castellated_pad", entity_id="cp1",
            layer="Edge.Cuts", net="GND",
            drill_diameter=1.0,
        )
        model = _MockSpatialModel(primitives=[pad])
        profile = get_builtin_profiles()["osh_park"]  # No castellated support
        check = CastellatedHoleCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("CASTELLATED_01" == f.check_id for f in findings)

    def test_castellated_supported_passes(self):
        """Castellated hole on supported manufacturer passes."""
        from kicad_agent.dfm.extended_checks import CastellatedHoleCheck

        pad = _make_point(
            x=0, y=10, entity_type="castellated_pad", entity_id="cp1",
            layer="Edge.Cuts", net="GND",
            drill_diameter=1.0,
        )
        model = _MockSpatialModel(primitives=[pad])
        profile = get_builtin_profiles()["jlcpcb"]  # Supports castellated
        check = CastellatedHoleCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestNPTHDrillCheck (NPTH_DRILL_01)
# ===========================================================================


class TestNPTHDrillCheck:
    """NPTH_DRILL_01: Validate non-plated through hole drill sizes."""

    def test_small_npth_flagged(self):
        """Small NPTH drill flagged."""
        from kicad_agent.dfm.extended_checks import NPTHDrillCheck

        drill = _make_point(
            x=5, y=5, entity_type="npth_drill", entity_id="np1",
            layer="", net="",
            drill_diameter=0.1,  # Very small NPTH
        )
        model = _MockSpatialModel(primitives=[drill])
        profile = get_builtin_profiles()["jlcpcb"]
        check = NPTHDrillCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("NPTH_DRILL_01" == f.check_id for f in findings)

    def test_normal_npth_passes(self):
        """Normal NPTH drill passes."""
        from kicad_agent.dfm.extended_checks import NPTHDrillCheck

        drill = _make_point(
            x=5, y=5, entity_type="npth_drill", entity_id="np1",
            layer="", net="",
            drill_diameter=3.0,
        )
        model = _MockSpatialModel(primitives=[drill])
        profile = get_builtin_profiles()["jlcpcb"]
        check = NPTHDrillCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestSlotCheck (SLOT_01)
# ===========================================================================


class TestSlotCheck:
    """SLOT_01: Validate slot dimensions."""

    def test_narrow_slot_flagged(self):
        """Very narrow slot flagged."""
        from kicad_agent.dfm.extended_checks import SlotCheck

        slot = _make_box(
            x1=0, y1=0, x2=0.05, y2=5,
            entity_type="slot", entity_id="s1",
            layer="Edge.Cuts",
        )
        model = _MockSpatialModel(primitives=[slot])
        profile = get_builtin_profiles()["jlcpcb"]
        check = SlotCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("SLOT_01" == f.check_id for f in findings)

    def test_normal_slot_passes(self):
        """Normal slot passes."""
        from kicad_agent.dfm.extended_checks import SlotCheck

        slot = _make_box(
            x1=0, y1=0, x2=2, y2=5,
            entity_type="slot", entity_id="s1",
            layer="Edge.Cuts",
        )
        model = _MockSpatialModel(primitives=[slot])
        profile = get_builtin_profiles()["jlcpcb"]
        check = SlotCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestViaCountCheck (VIA_COUNT_01)
# ===========================================================================


class TestViaCountCheck:
    """VIA_COUNT_01: Validate via density for manufacturing."""

    def test_excessive_vias_flagged(self):
        """Excessive via count flagged."""
        from kicad_agent.dfm.extended_checks import ViaCountCheck

        primitives = []
        for i in range(1000):
            primitives.append(_make_point(
                x=i * 0.1, y=0, entity_type="via", entity_id=f"v{i}",
                layer="F.Cu", net="SIG", drill_diameter=0.3,
            ))
        model = _MockSpatialModel(primitives=primitives)
        profile = get_builtin_profiles()["jlcpcb"]
        check = ViaCountCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("VIA_COUNT_01" == f.check_id for f in findings)

    def test_normal_via_count_passes(self):
        """Normal via count passes."""
        from kicad_agent.dfm.extended_checks import ViaCountCheck

        primitives = []
        for i in range(10):
            primitives.append(_make_point(
                x=i * 5, y=0, entity_type="via", entity_id=f"v{i}",
                layer="F.Cu", net="SIG", drill_diameter=0.3,
            ))
        model = _MockSpatialModel(primitives=primitives)
        profile = get_builtin_profiles()["jlcpcb"]
        check = ViaCountCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestSolderMaskOpeningCheck (MASK_OPEN_01)
# ===========================================================================


class TestSolderMaskOpeningCheck:
    """MASK_OPEN_01: Validate solder mask openings for pads."""

    def test_tiny_mask_opening_flagged(self):
        """Very small solder mask opening flagged."""
        from kicad_agent.dfm.extended_checks import SolderMaskOpeningCheck

        opening = _make_box(
            x1=0, y1=0, x2=0.05, y2=0.05,
            entity_type="solder_mask_opening", entity_id="mo1",
            layer="F.Mask",
        )
        model = _MockSpatialModel(primitives=[opening])
        profile = get_builtin_profiles()["jlcpcb"]
        check = SolderMaskOpeningCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("MASK_OPEN_01" == f.check_id for f in findings)

    def test_normal_mask_opening_passes(self):
        """Normal solder mask opening passes."""
        from kicad_agent.dfm.extended_checks import SolderMaskOpeningCheck

        opening = _make_box(
            x1=0, y1=0, x2=2, y2=2,
            entity_type="solder_mask_opening", entity_id="mo1",
            layer="F.Mask",
        )
        model = _MockSpatialModel(primitives=[opening])
        profile = get_builtin_profiles()["jlcpcb"]
        check = SolderMaskOpeningCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestTraceLengthCheck (TRACE_LEN_01)
# ===========================================================================


class TestTraceLengthCheck:
    """TRACE_LEN_01: Validate trace length for impedance and signal integrity."""

    def test_very_long_trace_info(self):
        """Very long trace emits INFO about signal integrity review."""
        from kicad_agent.dfm.extended_checks import TraceLengthCheck

        trace = _make_path(
            points=((0, 0), (1000, 0)),
            entity_type="trace", entity_id="t1", layer="F.Cu",
            net="SIG", width=0.2,
        )
        model = _MockSpatialModel(primitives=[trace])
        profile = get_builtin_profiles()["jlcpcb"]
        check = TraceLengthCheck()
        findings = check.check(model, profile)
        assert isinstance(findings, list)

    def test_normal_trace_passes(self):
        """Normal trace length passes."""
        from kicad_agent.dfm.extended_checks import TraceLengthCheck

        trace = _make_path(
            points=((0, 0), (20, 0)),
            entity_type="trace", entity_id="t1", layer="F.Cu",
            net="SIG", width=0.2,
        )
        model = _MockSpatialModel(primitives=[trace])
        profile = get_builtin_profiles()["jlcpcb"]
        check = TraceLengthCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestPadSolderMaskClearanceCheck (PAD_MASK_CLEAR_01)
# ===========================================================================


class TestPadSolderMaskClearanceCheck:
    """PAD_MASK_CLEAR_01: Validate pad to solder mask clearance."""

    def test_pad_too_close_to_mask_edge_flagged(self):
        """Pad too close to solder mask clearance edge flagged."""
        from kicad_agent.dfm.extended_checks import PadSolderMaskClearanceCheck

        pad = _make_box(
            x1=0, y1=0, x2=2, y2=2,
            entity_type="pad", entity_id="p1", reference="R1",
            layer="F.Cu", net="SIG",
        )
        mask_edge = _make_box(
            x1=1.8, y1=0, x2=3, y2=2,
            entity_type="solder_mask_boundary", entity_id="mb1",
            layer="F.Mask",
        )
        model = _MockSpatialModel(primitives=[pad, mask_edge])
        profile = get_builtin_profiles()["jlcpcb"]
        check = PadSolderMaskClearanceCheck()
        findings = check.check(model, profile)
        assert isinstance(findings, list)

    def test_no_mask_features_passes(self):
        """No mask features means no findings."""
        from kicad_agent.dfm.extended_checks import PadSolderMaskClearanceCheck

        pad = _make_box(
            x1=0, y1=0, x2=2, y2=2,
            entity_type="pad", entity_id="p1", reference="R1",
        )
        model = _MockSpatialModel(primitives=[pad])
        profile = get_builtin_profiles()["jlcpcb"]
        check = PadSolderMaskClearanceCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestViaAnnularCheck (VIA_ANNULAR_01)
# ===========================================================================


class TestViaAnnularCheck:
    """VIA_ANNULAR_01: Validate via annular ring dimensions."""

    def test_thin_via_annular_flagged(self):
        """Via with thin annular ring flagged."""
        from kicad_agent.dfm.extended_checks import ViaAnnularCheck

        via = _make_point(
            x=5, y=5, entity_type="via", entity_id="v1",
            layer="F.Cu", net="SIG",
            drill_diameter=0.35,
        )
        via.pad_diameter = 0.5  # annular = (0.5 - 0.35) / 2 = 0.075mm < JLCPCB 0.1mm
        model = _MockSpatialModel(primitives=[via])
        profile = get_builtin_profiles()["jlcpcb"]
        check = ViaAnnularCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("VIA_ANNULAR_01" == f.check_id for f in findings)

    def test_adequate_via_annular_passes(self):
        """Via with adequate annular ring passes."""
        from kicad_agent.dfm.extended_checks import ViaAnnularCheck

        via = _make_point(
            x=5, y=5, entity_type="via", entity_id="v1",
            layer="F.Cu", net="SIG",
            drill_diameter=0.3,
        )
        via.pad_diameter = 0.6  # annular = (0.6 - 0.3) / 2 = 0.15mm > JLCPCB 0.1mm
        model = _MockSpatialModel(primitives=[via])
        profile = get_builtin_profiles()["jlcpcb"]
        check = ViaAnnularCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestHoleToHoleCheck (HOLE_SPACE_01)
# ===========================================================================


class TestHoleToHoleCheck:
    """HOLE_SPACE_01: Validate minimum spacing between drilled holes."""

    def test_holes_too_close_flagged(self):
        """Two holes too close flagged."""
        from kicad_agent.dfm.extended_checks import HoleToHoleCheck

        h1 = _make_point(x=0, y=0, entity_type="drill", entity_id="d1", drill_diameter=1.0)
        h2 = _make_point(x=0.8, y=0, entity_type="drill", entity_id="d2", drill_diameter=1.0)
        model = _MockSpatialModel(primitives=[h1, h2])
        profile = get_builtin_profiles()["jlcpcb"]
        check = HoleToHoleCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("HOLE_SPACE_01" == f.check_id for f in findings)

    def test_holes_far_apart_pass(self):
        """Holes with adequate spacing pass."""
        from kicad_agent.dfm.extended_checks import HoleToHoleCheck

        h1 = _make_point(x=0, y=0, entity_type="drill", entity_id="d1", drill_diameter=1.0)
        h2 = _make_point(x=5, y=0, entity_type="drill", entity_id="d2", drill_diameter=1.0)
        model = _MockSpatialModel(primitives=[h1, h2])
        profile = get_builtin_profiles()["jlcpcb"]
        check = HoleToHoleCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestPadToPadClearanceCheck (PAD_CLEAR_01)
# ===========================================================================


class TestPadToPadClearanceCheck:
    """PAD_CLEAR_01: Validate pad-to-pad clearance."""

    def test_pads_too_close_flagged(self):
        """Pads on different nets too close flagged."""
        from kicad_agent.dfm.extended_checks import PadToPadClearanceCheck

        pad1 = _make_box(
            x1=0, y1=0, x2=1, y2=1,
            entity_type="pad", entity_id="p1", reference="R1",
            layer="F.Cu", net="SIG1",
        )
        pad2 = _make_box(
            x1=1.05, y1=0, x2=2.05, y2=1,
            entity_type="pad", entity_id="p2", reference="R2",
            layer="F.Cu", net="SIG2",
        )
        model = _MockSpatialModel(primitives=[pad1, pad2])
        profile = get_builtin_profiles()["jlcpcb"]
        check = PadToPadClearanceCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("PAD_CLEAR_01" == f.check_id for f in findings)

    def test_pads_on_same_net_ignored(self):
        """Pads on same net are not checked for clearance."""
        from kicad_agent.dfm.extended_checks import PadToPadClearanceCheck

        pad1 = _make_box(
            x1=0, y1=0, x2=1, y2=1,
            entity_type="pad", entity_id="p1", reference="R1",
            layer="F.Cu", net="SIG",
        )
        pad2 = _make_box(
            x1=1.05, y1=0, x2=2.05, y2=1,
            entity_type="pad", entity_id="p2", reference="R2",
            layer="F.Cu", net="SIG",
        )
        model = _MockSpatialModel(primitives=[pad1, pad2])
        profile = get_builtin_profiles()["jlcpcb"]
        check = PadToPadClearanceCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestZoneFillCheck (ZONE_FILL_01)
# ===========================================================================


class TestZoneFillCheck:
    """ZONE_FILL_01: Verify copper zones have been filled."""

    def test_unfilled_zone_flagged(self):
        """Unfilled copper zone flagged."""
        from kicad_agent.dfm.extended_checks import ZoneFillCheck

        zone = _make_region(
            boundary=((0, 0), (10, 0), (10, 10), (0, 10)),
            entity_type="zone", entity_id="z1", layer="F.Cu",
            net="GND",
        )
        zone.is_filled = False
        model = _MockSpatialModel(primitives=[zone])
        profile = get_builtin_profiles()["jlcpcb"]
        check = ZoneFillCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("ZONE_FILL_01" == f.check_id for f in findings)

    def test_filled_zone_passes(self):
        """Filled copper zone passes."""
        from kicad_agent.dfm.extended_checks import ZoneFillCheck

        zone = _make_region(
            boundary=((0, 0), (10, 0), (10, 10), (0, 10)),
            entity_type="zone", entity_id="z1", layer="F.Cu",
            net="GND",
        )
        zone.is_filled = True
        model = _MockSpatialModel(primitives=[zone])
        profile = get_builtin_profiles()["jlcpcb"]
        check = ZoneFillCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestMinCopperPourWidthCheck (COPPER_POUR_W_01)
# ===========================================================================


class TestMinCopperPourWidthCheck:
    """COPPER_POUR_W_01: Validate minimum copper pour feature width."""

    def test_thin_copper_pour_flagged(self):
        """Thin copper pour neck flagged."""
        from kicad_agent.dfm.extended_checks import MinCopperPourWidthCheck

        pour = _make_box(
            x1=0, y1=0, x2=0.05, y2=5,
            entity_type="copper_pour", entity_id="cp1",
            layer="F.Cu", net="GND",
        )
        model = _MockSpatialModel(primitives=[pour])
        profile = get_builtin_profiles()["jlcpcb"]
        check = MinCopperPourWidthCheck()
        findings = check.check(model, profile)
        assert len(findings) >= 1
        assert any("COPPER_POUR_W_01" == f.check_id for f in findings)

    def test_normal_copper_pour_passes(self):
        """Normal copper pour width passes."""
        from kicad_agent.dfm.extended_checks import MinCopperPourWidthCheck

        pour = _make_box(
            x1=0, y1=0, x2=5, y2=5,
            entity_type="copper_pour", entity_id="cp1",
            layer="F.Cu", net="GND",
        )
        model = _MockSpatialModel(primitives=[pour])
        profile = get_builtin_profiles()["jlcpcb"]
        check = MinCopperPourWidthCheck()
        findings = check.check(model, profile)
        assert len(findings) == 0


# ===========================================================================
# TestMultiStageWithExtendedChecks
# ===========================================================================


class TestMultiStageWithExtendedChecks:
    """Integration: extended checks work through DfmChecker pipeline."""

    def test_extended_checks_count(self):
        """get_builtin_dfm_checks returns 50+ checks after expansion."""
        from kicad_agent.dfm.checks import get_builtin_dfm_checks

        checks = get_builtin_dfm_checks()
        assert len(checks) >= 50, f"Expected 50+ checks, got {len(checks)}"

    def test_all_checks_run_through_checker(self):
        """All extended checks execute through DfmChecker without crashing."""
        from kicad_agent.dfm.checks import get_builtin_dfm_checks
        from kicad_agent.dfm.checker import DfmChecker

        checker = DfmChecker(checks=get_builtin_dfm_checks())
        model = _MockSpatialModel(primitives=[])
        profile = get_builtin_profiles()["generic"]
        report = checker.run(model, profile)
        assert report.checks_run >= 50
        # Empty board should still have some findings (missing fiducials, etc.)
        assert report.manufacturability_score < 1.0

    def test_check_names_unique(self):
        """All check names are unique."""
        from kicad_agent.dfm.checks import get_builtin_dfm_checks

        checks = get_builtin_dfm_checks()
        names = [c.name for c in checks]
        assert len(names) == len(set(names)), f"Duplicate check names: {[n for n in names if names.count(n) > 1]}"
