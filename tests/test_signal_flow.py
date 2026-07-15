"""Tests for signal flow grouping (signal_flow.py).

Covers:
  - SignalFlowGrouper.group with empty subcircuits
  - Single subcircuit handling
  - Multiple disconnected subcircuits (separate groups)
  - Connected subcircuits via shared boundary nets
  - Zone ordering by type priority fallback
  - Data class immutability and construction
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from volta.analysis.subcircuit_detector import Subcircuit, SubcircuitType
from volta.placement.signal_flow import (
    SignalFlowGroup,
    SignalFlowGrouper,
    SignalFlowZone,
)


def _make_subcircuit(
    sc_id: str,
    components: tuple[str, ...],
    nets: tuple[str, ...],
    boundary_nets: tuple[str, ...],
    sc_type: SubcircuitType = SubcircuitType.UNKNOWN,
) -> Subcircuit:
    """Create a Subcircuit for testing without extra dependencies."""
    # Subcircuit is a dataclass, not frozen, so direct construction works.
    return Subcircuit(
        subcircuit_id=sc_id,
        components=components,
        nets=nets,
        boundary_nets=boundary_nets,
        subcircuit_type=sc_type,
        confidence=0.8,
        center_component=components[0] if components else "",
        features={},
    )


class TestSignalFlowGrouperEmpty:
    """Edge case: empty or minimal input to group()."""

    def test_empty_subcircuits_returns_empty(self) -> None:
        grouper = SignalFlowGrouper()
        result = grouper.group([])
        assert result == []

    def test_none_intents_returns_groups(self) -> None:
        """intents=None should still produce groups from subcircuits."""
        grouper = SignalFlowGrouper()
        sc = _make_subcircuit("SC-001", ("U1",), ("NET1",), ())
        result = grouper.group([sc], intents=None)
        assert len(result) == 1


class TestSignalFlowGrouperSingleSubcircuit:
    """Single subcircuit produces one group with one zone."""

    def test_single_unknown_subcircuit(self) -> None:
        grouper = SignalFlowGrouper()
        sc = _make_subcircuit("SC-001", ("R1", "R2"), ("NET1",), ())
        result = grouper.group([sc])

        assert len(result) == 1
        group = result[0]
        assert group.group_id == "GRP-001"
        assert len(group.ordered_zones) == 1
        zone = group.ordered_zones[0]
        assert zone.zone_id == "SC-001"
        assert zone.zone_type == "ungrouped"
        assert zone.priority == 40

    def test_single_power_supply(self) -> None:
        grouper = SignalFlowGrouper()
        sc = _make_subcircuit(
            "SC-PWR", ("U5",), ("VCC",), (),
            sc_type=SubcircuitType.POWER_SUPPLY,
        )
        result = grouper.group([sc])
        zone = result[0].ordered_zones[0]
        assert zone.zone_type == "power"
        assert zone.priority == 30

    def test_single_output_stage(self) -> None:
        grouper = SignalFlowGrouper()
        sc = _make_subcircuit(
            "SC-OUT", ("U3",), ("OUT_NET",), (),
            sc_type=SubcircuitType.OUTPUT_STAGE,
        )
        result = grouper.group([sc])
        zone = result[0].ordered_zones[0]
        assert zone.zone_type == "output"
        assert zone.priority == 20

    def test_single_filter(self) -> None:
        grouper = SignalFlowGrouper()
        sc = _make_subcircuit(
            "SC-FILT", ("R1", "C1"), ("FILT_NET",), (),
            sc_type=SubcircuitType.FILTER,
        )
        result = grouper.group([sc])
        zone = result[0].ordered_zones[0]
        assert zone.zone_type == "processing"
        assert zone.priority == 10


class TestSignalFlowGrouperDisconnected:
    """Disconnected subcircuits produce separate groups."""

    def test_two_disconnected_subcircuits(self) -> None:
        grouper = SignalFlowGrouper()
        sc1 = _make_subcircuit("SC-001", ("U1",), ("NET1",), ())
        sc2 = _make_subcircuit("SC-002", ("U2",), ("NET2",), ())
        result = grouper.group([sc1, sc2])

        assert len(result) == 2
        ids = {g.group_id for g in result}
        assert "GRP-001" in ids
        assert "GRP-002" in ids

    def test_disconnected_sorted_by_priority(self) -> None:
        grouper = SignalFlowGrouper()
        sc_pwr = _make_subcircuit(
            "SC-PWR", ("U5",), ("VCC",), (),
            sc_type=SubcircuitType.POWER_SUPPLY,
        )
        sc_filt = _make_subcircuit(
            "SC-FILT", ("R1", "C1"), ("NET1",), (),
            sc_type=SubcircuitType.FILTER,
        )
        result = grouper.group([sc_pwr, sc_filt])

        # Filter (priority 10) should come before Power (priority 30)
        assert result[0].ordered_zones[0].zone_type == "processing"
        assert result[1].ordered_zones[0].zone_type == "power"


class TestSignalFlowGrouperConnected:
    """Subcircuits connected via shared boundary nets form one group."""

    def test_shared_boundary_net_forms_group(self) -> None:
        grouper = SignalFlowGrouper()
        sc1 = _make_subcircuit(
            "SC-001", ("U1",), ("NET1", "BRIDGE"), ("BRIDGE",),
            sc_type=SubcircuitType.PREAMP,
        )
        sc2 = _make_subcircuit(
            "SC-002", ("U2",), ("NET2", "BRIDGE"), ("BRIDGE",),
            sc_type=SubcircuitType.OUTPUT_STAGE,
        )
        result = grouper.group([sc1, sc2])

        assert len(result) == 1
        group = result[0]
        assert len(group.ordered_zones) == 2


class TestSignalFlowGrouperOrdering:
    """Zone ordering within a connected group."""

    def test_type_priority_ordering_fallback(self) -> None:
        """Without intents, zones should be ordered by type priority."""
        grouper = SignalFlowGrouper()
        sc_out = _make_subcircuit(
            "SC-OUT", ("U3",), ("NET_OUT",), ("BRIDGE",),
            sc_type=SubcircuitType.OUTPUT_STAGE,
        )
        sc_filt = _make_subcircuit(
            "SC-FILT", ("R1",), ("NET_FILT",), ("BRIDGE",),
            sc_type=SubcircuitType.FILTER,
        )
        result = grouper.group([sc_out, sc_filt])
        group = result[0]

        # Filter (priority 10) should be before Output (priority 20)
        assert group.ordered_zones[0].zone_type == "processing"
        assert group.ordered_zones[1].zone_type == "output"


class TestSignalFlowZoneImmutable:
    """SignalFlowZone should be frozen/immutable."""

    def test_zone_frozen(self) -> None:
        zone = SignalFlowZone(
            zone_id="Z1",
            component_refs=("U1",),
            nets=("NET1",),
            zone_type="processing",
            priority=10,
        )
        with pytest.raises(AttributeError):
            zone.priority = 99  # type: ignore[misc]


class TestSignalFlowGroupImmutable:
    """SignalFlowGroup should be frozen/immutable."""

    def test_group_frozen(self) -> None:
        group = SignalFlowGroup(
            group_id="G1",
            ordered_zones=(),
            signal_entry_nets=(),
            signal_exit_nets=(),
        )
        with pytest.raises(AttributeError):
            group.group_id = "changed"  # type: ignore[misc]


class TestSignalFlowGrouperThreeSubcircuits:
    """Three subcircuits with two connected and one isolated."""

    def test_mixed_connectivity(self) -> None:
        grouper = SignalFlowGrouper()
        sc1 = _make_subcircuit(
            "SC-001", ("U1",), ("N1", "BR1"), ("BR1",),
            sc_type=SubcircuitType.PREAMP,
        )
        sc2 = _make_subcircuit(
            "SC-002", ("U2",), ("N2", "BR1"), ("BR1",),
            sc_type=SubcircuitType.FILTER,
        )
        sc3 = _make_subcircuit(
            "SC-003", ("U3",), ("N3",), (),
            sc_type=SubcircuitType.POWER_SUPPLY,
        )
        result = grouper.group([sc1, sc2, sc3])

        # SC-001 and SC-002 share BR1 -> one group; SC-003 is separate
        assert len(result) == 2
        group_sizes = [len(g.ordered_zones) for g in result]
        assert sorted(group_sizes) == [1, 2]
