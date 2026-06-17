"""Tests for PcbRawWriter -- centralized raw S-expression manipulation.

Covers:
- Phase 79: insert_segments (#37), insert_zone / build_zone_sexp (#38)
- Phase 80: assign_net_class, modify_footprint_position, update_footprint
- Council C-01: All methods return content strings (no disk writes)
- Council C-02: Consolidated from pcb_ir.py and pcb_ops.py sites
- Council C-04: Integration tests with real .kicad_pcb fixtures
"""

from pathlib import Path
from uuid import uuid4

import pytest

from kicad_agent.ops.pcb_raw_writer import PcbRawWriter


# ---------------------------------------------------------------------------
# Minimal PCB fixture for unit tests
# ---------------------------------------------------------------------------

_MINIMAL_PCB = """\
(kicad_pcb
  (version 20240101)
  (generator "eeschema")
  (general (thickness 1.6))
  (paper "A4")
  (net 0 "")
  (net 1 "GND")
  (net 2 "VCC")
  (net_class "Default" ""
    (clearance 0.2)
    (track_width 0.25)
    (via_diameter 0.6)
    (via_drill 0.3)
    (add_net "")
  )
\t(footprint "Resistor_SMD:R_0805_2012Metric" (layer "F.Cu")
\t  (at 50.0 30.0 90)
\t  (property "Reference" "R1" (at 0 -1.5) (layer "F.SilkS"))
\t  (property "Value" "10k" (at 0 1.5) (layer "F.SilkS"))
\t  (pad 1 smd rect (at -0.9 0) (size 1.0 1.2) (layers "F.Cu" "F.Paste" "F.Mask"))
\t  (pad 2 smd rect (at 0.9 0) (size 1.0 1.2) (layers "F.Cu" "F.Paste" "F.Mask"))
\t)
)
"""


# ===========================================================================
# Phase 79: insert_segments (#37)
# ===========================================================================


class TestInsertSegments:
    """PcbRawWriter.insert_segments — track segment insertion."""

    def test_inserts_before_closing_paren(self):
        """Segments are inserted before the last closing paren."""
        result = PcbRawWriter.insert_segments(_MINIMAL_PCB, "(segment)")
        assert result.endswith(")\n)\n")
        assert "(segment)" in result

    def test_empty_content_returns_unchanged(self):
        """Empty content returns unchanged."""
        result = PcbRawWriter.insert_segments("", "(segment)")
        assert result == ""

    def test_no_closing_paren_returns_unchanged(self):
        """Content without closing paren returns unchanged."""
        result = PcbRawWriter.insert_segments("(kicad_pcb", "(segment)")
        assert result == "(kicad_pcb"

    def test_multiple_segments_inserted(self):
        """Multiple segment blocks are inserted together."""
        blocks = "(segment (start 10 20) (end 30 40))\n(segment (start 50 60) (end 70 80))"
        result = PcbRawWriter.insert_segments(_MINIMAL_PCB, blocks)
        assert "(start 10 20)" in result
        assert "(start 50 60)" in result

    def test_returns_new_string_does_not_mutate_input(self):
        """Original content is not mutated."""
        original = _MINIMAL_PCB
        _ = PcbRawWriter.insert_segments(original, "(segment)")
        assert original == _MINIMAL_PCB


# ===========================================================================
# Phase 79: build_zone_sexp + insert_zone (#38)
# ===========================================================================


class TestBuildZoneSexpr:
    """PcbRawWriter.build_zone_sexp — zone S-expression generation."""

    def test_basic_zone_structure(self):
        """Generated zone has correct net, layer, and polygon."""
        result = PcbRawWriter.build_zone_sexp(
            net_number=1,
            net_name="GND",
            layer="F.Cu",
            polygon=[(0, 0), (100, 0), (100, 100), (0, 100)],
        )
        # KiCad format: (net "name") — universal across all versions
        assert '(net "GND")' in result
        assert '(layer "F.Cu")' in result
        assert "(xy 0 0)" in result
        assert "(xy 100 100)" in result
        # UUID must be quoted (fixes #65)
        assert '(uuid "00000000-0000-0000-0000-000000000000")' in result
        # No stub filled_polygon (fixes #65)
        assert "filled_polygon" not in result
        # No invalid fields
        assert "zone_locks" not in result
        assert "net_name" not in result

    def test_custom_clearance_and_thickness(self):
        """Custom clearance and min_thickness appear in output."""
        result = PcbRawWriter.build_zone_sexp(
            net_number=0,
            net_name="",
            layer="B.Cu",
            polygon=[(0, 0), (50, 0), (50, 50), (0, 50)],
            clearance=0.3,
            min_thickness=0.15,
        )
        assert "(min_thickness 0.15)" in result
        assert '(layer "B.Cu")' in result

    def test_custom_uuid(self):
        """Custom UUID is used in zone (quoted, fixes #65)."""
        test_uuid = "12345678-1234-1234-1234-123456789abc"
        result = PcbRawWriter.build_zone_sexp(
            net_number=1,
            net_name="GND",
            layer="F.Cu",
            polygon=[(0, 0), (100, 100)],
            uuid=test_uuid,
        )
        assert f'(uuid "{test_uuid}")' in result

    def test_name_only_net_format(self):
        """When net_number is 0 and name is provided, uses (net "name") format."""
        result = PcbRawWriter.build_zone_sexp(
            net_number=0,
            net_name="GND",
            layer="F.Cu",
            polygon=[(0, 0), (100, 100)],
        )
        assert '(net "GND")' in result
        assert "net_name" not in result


class TestInsertZone:
    """PcbRawWriter.insert_zone — zone insertion into PCB content."""

    def test_inserts_zone_before_closing_paren(self):
        """Zone is inserted before the last closing paren."""
        zone = '  (zone (net 1 "GND")\n  )\n'
        result = PcbRawWriter.insert_zone(_MINIMAL_PCB, zone)
        assert '(zone' in result
        assert result.rstrip().endswith(")")

    def test_empty_content_returns_unchanged(self):
        """Empty content returns unchanged."""
        result = PcbRawWriter.insert_zone("", "(zone)")
        assert result == ""

    def test_returns_new_string_does_not_mutate(self):
        """Original content is not mutated."""
        original = _MINIMAL_PCB
        _ = PcbRawWriter.insert_zone(original, "(zone)")
        assert original == _MINIMAL_PCB


# ===========================================================================
# Phase 80: assign_net_class
# ===========================================================================


class TestAssignNetClass:
    """PcbRawWriter.assign_net_class — net class assignment."""

    def test_adds_net_to_existing_class(self):
        """Net is added to existing net_class block."""
        result = PcbRawWriter.assign_net_class(_MINIMAL_PCB, "VCC", "Default")
        # The net should appear inside the Default class
        assert '(add_net "VCC")' in result

    def test_creates_new_class_when_missing(self):
        """New net_class block is created when class doesn't exist."""
        result = PcbRawWriter.assign_net_class(_MINIMAL_PCB, "VCC", "HighSpeed")
        assert '(net_class "HighSpeed"' in result
        assert '(add_net "VCC")' in result

    def test_removes_net_from_old_class(self):
        """Net is removed from its previous net_class before reassignment."""
        # First assign VCC to Default
        step1 = PcbRawWriter.assign_net_class(_MINIMAL_PCB, "VCC", "Default")
        # Then reassign to a new class
        result = PcbRawWriter.assign_net_class(step1, "VCC", "Power")
        assert '(add_net "VCC")' in result
        # Count occurrences — should be exactly 1
        count = result.count('(add_net "VCC")')
        assert count == 1

    def test_escapes_special_chars_in_names(self):
        """Special regex characters in net/class names are escaped."""
        content = '(kicad_pcb\n  (net 0 "")\n)'
        result = PcbRawWriter.assign_net_class(content, "NET+*?", "Class+*?")
        assert "NET+*?" in result
        assert "Class+*?" in result


# ===========================================================================
# Phase 80: modify_footprint_position (#39)
# ===========================================================================


class TestModifyFootprintPosition:
    """PcbRawWriter.modify_footprint_position — footprint relocation."""

    def test_changes_at_position(self):
        """Footprint (at X Y angle) is updated."""
        result = PcbRawWriter.modify_footprint_position(
            _MINIMAL_PCB, "R1", 75.0, 50.0, 180.0
        )
        assert "(at 75.000000 50.000000 180.000000)" in result
        assert "(at 50.0 30.0 90)" not in result

    def test_unknown_footprint_returns_unchanged(self):
        """Unknown reference returns original content unchanged."""
        result = PcbRawWriter.modify_footprint_position(
            _MINIMAL_PCB, "X99", 10.0, 20.0
        )
        assert result == _MINIMAL_PCB

    def test_returns_new_string_does_not_mutate(self):
        """Original content is not mutated."""
        original = _MINIMAL_PCB
        _ = PcbRawWriter.modify_footprint_position(original, "R1", 1, 2)
        assert original == _MINIMAL_PCB

    def test_default_angle_zero(self):
        """Default angle is 0.0."""
        result = PcbRawWriter.modify_footprint_position(
            _MINIMAL_PCB, "R1", 10.0, 20.0
        )
        assert "(at 10.000000 20.000000 0.000000)" in result


# ===========================================================================
# Phase 80: update_footprint
# ===========================================================================


class TestUpdateFootprint:
    """PcbRawWriter.update_footprint — footprint replacement."""

    def test_replaces_footprint_block(self):
        """Footprint block is replaced with new content."""
        new_fp = '(footprint "Capacitor_SMD:C_0603" (layer "F.Cu")\n  (at 10 20 0)\n)'
        result = PcbRawWriter.update_footprint(_MINIMAL_PCB, "R1", new_fp)
        assert "Capacitor_SMD:C_0603" in result
        assert "Resistor_SMD:R_0805" not in result

    def test_unknown_footprint_returns_unchanged(self):
        """Unknown reference returns original content unchanged."""
        new_fp = '(footprint "Test" (layer "F.Cu"))'
        result = PcbRawWriter.update_footprint(_MINIMAL_PCB, "X99", new_fp)
        assert result == _MINIMAL_PCB

    def test_new_footprint_indented(self):
        """New footprint content is indented with one tab."""
        new_fp = '(footprint "Test" (layer "F.Cu"))'
        result = PcbRawWriter.update_footprint(_MINIMAL_PCB, "R1", new_fp)
        assert "\t(footprint \"Test\"" in result


# ===========================================================================
# Helpers: _find_matching_close
# ===========================================================================


class TestFindMatchingClose:
    """PcbRawWriter._find_matching_close — S-expression paren matching."""

    def test_simple_expr(self):
        """Simple (foo bar) returns correct close position."""
        content = "(foo bar)rest"
        result = PcbRawWriter._find_matching_close(content, 0)
        assert result == 8

    def test_nested_expr(self):
        """Nested (foo (bar baz)) returns correct close position."""
        content = "(foo (bar baz))rest"
        result = PcbRawWriter._find_matching_close(content, 0)
        assert result == 14

    def test_quoted_string_with_parens(self):
        """Quoted strings containing parens are not counted."""
        content = '(foo "(bar)")rest'
        result = PcbRawWriter._find_matching_close(content, 0)
        assert result == 12

    def test_doubled_quote_escape(self):
        """KiCad doubled-quote escape inside strings is handled."""
        content = '(foo "bar""baz")rest'
        result = PcbRawWriter._find_matching_close(content, 0)
        assert result is not None


class TestFindFootprintBlock:
    """PcbRawWriter._find_footprint_block — footprint location."""

    def test_finds_existing_footprint(self):
        """Finds footprint block by reference."""
        start, end = PcbRawWriter._find_footprint_block(_MINIMAL_PCB, "R1")
        assert start is not None
        assert end is not None
        block = _MINIMAL_PCB[start:end]
        assert "Resistor_SMD:R_0805" in block

    def test_returns_none_for_unknown(self):
        """Returns (None, None) for unknown reference."""
        start, end = PcbRawWriter._find_footprint_block(_MINIMAL_PCB, "X99")
        assert start is None
        assert end is None


# ===========================================================================
# Council C-04: Integration with real PCB fixture
# ===========================================================================


class TestIntegrationWithRealPcb:
    """Round-trip tests with real .kicad_pcb fixtures."""

    def test_insert_segments_round_trip(self, arduino_mega_pcb: Path):
        """Insert segments into real PCB and verify structure is valid."""
        content = arduino_mega_pcb.read_text(encoding="utf-8")
        original_len = len(content)

        segment = '(segment (start 50 50) (end 100 100) (width 0.25) (layer "F.Cu") (net 0))'
        result = PcbRawWriter.insert_segments(content, segment)

        assert len(result) > original_len
        assert "(segment" in result
        assert "(start 50 50)" in result
        assert "(end 100 100)" in result
        # File still starts with (kicad_pcb
        assert result.strip().startswith("(kicad_pcb")

    def test_insert_zone_round_trip(self, arduino_mega_pcb: Path):
        """Insert zone into real PCB and verify structure is valid."""
        content = arduino_mega_pcb.read_text(encoding="utf-8")

        zone_sexp = PcbRawWriter.build_zone_sexp(
            net_number=0,
            net_name="GND",
            layer="F.Cu",
            polygon=[(0, 0), (100, 0), (100, 100), (0, 100)],
            uuid=str(uuid4()),
        )
        result = PcbRawWriter.insert_zone(content, zone_sexp)

        assert '(zone' in result
        assert '(net "GND")' in result
        assert '(layer "F.Cu")' in result
        # UUID quoted (fixes #65)
        assert '(uuid "' in result

    def test_modify_footprint_position_round_trip(
        self, arduino_mega_pcb: Path
    ):
        """Move a footprint in real PCB and verify position changed."""
        content = arduino_mega_pcb.read_text(encoding="utf-8")

        # Find the first footprint's reference
        import re
        ref_match = re.search(
            r'\(property "Reference" "([^"]+)"', content
        )
        if ref_match is None:
            pytest.skip("No footprints with Reference property found")

        ref = ref_match.group(1)
        result = PcbRawWriter.modify_footprint_position(
            content, ref, 123.456, 78.910, 45.0
        )

        # Verify the modified (at ...) is in the result
        assert "(at 123.456000 78.910000 45.000000)" in result

    def test_assign_net_class_round_trip(self, arduino_mega_pcb: Path):
        """Assign net class in real PCB and verify structure."""
        content = arduino_mega_pcb.read_text(encoding="utf-8")

        result = PcbRawWriter.assign_net_class(content, "GND", "Default")
        assert '(add_net "GND")' in result


# ===========================================================================
# Plan 96-03: modify_zone_field net resolution (D-13, H-05)
# ===========================================================================


_ZONE_WITH_NET_2 = """\
(kicad_pcb
  (version 20240101)
  (generator "eeschema")
  (general (thickness 1.6))
  (paper "A4")
  (net 0 "")
  (net 1 "GND")
  (net 2 "VCC")
  (zone (net 2 "VCC") (layer "F.Cu") (net_name "VCC")
    (hatch full 0.508)
    (connect_pads (clearance 0.2))
    (min_thickness 0.25)
    (filled_polygon
      (layer "F.Cu")
      (pts (xy 10 10) (xy 20 10) (xy 20 20) (xy 10 20))
    )
    (uuid "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
  )
)
"""


_ZONE_WITHOUT_NET = """\
(kicad_pcb
  (version 20240101)
  (generator "eeschema")
  (general (thickness 1.6))
  (paper "A4")
  (zone (layer "F.Cu") (priority 1)
    (hatch full 0.508)
    (connect_pads (clearance 0.2))
    (min_thickness 0.25)
    (filled_polygon
      (layer "F.Cu")
      (pts (xy 10 10) (xy 20 10) (xy 20 20) (xy 10 20))
    )
    (uuid "aaaaaaaa-bbbb-cccc-dddd-ffffffffffff")
  )
)
"""


class TestModifyZoneFieldNetResolution:
    """D-13/H-05: Net substitution reuses existing net ID from content, not hardcoded 1."""

    def test_modify_zone_field_preserves_staticmethod(self):
        """H-05: modify_zone_field is still @staticmethod with 4 params."""
        import ast

        # Read from file directly to avoid inspect.getsource indent issues on staticmethod
        source = Path(__file__).parent.parent.joinpath(
            "src/kicad_agent/ops/pcb_raw_writer.py"
        ).read_text()
        tree = ast.parse(source)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "modify_zone_field":
                param_names = [a.arg for a in node.args.args]
                assert "self" not in param_names, "Should not have self"
                assert len(param_names) == 4, f"Expected 4 params, got {len(param_names)}: {param_names}"
                assert param_names == ["content", "zone_uuid", "field", "value"]
                # Verify @staticmethod decorator
                is_static = any(
                    isinstance(d, ast.Name) and d.id == "staticmethod"
                    for d in node.decorator_list
                )
                assert is_static, "modify_zone_field should have @staticmethod decorator"
                found = True
                break
        assert found, "modify_zone_field function not found"

    def test_modify_zone_field_reuses_existing_net_id(self):
        """D-13: Net substitution reuses existing net ID from content, not hardcoded 1."""
        # Zone has (net 2 "VCC") -- after modifying net_name, should still have net 2
        result = PcbRawWriter.modify_zone_field(
            _ZONE_WITH_NET_2, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "net_name", "NEW_VCC"
        )
        assert '(net 2 "NEW_VCC")' in result
        # Should NOT have hardcoded net 1
        assert '(net 1 "NEW_VCC")' not in result

    def test_modify_zone_field_no_net_in_block_returns_unchanged(self):
        """D-13: When no existing net pattern found in zone, re.sub has no effect (returns original)."""
        result = PcbRawWriter.modify_zone_field(
            _ZONE_WITHOUT_NET, "aaaaaaaa-bbbb-cccc-dddd-ffffffffffff", "net_name", "NEW_NET"
        )
        # No (net ...) line to substitute -- content stays as-is
        assert result == _ZONE_WITHOUT_NET
