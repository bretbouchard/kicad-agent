"""Tests for PinResolver -- pin position resolution for schematic routing.

TDD RED phase: tests written before implementation.
Tests cover:
  1. ResolvePinPositionsOp schema validation
  2. R/C passive pin resolution (Device:R at known position)
  3. Multi-unit component pin resolution
  4. Named-pin resolution (by number and name)
  5. Rotation transforms
  6. resolve_all() returns dict keyed by ref
  7. resolve(ref=...) filters to single component
  8. TargetFile rejects path traversal and non-KiCad extensions
"""

import math
import tempfile
from pathlib import Path

import pytest

from volta.ops._schema_schematic_routing import ResolvePinPositionsOp


# ---------------------------------------------------------------------------
# Fixture helpers -- minimal .kicad_sch content generators
# ---------------------------------------------------------------------------


def _make_sch_content(lib_symbols: str, symbols: str) -> str:
    """Wrap lib_symbols and symbols into a valid .kicad_sch skeleton."""
    return f"""(kicad_sch (version 20250114) (generator "kicad-agent-test")
  (uuid "00000000-0000-0000-0000-000000000001")
  (paper "A4")
  {lib_symbols}
  (symbol_instances
    {symbols}
  )
)
"""


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


def _multi_unit_lib_symbols() -> str:
    """lib_symbols section with a multi-unit IC (2 units + power unit).

    Unit A has pins 1, 2; unit B has pins 3, 4; power unit has pins 5, 6.
    """
    return """(lib_symbols
    (symbol "CD4066BE" (in_bom yes) (on_board yes)
      (property "Reference" "U" (at 0 0 0)
        (effects (font (size 1.27 1.27)))
      )
      (symbol "CD4066BE_1_1"
        (pin input line (at -7.62 0 0) (length 3.81)
          (name "IN_A" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27))))
        )
        (pin output line (at 7.62 0 0) (length 3.81)
          (name "OUT_A" (effects (font (size 1.27 1.27))))
          (number "2" (effects (font (size 1.27 1.27))))
        )
      )
      (symbol "CD4066BE_2_1"
        (pin input line (at -7.62 0 0) (length 3.81)
          (name "IN_B" (effects (font (size 1.27 1.27))))
          (number "3" (effects (font (size 1.27 1.27))))
        )
        (pin output line (at 7.62 0 0) (length 3.81)
          (name "OUT_B" (effects (font (size 1.27 1.27))))
          (number "4" (effects (font (size 1.27 1.27))))
        )
      )
      (symbol "CD4066BE_5_1"
        (pin power_in line (at 0 7.62 270) (length 3.81)
          (name "VDD" (effects (font (size 1.27 1.27))))
          (number "14" (effects (font (size 1.27 1.27))))
        )
        (pin power_in line (at 0 -7.62 90) (length 3.81)
          (name "VSS" (effects (font (size 1.27 1.27))))
          (number "7" (effects (font (size 1.27 1.27))))
        )
      )
    )
  )"""


def _multi_unit_symbol(
    ref: str, x: float, y: float, rotation: float, unit: int
) -> str:
    """A symbol instance for a specific unit of a multi-unit IC."""
    return f"""(symbol (lib_id "CD4066BE") (at {x} {y} {rotation}) (unit {unit})
      (in_bom yes) (on_board yes) (dnp no)
      (uuid "00000000-0000-0000-0000-000000000020")
      (property "Reference" "{ref}" (at 0 0 0)
        (effects (font (size 1.27 1.27)))
      )
      (property "Value" "CD4066BE" (at 0 0 0)
        (effects (font (size 1.27 1.27)))
      )
      (instances
        (project "test"
          (path "/" (reference "{ref}") (unit {unit}))
        )
      )
    )"""


def _named_pin_lib_symbols() -> str:
    """lib_symbols with named-pin IC (THAT4301-style)."""
    return """(lib_symbols
    (symbol "THAT4301" (in_bom yes) (on_board yes)
      (property "Reference" "U" (at 0 0 0)
        (effects (font (size 1.27 1.27)))
      )
      (symbol "THAT4301_1_1"
        (pin input line (at -10.16 5.08 0) (length 3.81)
          (name "VCA_IN" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27))))
        )
        (pin output line (at 10.16 5.08 0) (length 3.81)
          (name "EC_SPAN" (effects (font (size 1.27 1.27))))
          (number "2" (effects (font (size 1.27 1.27))))
        )
        (pin input line (at -10.16 -5.08 0) (length 3.81)
          (name "GAIN" (effects (font (size 1.27 1.27))))
          (number "3" (effects (font (size 1.27 1.27))))
        )
      )
    )
  )"""


def _named_pin_symbol(ref: str, x: float, y: float, rotation: float = 0) -> str:
    """A named-pin IC symbol instance."""
    return f"""(symbol (lib_id "THAT4301") (at {x} {y} {rotation}) (unit 1)
      (in_bom yes) (on_board yes) (dnp no)
      (uuid "00000000-0000-0000-0000-000000000030")
      (property "Reference" "{ref}" (at 0 0 0)
        (effects (font (size 1.27 1.27)))
      )
      (property "Value" "THAT4301" (at 0 0 0)
        (effects (font (size 1.27 1.27)))
      )
    )"""


def _write_sch(content: str) -> Path:
    """Write content to a temp .kicad_sch file and return the path."""
    tmpdir = tempfile.mkdtemp()
    path = Path(tmpdir) / "test.kicad_sch"
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Test 1: ResolvePinPositionsOp schema validation
# ---------------------------------------------------------------------------


class TestResolvePinPositionsOpSchema:
    """Validate ResolvePinPositionsOp accepts valid and rejects invalid input."""

    def test_valid_op_with_ref_filter(self):
        op = ResolvePinPositionsOp(
            target_file="schematic.kicad_sch",
            ref="R55",
        )
        assert op.op_type == "resolve_pin_positions"
        assert op.target_file == "schematic.kicad_sch"
        assert op.ref == "R55"

    def test_valid_op_without_ref(self):
        op = ResolvePinPositionsOp(target_file="board.kicad_sch")
        assert op.op_type == "resolve_pin_positions"
        assert op.ref is None

    def test_rejects_path_traversal(self):
        with pytest.raises(Exception):
            ResolvePinPositionsOp(target_file="../../../etc/passwd")

    def test_rejects_non_kicad_extension(self):
        with pytest.raises(Exception):
            ResolvePinPositionsOp(target_file="schematic.txt")

    def test_rejects_absolute_path(self):
        with pytest.raises(Exception):
            ResolvePinPositionsOp(target_file="/tmp/schematic.kicad_sch")


# ---------------------------------------------------------------------------
# Test 2-7: PinResolver functionality
# ---------------------------------------------------------------------------


class TestPinResolver:
    """Test PinResolver pin position resolution."""

    def test_rc_passive_pin_positions(self):
        """Test 2: Device:R at (59.69, 74.93) returns pin 1 at top, pin 2 at bottom.

        Device:R has pin 1 at (0, 3.81, 90) and pin 2 at (0, -3.81, 270),
        both with length 1.27.
        For rotation=0:
          pin 1 body: (59.69, 74.93) + (0, 3.81) = (59.69, 78.74)
          pin 1 wire: body + 1.27*sin(90+0) = 78.74 + 1.27 = 80.01
                      Wait, let me recalculate using the schematic_graph formula.

        Actually, the formula from _parse_symbol_pins:
          rot_px = px * cos(sa) - py * sin(sa)
          rot_py = px * sin(sa) + py * cos(sa)
          body_x = sx + rot_px
          body_y = sy + rot_py
          total_angle = pa + sa
          wire_x = body_x + pl * cos(total_angle_rad)
          wire_y = body_y + pl * sin(total_angle_rad)

        For pin 1 at (0, 3.81, 90), sa=0:
          rot_px = 0*cos(0) - 3.81*sin(0) = 0
          rot_py = 0*sin(0) + 3.81*cos(0) = 3.81
          body = (59.69, 74.93 + 3.81) = (59.69, 78.74)
          total_angle = 90 + 0 = 90
          wire_x = 59.69 + 1.27 * cos(90) = 59.69 + 0 = 59.69
          wire_y = 78.74 + 1.27 * sin(90) = 78.74 + 1.27 = 80.01

        For pin 2 at (0, -3.81, 270), sa=0:
          rot_px = 0*cos(0) - (-3.81)*sin(0) = 0
          rot_py = 0*sin(0) + (-3.81)*cos(0) = -3.81
          body = (59.69, 74.93 - 3.81) = (59.69, 71.12)
          total_angle = 270 + 0 = 270
          wire_x = 59.69 + 1.27 * cos(270) = 59.69 + 0 = 59.69
          wire_y = 71.12 + 1.27 * sin(270) = 71.12 - 1.27 = 69.85
        """
        from volta.schematic_routing.pin_resolver import PinResolver

        content = _make_sch_content(
            _rc_lib_symbols(),
            _rc_symbol("R55", 59.69, 74.93, 0),
        )
        path = _write_sch(content)
        resolver = PinResolver(path)

        result = resolver.resolve("R55")
        assert result is not None
        assert result["ref"] == "R55"
        assert result["lib_id"] == "Device:R"

        pins = result["pins"]
        # Pin 1 (top): body at (59.69, 78.74), wire at (59.69, 80.01)
        assert "1" in pins
        assert pins["1"]["position"] == (59.69, 80.01)
        assert pins["1"]["body_position"] == (59.69, 78.74)

        # Pin 2 (bottom): body at (59.69, 71.12), wire at (59.69, 69.85)
        assert "2" in pins
        assert pins["2"]["position"] == (59.69, 69.85)
        assert pins["2"]["body_position"] == (59.69, 71.12)

    def test_multi_unit_pins_resolve_per_unit(self):
        """Test 3: Multi-unit IC resolves each unit's pins to correct positions.

        CD4066BE unit A at (69.85, 69.85), unit B at (85.09, 69.85), unit 5 at (100, 69.85).
        Unit A pins: pin 1 at (-7.62, 0, 0), pin 2 at (7.62, 0, 0)
          pin 1 body: (69.85 - 7.62, 69.85) = (62.23, 69.85)
          pin 1 wire: body + 3.81*cos(0) = (62.23 + 3.81, 69.85) = (66.04, 69.85)
          pin 2 body: (69.85 + 7.62, 69.85) = (77.47, 69.85)
          pin 2 wire: (77.47 + 3.81, 69.85) = (81.28, 69.85)
        """
        from volta.schematic_routing.pin_resolver import PinResolver

        symbols = (
            _multi_unit_symbol("U21", 69.85, 69.85, 0, 1)
            + "\n"
            + _multi_unit_symbol("U21", 85.09, 69.85, 0, 2)
            + "\n"
            + _multi_unit_symbol("U21", 100.0, 69.85, 0, 5)
        )
        content = _make_sch_content(_multi_unit_lib_symbols(), symbols)
        path = _write_sch(content)
        resolver = PinResolver(path)

        result = resolver.resolve("U21")
        assert result is not None
        pins = result["pins"]

        # Unit 1 (A) at (69.85, 69.85): pin 1 body (62.23, 69.85), wire (66.04, 69.85)
        assert "1" in pins
        assert pins["1"]["body_position"] == (62.23, 69.85)
        assert pins["1"]["position"] == (66.04, 69.85)

        # Unit 2 (B) at (85.09, 69.85): pin 3 body (77.47, 69.85), wire (81.28, 69.85)
        assert "3" in pins
        assert pins["3"]["body_position"] == (77.47, 69.85)
        assert pins["3"]["position"] == (81.28, 69.85)

        # Unit 5 (power) at (100, 69.85): pin 14 at (0, 7.62, 270)
        # rot_px = 0, rot_py = 7.62; body = (100, 69.85 + 7.62) = (100, 77.47)
        # total_angle = 270, wire = (100 + 3.81*cos(270), 77.47 + 3.81*sin(270))
        #             = (100 + 0, 77.47 - 3.81) = (100, 73.66)
        assert "14" in pins
        assert pins["14"]["body_position"] == (100.0, 77.47)
        assert pins["14"]["position"] == (100.0, 73.66)

    def test_named_pins_resolved_by_name_and_number(self):
        """Test 4: Named-pin IC resolves by both number and name.

        THAT4301 at (100, 100) with pin 1 (VCA_IN) at (-10.16, 5.08, 0), length 3.81.
          body: (100 - 10.16, 100 + 5.08) = (89.84, 105.08)
          wire: (89.84 + 3.81, 105.08) = (93.65, 105.08)
        """
        from volta.schematic_routing.pin_resolver import PinResolver

        content = _make_sch_content(
            _named_pin_lib_symbols(),
            _named_pin_symbol("U22", 100, 100, 0),
        )
        path = _write_sch(content)
        resolver = PinResolver(path)

        result = resolver.resolve("U22")
        assert result is not None
        pins = result["pins"]

        # Pin 1 should exist and have the name VCA_IN
        assert "1" in pins
        assert pins["1"]["pin_name"] == "VCA_IN"
        assert pins["1"]["body_position"] == (89.84, 105.08)
        assert pins["1"]["position"] == (93.65, 105.08)

        # Pin 2 (EC_SPAN) at (10.16, 5.08, 0)
        # body: (100 + 10.16, 100 + 5.08) = (110.16, 105.08)
        # wire: (110.16 + 3.81, 105.08) = (113.97, 105.08)
        assert "2" in pins
        assert pins["2"]["pin_name"] == "EC_SPAN"

    def test_rotation_transform(self):
        """Test 5: Component at (100, 100) with rotation=90.

        Device:R at (100, 100, 90):
          pin 1 at (0, 3.81, 90), sa=90:
            rot_px = 0*cos(90) - 3.81*sin(90) = -3.81
            rot_py = 0*sin(90) + 3.81*cos(90) = 0
            body = (100 - 3.81, 100 + 0) = (96.19, 100)
            total_angle = 90 + 90 = 180
            wire_x = 96.19 + 1.27*cos(180) = 96.19 - 1.27 = 94.92
            wire_y = 100 + 1.27*sin(180) = 100 + 0 = 100
        """
        from volta.schematic_routing.pin_resolver import PinResolver

        content = _make_sch_content(
            _rc_lib_symbols(),
            _rc_symbol("R99", 100, 100, 90),
        )
        path = _write_sch(content)
        resolver = PinResolver(path)

        result = resolver.resolve("R99")
        assert result is not None
        pins = result["pins"]

        assert "1" in pins
        assert pins["1"]["body_position"] == (96.19, 100.0)
        assert pins["1"]["position"] == (94.92, 100.0)

    def test_resolve_all_returns_all_components(self):
        """Test 6: resolve_all() returns dict keyed by ref."""
        from volta.schematic_routing.pin_resolver import PinResolver

        symbols = (
            _rc_symbol("R55", 59.69, 74.93, 0)
            + "\n"
            + _rc_symbol("R56", 59.69, 82.55, 0)
        )
        content = _make_sch_content(_rc_lib_symbols(), symbols)
        path = _write_sch(content)
        resolver = PinResolver(path)

        result = resolver.resolve_all()
        assert isinstance(result, dict)
        assert "R55" in result
        assert "R56" in result
        assert result["R55"]["lib_id"] == "Device:R"
        assert result["R56"]["lib_id"] == "Device:R"
        assert "pins" in result["R55"]
        assert "pins" in result["R56"]

    def test_resolve_single_ref_filters(self):
        """Test 7: resolve(ref="R55") returns only that component."""
        from volta.schematic_routing.pin_resolver import PinResolver

        symbols = (
            _rc_symbol("R55", 59.69, 74.93, 0)
            + "\n"
            + _rc_symbol("R56", 59.69, 82.55, 0)
        )
        content = _make_sch_content(_rc_lib_symbols(), symbols)
        path = _write_sch(content)
        resolver = PinResolver(path)

        result = resolver.resolve("R55")
        assert result is not None
        assert result["ref"] == "R55"
        assert "pins" in result

    def test_resolve_missing_ref_returns_none(self):
        """resolve() with a ref that doesn't exist returns None."""
        from volta.schematic_routing.pin_resolver import PinResolver

        content = _make_sch_content(
            _rc_lib_symbols(),
            _rc_symbol("R55", 59.69, 74.93, 0),
        )
        path = _write_sch(content)
        resolver = PinResolver(path)

        result = resolver.resolve("R999")
        assert result is None

    def test_large_file_rejected(self):
        """T-38-01-03: PinResolver rejects files >10MB."""
        from volta.schematic_routing.pin_resolver import PinResolver

        # Create a file larger than 10MB
        path = _write_sch("(kicad_sch)")
        # Overwrite with large content
        path.write_text("x" * (10 * 1024 * 1024 + 1), encoding="utf-8")

        with pytest.raises(ValueError, match="[Ff]ile.*large"):
            PinResolver(path)

    def test_pin_count_limit(self):
        """T-38-01-03: PinResolver rejects files with >10000 pins."""
        from volta.schematic_routing.pin_resolver import PinResolver

        # Generate a file with too many pins (exaggerated lib_symbols)
        # Each pin entry is ~100 chars, so 10001 pins is ~1MB (under the 10MB limit)
        pin_entries = "\n".join(
            f'        (pin passive line (at 0 0 0) (length 1.27) (name "P{i}" (effects (font (size 1.27 1.27)))) (number "{i}" (effects (font (size 1.27 1.27)))))'
            for i in range(10001)
        )
        lib_section = f"""(lib_symbols
    (symbol "BIG:IC" (in_bom yes) (on_board yes)
      (symbol "IC_1_1"
{pin_entries}
      )
    )
  )"""
        sym_instance = """(symbol (lib_id "BIG:IC") (at 0 0 0) (unit 1)
      (in_bom yes) (on_board yes) (dnp no)
      (uuid "00000000-0000-0000-0000-000000000010")
      (property "Reference" "U1" (at 0 0 0)
        (effects (font (size 1.27 1.27)))
      )
      (property "Value" "IC" (at 0 0 0)
        (effects (font (size 1.27 1.27)))
      )
    )"""
        content = _make_sch_content(lib_section, sym_instance)
        path = _write_sch(content)

        with pytest.raises(ValueError, match="[Pp]in.*limit"):
            PinResolver(path)
