"""Tests for PlacementReadinessGate (Phase 89).

Tests use lightweight mocks of PcbIR and footprint objects rather than
real .kicad_pcb fixture files, since the gate operates on PcbIR properties
that can be constructed in-memory.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from volta.analysis.types import NetClassification
from volta.validation.gates.placement_gate import (
    PlacementReadinessGate,
    _BLOCKED_CHANNEL_MIN_MM,
    _CONNECTOR_EDGE_MAX_MM,
    _DENSITY_WARNING_THRESHOLD,
    _MOUNTING_HOLE_CORNER_MAX_MM,
    _THERMAL_DEFAULT_CLEARANCE_MM,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


@dataclass
class MockPad:
    """Minimal pad mock for PcbIR."""
    number: str = "1"
    position: Any = None
    net: Any = None
    net_name: str = ""
    net_number: int = 0


@dataclass
class MockFootprint:
    """Minimal footprint mock for PcbIR."""
    properties: dict = field(default_factory=dict)
    lib_id: str = ""
    libId: str = ""  # kiutils spelling
    position: Any = None
    pads: list = field(default_factory=list)
    graphic_items: list = field(default_factory=list)
    graphicItems: list = field(default_factory=list)


@dataclass
class MockGraphic:
    """Minimal graphic item for Edge.Cuts."""
    layer: str = "Edge.Cuts"
    start: Any = None
    end: Any = None
    center: Any = None
    radius: Any = None


@dataclass
class MockPos:
    """Position with X, Y, angle."""
    X: float = 0.0
    Y: float = 0.0
    angle: float = 0.0


def _make_pcb_ir(
    footprints: list[MockFootprint] | None = None,
    board_bounds: tuple[float, float, float, float] | None = (0, 0, 100, 80),
    _is_native: bool = True,
) -> MagicMock:
    """Create a mock PcbIR with the given footprints and board bounds.

    Defaults to _is_native=True so MockPad.net_name is used (matches native PcbIR).
    """
    ir = MagicMock()
    ir._is_native = _is_native
    ir.footprints = footprints or []
    ir.get_board_bounds.return_value = board_bounds
    ir.get_footprint_by_ref.side_effect = lambda ref: next(
        (fp for fp in ir.footprints if fp.properties.get("Reference") == ref),
        None,
    )
    # Wire up _unpack_position to our helper
    ir._unpack_position = _unpack_pos
    return ir


def _unpack_pos(pos: Any) -> tuple[float, float, float]:
    """Unpack position from mock or real object."""
    if hasattr(pos, "X"):
        return (pos.X, pos.Y, getattr(pos, "angle", 0.0) or 0.0)
    if isinstance(pos, (list, tuple)):
        return (
            pos[0] if len(pos) > 0 else 0.0,
            pos[1] if len(pos) > 1 else 0.0,
            pos[2] if len(pos) > 2 else 0.0,
        )
    return (0.0, 0.0, 0.0)


@pytest.fixture
def gate() -> PlacementReadinessGate:
    return PlacementReadinessGate()


# ---------------------------------------------------------------------------
# Sub-check 1: Footprint bounds
# ---------------------------------------------------------------------------


class TestFootprintBounds:
    def test_all_inside_no_issues(self, gate: PlacementReadinessGate) -> None:
        """Footprints inside outline produce no issues."""
        ir = _make_pcb_ir([
            MockFootprint(
                properties={"Reference": "R1"},
                lib_id="Device:R",
                position=MockPos(X=50, Y=40),
                pads=[MockPad(position=MockPos(X=-1, Y=0))],
            ),
        ])
        blockers, warnings = gate._check_footprint_bounds(ir)
        assert blockers == []
        assert warnings == []

    def test_outside_outline_blocker(self, gate: PlacementReadinessGate) -> None:
        """Footprint outside board outline produces blocker."""
        ir = _make_pcb_ir(
            footprints=[
                MockFootprint(
                    properties={"Reference": "R1"},
                    lib_id="Device:R",
                    position=MockPos(X=110, Y=40),  # outside x_max=100
                    pads=[MockPad(position=MockPos(X=-1, Y=0))],
                ),
            ],
            board_bounds=(0, 0, 100, 80),
        )
        blockers, warnings = gate._check_footprint_bounds(ir)
        assert any("outside board outline" in b for b in blockers)

    def test_near_edge_warning(self, gate: PlacementReadinessGate) -> None:
        """Footprint near edge produces warning."""
        ir = _make_pcb_ir(
            footprints=[
                MockFootprint(
                    properties={"Reference": "R1"},
                    lib_id="Device:R",
                    position=MockPos(X=0.3, Y=40),  # within 1mm of x_min=0
                    pads=[MockPad(position=MockPos(X=0, Y=0))],
                ),
            ],
            board_bounds=(0, 0, 100, 80),
        )
        blockers, warnings = gate._check_footprint_bounds(ir)
        assert any("within 1.0mm of board edge" in w for w in warnings)


# ---------------------------------------------------------------------------
# Sub-check 2: Courtyard clearance
# ---------------------------------------------------------------------------


class TestCourtyardClearance:
    def test_no_overlap(self, gate: PlacementReadinessGate) -> None:
        """Well-separated footprints produce no issues."""
        ir = _make_pcb_ir([
            MockFootprint(properties={"Reference": "R1"}, lib_id="Device:R",
                           position=MockPos(X=10, Y=10), pads=[MockPad(position=MockPos())]),
            MockFootprint(properties={"Reference": "R2"}, lib_id="Device:R",
                           position=MockPos(X=50, Y=50), pads=[MockPad(position=MockPos())]),
        ])
        blockers, warnings = gate._check_courtyard_clearance(ir)
        assert blockers == []

    def test_overlapping_blocker(self, gate: PlacementReadinessGate) -> None:
        """Overlapping footprint bounding boxes produce blocker."""
        ir = _make_pcb_ir([
            MockFootprint(properties={"Reference": "U1"}, lib_id="IC:NE5532",
                           position=MockPos(X=50, Y=40),
                           pads=[MockPad(position=MockPos(X=-2, Y=-2)), MockPad(position=MockPos(X=2, Y=2))]),
            MockFootprint(properties={"Reference": "U2"}, lib_id="IC:NE5532",
                           position=MockPos(X=51, Y=40),  # 1mm away -> overlaps
                           pads=[MockPad(position=MockPos(X=-2, Y=-2)), MockPad(position=MockPos(X=2, Y=2))]),
        ])
        blockers, warnings = gate._check_courtyard_clearance(ir)
        assert any("overlap" in b.lower() for b in blockers)


# ---------------------------------------------------------------------------
# Sub-check 3: Mechanical positions
# ---------------------------------------------------------------------------


class TestMechanicalPositions:
    def test_connector_at_edge_ok(self, gate: PlacementReadinessGate) -> None:
        """Connector at board edge produces no warning."""
        ir = _make_pcb_ir([
            MockFootprint(
                properties={"Reference": "J1"},
                lib_id="Connector:USB_C",
                position=MockPos(X=1, Y=40),  # 1mm from edge
                pads=[],
            ),
        ])
        blockers, warnings = gate._check_mechanical_positions(ir)
        assert not any("Connector" in w for w in warnings)

    def test_connector_in_center_warning(self, gate: PlacementReadinessGate) -> None:
        """Connector in board center produces warning."""
        ir = _make_pcb_ir([
            MockFootprint(
                properties={"Reference": "J1"},
                lib_id="Connector:USB_C",
                position=MockPos(X=50, Y=40),  # center
                pads=[],
            ),
        ])
        blockers, warnings = gate._check_mechanical_positions(ir)
        assert any("Connector" in w for w in warnings)

    def test_mounting_hole_not_near_corner(self, gate: PlacementReadinessGate) -> None:
        """Mounting hole far from corners produces warning."""
        ir = _make_pcb_ir([
            MockFootprint(
                properties={"Reference": "H1"},
                lib_id="MountingHole:MountingHole_3.2mm",
                position=MockPos(X=50, Y=40),  # center
                pads=[],
            ),
        ])
        blockers, warnings = gate._check_mechanical_positions(ir)
        assert any("Mounting hole" in w for w in warnings)


# ---------------------------------------------------------------------------
# Sub-check 4: Decoupling proximity
# ---------------------------------------------------------------------------


class TestDecouplingProximity:
    def _make_decoupling_ir(
        self,
        cap_x: float = 45,
        cap_y: float = 40,
        ic_x: float = 50,
        ic_y: float = 40,
        cap_package: str = "0402",
    ) -> MagicMock:
        """Create PcbIR mock with one IC and one decoupling cap."""
        vcc_net = "VCC3V3"
        gnd_net = "GND"
        net_classifications = {
            vcc_net: NetClassification.POWER,
            gnd_net: NetClassification.GROUND,
        }

        ir = _make_pcb_ir([
            MockFootprint(
                properties={"Reference": "C1"},
                lib_id="Device:C",
                position=MockPos(X=cap_x, Y=cap_y),
                pads=[
                    MockPad(number="1", position=MockPos(), net_name=vcc_net),
                    MockPad(number="2", position=MockPos(), net_name=gnd_net),
                ],
            ),
            MockFootprint(
                properties={"Reference": "U1"},
                lib_id="Amplifier_Operational:NE5532",
                position=MockPos(X=ic_x, Y=ic_y),
                pads=[
                    MockPad(number="1", position=MockPos(), net_name=vcc_net),
                    MockPad(number="2", position=MockPos(), net_name="SIG"),
                    MockPad(number="3", position=MockPos(), net_name="OUT"),
                    MockPad(number="4", position=MockPos(), net_name=gnd_net),
                ],
            ),
        ])
        return ir, net_classifications

    def test_cap_near_ic_ok(self, gate: PlacementReadinessGate) -> None:
        """Decoupling cap within 5mm of IC produces no warning."""
        ir, net_cls = self._make_decoupling_ir(cap_x=48, ic_x=50)
        blockers, warnings = gate._check_decoupling_proximity(ir, None, None, net_cls)
        assert all("Decoupling" not in w for w in warnings)

    def test_cap_far_from_ic_warning(self, gate: PlacementReadinessGate) -> None:
        """Decoupling cap far from IC produces warning."""
        ir, net_cls = self._make_decoupling_ir(cap_x=10, ic_x=50)  # 40mm apart
        blockers, warnings = gate._check_decoupling_proximity(ir, None, None, net_cls)
        assert any("Decoupling" in w and "mm from" in w for w in warnings)

    def test_cap_no_associated_ic_warning(self, gate: PlacementReadinessGate) -> None:
        """Decoupling cap with no IC on shared power net produces warning."""
        # Cap on VCC but no IC
        ir = _make_pcb_ir([
            MockFootprint(
                properties={"Reference": "C1"},
                lib_id="Device:C",
                position=MockPos(X=10, Y=10),
                pads=[
                    MockPad(number="1", position=MockPos(), net_name="VCC"),
                ],
            ),
        ])
        net_cls = {"VCC": NetClassification.POWER}
        blockers, warnings = gate._check_decoupling_proximity(ir, None, None, net_cls)
        assert any("no associated IC" in w for w in warnings)


# ---------------------------------------------------------------------------
# Sub-check 5: Thermal spacing
# ---------------------------------------------------------------------------


class TestThermalSpacing:
    def test_regulator_isolated_ok(self, gate: PlacementReadinessGate) -> None:
        """Isolated thermal component produces no issues."""
        ir = _make_pcb_ir([
            MockFootprint(
                properties={"Reference": "U1"},
                lib_id="Regulator_Linear:LM7805_TO220",
                position=MockPos(X=10, Y=10),
                pads=[MockPad(position=MockPos())],
            ),
            MockFootprint(
                properties={"Reference": "R1"},
                lib_id="Device:R",
                position=MockPos(X=50, Y=50),
                pads=[MockPad(position=MockPos())],
            ),
        ])
        blockers, warnings = gate._check_thermal_spacing(ir, None, {})
        assert blockers == []
        assert warnings == []

    def test_regulator_too_close_warning(self, gate: PlacementReadinessGate) -> None:
        """Thermal component too close to another produces warning."""
        ir = _make_pcb_ir([
            MockFootprint(
                properties={"Reference": "U1"},
                lib_id="Regulator_Linear:LM7805_TO220",
                position=MockPos(X=50, Y=40),
                pads=[MockPad(position=MockPos())],
            ),
            MockFootprint(
                properties={"Reference": "R1"},
                lib_id="Device:R",
                position=MockPos(X=51, Y=40),  # 1mm away
                pads=[MockPad(position=MockPos())],
            ),
        ])
        blockers, warnings = gate._check_thermal_spacing(ir, None, {})
        assert any("Thermal" in w for w in warnings)

    def test_two_thermal_adjacent_blocker(self, gate: PlacementReadinessGate) -> None:
        """Two thermal components adjacent produces blocker."""
        ir = _make_pcb_ir([
            MockFootprint(
                properties={"Reference": "U1"},
                lib_id="Regulator_Linear:LM7805_TO220",
                position=MockPos(X=50, Y=40),
                pads=[MockPad(position=MockPos())],
            ),
            MockFootprint(
                properties={"Reference": "U2"},
                lib_id="Regulator_Linear:AMS1117_SOT-223",
                position=MockPos(X=51, Y=40),  # 1mm away
                pads=[MockPad(position=MockPos())],
            ),
        ])
        blockers, warnings = gate._check_thermal_spacing(ir, None, {})
        assert len(blockers) > 0


# ---------------------------------------------------------------------------
# Sub-check 6: Routability
# ---------------------------------------------------------------------------


class TestRoutability:
    def test_low_density_ok(self, gate: PlacementReadinessGate) -> None:
        """Low component density produces no warning."""
        ir = _make_pcb_ir([
            MockFootprint(
                properties={"Reference": "R1"}, lib_id="Device:R",
                position=MockPos(X=10, Y=10), pads=[MockPad(position=MockPos())],
            ),
        ], board_bounds=(0, 0, 100, 80))  # 1 tiny part in 8000mm^2
        blockers, warnings = gate._check_routability(ir, None)
        assert not any("density" in w for w in warnings)

    def test_high_density_warning(self, gate: PlacementReadinessGate) -> None:
        """High component density produces warning."""
        # Large parts filling >70% of board area.
        # Board = 100x80 = 8000mm², need >5600mm² of footprints.
        # Use 14x11 = 154 parts, each ~8x8mm = 64mm² → 9856mm²
        fps = []
        for i in range(14):
            for j in range(11):
                fps.append(MockFootprint(
                    properties={"Reference": f"R{i*11+j}"},
                    lib_id="Device:R",
                    position=MockPos(X=3 + i * 7, Y=3 + j * 7),
                    pads=[MockPad(position=MockPos(X=-4, Y=-4)), MockPad(position=MockPos(X=4, Y=4))],
                ))
        ir = _make_pcb_ir(fps, board_bounds=(0, 0, 100, 80))
        blockers, warnings = gate._check_routability(ir, None)
        assert any("density" in w for w in warnings)

    def test_blocked_channel_warning(self, gate: PlacementReadinessGate) -> None:
        """Narrow gap between components produces warning."""
        ir = _make_pcb_ir([
            MockFootprint(
                properties={"Reference": "U1"}, lib_id="IC:NE5532",
                position=MockPos(X=48, Y=40),
                pads=[MockPad(position=MockPos(X=-3, Y=-3)), MockPad(position=MockPos(X=3, Y=3))],
            ),
            MockFootprint(
                properties={"Reference": "U2"}, lib_id="IC:NE5532",
                position=MockPos(X=55, Y=40),  # gap = 55-3 - (48+3) = 1mm
                pads=[MockPad(position=MockPos(X=-3, Y=-3)), MockPad(position=MockPos(X=3, Y=3))],
            ),
        ])
        blockers, warnings = gate._check_routability(ir, None)
        assert any("Blocked channel" in w for w in warnings)


# ---------------------------------------------------------------------------
# Integration: Full gate
# ---------------------------------------------------------------------------


class TestGateIntegration:
    def test_good_placement_passes(self, gate: PlacementReadinessGate) -> None:
        """Well-placed board passes all checks."""
        ir = _make_pcb_ir([
            MockFootprint(
                properties={"Reference": "J1"}, lib_id="Connector:USB",
                position=MockPos(X=1, Y=40), pads=[],
            ),
            MockFootprint(
                properties={"Reference": "C1"}, lib_id="Device:C",
                position=MockPos(X=48, Y=38),
                pads=[MockPad(net_name="VCC"), MockPad(net_name="GND")],
            ),
            MockFootprint(
                properties={"Reference": "U1"}, lib_id="IC:NE5532",
                position=MockPos(X=50, Y=40),
                pads=[MockPad(net_name="VCC"), MockPad(net_name="GND"), MockPad(net_name="SIG")],
            ),
            MockFootprint(
                properties={"Reference": "R1"}, lib_id="Device:R",
                position=MockPos(X=60, Y=40),
                pads=[MockPad(net_name="SIG")],
            ),
        ], board_bounds=(0, 0, 100, 80))

        result = gate.run({
            "pcb_ir": ir,
            "schematic_ir": None,
            "constraints": None,
            "net_classifications": {
                "VCC": NetClassification.POWER,
                "GND": NetClassification.GROUND,
                "SIG": NetClassification.SIGNAL,
            },
        })
        assert result.pass_ is True

    def test_out_of_bounds_fails(self, gate: PlacementReadinessGate) -> None:
        """Board with out-of-bounds footprint fails."""
        ir = _make_pcb_ir([
            MockFootprint(
                properties={"Reference": "R1"}, lib_id="Device:R",
                position=MockPos(X=110, Y=40),  # outside
                pads=[MockPad(position=MockPos())],
            ),
        ])
        result = gate.run({
            "pcb_ir": ir,
            "schematic_ir": None,
            "constraints": None,
        })
        assert result.pass_ is False
        assert any("outside" in b for b in result.blockers)

    def test_no_pcb_ir_fails(self, gate: PlacementReadinessGate) -> None:
        """Missing pcb_ir in context fails immediately."""
        result = gate.run({})
        assert result.pass_ is False
        assert any("pcb_ir" in b for b in result.blockers)

    def test_analog_digital_overlap_warning(self, gate: PlacementReadinessGate) -> None:
        """Analog and digital sections in same area produce grouping warning."""
        ir = _make_pcb_ir([
            MockFootprint(
                properties={"Reference": "U1"}, lib_id="IC:NE5532",
                position=MockPos(X=48, Y=40),
                pads=[MockPad(net_name="AUDIO_IN"), MockPad(net_name="GND")],
            ),
            MockFootprint(
                properties={"Reference": "U2"}, lib_id="IC:STM32",
                position=MockPos(X=50, Y=40),
                pads=[MockPad(net_name="SPI_CLK"), MockPad(net_name="GND")],
            ),
        ])

        result = gate.run({
            "pcb_ir": ir,
            "schematic_ir": None,
            "constraints": None,
            "net_classifications": {
                "AUDIO_IN": NetClassification.ANALOG,
                "SPI_CLK": NetClassification.DIGITAL,
                "GND": NetClassification.GROUND,
            },
        })
        assert any("Analog and digital" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Gate registration
# ---------------------------------------------------------------------------


class TestGateRegistration:
    def test_gate_registered(self) -> None:
        """placement_readiness gate is registered for PLACEMENT -> ROUTING."""
        import volta.validation  # noqa: ensure gates registered
        from volta.validation.gate_runner import get_gate_runner

        runner = get_gate_runner()
        assert runner.get_gate("placement_readiness") is not None
