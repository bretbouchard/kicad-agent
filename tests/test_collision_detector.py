"""Tests for CollisionDetector -- collision and overlap detection for schematic routing.

TDD RED phase: tests written before implementation.
Tests cover:
  1. DetectRoutingCollisionsOp schema validation
  2. DetectPinOverlapsOp schema validation
  3. Vertical collision zones detected for IC pin columns (8 pins at same x)
  4. Single pin at x=50.0 NOT flagged as collision
  5. Pin overlap detection with different nets -> severity="error"
  6. Pin overlap detection with same net -> severity="warning"
  7. Horizontal row collision detection (multiple pins at same y)
  8. Schema rejects invalid target_file
"""

import tempfile
from pathlib import Path

import pytest

from volta.ops._schema_schematic_routing import (
    DetectPinOverlapsOp,
    DetectRoutingCollisionsOp,
)


# ---------------------------------------------------------------------------
# Fixture helpers -- minimal .kicad_sch content generators
# ---------------------------------------------------------------------------


def _make_sch_content(lib_symbols: str, symbols: str) -> str:
    """Wrap lib_symbols and symbols into a valid .kicad_sch skeleton."""
    return f"""(kicad_sch (version 20250114) (generator "volta-test")
  (uuid "00000000-0000-0000-0000-000000000001")
  (paper "A4")
  {lib_symbols}
  (symbol_instances
    {symbols}
  )
)
"""


def _ic_lib_symbols() -> str:
    """lib_symbols with an IC that has 8 pins on each side (THAT4301-style).

    Pins at x=-5.08 (left column) and x=5.08 (right column),
    spaced at y intervals: -7.62, -5.08, -2.54, 0, 2.54, 5.08, 7.62, 10.16.
    All pins have length 2.54.
    """
    y_positions = [-7.62, -5.08, -2.54, 0, 2.54, 5.08, 7.62, 10.16]
    left_pins = "\n".join(
        f'        (pin input line (at -5.08 {y} 0) (length 2.54)'
        f' (name "L{i}" (effects (font (size 1.27 1.27))))'
        f' (number "{i}" (effects (font (size 1.27 1.27)))))'
        for i, y in enumerate(y_positions, 1)
    )
    right_pins = "\n".join(
        f'        (pin output line (at 5.08 {y} 180) (length 2.54)'
        f' (name "R{i}" (effects (font (size 1.27 1.27))))'
        f' (number "{i + 8}" (effects (font (size 1.27 1.27)))))'
        for i, y in enumerate(y_positions, 1)
    )
    return f"""(lib_symbols
    (symbol "IC:TEST_IC" (in_bom yes) (on_board yes)
      (property "Reference" "U" (at 0 0 0)
        (effects (font (size 1.27 1.27)))
      )
      (symbol "TEST_IC_1_1"
{left_pins}
{right_pins}
      )
    )
  )"""


def _ic_symbol(ref: str, x: float, y: float, rotation: float = 0) -> str:
    """A single IC symbol instance."""
    return f"""(symbol (lib_id "IC:TEST_IC") (at {x} {y} {rotation}) (unit 1)
      (in_bom yes) (on_board yes) (dnp no)
      (uuid "00000000-0000-0000-0000-000000000100")
      (property "Reference" "{ref}" (at 0 0 0)
        (effects (font (size 1.27 1.27)))
      )
      (property "Value" "TEST_IC" (at 0 0 0)
        (effects (font (size 1.27 1.27)))
      )
    )"""


def _rc_lib_symbols() -> str:
    """lib_symbols section with Device:R (pin1 top, pin2 bottom, 3.81mm offset)."""
    return """(lib_symbols
    (symbol "Device:R" (pin_numbers hide) (in_bom yes) (on_board yes)
      (property "Reference" "R" (at 2.032 0 90)
        (effects (font (size 1.27 1.27)))
      )
      (property "Value" "R" (at 0 -2.54 0)
        (effects (font (size 1.27 1.27)))
      )
      (symbol "R_1_1"
        (pin passive line (at 0 3.81 90) (length 1.27)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27))))
        )
        (pin passive line (at 0 -3.81 270) (length 1.27)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "2" (effects (font (size 1.27 1.27))))
        )
      )
    )
  )"""


def _rc_symbol(ref: str, x: float, y: float, rotation: float = 0) -> str:
    """A single Device:R symbol instance."""
    return f"""(symbol (lib_id "Device:R") (at {x} {y} {rotation}) (unit 1)
      (in_bom yes) (on_board yes) (dnp no)
      (uuid "00000000-0000-0000-0000-000000000010")
      (property "Reference" "{ref}" (at 0 0 0)
        (effects (font (size 1.27 1.27)))
      )
      (property "Value" "10k" (at 0 0 0)
        (effects (font (size 1.27 1.27)))
      )
      (pin "1" (uuid "00000000-0000-0000-0000-000000000011"))
      (pin "2" (uuid "00000000-0000-0000-0000-000000000012"))
    )"""


def _write_sch(content: str) -> Path:
    """Write content to a temp .kicad_sch file and return the path."""
    tmpdir = tempfile.mkdtemp()
    path = Path(tmpdir) / "test.kicad_sch"
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Test fixtures for collision scenarios
# ---------------------------------------------------------------------------


def _u22_ic_fixture() -> Path:
    """Create a schematic with U22 (16-pin IC) at (100, 100).

    Left pins (1-8) have body at x=100-5.08=94.92, wire at x=94.92-2.54=92.38
    Right pins (9-16) have body at x=100+5.08=105.08, wire at x=105.08+2.54=107.62

    All 8 left pins share x=92.38 -- that's a collision column.
    All 8 right pins share x=107.62 -- that's a collision column.
    """
    content = _make_sch_content(
        _ic_lib_symbols(),
        _ic_symbol("U22", 100, 100, 0),
    )
    return _write_sch(content)


def _r55_r56_overlap_fixture() -> Path:
    """R55 at (59.69, 74.93) and R56 at (59.69, 85.09).

    R55 pin 1 (top):    body at (59.69, 78.74), wire at (59.69, 80.01)
    R56 pin 2 (bottom): body at (59.69, 81.28), wire at (59.69, 80.01)

    Both R55 pin 1 and R56 pin 2 have wire endpoints at (59.69, 80.01).
    This is the R55/R56-style overlap bug: pins from different nets share
    the exact same wire endpoint position.
    """
    symbols = (
        _rc_symbol("R55", 59.69, 74.93, 0)
        + "\n"
        + _rc_symbol("R56", 59.69, 85.09, 0)
    )
    content = _make_sch_content(_rc_lib_symbols(), symbols)
    return _write_sch(content)


def _single_component_fixture() -> Path:
    """Single R at (50, 50) -- no collisions expected."""
    content = _make_sch_content(
        _rc_lib_symbols(),
        _rc_symbol("R1", 50.0, 50.0, 0),
    )
    return _write_sch(content)


def _horizontal_row_fixture() -> Path:
    """Multiple R/C components at different x but same y, creating a horizontal row.

    R1 at (50, 50), R2 at (60, 50), R3 at (70, 50).
    All have pin 1 body at y = 50 + 3.81 = 53.81, pin 2 body at y = 50 - 3.81 = 46.19.
    Three pins at y=53.81 from different refs = horizontal collision.
    """
    symbols = "\n".join(
        _rc_symbol(f"R{i}", x, 50.0, 0)
        for i, x in enumerate([50.0, 60.0, 70.0], 1)
    )
    content = _make_sch_content(_rc_lib_symbols(), symbols)
    return _write_sch(content)


# ---------------------------------------------------------------------------
# Test 1 & 2: Schema validation
# ---------------------------------------------------------------------------


class TestDetectRoutingCollisionsOpSchema:
    """Validate DetectRoutingCollisionsOp schema."""

    def test_valid_op_defaults(self):
        """Test 1: Schema validates with op_type, target_file, default collision_tolerance."""
        op = DetectRoutingCollisionsOp(
            target_file="schematic.kicad_sch",
        )
        assert op.op_type == "detect_routing_collisions"
        assert op.target_file == "schematic.kicad_sch"
        assert op.collision_tolerance == 2.54

    def test_valid_op_custom_tolerance(self):
        op = DetectRoutingCollisionsOp(
            target_file="schematic.kicad_sch",
            collision_tolerance=5.0,
        )
        assert op.collision_tolerance == 5.0

    def test_rejects_zero_tolerance(self):
        """Tolerance must be > 0."""
        with pytest.raises(Exception):
            DetectRoutingCollisionsOp(
                target_file="schematic.kicad_sch",
                collision_tolerance=0,
            )

    def test_rejects_negative_tolerance(self):
        with pytest.raises(Exception):
            DetectRoutingCollisionsOp(
                target_file="schematic.kicad_sch",
                collision_tolerance=-1.0,
            )

    def test_rejects_too_large_tolerance(self):
        """Tolerance must be <= 10."""
        with pytest.raises(Exception):
            DetectRoutingCollisionsOp(
                target_file="schematic.kicad_sch",
                collision_tolerance=15.0,
            )


class TestDetectPinOverlapsOpSchema:
    """Validate DetectPinOverlapsOp schema."""

    def test_valid_op_defaults(self):
        """Test 2: Schema validates with op_type and target_file."""
        op = DetectPinOverlapsOp(
            target_file="schematic.kicad_sch",
        )
        assert op.op_type == "detect_pin_overlaps"
        assert op.target_file == "schematic.kicad_sch"
        assert op.tolerance == 0.01

    def test_valid_op_custom_tolerance(self):
        op = DetectPinOverlapsOp(
            target_file="schematic.kicad_sch",
            tolerance=0.5,
        )
        assert op.tolerance == 0.5

    def test_rejects_zero_tolerance(self):
        with pytest.raises(Exception):
            DetectPinOverlapsOp(
                target_file="schematic.kicad_sch",
                tolerance=0,
            )

    def test_rejects_too_large_tolerance(self):
        """Tolerance must be <= 1.0."""
        with pytest.raises(Exception):
            DetectPinOverlapsOp(
                target_file="schematic.kicad_sch",
                tolerance=2.0,
            )


# ---------------------------------------------------------------------------
# Test 8: Schema rejects invalid target_file
# ---------------------------------------------------------------------------


class TestSchemaTargetFileValidation:
    """Test 8: Both schemas reject invalid target_file."""

    def test_collisions_rejects_path_traversal(self):
        with pytest.raises(Exception):
            DetectRoutingCollisionsOp(target_file="../../../etc/passwd")

    def test_collisions_rejects_non_kicad(self):
        with pytest.raises(Exception):
            DetectRoutingCollisionsOp(target_file="file.txt")

    def test_overlaps_rejects_absolute_path(self):
        with pytest.raises(Exception):
            DetectPinOverlapsOp(target_file="/tmp/schematic.kicad_sch")

    def test_overlaps_rejects_path_traversal(self):
        with pytest.raises(Exception):
            DetectPinOverlapsOp(target_file="../secret.kicad_sch")


# ---------------------------------------------------------------------------
# Test 3-7: CollisionDetector functionality
# ---------------------------------------------------------------------------


class TestCollisionDetector:
    """Test CollisionDetector collision and overlap detection."""

    def test_ic_vertical_collision_columns(self):
        """Test 3: U22 with 16-pin IC returns vertical collision zones.

        U22 at (100, 100) with pins at offsets (-5.08, y, 0) and (5.08, y, 180).
        PinResolver computes:
          Left pins (direction=0): body_x = 100-5.08 = 94.92, wire_x = 94.92+2.54 = 97.46
          Right pins (direction=180): body_x = 100+5.08 = 105.08, wire_x = 105.08-2.54 = 102.54
        All 8 left pins share x=97.46, all 8 right pins share x=102.54 => 2 collision zones.
        """
        from volta.schematic_routing.collision_detector import CollisionDetector

        path = _u22_ic_fixture()
        detector = CollisionDetector(path)
        zones = detector.detect_routing_collisions()

        vertical_zones = [z for z in zones if z["direction"] == "vertical"]
        assert len(vertical_zones) >= 2, f"Expected >=2 vertical zones, got {len(vertical_zones)}"

        # Check that the left pin column (x~97.46) is detected
        left_zone = next(
            (z for z in vertical_zones if abs(z["coordinate"] - 97.46) < 0.1),
            None,
        )
        assert left_zone is not None, f"No vertical zone near x=97.46. Zones: {vertical_zones}"
        assert len(left_zone["pins"]) == 8, f"Expected 8 pins in left zone, got {len(left_zone['pins'])}"

        # Check that the right pin column (x~102.54) is detected
        right_zone = next(
            (z for z in vertical_zones if abs(z["coordinate"] - 102.54) < 0.1),
            None,
        )
        assert right_zone is not None, f"No vertical zone near x=102.54"
        assert len(right_zone["pins"]) == 8

    def test_single_component_no_cross_component_collision(self):
        """Test 4: Single R at (50, 50) has only same-ref collision zones.

        R at (50, 50) has pin 1 at (50, 55.08) and pin 2 at (50, 44.92).
        Both pins share x=50, so they form a vertical zone, but both are from R1.
        No horizontal zones (pin 1 and pin 2 have different y values).
        The important thing: no zones involve pins from different components.
        """
        from volta.schematic_routing.collision_detector import CollisionDetector

        path = _single_component_fixture()
        detector = CollisionDetector(path)
        zones = detector.detect_routing_collisions()

        # A single R has 2 pins at same x but same ref. With >=2 pin threshold,
        # it gets 1 vertical zone (both pins at x=50) but 0 horizontal zones.
        # The key assertion: no zone has pins from different components.
        for zone in zones:
            refs = {p["ref"] for p in zone["pins"]}
            assert len(refs) == 1, "Single component fixture should only have same-ref zones"

    def test_pin_overlap_different_nets_error(self):
        """Test 5: R55/R56 pins at same position on different nets -> severity="error".

        We mock the net membership to simulate R55 pin 1 on "net_A" and R56 pin 2 on "net_B".
        Since CollisionDetector uses PinResolver (no netlist), we test with the netlist_path
        parameter or by checking the behavior when no netlist is provided.

        When no netlist is provided, overlaps default to severity="warning".
        To test severity="error", we need to provide a netlist.
        """
        from volta.schematic_routing.collision_detector import CollisionDetector

        path = _r55_r56_overlap_fixture()
        detector = CollisionDetector(path)

        overlaps = detector.detect_pin_overlaps()

        # R55 pin 1 wire (59.69, 80.01) and R56 pin 2 wire (59.69, 80.01) overlap
        # Without netlist, both get severity="warning"
        assert len(overlaps) >= 1, f"Expected >=1 overlap, got {len(overlaps)}"

        # Find the overlap at wire position (59.69, 80.01)
        wire_overlap = next(
            (o for o in overlaps
             if abs(o["position"][0] - 59.69) < 0.1 and abs(o["position"][1] - 80.01) < 0.1),
            None,
        )
        assert wire_overlap is not None, f"No overlap at wire position (59.69, 80.01). Overlaps: {overlaps}"

        # Without netlist, default severity is "warning"
        assert wire_overlap["severity"] == "warning"

        # Verify both pins are present
        refs_in_overlap = {p["ref"] for p in wire_overlap["pins"]}
        assert "R55" in refs_in_overlap
        assert "R56" in refs_in_overlap

    def test_pin_overlap_different_nets_with_netlist(self):
        """Test 5 (extended): Overlap with netlist showing different nets -> severity="error"."""
        from volta.schematic_routing.collision_detector import CollisionDetector

        path = _r55_r56_overlap_fixture()

        # Create a mock netlist file that assigns R55.pin1 to net_A and R56.pin2 to net_B
        netlist_content = """(export (version "E")
  (design (source "test.sch"))
  (nets
    (net (code 1) (name "net_A")
      (node (ref "R55") (pin "1"))
    )
    (net (code 2) (name "net_B")
      (node (ref "R56") (pin "2"))
    )
  )
)
"""
        netlist_path = path.parent / "test.net"
        netlist_path.write_text(netlist_content, encoding="utf-8")

        detector = CollisionDetector(path, netlist_path=netlist_path)
        overlaps = detector.detect_pin_overlaps()

        wire_overlap = next(
            (o for o in overlaps
             if abs(o["position"][0] - 59.69) < 0.1 and abs(o["position"][1] - 80.01) < 0.1),
            None,
        )
        assert wire_overlap is not None, f"No overlap found. Overlaps: {overlaps}"

        # With netlist showing different nets, severity should be "error"
        assert wire_overlap["severity"] == "error"
        assert "different nets" in wire_overlap["note"].lower() or "unintended" in wire_overlap["note"].lower()

    def test_pin_overlap_same_net_warning(self):
        """Test 6: Pins at same position on SAME net -> severity="warning".

        Both R55 pin 1 and R56 pin 2 assigned to "same_net" in netlist.
        """
        from volta.schematic_routing.collision_detector import CollisionDetector

        path = _r55_r56_overlap_fixture()

        netlist_content = """(export (version "E")
  (design (source "test.sch"))
  (nets
    (net (code 1) (name "same_net")
      (node (ref "R55") (pin "1"))
      (node (ref "R56") (pin "2"))
    )
  )
)
"""
        netlist_path = path.parent / "test.net"
        netlist_path.write_text(netlist_content, encoding="utf-8")

        detector = CollisionDetector(path, netlist_path=netlist_path)
        overlaps = detector.detect_pin_overlaps()

        wire_overlap = next(
            (o for o in overlaps
             if abs(o["position"][0] - 59.69) < 0.1 and abs(o["position"][1] - 80.01) < 0.1),
            None,
        )
        assert wire_overlap is not None

        # Same net -> severity="warning" (intentional)
        assert wire_overlap["severity"] == "warning"
        assert "same net" in wire_overlap["note"].lower()

    def test_horizontal_row_collision(self):
        """Test 7: Three R components at same y detect horizontal collision row.

        R1/R2/R3 at y=50 all have pin 1 wire at y=55.08 from different refs.
        That's a horizontal collision row.
        """
        from volta.schematic_routing.collision_detector import CollisionDetector

        path = _horizontal_row_fixture()
        detector = CollisionDetector(path)
        zones = detector.detect_routing_collisions()

        horizontal_zones = [z for z in zones if z["direction"] == "horizontal"]
        assert len(horizontal_zones) >= 1, f"Expected >=1 horizontal zone, got {len(horizontal_zones)}"

        # Find the zone at y~55.08 (pin 1 wire y for all three R's)
        pin1_row = next(
            (z for z in horizontal_zones if abs(z["coordinate"] - 55.08) < 0.1),
            None,
        )
        assert pin1_row is not None, f"No horizontal zone near y=55.08. Zones: {horizontal_zones}"
        assert len(pin1_row["pins"]) == 3, f"Expected 3 pins in row, got {len(pin1_row['pins'])}"

    def test_collision_zone_has_description(self):
        """Each collision zone includes a human-readable description."""
        from volta.schematic_routing.collision_detector import CollisionDetector

        path = _u22_ic_fixture()
        detector = CollisionDetector(path)
        zones = detector.detect_routing_collisions()

        for zone in zones:
            assert "description" in zone
            assert isinstance(zone["description"], str)
            assert len(zone["description"]) > 0

    def test_collision_zone_has_range(self):
        """Each collision zone includes the min/max range."""
        from volta.schematic_routing.collision_detector import CollisionDetector

        path = _u22_ic_fixture()
        detector = CollisionDetector(path)
        zones = detector.detect_routing_collisions()

        for zone in zones:
            assert "range" in zone
            rng = zone["range"]
            assert isinstance(rng, (list, tuple))
            assert len(rng) == 2
            assert rng[0] <= rng[1]

    def test_overlap_each_pin_has_net_info(self):
        """Each pin in an overlap report includes net information."""
        from volta.schematic_routing.collision_detector import CollisionDetector

        path = _r55_r56_overlap_fixture()
        detector = CollisionDetector(path)
        overlaps = detector.detect_pin_overlaps()

        for overlap in overlaps:
            for pin in overlap["pins"]:
                assert "ref" in pin
                assert "pin" in pin
                assert "net" in pin

    def test_kicad10_quoted_code_netlist_parses(self):
        """R-BUG-005: KiCad 10 netlist with (code \"1\") quoted values parses correctly.

        KiCad 10 uses quoted code values like (code \"1\") instead of (code 1).
        The netlist parser must handle both formats.
        """
        from volta.schematic_routing.collision_detector import CollisionDetector

        path = _r55_r56_overlap_fixture()

        # KiCad 10 format: code values are quoted strings
        netlist_content = """(export (version "E")
  (design (source "test.sch"))
  (nets
    (net (code "1") (name "net_A")
      (node (ref "R55") (pin "1"))
    )
    (net (code "2") (name "net_B")
      (node (ref "R56") (pin "2"))
    )
  )
)
"""
        netlist_path = path.parent / "test_kicad10.net"
        netlist_path.write_text(netlist_content, encoding="utf-8")

        detector = CollisionDetector(path, netlist_path=netlist_path)
        overlaps = detector.detect_pin_overlaps()

        wire_overlap = next(
            (o for o in overlaps
             if abs(o["position"][0] - 59.69) < 0.1 and abs(o["position"][1] - 80.01) < 0.1),
            None,
        )
        assert wire_overlap is not None, "KiCad 10 quoted code netlist should parse and detect overlap"

        # With netlist showing different nets, severity should be "error"
        assert wire_overlap["severity"] == "error"
