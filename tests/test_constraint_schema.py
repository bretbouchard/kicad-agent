"""Tests for constraint schema validation.

Covers ElectricalConstraints, MechanicalConstraints, FabProfileConstraints,
DesignConstraints, and their validators.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kicad_agent.validation.gates.constraint_schema import (
    DesignConstraints,
    DiffPairSpec,
    ElectricalConstraints,
    FabProfileConstraints,
    KeepoutZone,
    LengthMatchSpec,
    LockZone,
    MechanicalConstraints,
    MountingHoleSpec,
)


# ---------------------------------------------------------------------------
# DiffPairSpec
# ---------------------------------------------------------------------------

class TestDiffPairSpec:
    def test_valid_diff_pair(self) -> None:
        dp = DiffPairSpec(pair_name="USB_DP", gap_mm=0.15)
        assert dp.pair_name == "USB_DP"
        assert dp.gap_mm == 0.15
        assert dp.length_match_mm is None
        assert dp.tolerance_mm is None

    def test_diff_pair_with_length_match(self) -> None:
        dp = DiffPairSpec(
            pair_name="ETH_DP",
            gap_mm=0.1,
            length_match_mm=50.0,
            tolerance_mm=0.5,
        )
        assert dp.length_match_mm == 50.0
        assert dp.tolerance_mm == 0.5

    def test_diff_pair_zero_gap_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DiffPairSpec(pair_name="X", gap_mm=0)

    def test_diff_pair_negative_gap_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DiffPairSpec(pair_name="X", gap_mm=-0.1)

    def test_diff_pair_negative_length_match_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DiffPairSpec(pair_name="X", gap_mm=0.1, length_match_mm=-1.0)

    def test_diff_pair_negative_tolerance_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DiffPairSpec(pair_name="X", gap_mm=0.1, tolerance_mm=-0.1)


# ---------------------------------------------------------------------------
# LengthMatchSpec
# ---------------------------------------------------------------------------

class TestLengthMatchSpec:
    def test_valid_length_match(self) -> None:
        lm = LengthMatchSpec(target_mm=100.0, tolerance_mm=2.0, group_name="DDR_ADDR")
        assert lm.target_mm == 100.0
        assert lm.tolerance_mm == 2.0
        assert lm.group_name == "DDR_ADDR"

    def test_zero_target_allowed(self) -> None:
        """Zero target length is technically valid (ge=0 constraint)."""
        lm = LengthMatchSpec(target_mm=0, tolerance_mm=1.0, group_name="X")
        assert lm.target_mm == 0

    def test_negative_tolerance_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LengthMatchSpec(target_mm=50.0, tolerance_mm=-1.0, group_name="X")


# ---------------------------------------------------------------------------
# MountingHoleSpec
# ---------------------------------------------------------------------------

class TestMountingHoleSpec:
    def test_valid_mounting_hole(self) -> None:
        mh = MountingHoleSpec(position=(10.0, 20.0), drill_diameter_mm=3.2)
        assert mh.position == (10.0, 20.0)
        assert mh.drill_diameter_mm == 3.2
        assert mh.plating == "non_plated"

    def test_plated_mounting_hole(self) -> None:
        mh = MountingHoleSpec(
            position=(5.0, 5.0), drill_diameter_mm=2.5, plating="plated"
        )
        assert mh.plating == "plated"

    def test_invalid_plating_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MountingHoleSpec(
                position=(0.0, 0.0),
                drill_diameter_mm=3.0,
                plating="gold_plated",
            )

    def test_zero_drill_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MountingHoleSpec(position=(0.0, 0.0), drill_diameter_mm=0)

    def test_negative_drill_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MountingHoleSpec(position=(0.0, 0.0), drill_diameter_mm=-1.0)


# ---------------------------------------------------------------------------
# KeepoutZone
# ---------------------------------------------------------------------------

class TestKeepoutZone:
    def test_valid_keepout(self) -> None:
        ko = KeepoutZone(bounds=(0.0, 0.0, 10.0, 20.0), zone_type="copper")
        assert ko.bounds == (0.0, 0.0, 10.0, 20.0)
        assert ko.zone_type == "copper"

    def test_via_keepout(self) -> None:
        ko = KeepoutZone(bounds=(5.0, 5.0, 15.0, 25.0), zone_type="via")
        assert ko.zone_type == "via"

    def test_track_keepout(self) -> None:
        ko = KeepoutZone(bounds=(0.0, 0.0, 50.0, 50.0), zone_type="track")
        assert ko.zone_type == "track"

    def test_invalid_zone_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            KeepoutZone(bounds=(0, 0, 10, 10), zone_type="component")


# ---------------------------------------------------------------------------
# LockZone
# ---------------------------------------------------------------------------

class TestLockZone:
    def test_valid_lock_zone(self) -> None:
        lz = LockZone(bounds=(0.0, 0.0, 20.0, 30.0), connector_ref="J1")
        assert lz.connector_ref == "J1"


# ---------------------------------------------------------------------------
# ElectricalConstraints
# ---------------------------------------------------------------------------

class TestElectricalConstraints:
    def test_minimal(self) -> None:
        ec = ElectricalConstraints(net_name="VCC")
        assert ec.net_name == "VCC"
        assert ec.current_ma is None
        assert ec.voltage_v is None
        assert ec.impedance_ohm is None
        assert ec.diff_pair is None
        assert ec.frequency_hz is None
        assert ec.max_length_mm is None

    def test_full_constraints(self) -> None:
        ec = ElectricalConstraints(
            net_name="USB_DP",
            current_ma=100.0,
            voltage_v=3.3,
            impedance_ohm=50.0,
            diff_pair=DiffPairSpec(pair_name="USB", gap_mm=0.15),
            frequency_hz=480e6,
            max_length_mm=100.0,
        )
        assert ec.current_ma == 100.0
        assert ec.voltage_v == 3.3
        assert ec.impedance_ohm == 50.0
        assert ec.diff_pair.pair_name == "USB"
        assert ec.frequency_hz == 480e6
        assert ec.max_length_mm == 100.0

    def test_length_match(self) -> None:
        ec = ElectricalConstraints(
            net_name="DDR_DQ0",
            length_match=LengthMatchSpec(
                target_mm=50.0, tolerance_mm=0.5, group_name="DDR_DATA"
            ),
        )
        assert ec.length_match.group_name == "DDR_DATA"

    def test_negative_current_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ElectricalConstraints(net_name="X", current_ma=-1.0)

    def test_zero_voltage_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ElectricalConstraints(net_name="X", voltage_v=0)

    def test_negative_voltage_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ElectricalConstraints(net_name="X", voltage_v=-5.0)

    def test_zero_impedance_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ElectricalConstraints(net_name="X", impedance_ohm=0)

    def test_zero_frequency_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ElectricalConstraints(net_name="X", frequency_hz=0)

    def test_zero_max_length_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ElectricalConstraints(net_name="X", max_length_mm=0)


# ---------------------------------------------------------------------------
# MechanicalConstraints
# ---------------------------------------------------------------------------

class TestMechanicalConstraints:
    def test_minimal(self) -> None:
        mc = MechanicalConstraints()
        assert mc.board_outline is None
        assert mc.mounting_holes == []
        assert mc.keepouts == []
        assert mc.connector_lock_zones == []

    def test_board_outline_valid_closed_polygon(self) -> None:
        outline = [(0, 0), (100, 0), (100, 80), (0, 80), (0, 0)]
        mc = MechanicalConstraints(board_outline=outline)
        assert mc.board_outline == outline

    def test_board_outline_rejects_not_closed(self) -> None:
        outline = [(0, 0), (100, 0), (100, 80), (0, 80)]
        with pytest.raises(ValidationError) as exc_info:
            MechanicalConstraints(board_outline=outline)
        assert "closed" in str(exc_info.value).lower()

    def test_board_outline_rejects_less_than_3_points(self) -> None:
        outline = [(0, 0), (100, 0), (0, 0)]
        with pytest.raises(ValidationError) as exc_info:
            MechanicalConstraints(board_outline=outline)
        assert "at least 3" in str(exc_info.value)

    def test_board_outline_rejects_2_points(self) -> None:
        outline = [(0, 0), (100, 100)]
        with pytest.raises(ValidationError):
            MechanicalConstraints(board_outline=outline)

    def test_board_outline_rejects_1_point(self) -> None:
        outline = [(0, 0)]
        with pytest.raises(ValidationError):
            MechanicalConstraints(board_outline=outline)

    def test_board_outline_triangle(self) -> None:
        outline = [(0, 0), (50, 0), (25, 50), (0, 0)]
        mc = MechanicalConstraints(board_outline=outline)
        assert len(mc.board_outline) == 4  # closed triangle

    def test_with_mounting_holes(self) -> None:
        mc = MechanicalConstraints(
            mounting_holes=[
                MountingHoleSpec(position=(5, 5), drill_diameter_mm=3.2),
                MountingHoleSpec(position=(95, 5), drill_diameter_mm=3.2),
            ]
        )
        assert len(mc.mounting_holes) == 2

    def test_with_keepouts(self) -> None:
        mc = MechanicalConstraints(
            keepouts=[
                KeepoutZone(bounds=(10, 10, 30, 30), zone_type="via"),
            ]
        )
        assert len(mc.keepouts) == 1
        assert mc.keepouts[0].zone_type == "via"

    def test_with_connector_lock_zones(self) -> None:
        mc = MechanicalConstraints(
            connector_lock_zones=[
                LockZone(bounds=(0, 0, 20, 30), connector_ref="J1"),
            ]
        )
        assert mc.connector_lock_zones[0].connector_ref == "J1"

    def test_full_mechanical(self) -> None:
        mc = MechanicalConstraints(
            board_outline=[(0, 0), (100, 0), (100, 80), (0, 80), (0, 0)],
            mounting_holes=[MountingHoleSpec(position=(5, 5), drill_diameter_mm=3.2)],
            keepouts=[KeepoutZone(bounds=(10, 10, 30, 30))],
            connector_lock_zones=[LockZone(bounds=(0, 0, 20, 30), connector_ref="J1")],
        )
        assert len(mc.mounting_holes) == 1
        assert len(mc.keepouts) == 1
        assert len(mc.connector_lock_zones) == 1


# ---------------------------------------------------------------------------
# FabProfileConstraints
# ---------------------------------------------------------------------------

class TestFabProfileConstraints:
    def test_defaults(self) -> None:
        fab = FabProfileConstraints()
        assert fab.min_trace_width_mm == 0.15
        assert fab.min_drill_mm == 0.2
        assert fab.min_clearance_mm == 0.15
        assert fab.layer_count == 2
        assert fab.copper_weight_oz == 1.0
        assert fab.material == "FR-4"

    def test_invalid_material_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FabProfileConstraints(material="cardboard")

    def test_invalid_layer_count_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FabProfileConstraints(layer_count=0)

    def test_invalid_copper_weight_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FabProfileConstraints(copper_weight_oz=0.1)

    def test_jlcpcb_preset(self) -> None:
        fab = FabProfileConstraints.jlcpcb()
        assert fab.min_trace_width_mm == 0.127
        assert fab.min_drill_mm == 0.2
        assert fab.min_clearance_mm == 0.127
        assert fab.layer_count == 2
        assert fab.material == "FR-4"

    def test_jlcpcb_4layer_preset(self) -> None:
        fab = FabProfileConstraints.jlcpcb_4layer()
        assert fab.min_trace_width_mm == 0.1
        assert fab.layer_count == 4
        assert fab.min_clearance_mm == 0.1

    def test_pcbway_preset(self) -> None:
        fab = FabProfileConstraints.pcbway()
        assert fab.min_trace_width_mm == 0.1
        assert fab.min_clearance_mm == 0.1
        assert fab.layer_count == 2

    def test_osh_park_preset(self) -> None:
        fab = FabProfileConstraints.osh_park()
        assert abs(fab.min_trace_width_mm - 0.1524) < 1e-6
        assert abs(fab.min_drill_mm - 0.3556) < 1e-6
        assert abs(fab.min_clearance_mm - 0.1524) < 1e-6
        assert fab.layer_count == 2

    def test_validate_achievable_no_issues(self) -> None:
        fab = FabProfileConstraints.jlcpcb()
        ec = ElectricalConstraints(net_name="VCC", current_ma=100.0)
        warnings = fab.validate_achievable([ec])
        assert warnings == []

    def test_validate_achievable_diff_pair_gap_below_clearance(self) -> None:
        fab = FabProfileConstraints.jlcpcb()
        ec = ElectricalConstraints(
            net_name="USB_DP",
            diff_pair=DiffPairSpec(pair_name="USB", gap_mm=0.05),
        )
        warnings = fab.validate_achievable([ec])
        assert any("below fab min clearance" in w for w in warnings)

    def test_validate_achievable_diff_pair_gap_below_trace_width(self) -> None:
        fab = FabProfileConstraints.jlcpcb()
        ec = ElectricalConstraints(
            net_name="USB_DP",
            diff_pair=DiffPairSpec(pair_name="USB", gap_mm=0.1),
        )
        warnings = fab.validate_achievable([ec])
        # JLCPCB min_clearance=0.127, gap=0.1 < 0.127 => clearance warning
        # JLCPCB min_trace=0.127, gap=0.1 < 0.127 => trace width warning
        assert len(warnings) == 2

    def test_validate_achievable_low_impedance_2layer(self) -> None:
        fab = FabProfileConstraints()  # default 2-layer FR4
        ec = ElectricalConstraints(net_name="RF", impedance_ohm=20.0)
        warnings = fab.validate_achievable([ec])
        assert any("very low" in w.lower() for w in warnings)

    def test_validate_achievable_high_impedance(self) -> None:
        fab = FabProfileConstraints(min_trace_width_mm=0.15)
        ec = ElectricalConstraints(net_name="RF", impedance_ohm=100.0)
        warnings = fab.validate_achievable([ec])
        assert any("below fab minimum" in w for w in warnings)

    def test_validate_achievable_multiple_nets(self) -> None:
        fab = FabProfileConstraints.jlcpcb()
        electrical = [
            ElectricalConstraints(net_name="VCC", current_ma=100.0),
            ElectricalConstraints(
                net_name="USB_DP",
                diff_pair=DiffPairSpec(pair_name="USB", gap_mm=0.05),
            ),
        ]
        warnings = fab.validate_achievable(electrical)
        assert len(warnings) >= 1  # USB diff pair gap issue


# ---------------------------------------------------------------------------
# DesignConstraints
# ---------------------------------------------------------------------------

class TestDesignConstraints:
    def test_defaults(self) -> None:
        dc = DesignConstraints()
        assert dc.electrical == []
        assert dc.mechanical is None
        assert dc.fab.min_trace_width_mm == 0.15

    def test_with_electrical(self) -> None:
        dc = DesignConstraints(
            electrical=[ElectricalConstraints(net_name="VCC", current_ma=500.0)]
        )
        assert len(dc.electrical) == 1

    def test_with_mechanical(self) -> None:
        dc = DesignConstraints(
            mechanical=MechanicalConstraints(
                board_outline=[(0, 0), (100, 0), (100, 80), (0, 80), (0, 0)]
            )
        )
        assert dc.mechanical is not None

    def test_validate_cross_constraints_no_issues(self) -> None:
        dc = DesignConstraints(
            electrical=[ElectricalConstraints(net_name="VCC", current_ma=100.0)],
            fab=FabProfileConstraints.jlcpcb(),
        )
        warnings = dc.validate_cross_constraints()
        assert warnings == []

    def test_validate_cross_constraints_diff_pair_gap(self) -> None:
        dc = DesignConstraints(
            electrical=[
                ElectricalConstraints(
                    net_name="USB_DP",
                    diff_pair=DiffPairSpec(pair_name="USB", gap_mm=0.05),
                )
            ],
            fab=FabProfileConstraints.jlcpcb(),
        )
        warnings = dc.validate_cross_constraints()
        assert any("diff pair gap" in w.lower() for w in warnings)

    def test_validate_cross_constraints_high_current(self) -> None:
        dc = DesignConstraints(
            electrical=[
                ElectricalConstraints(net_name="MOTOR", current_ma=3000.0)
            ],
            fab=FabProfileConstraints.jlcpcb(),
        )
        warnings = dc.validate_cross_constraints()
        # 3000mA > capacity of ~300mA for 0.127mm trace
        assert any("exceeds estimated capacity" in w for w in warnings)

    def test_validate_cross_constraints_voltage_safety(self) -> None:
        """High voltage should trigger wider clearance implicitly."""
        dc = DesignConstraints(
            electrical=[
                ElectricalConstraints(net_name="HV", voltage_v=120.0, current_ma=100.0)
            ],
            fab=FabProfileConstraints(),
        )
        warnings = dc.validate_cross_constraints()
        # With voltage > 60V and narrow default trace, current capacity is limited
        # but 100mA should be fine for default trace width
        assert len(warnings) == 0

    def test_full_design_constraints(self) -> None:
        dc = DesignConstraints(
            electrical=[
                ElectricalConstraints(net_name="VCC", current_ma=500.0),
                ElectricalConstraints(
                    net_name="USB_DP",
                    diff_pair=DiffPairSpec(pair_name="USB", gap_mm=0.15),
                    impedance_ohm=90.0,
                ),
            ],
            mechanical=MechanicalConstraints(
                board_outline=[(0, 0), (100, 0), (100, 80), (0, 80), (0, 0)],
                mounting_holes=[
                    MountingHoleSpec(position=(5, 5), drill_diameter_mm=3.2)
                ],
            ),
            fab=FabProfileConstraints.jlcpcb_4layer(),
        )
        assert len(dc.electrical) == 2
        assert dc.mechanical is not None
        assert dc.fab.layer_count == 4
