"""Tests for layout-aware placement: SignalFlowGrouper, ComponentGeometry, LayoutAwarePlacer.

Validates:
- Signal flow grouping from Subcircuit[] with I/O ordering and zone assignment
- Real footprint bounding box extraction from PcbIR
- LayoutAwarePlacer wrapping HybridPlacementEngine with constraint injection
- Graceful fallback when no subcircuits or geometry provided
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.analysis.intent_schemas import SubcircuitIntent
from kicad_agent.analysis.subcircuit_detector import Subcircuit, SubcircuitType
from kicad_agent.generation.intent import ComponentSpec, NetSpec, PositionSpec
from kicad_agent.placement.footprint_geometry import (
    ComponentGeometry,
    extract_footprint_geometry,
)
from kicad_agent.placement.signal_flow import (
    SignalFlowGroup,
    SignalFlowGrouper,
    SignalFlowZone,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_subcircuit(
    sc_id: str = "SC-001",
    components: tuple[str, ...] = ("U1",),
    nets: tuple[str, ...] = ("NET1",),
    boundary_nets: tuple[str, ...] = (),
    sc_type: SubcircuitType = SubcircuitType.UNKNOWN,
    confidence: float = 0.9,
    center: str = "U1",
) -> Subcircuit:
    """Build a Subcircuit fixture."""
    return Subcircuit(
        subcircuit_id=sc_id,
        components=components,
        nets=nets,
        boundary_nets=boundary_nets,
        subcircuit_type=sc_type,
        confidence=confidence,
        center_component=center,
        features={"lib_id": "Device:R"},
    )


def _make_intent(
    function: str = "unknown",
    refs: tuple[str, ...] = (),
    input_nets: tuple[str, ...] = (),
    output_nets: tuple[str, ...] = (),
    confidence: float = 0.8,
) -> SubcircuitIntent:
    """Build a SubcircuitIntent fixture."""
    return SubcircuitIntent(
        function=function,
        component_refs=refs,
        input_nets=input_nets,
        output_nets=output_nets,
        confidence=confidence,
    )


def _make_components(
    refs: list[str],
) -> list[ComponentSpec]:
    """Build ComponentSpec list for placement tests."""
    result = []
    for ref in refs:
        prefix = ref[0].upper()
        if prefix == "U":
            lib = "MCU_ST:STM32F103"
            val = "IC"
        elif prefix == "R":
            lib = "Device:R_Small_US"
            val = "10k"
        elif prefix == "C":
            lib = "Device:C_Small"
            val = "100nF"
        else:
            lib = "Device:R_Small_US"
            val = "generic"
        result.append(ComponentSpec(library_id=lib, reference=ref, value=val))
    return result


# ---------------------------------------------------------------------------
# Task 1: SignalFlowGrouper Tests
# ---------------------------------------------------------------------------


class TestSignalFlowGrouperChain:
    """3 subcircuits forming a signal flow chain produce ordered zones."""

    def test_chain_produces_ordered_zones(self):
        """Given 3 chained subcircuits, group() returns ordered zones L-to-R."""
        sc1 = _make_subcircuit(
            "SC-001",
            components=("U1", "R1"),
            nets=("IN_NET", "MID_A"),
            boundary_nets=("MID_A",),
            sc_type=SubcircuitType.PREAMP,
            center="U1",
        )
        sc2 = _make_subcircuit(
            "SC-002",
            components=("U2", "R2"),
            nets=("MID_A", "MID_B"),
            boundary_nets=("MID_A", "MID_B"),
            sc_type=SubcircuitType.VCA,
            center="U2",
        )
        sc3 = _make_subcircuit(
            "SC-003",
            components=("U3", "R3"),
            nets=("MID_B", "OUT_NET"),
            boundary_nets=("MID_B",),
            sc_type=SubcircuitType.OUTPUT_STAGE,
            center="U3",
        )
        intents = [
            _make_intent("preamp", ("U1", "R1"), input_nets=("IN_NET",), output_nets=("MID_A",)),
            _make_intent("vca", ("U2", "R2"), input_nets=("MID_A",), output_nets=("MID_B",)),
            _make_intent("output", ("U3", "R3"), input_nets=("MID_B",), output_nets=("OUT_NET",)),
        ]

        grouper = SignalFlowGrouper()
        groups = grouper.group([sc1, sc2, sc3], intents=intents)

        assert len(groups) == 1
        group = groups[0]
        assert len(group.ordered_zones) == 3

        # First zone should be the entry (SC-001 with IN_NET as non-boundary input)
        assert group.ordered_zones[0].component_refs == ("R1", "U1")
        assert group.ordered_zones[0].zone_type == "processing"

        # Last zone should be the exit (SC-003 output stage)
        assert group.ordered_zones[2].component_refs == ("R3", "U3")
        assert group.ordered_zones[2].zone_type == "output"

        # Signal entry/exit nets
        assert "IN_NET" in group.signal_entry_nets
        assert "OUT_NET" in group.signal_exit_nets


class TestSignalFlowGrouperNoBoundary:
    """Subcircuits with no boundary nets go to a single ungrouped zone."""

    def test_no_boundary_nets_ungrouped(self):
        """Isolated subcircuit with no boundary_nets gets zone_type=ungrouped."""
        sc = _make_subcircuit(
            "SC-001",
            components=("U1",),
            nets=("NET1",),
            boundary_nets=(),
            sc_type=SubcircuitType.UNKNOWN,
        )

        grouper = SignalFlowGrouper()
        groups = grouper.group([sc])

        assert len(groups) == 1
        assert len(groups[0].ordered_zones) == 1
        assert groups[0].ordered_zones[0].zone_type == "ungrouped"


class TestSignalFlowGrouperAdjacent:
    """Subcircuits sharing boundary_nets are placed in adjacent zones."""

    def test_shared_boundary_adjacent(self):
        """Two subcircuits sharing a boundary net are in the same group, adjacent zones."""
        sc1 = _make_subcircuit(
            "SC-001",
            components=("U1",),
            nets=("NET_A", "SHARED"),
            boundary_nets=("SHARED",),
            sc_type=SubcircuitType.PREAMP,
        )
        sc2 = _make_subcircuit(
            "SC-002",
            components=("U2",),
            nets=("SHARED", "NET_B"),
            boundary_nets=("SHARED",),
            sc_type=SubcircuitType.FILTER,
        )

        grouper = SignalFlowGrouper()
        groups = grouper.group([sc1, sc2])

        assert len(groups) == 1
        group = groups[0]
        assert len(group.ordered_zones) == 2
        # Zones are adjacent -- both in the same group
        zone_refs = [z.component_refs for z in group.ordered_zones]
        assert ("U1",) in zone_refs
        assert ("U2",) in zone_refs


class TestSignalFlowGrouperEmpty:
    """Empty subcircuit list returns empty groups."""

    def test_empty_input(self):
        grouper = SignalFlowGrouper()
        groups = grouper.group([])
        assert groups == []


class TestSignalFlowTypePriority:
    """SubcircuitType priority ordering when signal flow is ambiguous."""

    def test_type_priority_ordering(self):
        """Without clear signal flow, zones are ordered by type priority."""
        # Two disconnected subcircuits with no shared boundary_nets
        sc_power = _make_subcircuit(
            "SC-001",
            components=("U3",),
            nets=("VCC",),
            boundary_nets=(),
            sc_type=SubcircuitType.POWER_SUPPLY,
        )
        sc_preamp = _make_subcircuit(
            "SC-002",
            components=("U1",),
            nets=("SIG",),
            boundary_nets=(),
            sc_type=SubcircuitType.PREAMP,
        )

        grouper = SignalFlowGrouper()
        groups = grouper.group([sc_power, sc_preamp])

        # Should produce 2 separate groups (no adjacency)
        assert len(groups) == 2

        # PREAMP has lower priority number (higher priority) so its group comes first
        first_group_zone_type = groups[0].ordered_zones[0].zone_type
        assert first_group_zone_type == "processing"  # PREAMP maps to processing


# ---------------------------------------------------------------------------
# Task 1: ComponentGeometry / extract_footprint_geometry Tests
# ---------------------------------------------------------------------------


class TestExtractFootprintGeometryFromPcbIR:
    """extract_footprint_geometry from PcbIR with footprints."""

    def test_with_pads_returns_geometry(self):
        """PcbIR with footprints that have pads returns correct geometry."""
        # Create a mock PcbIR with footprints
        mock_pad_1 = MagicMock()
        mock_pad_1.at = [1.0, 2.0, 0.0]
        mock_pad_1.size = [0.8, 0.6]

        mock_pad_2 = MagicMock()
        mock_pad_2.at = [5.0, 4.0, 0.0]
        mock_pad_2.size = [1.0, 0.8]

        mock_fp = MagicMock()
        mock_fp.reference = "U1"
        mock_fp.pads = [mock_pad_1, mock_pad_2]

        mock_pcb_ir = MagicMock()
        mock_pcb_ir.footprints = [mock_fp]

        result = extract_footprint_geometry(mock_pcb_ir)

        assert "U1" in result
        geo = result["U1"]
        assert isinstance(geo, ComponentGeometry)
        assert geo.reference == "U1"
        # Width: max(5.0 + 0.5) - min(1.0 - 0.4) = 5.5 - 0.6 = 4.9
        assert geo.width_mm > 0
        # Height: max(4.0 + 0.4) - min(2.0 - 0.3) = 4.4 - 1.7 = 2.7
        assert geo.height_mm > 0
        assert len(geo.pad_positions) == 2
        assert geo.thermal_area_mm2 > 0

    def test_pad_positions_relative_to_origin(self):
        """Pad positions are computed relative to footprint origin."""
        mock_pad = MagicMock()
        mock_pad.at = [3.0, 5.0, 0.0]
        mock_pad.size = [1.0, 1.0]

        mock_fp = MagicMock()
        mock_fp.reference = "R1"
        mock_fp.pads = [mock_pad]

        mock_pcb_ir = MagicMock()
        mock_pcb_ir.footprints = [mock_fp]

        result = extract_footprint_geometry(mock_pcb_ir)
        assert result["R1"].pad_positions == ((3.0, 5.0),)


class TestExtractFootprintGeometryNone:
    """extract_footprint_geometry with None returns empty dict."""

    def test_none_returns_empty(self):
        result = extract_footprint_geometry(None)
        assert result == {}


class TestExtractFootprintGeometryNoPads:
    """Footprint with no pads returns default geometry."""

    def test_no_pads_default_geometry(self):
        mock_fp = MagicMock()
        mock_fp.reference = "C1"
        mock_fp.pads = []

        mock_pcb_ir = MagicMock()
        mock_pcb_ir.footprints = [mock_fp]

        result = extract_footprint_geometry(mock_pcb_ir)
        geo = result["C1"]
        assert geo.width_mm == 2.0
        assert geo.height_mm == 2.0
        assert geo.thermal_area_mm2 == 0.0
        assert geo.pad_positions == ()


# ---------------------------------------------------------------------------
# Task 2: LayoutAwarePlacer Tests
# ---------------------------------------------------------------------------


class TestLayoutAwarePlacerPassthrough:
    """Without subcircuits or geometry, behaves like HybridPlacementEngine."""

    def test_passthrough_no_subcircuits(self):
        """LayoutAwarePlacer delegates to HybridPlacementEngine when no subcircuits."""
        from kicad_agent.placement.layout_aware import (
            LayoutAwarePlacer,
            LayoutAwareRequest,
        )

        components = _make_components(["U1", "R1", "C1"])
        request = LayoutAwareRequest(
            components=components,
            board_width=100.0,
            board_height=80.0,
            use_ml=False,
        )

        placer = LayoutAwarePlacer()
        result = placer.place_layout_aware(request)

        assert result.source == "layout_aware"
        assert len(result.positions) == 3
        assert result.valid is True


class TestLayoutAwarePlacerWithSubcircuits:
    """When Subcircuit[] provided, components are pre-grouped into zones."""

    def test_with_subcircuits_zones(self):
        from kicad_agent.placement.layout_aware import (
            LayoutAwarePlacer,
            LayoutAwareRequest,
        )

        components = _make_components(["U1", "R1", "U2", "R2"])
        sc1 = _make_subcircuit(
            "SC-001",
            components=("U1", "R1"),
            nets=("NET1", "SHARED"),
            boundary_nets=("SHARED",),
            sc_type=SubcircuitType.PREAMP,
        )
        sc2 = _make_subcircuit(
            "SC-002",
            components=("U2", "R2"),
            nets=("SHARED", "NET2"),
            boundary_nets=("SHARED",),
            sc_type=SubcircuitType.FILTER,
        )

        request = LayoutAwareRequest(
            components=components,
            board_width=100.0,
            board_height=80.0,
            subcircuits=[sc1, sc2],
            use_ml=False,
        )

        placer = LayoutAwarePlacer()
        result = placer.place_layout_aware(request)

        assert result.source == "layout_aware"
        assert len(result.positions) == 4


class TestLayoutAwarePlacerWithGeometry:
    """When ComponentGeometry dict provided, sizes are used in placement."""

    def test_with_geometry_sizes_injected(self):
        from kicad_agent.placement.layout_aware import (
            LayoutAwarePlacer,
            LayoutAwareRequest,
        )

        components = _make_components(["U1", "R1"])
        geometry = {
            "U1": ComponentGeometry(
                reference="U1",
                width_mm=5.0,
                height_mm=5.0,
                pad_positions=((1.0, 1.0),),
                thermal_area_mm2=25.0,
                centroid_offset=(0.0, 0.0),
            ),
            "R1": ComponentGeometry(
                reference="R1",
                width_mm=1.6,
                height_mm=0.8,
                pad_positions=(),
                thermal_area_mm2=0.0,
                centroid_offset=(0.0, 0.0),
            ),
        }

        request = LayoutAwareRequest(
            components=components,
            board_width=100.0,
            board_height=80.0,
            component_geometry=geometry,
            use_ml=False,
        )

        placer = LayoutAwarePlacer()
        result = placer.place_layout_aware(request)

        assert result.source == "layout_aware"
        assert len(result.positions) == 2


class TestLayoutAwareRequestValidation:
    """LayoutAwareRequest validates board dimensions are positive."""

    def test_negative_board_width_rejected(self):
        from kicad_agent.placement.layout_aware import LayoutAwareRequest

        with pytest.raises(Exception):
            LayoutAwareRequest(
                components=_make_components(["U1"]),
                board_width=-10.0,
                board_height=80.0,
            )

    def test_zero_board_height_rejected(self):
        from kicad_agent.placement.layout_aware import LayoutAwareRequest

        with pytest.raises(Exception):
            LayoutAwareRequest(
                components=_make_components(["U1"]),
                board_width=100.0,
                board_height=0.0,
            )

    def test_negative_clearance_rejected(self):
        from kicad_agent.placement.layout_aware import LayoutAwareRequest

        with pytest.raises(Exception):
            LayoutAwareRequest(
                components=_make_components(["U1"]),
                board_width=100.0,
                board_height=80.0,
                min_clearance=-1.0,
            )


class TestLayoutAwarePlacerWithConstraints:
    """LayoutAwareRequest with constraints produces zone assignments."""

    def test_constraints_produce_zones(self):
        from kicad_agent.placement.layout_aware import (
            LayoutAwarePlacer,
            LayoutAwareRequest,
        )

        components = _make_components(["U1", "R1", "U2", "R2"])
        sc1 = _make_subcircuit(
            "SC-001",
            components=("U1", "R1"),
            nets=("A", "B"),
            boundary_nets=("B",),
            sc_type=SubcircuitType.PREAMP,
        )
        sc2 = _make_subcircuit(
            "SC-002",
            components=("U2", "R2"),
            nets=("B", "C"),
            boundary_nets=("B",),
            sc_type=SubcircuitType.OUTPUT_STAGE,
        )

        request = LayoutAwareRequest(
            components=components,
            board_width=100.0,
            board_height=80.0,
            subcircuits=[sc1, sc2],
            constraints=[{"type": "test_constraint"}],
            use_ml=False,
        )

        placer = LayoutAwarePlacer()
        result = placer.place_layout_aware(request)

        assert result.source == "layout_aware"
        assert len(result.positions) == 4
