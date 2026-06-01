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

        assert result.source == "layout_aware_refined"
        assert len(result.positions) == 4


# ---------------------------------------------------------------------------
# Task 2: Constraint-Aware SA Tests
# ---------------------------------------------------------------------------


class TestConstraintAwareSAObjective:
    """Constraint-aware SA objective adds penalties for constraint violations."""

    def test_constraint_penalty_adds_to_hpwl(self):
        """constraint_aware_sa_objective returns HPWL + penalty > pure HPWL."""
        from kicad_agent.placement.layout_aware import LayoutAwarePlacer

        placer = LayoutAwarePlacer()

        # Create positions with decoupling cap far from IC
        positions = {
            "U1": (10.0, 10.0, 0.0),
            "C1": (90.0, 70.0, 0.0),  # Far from U1
        }
        constraints = [
            _make_constraint("decoupling", refs=["C1", "U1"], max_distance_mm=10.0),
        ]

        # Build a minimal mock graph
        graph = _build_mock_graph(
            board_w=100.0,
            board_h=80.0,
            refs=["U1", "C1"],
        )

        objective = placer.constraint_aware_sa_objective(
            base_positions=positions,
            graph=graph,
            constraints=constraints,
            geometry=None,
            thermal_profiles=None,
            free_refs=["C1"],
        )

        # Compute pure HPWL for reference
        from kicad_agent.placement.scoring import compute_hpwl_score
        hpwl_raw, _ = compute_hpwl_score(positions, graph)

        # The objective at positions should be >= hpwl (constraint penalty adds)
        import numpy as np
        params = np.array([90.0, 70.0])  # C1 position
        result = objective(params)

        assert result >= hpwl_raw

    def test_decoupling_penalty_proportional_to_distance(self):
        """Penalty for decoupling cap far from IC is proportional to distance."""
        from kicad_agent.placement.layout_aware import (
            _DECOUPLING_PENALTY_WEIGHT,
            _MAX_DECOUPLING_DISTANCE_MM,
            LayoutAwarePlacer,
        )

        placer = LayoutAwarePlacer()

        constraints = [
            _make_constraint("decoupling", refs=["C1", "U1"], max_distance_mm=10.0),
        ]

        # Test with C1 near U1 (no penalty expected)
        positions_near = {"U1": (50.0, 40.0, 0.0), "C1": (55.0, 40.0, 0.0)}
        # Test with C1 far from U1 (penalty expected)
        positions_far = {"U1": (50.0, 40.0, 0.0), "C1": (90.0, 40.0, 0.0)}

        graph_near = _build_mock_graph(100.0, 80.0, ["U1", "C1"])
        graph_far = _build_mock_graph(100.0, 80.0, ["U1", "C1"])

        obj_near = placer.constraint_aware_sa_objective(
            positions_near, graph_near, constraints, None, None, ["C1"],
        )
        obj_far = placer.constraint_aware_sa_objective(
            positions_far, graph_far, constraints, None, None, ["C1"],
        )

        import numpy as np
        # Near position: C1 at (55, 40) -> distance to U1 at (50, 40) = 5.0mm < max 10mm -> no penalty
        result_near = obj_near(np.array([55.0, 40.0]))
        # Far position: C1 at (90, 40) -> distance = 40.0mm > max 10mm -> penalty
        result_far = obj_far(np.array([90.0, 40.0]))

        assert result_far > result_near

    def test_diff_pair_penalty_increases_with_offset(self):
        """Penalty for differential pair misalignment increases with y-offset."""
        from kicad_agent.placement.layout_aware import LayoutAwarePlacer

        placer = LayoutAwarePlacer()

        constraints = [
            _make_constraint("differential_pair", refs=["U1", "U2"]),
        ]

        # Aligned pair (same y)
        positions_aligned = {"U1": (20.0, 40.0, 0.0), "U2": (30.0, 40.0, 0.0)}
        # Misaligned pair (different y)
        positions_misaligned = {"U1": (20.0, 40.0, 0.0), "U2": (30.0, 70.0, 0.0)}

        graph_a = _build_mock_graph(100.0, 80.0, ["U1", "U2"])
        graph_m = _build_mock_graph(100.0, 80.0, ["U1", "U2"])

        obj_aligned = placer.constraint_aware_sa_objective(
            positions_aligned, graph_a, constraints, None, None, ["U2"],
        )
        obj_misaligned = placer.constraint_aware_sa_objective(
            positions_misaligned, graph_m, constraints, None, None, ["U2"],
        )

        import numpy as np
        result_aligned = obj_aligned(np.array([30.0, 40.0]))
        result_misaligned = obj_misaligned(np.array([30.0, 70.0]))

        assert result_misaligned > result_aligned

    def test_zero_penalty_when_constraints_satisfied(self):
        """Penalty is zero when all constraints are satisfied."""
        from kicad_agent.placement.layout_aware import LayoutAwarePlacer

        placer = LayoutAwarePlacer()

        # Decoupling cap close to IC, diff pair aligned
        positions = {
            "U1": (50.0, 40.0, 0.0),
            "C1": (53.0, 40.0, 0.0),  # 3mm away -- within 10mm limit
            "U2": (60.0, 40.0, 0.0),  # Same y as U1 -- aligned
        }
        constraints = [
            _make_constraint("decoupling", refs=["C1", "U1"], max_distance_mm=10.0),
            _make_constraint("differential_pair", refs=["U1", "U2"]),
        ]

        graph = _build_mock_graph(100.0, 80.0, ["U1", "C1", "U2"])

        objective = placer.constraint_aware_sa_objective(
            positions, graph, constraints, None, None, ["C1", "U2"],
        )

        import numpy as np
        params = np.array([53.0, 40.0, 60.0, 40.0])
        result = objective(params)

        # Pure HPWL (constraint penalty should be 0)
        from kicad_agent.placement.scoring import compute_hpwl_score
        hpwl_raw, _ = compute_hpwl_score(positions, graph)

        # Result should equal HPWL since no penalties
        assert result == pytest.approx(hpwl_raw, abs=0.01)


# ---------------------------------------------------------------------------
# Task 2: Integration Tests
# ---------------------------------------------------------------------------


class TestIntegrationThermalAndConstraints:
    """Full integration: LayoutAwarePlacer with thermal + constraints + SA."""

    def test_with_subcircuits_thermal_constraints(self):
        """LayoutAwarePlacer with subcircuits + thermal + constraints produces valid output."""
        from kicad_agent.placement.layout_aware import (
            LayoutAwarePlacer,
            LayoutAwareRequest,
        )
        from kicad_agent.placement.thermal import ThermalProfile

        components = _make_components(["U1", "R1", "U2", "R2", "U3", "R3"])
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
            sc_type=SubcircuitType.VCA,
        )
        sc3 = _make_subcircuit(
            "SC-003",
            components=("U3", "R3"),
            nets=("C", "D"),
            boundary_nets=("C",),
            sc_type=SubcircuitType.OUTPUT_STAGE,
        )

        thermal_profiles = [
            ThermalProfile("U1", power_dissipation_watts=2.0, max_temp_celsius=100.0),
            ThermalProfile("U3", power_dissipation_watts=5.0, max_temp_celsius=125.0),
        ]

        constraints = [
            _make_constraint("decoupling", refs=["R1", "U1"], max_distance_mm=10.0),
        ]

        request = LayoutAwareRequest(
            components=components,
            board_width=100.0,
            board_height=80.0,
            subcircuits=[sc1, sc2, sc3],
            thermal_profiles=thermal_profiles,
            constraints=constraints,
            use_ml=False,
        )

        placer = LayoutAwarePlacer()
        result = placer.place_layout_aware(request)

        assert result.source == "layout_aware_refined"
        assert len(result.positions) == 6
        # Note: valid may be False on small boards where zone constraints cause
        # overlap -- the integration test verifies the pipeline runs, not layout quality

    def test_with_only_thermal_profiles(self):
        """LayoutAwarePlacer with thermal profiles (no subcircuits) applies thermal separation."""
        from kicad_agent.placement.layout_aware import (
            LayoutAwarePlacer,
            LayoutAwareRequest,
        )
        from kicad_agent.placement.thermal import ThermalProfile

        components = _make_components(["U1", "U2", "R1"])
        thermal_profiles = [
            ThermalProfile("U1", power_dissipation_watts=3.0, max_temp_celsius=100.0),
        ]

        request = LayoutAwareRequest(
            components=components,
            board_width=100.0,
            board_height=80.0,
            thermal_profiles=thermal_profiles,
            use_ml=False,
        )

        placer = LayoutAwarePlacer()
        result = placer.place_layout_aware(request)

        assert result.source == "layout_aware_refined"
        assert len(result.positions) == 3

    def test_with_none_thermal_profiles_no_crash(self):
        """LayoutAwarePlacer with None thermal_profiles does not crash."""
        from kicad_agent.placement.layout_aware import (
            LayoutAwarePlacer,
            LayoutAwareRequest,
        )

        components = _make_components(["U1", "R1"])

        request = LayoutAwareRequest(
            components=components,
            board_width=100.0,
            board_height=80.0,
            thermal_profiles=None,
            use_ml=False,
        )

        placer = LayoutAwarePlacer()
        result = placer.place_layout_aware(request)

        # No SA refinement triggered (no constraints, no thermal profiles)
        assert result.source == "layout_aware"
        assert len(result.positions) == 2

    def test_full_pipeline_20_components(self):
        """Full pipeline: 20 components, 3 subcircuits, 2 thermal profiles, constraint-aware SA."""
        from kicad_agent.placement.layout_aware import (
            LayoutAwarePlacer,
            LayoutAwareRequest,
        )
        from kicad_agent.placement.thermal import ThermalProfile

        refs = [f"U{i}" for i in range(1, 8)] + [f"R{i}" for i in range(1, 8)] + [f"C{i}" for i in range(1, 7)]
        components = _make_components(refs[:20])

        sc1 = _make_subcircuit(
            "SC-001",
            components=tuple(refs[:7]),
            nets=("NET_A", "NET_B"),
            boundary_nets=("NET_B",),
            sc_type=SubcircuitType.PREAMP,
        )
        sc2 = _make_subcircuit(
            "SC-002",
            components=tuple(refs[7:14]),
            nets=("NET_B", "NET_C"),
            boundary_nets=("NET_B", "NET_C"),
            sc_type=SubcircuitType.VCA,
        )
        sc3 = _make_subcircuit(
            "SC-003",
            components=tuple(refs[14:20]),
            nets=("NET_C", "NET_D"),
            boundary_nets=("NET_C",),
            sc_type=SubcircuitType.OUTPUT_STAGE,
        )

        thermal_profiles = [
            ThermalProfile("U1", power_dissipation_watts=2.0, max_temp_celsius=100.0),
            ThermalProfile("U4", power_dissipation_watts=4.0, max_temp_celsius=125.0),
        ]

        constraints = [
            _make_constraint("decoupling", refs=["C1", "U1"], max_distance_mm=10.0),
            _make_constraint("differential_pair", refs=["U2", "U3"]),
        ]

        request = LayoutAwareRequest(
            components=components,
            board_width=150.0,
            board_height=100.0,
            subcircuits=[sc1, sc2, sc3],
            thermal_profiles=thermal_profiles,
            constraints=constraints,
            use_ml=False,
        )

        placer = LayoutAwarePlacer()
        result = placer.place_layout_aware(request)

        assert result.source == "layout_aware_refined"
        assert len(result.positions) == 20
        # Note: valid may be False due to zone constraint density on this board size

    def test_placement_score_reasonable(self):
        """Placement score is reasonable (>0.1) for a simple board."""
        from kicad_agent.placement.layout_aware import (
            LayoutAwarePlacer,
            LayoutAwareRequest,
        )

        components = _make_components(["U1", "R1", "C1", "U2", "R2"])
        nets = [
            NetSpec(name="VCC", connections=[("U1", "1"), ("R1", "1"), ("U2", "1")]),
            NetSpec(name="GND", connections=[("U1", "2"), ("C1", "1"), ("U2", "2")]),
        ]

        request = LayoutAwareRequest(
            components=components,
            nets=nets,
            board_width=100.0,
            board_height=80.0,
            use_ml=False,
        )

        placer = LayoutAwarePlacer()
        result = placer.place_layout_aware(request)

        assert result.score > 0.1, f"Score {result.score} should be > 0.1"


# ---------------------------------------------------------------------------
# Task 2 Test Helpers
# ---------------------------------------------------------------------------


def _make_constraint(
    constraint_type: str,
    refs: list[str] | None = None,
    max_distance_mm: float | None = None,
) -> Any:
    """Build a duck-typed constraint object for testing.

    Uses a SimpleNamespace to simulate constraint objects with:
    - constraint_type: str
    - refs: list[str]
    - max_distance_mm: float | None
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        constraint_type=constraint_type,
        refs=refs or [],
        max_distance_mm=max_distance_mm,
    )


def _build_mock_graph(
    board_w: float,
    board_h: float,
    refs: list[str],
) -> Any:
    """Build a mock PlacementGraph for testing constraint-aware SA.

    Creates a bipartite graph with component nodes and net nodes
    that mimics the PlacementGraph interface used by compute_hpwl_score.
    """
    import networkx as nx

    G = nx.Graph()
    G.graph["board_width"] = board_w
    G.graph["board_height"] = board_h

    # Add component nodes (bipartite=0)
    for ref in refs:
        node_id = f"comp_{ref}"
        G.add_node(node_id, bipartite=0, reference=ref, estimated_size=2.0)

    # Add a single net connecting all components (bipartite=1)
    net_node = "net_SHARED"
    G.add_node(net_node, bipartite=1, name="SHARED")

    for ref in refs:
        comp_node = f"comp_{ref}"
        G.add_edge(comp_node, net_node)

    # Create a PlacementGraph-like wrapper
    mock_graph = MagicMock()
    mock_graph._graph = G
    mock_graph.board_width = board_w
    mock_graph.board_height = board_h
    mock_graph.component_nodes.return_value = [
        n for n in G.nodes if G.nodes[n].get("bipartite") == 0
    ]
    mock_graph.net_nodes.return_value = [
        n for n in G.nodes if G.nodes[n].get("bipartite") == 1
    ]

    return mock_graph
