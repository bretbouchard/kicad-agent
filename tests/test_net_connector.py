"""Tests for NetConnector -- connect pins into a net with wire/label generation.

TDD RED phase: tests written before implementation.
Tests cover:
  1. ConnectPinsOp schema validates with net_name, pins, strategy, collision_zones
  2. label_only strategy generates 0 wires and N labels
  3. wire_first strategy on same-axis pins generates 1 wire and 0 labels
  4. hybrid strategy generates both wire and labels
  5. Collision zone avoidance skips wires through flagged zones
  6. Wire S-expression format correctness
  7. Label S-expression format correctness at body_position
  8. Single-pin net (just one label, no wires)
  9. ConnectPinsOp rejects empty pins list
  10. max_wire_length respected -- pins >40mm apart get labels only
"""

import math
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from volta.ops._schema_schematic_routing import ConnectPinsOp


# ---------------------------------------------------------------------------
# Fixture helpers -- mock PinResolver results
# ---------------------------------------------------------------------------


def _make_mock_resolver(components: dict) -> MagicMock:
    """Create a mock PinResolver that returns pre-defined component data.

    Args:
        components: Dict mapping ref -> {"ref": str, "lib_id": str,
                   "pins": {pin_num: {"position": (x,y), "body_position": (x,y), "pin_name": str}}}
    """
    resolver = MagicMock()
    resolver.resolve.side_effect = lambda ref: components.get(ref)
    resolver.resolve_all.return_value = components
    return resolver


def _two_horizontal_pins():
    """Two resistors with horizontally-aligned pins at the same y-coordinate.

    R55 at (59.69, 74.93) pin 1 wire=(59.69, 80.01), body=(59.69, 78.74)
    R56 at (80.01, 74.93) pin 2 wire=(80.01, 69.85), body=(80.01, 71.12)

    Wire connection points share y=74.93 is NOT true -- they share y axis differently.
    Let's use body positions that are on the same y-axis for a clean horizontal wire.

    R55 pin 2 wire endpoint: (59.69, 69.85)
    R56 pin 1 wire endpoint: (80.01, 80.01)

    For same-axis test: use same y for both wire endpoints.
    """
    return {
        "R55": {
            "ref": "R55",
            "lib_id": "Device:R",
            "pins": {
                "1": {
                    "position": (59.69, 80.01),
                    "body_position": (59.69, 78.74),
                    "pin_name": "~",
                },
                "2": {
                    "position": (59.69, 69.85),
                    "body_position": (59.69, 71.12),
                    "pin_name": "~",
                },
            },
        },
        "R56": {
            "ref": "R56",
            "lib_id": "Device:R",
            "pins": {
                "1": {
                    "position": (80.01, 80.01),
                    "body_position": (80.01, 78.74),
                    "pin_name": "~",
                },
                "2": {
                    "position": (80.01, 69.85),
                    "body_position": (80.01, 71.12),
                    "pin_name": "~",
                },
            },
        },
    }


def _nearby_pins():
    """Two pins that are close but not on the same axis (for hybrid test)."""
    return {
        "R55": {
            "ref": "R55",
            "lib_id": "Device:R",
            "pins": {
                "2": {
                    "position": (59.69, 69.85),
                    "body_position": (59.69, 71.12),
                    "pin_name": "~",
                },
            },
        },
        "C10": {
            "ref": "C10",
            "lib_id": "Device:C",
            "pins": {
                "1": {
                    "position": (70.0, 69.85),
                    "body_position": (70.0, 71.12),
                    "pin_name": "~",
                },
            },
        },
    }


def _single_pin_net():
    """A single component with one pin."""
    return {
        "R99": {
            "ref": "R99",
            "lib_id": "Device:R",
            "pins": {
                "1": {
                    "position": (50.0, 50.0),
                    "body_position": (50.0, 48.73),
                    "pin_name": "~",
                },
            },
        },
    }


def _far_apart_pins():
    """Two pins >40mm apart."""
    return {
        "R1": {
            "ref": "R1",
            "lib_id": "Device:R",
            "pins": {
                "2": {
                    "position": (10.0, 50.0),
                    "body_position": (10.0, 48.73),
                    "pin_name": "~",
                },
            },
        },
        "R2": {
            "ref": "R2",
            "lib_id": "Device:R",
            "pins": {
                "1": {
                    "position": (100.0, 50.0),
                    "body_position": (100.0, 48.73),
                    "pin_name": "~",
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# Test 1: ConnectPinsOp schema validation
# ---------------------------------------------------------------------------


class TestConnectPinsOpSchema:
    """Validate ConnectPinsOp accepts valid and rejects invalid input."""

    def test_valid_op_with_all_fields(self):
        op = ConnectPinsOp(
            target_file="schematic.kicad_sch",
            net_name="VCC",
            pins=[{"ref": "R55", "pin": "1"}, {"ref": "R56", "pin": "2"}],
            strategy="hybrid",
            collision_zones=[{"direction": "vertical", "coordinate": 59.69}],
        )
        assert op.op_type == "connect_pins"
        assert op.net_name == "VCC"
        assert len(op.pins) == 2
        assert op.pins[0].ref == "R55"
        assert op.pins[0].pin == "1"
        assert op.strategy == "hybrid"
        assert len(op.collision_zones) == 1

    def test_default_strategy_is_hybrid(self):
        op = ConnectPinsOp(
            target_file="schematic.kicad_sch",
            net_name="GND",
            pins=[{"ref": "R1", "pin": "1"}],
        )
        assert op.strategy == "hybrid"

    def test_valid_wire_first_strategy(self):
        op = ConnectPinsOp(
            target_file="schematic.kicad_sch",
            net_name="NET",
            pins=[{"ref": "R1", "pin": "1"}],
            strategy="wire_first",
        )
        assert op.strategy == "wire_first"

    def test_valid_label_only_strategy(self):
        op = ConnectPinsOp(
            target_file="schematic.kicad_sch",
            net_name="NET",
            pins=[{"ref": "R1", "pin": "1"}],
            strategy="label_only",
        )
        assert op.strategy == "label_only"

    def test_rejects_path_traversal(self):
        with pytest.raises(Exception):
            ConnectPinsOp(
                target_file="../../../etc/passwd",
                net_name="NET",
                pins=[{"ref": "R1", "pin": "1"}],
            )

    def test_rejects_unsafe_net_name_with_paretheses(self):
        """T-38-03-01: net_name rejects S-expression injection."""
        with pytest.raises(Exception):
            ConnectPinsOp(
                target_file="schematic.kicad_sch",
                net_name='VCC") (hack "pwned',
                pins=[{"ref": "R1", "pin": "1"}],
            )

    def test_rejects_unsafe_pin_ref_with_parentheses(self):
        """T-38-03-01: pin ref rejects S-expression injection."""
        with pytest.raises(Exception):
            ConnectPinsOp(
                target_file="schematic.kicad_sch",
                net_name="NET",
                pins=[{"ref": 'R") (hack "x', "pin": "1"}],
            )


# ---------------------------------------------------------------------------
# Test 9: ConnectPinsOp rejects empty pins list
# ---------------------------------------------------------------------------


class TestConnectPinsOpEmptyPins:
    """ConnectPinsOp must reject empty pins list."""

    def test_rejects_empty_pins_list(self):
        with pytest.raises(Exception):
            ConnectPinsOp(
                target_file="schematic.kicad_sch",
                net_name="NET",
                pins=[],
            )


# ---------------------------------------------------------------------------
# Tests 2-8, 10: NetConnector functionality
# ---------------------------------------------------------------------------


class TestNetConnector:
    """Test NetConnector wire and label generation."""

    def _make_connector(self, components: dict) -> "NetConnector":
        """Create a NetConnector with mocked PinResolver.

        Patches PinResolver so that __init__ gets a mock and resolve()
        returns the provided component data.
        """
        from volta.schematic_routing.net_connector import NetConnector

        mock_resolver = _make_mock_resolver(components)

        # Write a temp file for the connector's filepath parameter
        tmpdir = tempfile.mkdtemp()
        tmpfile = Path(tmpdir) / "test.kicad_sch"
        tmpfile.write_text("(kicad_sch)", encoding="utf-8")

        with patch(
            "volta.schematic_routing.net_connector.PinResolver",
            return_value=mock_resolver,
        ):
            connector = NetConnector(tmpfile)
        return connector

    def test_label_only_generates_labels_no_wires(self):
        """Test 2: strategy='label_only' generates 0 wires and N labels."""
        connector = self._make_connector(_two_horizontal_pins())
        result = connector.connect_pins(
            net_name="VCC",
            pins=[{"ref": "R55", "pin": "1"}, {"ref": "R56", "pin": "1"}],
            strategy="label_only",
        )
        assert result["wires_generated"] == 0
        assert result["labels_generated"] == 2
        assert result["net_name"] == "VCC"

    def test_wire_first_same_axis_generates_wire(self):
        """Test 3: wire_first on same-axis pins generates 1 wire.

        R55 pin 2 body_position=(59.69, 71.12), R56 pin 1 body_position=(80.01, 78.74)
        Their wire endpoints are at same y=69.85 and 80.01 -- NOT same axis.

        Instead use R55 pin 2 (wire at 69.85) and R56 pin 2 (wire at 69.85).
        Both share y=69.85 so a direct horizontal wire connects them.
        """
        connector = self._make_connector(_two_horizontal_pins())
        result = connector.connect_pins(
            net_name="GND",
            pins=[{"ref": "R55", "pin": "2"}, {"ref": "R56", "pin": "2"}],
            strategy="wire_first",
        )
        # wire_first generates a wire connecting same-axis pins, plus labels for unreached
        assert result["wires_generated"] >= 1
        # Wire connects pin 2 wire endpoints
        wires = result["wires"]
        assert len(wires) >= 1
        # The wire should be horizontal (same y)
        w = wires[0]
        assert w["start"][1] == w["end"][1]  # same y

    def test_hybrid_generates_wire_and_labels(self):
        """Test 4: hybrid on nearby pins generates both wire and labels."""
        connector = self._make_connector(_nearby_pins())
        result = connector.connect_pins(
            net_name="NET_A",
            pins=[{"ref": "R55", "pin": "2"}, {"ref": "C10", "pin": "1"}],
            strategy="hybrid",
        )
        assert result["wires_generated"] >= 1
        assert result["labels_generated"] >= 2

    def test_collision_zone_skips_wires(self):
        """Test 5: Wires are NOT generated through collision zones.

        R55 pin 2 wire position is at x=59.69. A vertical collision zone at x=59.69
        should prevent wire generation for that pin.
        """
        connector = self._make_connector(_two_horizontal_pins())
        result = connector.connect_pins(
            net_name="NET_B",
            pins=[{"ref": "R55", "pin": "2"}, {"ref": "R56", "pin": "2"}],
            strategy="wire_first",
            collision_zones=[
                {"direction": "vertical", "coordinate": 59.69, "tolerance": 2.54},
            ],
        )
        # The wire between R55 pin 2 and R56 pin 2 would go through x=59.69
        # collision zone, so it should be skipped
        assert result["collisions_avoided"] >= 1

    def test_wire_sexpr_format(self):
        """Test 6: Wire S-expression format is correct."""
        connector = self._make_connector(_two_horizontal_pins())
        result = connector.connect_pins(
            net_name="NET_C",
            pins=[{"ref": "R55", "pin": "2"}, {"ref": "R56", "pin": "2"}],
            strategy="wire_first",
        )
        wires = result["wires"]
        assert len(wires) >= 1
        w = wires[0]
        # Verify the wire has start and end tuples
        sx, sy = w["start"]
        ex, ey = w["end"]
        # Verify sexpr field contains valid S-expression
        assert "wire" in w["sexpr"]
        assert "pts" in w["sexpr"]
        assert "xy" in w["sexpr"]

    def test_label_sexpr_format_offset_from_body(self):
        """Test 7: Labels are offset outward from IC body by label_offset (default 2.54mm).

        Pin R55.1: body_position=(59.69, 78.74), position=(59.69, 80.01).
        Pin direction is downward (y increases). Default offset=2.54.
        Expected label position: 80.01 + 2.54 = 82.55.
        """
        connector = self._make_connector(_two_horizontal_pins())
        result = connector.connect_pins(
            net_name="NET_D",
            pins=[{"ref": "R55", "pin": "1"}],
            strategy="label_only",
        )
        labels = result["labels"]
        assert len(labels) == 1
        label = labels[0]
        # Label should be at wire endpoint + offset outward from IC body
        assert label["position"] == (59.69, 82.55)
        # sexpr should contain the net name
        assert "NET_D" in label["sexpr"]

    def test_label_offset_zero_places_at_wire_endpoint(self):
        """Test 7b: label_offset=0 places labels at wire endpoint."""
        connector = self._make_connector(_two_horizontal_pins())
        result = connector.connect_pins(
            net_name="NET_Z",
            pins=[{"ref": "R55", "pin": "1"}],
            strategy="label_only",
            label_offset=0.0,
        )
        labels = result["labels"]
        assert len(labels) == 1
        # With offset=0, label goes to wire endpoint position
        assert labels[0]["position"] == (59.69, 80.01)

    def test_label_offset_custom_distance(self):
        """Test 7c: Custom label_offset (5.08mm = 2 grid units)."""
        connector = self._make_connector(_two_horizontal_pins())
        result = connector.connect_pins(
            net_name="NET_CUSTOM",
            pins=[{"ref": "R55", "pin": "1"}],
            strategy="label_only",
            label_offset=5.08,
        )
        labels = result["labels"]
        assert len(labels) == 1
        # 80.01 + 5.08 = 85.09
        assert labels[0]["position"] == (59.69, 85.09)

    def test_single_pin_net(self):
        """Test 8: Single-pin net generates just one label, no wires."""
        connector = self._make_connector(_single_pin_net())
        result = connector.connect_pins(
            net_name="SINGLE",
            pins=[{"ref": "R99", "pin": "1"}],
            strategy="wire_first",
        )
        assert result["wires_generated"] == 0
        assert result["labels_generated"] == 1
        assert len(result["wires"]) == 0
        assert len(result["labels"]) == 1

    def test_max_wire_length_respected(self):
        """Test 10: Pins >40mm apart get labels only (no wire)."""
        connector = self._make_connector(_far_apart_pins())
        result = connector.connect_pins(
            net_name="FAR_NET",
            pins=[{"ref": "R1", "pin": "2"}, {"ref": "R2", "pin": "1"}],
            strategy="wire_first",
            max_wire_length=40.0,
        )
        # Distance between pin positions is 90mm > 40mm, so no wire
        assert result["wires_generated"] == 0
        assert result["labels_generated"] == 2

    def test_pin_not_found_skipped(self):
        """Pins that cannot be resolved are skipped gracefully."""
        connector = self._make_connector(_single_pin_net())
        result = connector.connect_pins(
            net_name="MISSING",
            pins=[{"ref": "R99", "pin": "1"}, {"ref": "NONEXISTENT", "pin": "5"}],
            strategy="label_only",
        )
        # Should only generate label for the found pin
        assert result["labels_generated"] == 1

    def test_collision_zones_max_50(self):
        """T-38-03-04: collision_zones limited to max 50 entries."""
        zones = [{"direction": "vertical", "coordinate": float(i)} for i in range(51)]
        with pytest.raises(Exception):
            ConnectPinsOp(
                target_file="schematic.kicad_sch",
                net_name="NET",
                pins=[{"ref": "R1", "pin": "1"}],
                collision_zones=zones,
            )

    def test_pins_max_100(self):
        """T-38-03-02: pins list limited to max 100 entries."""
        pins = [{"ref": f"R{i}", "pin": "1"} for i in range(101)]
        with pytest.raises(Exception):
            ConnectPinsOp(
                target_file="schematic.kicad_sch",
                net_name="NET",
                pins=pins,
            )
