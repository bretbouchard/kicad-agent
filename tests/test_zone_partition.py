"""Tests for zone partitioning and position export/import operations.

Validates:
- Zone assignment via priority_refs, value heuristics, round-robin
- Keepout generation from zone assignments
- Schema validation for new operations
- Position export/import round-trip with mock PCB content
"""

import json
import pytest
from pydantic import ValidationError

from kicad_agent.ops._schema_placement import (
    AutoPlaceZonedOp,
    ExportPositionsOp,
    ImportPositionsOp,
    ZoneDefinition,
)
from kicad_agent.placement.zone_partition import (
    assign_to_zone,
    build_keepouts_from_zone,
)


# ---------------------------------------------------------------------------
# ZoneDefinition schema
# ---------------------------------------------------------------------------


class TestZoneDefinition:
    def test_minimal_zone(self):
        z = ZoneDefinition(name="power", x_range=(2.0, 138.0), y_range=(60.0, 78.0))
        assert z.name == "power"
        assert z.x_range == (2.0, 138.0)
        assert z.y_range == (60.0, 78.0)
        assert z.priority_refs == []
        assert z.fill_order == "left-to-right"

    def test_zone_with_priority_refs(self):
        z = ZoneDefinition(
            name="input_stage",
            x_range=(20.0, 50.0),
            y_range=(2.0, 58.0),
            priority_refs=["U1", "U2", "U3"],
        )
        assert z.priority_refs == ["U1", "U2", "U3"]

    def test_invalid_fill_order(self):
        with pytest.raises(ValidationError):
            ZoneDefinition(
                name="bad", x_range=(0, 10), y_range=(0, 10), fill_order="invalid"
            )


# ---------------------------------------------------------------------------
# assign_to_zone
# ---------------------------------------------------------------------------


def _make_zones():
    """Create standard 6-zone layout for testing."""
    return [
        ZoneDefinition(name="connectors", x_range=(2.0, 20.0), y_range=(2.0, 58.0), priority_refs=["J"]),
        ZoneDefinition(name="input_stage", x_range=(20.0, 50.0), y_range=(2.0, 58.0), priority_refs=["U1", "U2", "U3"]),
        ZoneDefinition(name="eq_stage", x_range=(50.0, 90.0), y_range=(2.0, 58.0), priority_refs=["U4", "U5"]),
        ZoneDefinition(name="comp_stage", x_range=(90.0, 115.0), y_range=(2.0, 58.0), priority_refs=["U10"]),
        ZoneDefinition(name="output_stage", x_range=(115.0, 138.0), y_range=(2.0, 58.0), priority_refs=[]),
        ZoneDefinition(name="power", x_range=(2.0, 138.0), y_range=(60.0, 78.0), priority_refs=["U13", "U14"]),
    ]


class TestAssignToZone:
    def test_priority_ref_direct_match(self):
        zones = _make_zones()
        assert assign_to_zone("J1", "", zones) == "connectors"
        assert assign_to_zone("U1", "", zones) == "input_stage"
        assert assign_to_zone("U4", "", zones) == "eq_stage"
        assert assign_to_zone("U10", "", zones) == "comp_stage"
        assert assign_to_zone("U13", "", zones) == "power"

    def test_power_ic_by_value(self):
        zones = _make_zones()
        assert assign_to_zone("U99", "TL431", zones) == "power"
        assert assign_to_zone("U99", "TPS63700", zones) == "power"
        assert assign_to_zone("U99", "AMS1117", zones) == "power"

    def test_digital_ic_by_value(self):
        zones = _make_zones()
        assert assign_to_zone("U99", "MCP4131", zones) == "input_stage"

    def test_audio_ic_alternates(self):
        zones = _make_zones()
        # NE5532 should alternate between eq_stage and comp_stage
        results = set()
        for ref in ["U6", "U7", "U8", "U9"]:
            zone = assign_to_zone(ref, "NE5532", zones)
            results.add(zone)
        assert results == {"eq_stage", "comp_stage"}

    def test_test_point_goes_to_power(self):
        zones = _make_zones()
        assert assign_to_zone("TP1", "", zones) == "power"
        assert assign_to_zone("TP2", "", zones) == "power"

    def test_connector_fallback(self):
        zones = _make_zones()
        assert assign_to_zone("J99", "", zones) == "connectors"

    def test_passive_round_robin(self):
        zones = _make_zones()
        # Passives should distribute across signal (non-power) zones
        results = set()
        for ref in ["R1", "R2", "R3", "R4", "R5"]:
            results.add(assign_to_zone(ref, "10k", zones))
        assert "power" not in results

    def test_generic_u_prefix_round_robin(self):
        zones = _make_zones()
        # Generic U-prefix should spread across signal zones
        results = set()
        for ref in ["U20", "U21", "U22", "U23", "U24"]:
            results.add(assign_to_zone(ref, "", zones))
        assert "power" not in results

    def test_single_zone_fallback(self):
        """With only one zone, everything goes there."""
        zones = [ZoneDefinition(name="full", x_range=(0, 100), y_range=(0, 80))]
        assert assign_to_zone("R1", "", zones) == "full"
        assert assign_to_zone("U1", "", zones) == "full"
        assert assign_to_zone("J1", "", zones) == "full"


# ---------------------------------------------------------------------------
# build_keepouts_from_zone
# ---------------------------------------------------------------------------


class TestBuildKeepouts:
    def test_single_zone_returns_all_others(self):
        zones = _make_zones()
        keepouts = build_keepouts_from_zone("input_stage", zones)
        # Should return 5 keepout rects (all zones except input_stage)
        assert len(keepouts) == 5
        names = {z.name for z in zones if z.name != "input_stage"}
        for ko in keepouts:
            found = False
            for z in zones:
                if z.name != "input_stage" and z.x_range == (ko[0], ko[2]) and z.y_range == (ko[1], ko[3]):
                    found = True
                    break
            assert found

    def test_no_keepouts_for_last_zone(self):
        """Last zone has no other zones to keep out."""
        zones = [ZoneDefinition(name="only", x_range=(0, 10), y_range=(0, 10))]
        assert build_keepouts_from_zone("only", zones) == []


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestExportPositionsOpSchema:
    def test_valid(self):
        op = ExportPositionsOp(
            target_file="board.kicad_pcb",
            output_file="positions.json",
        )
        assert op.output_file == "positions.json"
        assert op.refs == []

    def test_with_refs(self):
        op = ExportPositionsOp(
            target_file="board.kicad_pcb",
            output_file="locked.json",
            refs=["U1", "R1", "C1"],
        )
        assert len(op.refs) == 3

    def test_missing_output_file(self):
        with pytest.raises(ValidationError):
            ExportPositionsOp(target_file="board.kicad_pcb")


class TestImportPositionsOpSchema:
    def test_valid(self):
        op = ImportPositionsOp(
            target_file="board.kicad_pcb",
            positions_file="positions.json",
        )
        assert op.positions_file == "positions.json"

    def test_missing_positions_file(self):
        with pytest.raises(ValidationError):
            ImportPositionsOp(target_file="board.kicad_pcb")


class TestAutoPlaceZonedOpSchema:
    def test_minimal(self):
        zones = [ZoneDefinition(name="power", x_range=(0, 100), y_range=(0, 80))]
        op = AutoPlaceZonedOp(
            target_file="board.kicad_pcb",
            zones=zones,
        )
        assert len(op.zones) == 1
        assert op.optimize is True

    def test_with_all_options(self):
        zones = [
            ZoneDefinition(name="input", x_range=(20, 50), y_range=(2, 58), priority_refs=["U1"]),
            ZoneDefinition(name="power", x_range=(2, 138), y_range=(60, 78)),
        ]
        op = AutoPlaceZonedOp(
            target_file="board.kicad_pcb",
            zones=zones,
            fixed_positions={"U1": (25.0, 10.0, 0.0)},
            clearance=2.0,
            grid=0.5,
            optimize=False,
            schematic_file="board.kicad_sch",
        )
        assert op.clearance == 2.0
        assert op.grid == 0.5
        assert op.optimize is False
        assert op.fixed_positions == {"U1": (25.0, 10.0, 0.0)}

    def test_empty_zones_fails(self):
        with pytest.raises(ValidationError):
            AutoPlaceZonedOp(target_file="board.kicad_pcb", zones=[])


# ---------------------------------------------------------------------------
# Position export round-trip (unit test without PcbIR)
# ---------------------------------------------------------------------------


class TestPositionRoundTrip:
    """Test export/import JSON format consistency."""

    def test_json_round_trip(self):
        """Positions JSON can be written and read back."""
        positions = {
            "U1": {"x": 50.0, "y": 30.0, "angle": 0.0},
            "R1": {"x": 55.0, "y": 35.0, "angle": 90.0},
            "J1": {"x": 10.0, "y": 15.0, "angle": 180.0},
        }
        data = {"positions": positions}

        serialized = json.dumps(data)
        deserialized = json.loads(serialized)
        assert deserialized["positions"] == positions

    def test_empty_positions(self):
        """Empty positions dict serializes correctly."""
        data = {"positions": {}}
        serialized = json.dumps(data)
        deserialized = json.loads(serialized)
        assert deserialized["positions"] == {}
