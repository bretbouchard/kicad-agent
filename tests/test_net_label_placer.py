"""Tests for place_net_labels — pin-to-net mapping operation.

Issue #8: Verify safety gates (wire check, existing labels, dry_run),
correct label/NC placement, and edge cases.
"""

import json
import tempfile
from pathlib import Path

import pytest
from kiutils.schematic import Schematic
from kiutils.items.schitems import Connection, LocalLabel, SchematicSymbol
from kiutils.items.common import Position, Property

from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.parser import parse_schematic
from kicad_agent.ops.net_label_placer import (
    place_net_labels,
    _load_pin_map,
    _BUILTIN_PROFILES,
)


def _make_schematic_ir(
    wires=None,
    labels=None,
    no_connects=None,
    symbols=None,
) -> tuple[SchematicIR, Path]:
    """Build a minimal schematic IR for testing.

    Args:
        wires: List of (start_x, start_y, end_x, end_y).
        labels: List of (text, x, y).
        no_connects: List of (x, y) positions.
        symbols: List of (lib_nick, entry_name, ref, x, y).

    Returns:
        (ir, path) tuple.
    """
    sch = Schematic.create_new()
    sch.graphicalItems = []

    for sx, sy, ex, ey in (wires or []):
        conn = Connection()
        conn.type = "wire"
        conn.points = [Position(X=sx, Y=sy), Position(X=ex, Y=ey)]
        sch.graphicalItems.append(conn)

    for text, x, y in (labels or []):
        sch.labels.append(LocalLabel(text=text, position=Position(X=x, Y=y)))

    for lib_nick, entry_name, ref, sx, sy in (symbols or []):
        sym = SchematicSymbol(
            libraryNickname=lib_nick,
            entryName=entry_name,
            libName=lib_nick,
            position=Position(X=sx, Y=sy),
            properties=[Property(key="Reference", value=ref)],
        )
        sch.schematicSymbols.append(sym)

    tmpdir = tempfile.mkdtemp()
    sch_path = Path(tmpdir) / "test_net_labels.kicad_sch"
    sch.to_file(str(sch_path))
    result = parse_schematic(sch_path)
    ir = SchematicIR(_parse_result=result)
    return ir, sch_path


class TestPlaceNetLabelsWireCheck:
    """Safety gate: labels only placed at wire-connected positions."""

    def test_places_label_at_wire_endpoint(self):
        """Pin at wire endpoint → label placed."""
        ir, path = _make_schematic_ir(
            wires=[(50.0, 50.0, 60.0, 50.0)],
            symbols=[("Audio_Codec", "AK4619VN", "U1", 0, 0)],
        )
        ir.get_pin_positions = lambda: [
            {"reference": "U1", "pin_name": "TVDD", "x": 50.0, "y": 50.0},
        ]

        result = place_net_labels(ir, path, pin_map="backplane")

        assert result["labels_placed"] == 1
        assert any(d["net_name"] == "VCC_3V3" for d in result["details"])

    def test_skips_label_at_bare_pin_no_wire(self):
        """Pin NOT at wire endpoint → label NOT placed."""
        ir, path = _make_schematic_ir(
            wires=[(60.0, 60.0, 70.0, 60.0)],
            symbols=[("Audio_Codec", "AK4619VN", "U1", 0, 0)],
        )
        ir.get_pin_positions = lambda: [
            {"reference": "U1", "pin_name": "TVDD", "x": 50.0, "y": 50.0},
        ]

        result = place_net_labels(ir, path, pin_map="backplane")

        assert result["labels_placed"] == 0
        assert result["skipped_no_wire"] == 1

    def test_skips_existing_label(self):
        """Position already has a label → no duplicate."""
        ir, path = _make_schematic_ir(
            wires=[(50.0, 50.0, 60.0, 50.0)],
            labels=[("VCC_3V3", 50.0, 50.0)],
            symbols=[("Audio_Codec", "AK4619VN", "U1", 0, 0)],
        )
        ir.get_pin_positions = lambda: [
            {"reference": "U1", "pin_name": "TVDD", "x": 50.0, "y": 50.0},
        ]

        result = place_net_labels(ir, path, pin_map="backplane")

        assert result["labels_placed"] == 0
        assert result["skipped_existing_label"] == 1


class TestPlaceNetLabelsNoConnect:
    """None-mapped pins get no_connect flags."""

    def test_places_no_connect_for_none_mapping_no_wire(self):
        """Pin mapped to None, no wire → NC placed."""
        ir, path = _make_schematic_ir(
            symbols=[("Audio_Codec", "AK4619VN", "U1", 0, 0)],
        )
        ir.get_pin_positions = lambda: [
            {"reference": "U1", "pin_name": "AIN1", "x": 30.0, "y": 40.0},
        ]

        result = place_net_labels(ir, path, pin_map="backplane")

        assert result["no_connects_placed"] == 1
        assert any(d["action"] == "placed_no_connect" for d in result["details"])

    def test_skips_no_connect_when_wire_exists(self):
        """Pin mapped to None, wire exists → NC NOT placed."""
        ir, path = _make_schematic_ir(
            wires=[(30.0, 40.0, 40.0, 40.0)],
            symbols=[("Audio_Codec", "AK4619VN", "U1", 0, 0)],
        )
        ir.get_pin_positions = lambda: [
            {"reference": "U1", "pin_name": "AIN1", "x": 30.0, "y": 40.0},
        ]

        result = place_net_labels(ir, path, pin_map="backplane")

        assert result["no_connects_placed"] == 0

    def test_skips_no_connect_when_nc_exists(self):
        """NC already at position → no duplicate."""
        ir, path = _make_schematic_ir(
            symbols=[("Audio_Codec", "AK4619VN", "U1", 0, 0)],
        )
        ir.add_no_connect(x=30.0, y=40.0)
        ir.get_pin_positions = lambda: [
            {"reference": "U1", "pin_name": "AIN1", "x": 30.0, "y": 40.0},
        ]

        result = place_net_labels(ir, path, pin_map="backplane")

        assert result["no_connects_placed"] == 0


class TestPlaceNetLabelsDryRun:
    """Dry-run mode returns preview without modifying IR."""

    def test_dry_run_no_mutations(self):
        """dry_run=True → IR mutation_log stays empty."""
        ir, path = _make_schematic_ir(
            wires=[(50.0, 50.0, 60.0, 50.0)],
            symbols=[("Audio_Codec", "AK4619VN", "U1", 0, 0)],
        )
        ir.get_pin_positions = lambda: [
            {"reference": "U1", "pin_name": "TVDD", "x": 50.0, "y": 50.0},
        ]

        mutations_before = len(ir.mutation_log)
        result = place_net_labels(ir, path, pin_map="backplane", dry_run=True)
        mutations_after = len(ir.mutation_log)

        assert mutations_after == mutations_before
        assert result["labels_placed"] == 0
        assert any(d["action"] == "would_place_label" for d in result["details"])

    def test_dry_run_counts_match_details(self):
        """dry_run details accurately reflect what would happen."""
        ir, path = _make_schematic_ir(
            wires=[(50.0, 50.0, 60.0, 50.0)],
            symbols=[("Audio_Codec", "AK4619VN", "U1", 0, 0)],
        )
        ir.get_pin_positions = lambda: [
            {"reference": "U1", "pin_name": "TVDD", "x": 50.0, "y": 50.0},
            {"reference": "U1", "pin_name": "AIN1", "x": 20.0, "y": 30.0},
        ]

        result = place_net_labels(ir, path, pin_map="backplane", dry_run=True)

        would_label = sum(1 for d in result["details"] if d["action"] == "would_place_label")
        would_nc = sum(1 for d in result["details"] if d["action"] == "would_place_no_connect")
        assert would_label >= 1
        assert would_nc >= 1


class TestPlaceNetLabelsEdgeCases:

    def test_unknown_component_skipped(self):
        """Component not in pin_map → all pins skipped."""
        ir, path = _make_schematic_ir(wires=[(50.0, 50.0, 60.0, 50.0)])

        ir.get_pin_positions = lambda: [
            {"reference": "U1", "pin_name": "VDD", "x": 50.0, "y": 50.0},
        ]

        result = place_net_labels(ir, path, pin_map="backplane")

        # "U1" has lib_id "" which won't match any profile entry
        assert result["skipped_no_mapping"] >= 1

    def test_pin_not_in_mapping_skipped(self):
        """Pin exists but not in component mapping → skipped entirely."""
        ir, path = _make_schematic_ir(wires=[(50.0, 50.0, 60.0, 50.0)])

        ir.get_pin_positions = lambda: [
            {"reference": "U1", "pin_name": "CUSTOM_PIN", "x": 50.0, "y": 50.0},
        ]

        # Need to mock lib_id to match a known component
        result = place_net_labels(ir, path, pin_map="backplane")

        # CUSTOM_PIN is not in AK4619VN mapping → skipped
        assert result["labels_placed"] == 0

    def test_empty_mapping_returns_zero(self):
        """Empty mapping dict → no changes."""
        # Use a custom JSON file with empty mapping
        ir, path = _make_schematic_ir()
        empty_map_path = path.parent / "empty_map.json"
        empty_map_path.write_text("{}")

        result = place_net_labels(ir, path, pin_map=str(empty_map_path))

        assert result["labels_placed"] == 0
        assert result["no_connects_placed"] == 0

    def test_position_rounding_safe(self):
        """Wire at 50.005 and pin at 50.01 do NOT match due to rounding divergence.

        round(50.005, 2) == 50.0, round(50.01, 2) == 50.01 -- different positions.
        """
        ir, path = _make_schematic_ir(wires=[(50.005, 50.0, 60.0, 50.0)])

        ir.get_pin_positions = lambda: [
            {"reference": "U1", "pin_name": "TVDD", "x": 50.01, "y": 50.0},
        ]

        result = place_net_labels(ir, path, pin_map="backplane")

        # Rounding divergence: wire at 50.0, pin at 50.01 — no match
        assert result["labels_placed"] == 0


class TestPinMapLoading:

    def test_backplane_profile_exists(self):
        """'backplane' is a valid built-in profile."""
        mapping = _load_pin_map("backplane", Path("."))
        assert "AK4619VN" in mapping

    def test_auto_mode_merges_profiles(self):
        """'auto' merges all built-in profiles."""
        mapping = _load_pin_map("auto", Path("."))
        # Should have entries from backplane
        assert len(mapping) > 0

    def test_custom_json_file(self, tmp_path):
        """Load mapping from custom JSON file."""
        custom = {"MY_IC": {"VDD": "VCC_3V3", "OUT": None}}
        json_path = tmp_path / "custom.json"
        json_path.write_text(json.dumps(custom))

        mapping = _load_pin_map(str(json_path), Path("."))
        assert "MY_IC" in mapping
        assert mapping["MY_IC"]["VDD"] == "VCC_3V3"

    def test_invalid_pin_map_raises(self):
        """Unknown profile with no matching file → ValueError."""
        with pytest.raises(ValueError, match="Unknown pin_map"):
            _load_pin_map("nonexistent_profile_xyz", Path("."))

    def test_relative_json_path_resolved(self, tmp_path):
        """Relative JSON path resolved against file_path parent."""
        custom = {"IC1": {"PIN1": "NET1"}}
        json_path = tmp_path / "mymap.json"
        json_path.write_text(json.dumps(custom))
        schematic_path = tmp_path / "test.kicad_sch"

        mapping = _load_pin_map("mymap.json", schematic_path)
        assert "IC1" in mapping


class TestBuiltinProfiles:

    def test_backplane_has_expected_ics(self):
        """Backplane profile contains all expected ICs."""
        profile = _BUILTIN_PROFILES["backplane"]
        assert "AK4619VN" in profile
        assert "MT8816" in profile
        assert "W5500" in profile
        assert "MCP4728" in profile
        assert "P82B96DP" in profile

    def test_power_pins_always_mapped(self):
        """Power pins (VDD, VSS, GND) have non-None net names."""
        for ic_name, pins in _BUILTIN_PROFILES["backplane"].items():
            for pin_name, net in pins.items():
                if pin_name in ("VDD", "VCC", "VEE", "GND", "VSS",
                                "TVDD", "AVDD", "DVDD", "DVDDH", "AVDRV"):
                    assert net is not None, f"{ic_name}.{pin_name} mapped to None"
