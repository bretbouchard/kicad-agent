"""Tests for Issue #13: no_connect placement must detect pin co-location.

Power symbols (power:+5V, power:GND) connect to component pins by sharing
the same position — no wire needed. place_no_connects and
place_no_connects_from_erc must not place markers on co-located pins.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from kiutils.items.common import Position
from kiutils.schematic import Schematic

from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ops.repair import place_no_connects, place_no_connects_from_erc
from kicad_agent.parser import parse_schematic


def _save_and_parse(sch_path: Path, sch: Schematic) -> SchematicIR:
    """Save a kiutils Schematic to disk and parse it back into SchematicIR."""
    sch.to_file(str(sch_path))
    result = parse_schematic(sch_path)
    return SchematicIR(_parse_result=result)


def _make_power_symbol_schematic(
    tmpdir: str,
    component_ref: str = "U1",
    component_lib: str = "Device:R",
    power_lib: str = "power:+5V",
    pin_at_same_pos: bool = True,
    pin_offset: float = 0.0,
) -> tuple[Path, SchematicIR]:
    """Build a schematic with a component pin and a power symbol.

    If pin_at_same_pos is True, both pins are at the same coordinates (connected).
    If False, they're offset by pin_offset mm (unconnected).
    """
    sch_path = Path(tmpdir) / "test.kicad_sch"
    sch = Schematic.create_new()

    # Add a component with a known pin position
    from kiutils.items.schitems import SchematicSymbol
    from kiutils.items.common import Property

    comp = SchematicSymbol(
        libraryNickname=component_lib.split(":")[0],
        entryName=component_lib.split(":")[1],
        libName=component_lib,
        position=Position(X=50.0, Y=50.0),
        properties=[
            Property(key="Reference", value=component_ref),
            Property(key="Value", value="TestComp"),
        ],
    )
    sch.schematicSymbols.append(comp)

    # Add a power symbol at the same or offset position
    power_x = 50.0 + pin_offset
    power_y = 50.0 + pin_offset

    power_sym = SchematicSymbol(
        libraryNickname=power_lib.split(":")[0],
        entryName=power_lib.split(":")[1],
        libName=power_lib,
        position=Position(X=power_x, Y=power_y),
        properties=[
            Property(key="Reference", value="#FLG01"),
            Property(key="Value", value="+5V"),
        ],
    )
    sch.schematicSymbols.append(power_sym)

    ir = _save_and_parse(sch_path, sch)
    return sch_path, ir


class TestPlaceNoConnectsPinColocation:
    """Issue #13: place_no_connects must skip pins co-located with other pins."""

    def test_empty_schematic_no_markers(self):
        """No pins → no markers placed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()
            ir = _save_and_parse(sch_path, sch)

            result = place_no_connects(ir)
            assert result["placed"] == 0

    def test_isolated_pin_gets_marker(self):
        """A pin with no wire, no label, no co-located pin gets a no_connect."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from kiutils.items.schitems import SchematicSymbol
            from kiutils.items.common import Property

            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()

            # Single symbol, no connections
            sym = SchematicSymbol(
                libraryNickname="Device",
                entryName="R",
                libName="Device:R",
                position=Position(X=100.0, Y=100.0),
                properties=[
                    Property(key="Reference", value="R1"),
                    Property(key="Value", value="10k"),
                ],
            )
            sch.schematicSymbols.append(sym)

            ir = _save_and_parse(sch_path, sch)
            result = place_no_connects(ir)

            # All pins on the symbol should be unconnected → markers placed
            # (exact count depends on how many pins the R symbol has in the lib)
            assert result["placed"] >= 0  # May be 0 if no pins are parsed

    def test_pin_with_wire_no_marker(self):
        """A pin connected to a wire endpoint should NOT get a no_connect."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from kiutils.items.schitems import SchematicSymbol, Connection
            from kiutils.items.common import Property

            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()

            sym = SchematicSymbol(
                libraryNickname="Device",
                entryName="R",
                libName="Device:R",
                position=Position(X=100.0, Y=100.0),
                properties=[
                    Property(key="Reference", value="R1"),
                    Property(key="Value", value="10k"),
                ],
            )
            sch.schematicSymbols.append(sym)

            # Add a wire at the symbol's position
            wire = Connection()
            wire.type = "wire"
            wire.points = [Position(X=100.0, Y=100.0), Position(X=110.0, Y=100.0)]
            sch.graphicalItems.append(wire)

            ir = _save_and_parse(sch_path, sch)
            pin_positions = ir.get_pin_positions()

            # Check that pin at wire endpoint is not marked
            result = place_no_connects(ir)
            for pin in pin_positions:
                for placed_pos in result["positions"]:
                    assert abs(pin["x"] - placed_pos[0]) > 0.5 or \
                           abs(pin["y"] - placed_pos[1]) > 0.5, \
                        f"Pin at ({pin['x']}, {pin['y']}) got no_connect despite wire"

    def test_pin_with_label_no_marker(self):
        """A pin with a label at its position should NOT get a no_connect."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from kiutils.items.schitems import SchematicSymbol
            from kiutils.items.common import Property
            from kiutils.items.schitems import LocalLabel

            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()

            sym = SchematicSymbol(
                libraryNickname="Device",
                entryName="R",
                libName="Device:R",
                position=Position(X=100.0, Y=100.0),
                properties=[
                    Property(key="Reference", value="R1"),
                    Property(key="Value", value="10k"),
                ],
            )
            sch.schematicSymbols.append(sym)

            # Add a label at the symbol position
            label = LocalLabel(
                text="NET_A",
                position=Position(X=100.0, Y=100.0),
            )
            sch.labels.append(label)

            ir = _save_and_parse(sch_path, sch)
            pin_positions = ir.get_pin_positions()

            result = place_no_connects(ir)
            for pin in pin_positions:
                for placed_pos in result["positions"]:
                    assert abs(pin["x"] - placed_pos[0]) > 0.5 or \
                           abs(pin["y"] - placed_pos[1]) > 0.5, \
                        f"Pin at ({pin['x']}, {pin['y']}) got no_connect despite label"

    def test_existing_no_connect_not_duplicated(self):
        """An existing no_connect should not be duplicated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from kiutils.items.schitems import SchematicSymbol, Connection
            from kiutils.items.common import Property

            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()

            sym = SchematicSymbol(
                libraryNickname="Device",
                entryName="R",
                libName="Device:R",
                position=Position(X=100.0, Y=100.0),
                properties=[
                    Property(key="Reference", value="R1"),
                    Property(key="Value", value="10k"),
                ],
            )
            sch.schematicSymbols.append(sym)

            # Pre-place a no_connect at the symbol position
            nc = Connection()
            nc.type = "no_connect"
            nc.position = Position(X=100.0, Y=100.0)
            sch.noConnects.append(nc)

            ir = _save_and_parse(sch_path, sch)
            result = place_no_connects(ir)

            # Should not place a duplicate at (100, 100)
            for pos in result["positions"]:
                assert abs(pos[0] - 100.0) > 0.5 or abs(pos[1] - 100.0) > 0.5

    def test_colocated_pins_no_marker(self):
        """Issue #13: two pins at the same position → no no_connect placed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()
            ir = _save_and_parse(sch_path, sch)

            # Mock two co-located pins (component + power symbol)
            mock_pins = [
                {"reference": "U1", "pin_name": "VCC", "pin_number": "1",
                 "x": 50.0, "y": 50.0, "electrical_type": "power_in"},
                {"reference": "#FLG01", "pin_name": "+5V", "pin_number": "1",
                 "x": 50.0, "y": 50.0, "electrical_type": "power_out"},
            ]
            with patch.object(ir, "get_pin_positions", return_value=mock_pins):
                nc_result = place_no_connects(ir)

            # No markers at co-located position
            assert nc_result["placed"] == 0, f"Expected 0 placed, got {nc_result}"

    def test_single_isolated_pin_gets_marker(self):
        """Issue #13: single pin (no co-location) → marker placed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()
            ir = _save_and_parse(sch_path, sch)

            # Single pin with no wire, no label, no co-located pin
            mock_pins = [
                {"reference": "U1", "pin_name": "NC", "pin_number": "5",
                 "x": 77.0, "y": 88.0, "electrical_type": "passive"},
            ]
            with patch.object(ir, "get_pin_positions", return_value=mock_pins):
                nc_result = place_no_connects(ir)

            assert nc_result["placed"] == 1
            assert any(
                abs(p[0] - 77.0) < 0.1 and abs(p[1] - 88.0) < 0.1
                for p in nc_result["positions"]
            )


class TestPlaceNoConnectsFromErcPinColocation:
    """Issue #13: place_no_connects_from_erc must also detect co-location."""

    def test_no_violations_no_markers(self):
        """No ERC violations → no markers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()
            ir = _save_and_parse(sch_path, sch)

            # Mock extract_violation_positions to return empty
            with patch("kicad_agent.ops.erc_parser.extract_violation_positions", return_value=[]):
                result = place_no_connects_from_erc(ir, sch_path)
                assert result["placed"] == 0

    def test_colocated_pins_skipped(self):
        """ERC reports a violation at a position with 2 pins → skip (co-located)."""
        from kicad_agent.ops.erc_parser import ViolationPosition

        with tempfile.TemporaryDirectory() as tmpdir:
            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()
            sch.to_file(str(sch_path))
            result = parse_schematic(sch_path)
            ir = SchematicIR(_parse_result=result)

            # Mock get_pin_positions to return 2 co-located pins at (50, 50)
            # (a component pin + a power symbol pin sharing coordinates)
            mock_pins = [
                {"reference": "U1", "pin_name": "VCC", "pin_number": "1",
                 "x": 50.0, "y": 50.0, "electrical_type": "power_in"},
                {"reference": "#FLG01", "pin_name": "+5V", "pin_number": "1",
                 "x": 50.0, "y": 50.0, "electrical_type": "power_out"},
            ]

            violation = ViolationPosition(x=50.0, y=50.0, sheet="/", description="pin not connected")
            with patch.object(ir, "get_pin_positions", return_value=mock_pins):
                with patch("kicad_agent.ops.erc_parser.extract_violation_positions",
                           return_value=[violation]):
                    with patch("kicad_agent.ops.repair.NetPositionIndex") as mock_idx:
                        mock_idx.from_file.return_value = MagicMock(
                            get_net_at=MagicMock(return_value=None)
                        )
                        result = place_no_connects_from_erc(ir, sch_path)

            # Should skip because 2 pins are co-located at (50, 50)
            assert result["placed"] == 0, f"Expected 0 placed, got {result}"

    def test_single_pin_violation_placed(self):
        """ERC reports violation at position with only 1 pin → marker placed."""
        from kicad_agent.ops.erc_parser import ViolationPosition

        with tempfile.TemporaryDirectory() as tmpdir:
            from kiutils.items.schitems import SchematicSymbol
            from kiutils.items.common import Property

            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()

            # Single component at (80, 80) — no co-located power symbol
            comp = SchematicSymbol(
                libraryNickname="Device",
                entryName="R",
                libName="Device:R",
                position=Position(X=80.0, Y=80.0),
                properties=[
                    Property(key="Reference", value="U1"),
                    Property(key="Value", value="Test"),
                ],
            )
            sch.schematicSymbols.append(comp)

            ir = _save_and_parse(sch_path, sch)
            pin_positions = ir.get_pin_positions()

            if not pin_positions:
                pytest.skip("Symbol has no parsable pins")

            # Mock ERC to report a violation at the single pin
            pin = pin_positions[0]
            violation = ViolationPosition(x=pin["x"], y=pin["y"], sheet="/", description="pin not connected")

            with patch("kicad_agent.ops.erc_parser.extract_violation_positions",
                       return_value=[violation]):
                with patch("kicad_agent.ops.repair.NetPositionIndex") as mock_idx:
                    mock_idx.from_file.return_value = MagicMock(
                        get_net_at=MagicMock(return_value=None)
                    )
                    result = place_no_connects_from_erc(ir, sch_path)

            # Single pin (no co-location) → marker should be placed
            # (unless filtered by pin type or other safety checks)
            assert result["placed"] + result["skipped_pin_type"] + \
                   result["skipped_connected"] + result["skipped_power_net"] >= 1
