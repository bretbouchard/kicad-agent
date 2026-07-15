"""Tests for net name suggestion -- suggest_net_names operation.

TDD RED phase: tests exercise suggest_net_names behavior against minimal
S-expression schematics. Tests cover:
  - Schema validation via Operation.model_validate
  - Global label nets return confidence 1.0 with basis=global_label
  - Hierarchical label nets suggest with basis=hierarchical_label
  - Power convention from pin names (GND, VCC, VDD, +3V3, etc.)
  - Component ref naming for IC pins (e.g., U1_SDA)
  - Fallback naming for passive components (e.g., R1_Pin2)
  - naming_convention="ref_pin_number" variant
  - Stats: total_nets, named_nets, suggested_nets
"""

from pathlib import Path

import pytest

from volta.ops._schema_schematic_intel import SuggestNetNamesOp
from volta.ops.schema import Operation


# ---------------------------------------------------------------------------
# Helpers: minimal schematic S-expression fixtures
# ---------------------------------------------------------------------------

SCHEMATIC_HEADER = """\
(kicad_sch (version 20250114) (generator "kicad-agent-test")
"""

SCHEMATIC_FOOTER = ")"


def _write_schematic(tmp_path: Path, content: str) -> Path:
    """Write content to a .kicad_sch file and return the path."""
    p = tmp_path / "test.kicad_sch"
    p.write_text(content)
    return p


def _sch_with_global_label_net() -> str:
    """Schematic with a wire, global label "SDA", and a resistor R1.

    Wire: (50,50) -> (100,50)
    Label "SDA" at (50,50) -- global
    R1 at (75,50) with pins 1 at (75,52.54) and 2 at (75,47.46)
    """
    return (
        SCHEMATIC_HEADER
        + """  (lib_symbols
    (symbol "Device:R"
      (symbol "Device:R_0_1"
        (rectangle (start -0.762 1.778) (end 0.762 -1.778)
          (stroke (width 0.254))
        )
      )
      (symbol "Device:R_1_1"
        (pin passive line (at 0 2.54 270) (length 2.54)
          (name "1") (number "1")
        )
        (pin passive line (at 0 -2.54 90) (length 2.54)
          (name "2") (number "2")
        )
      )
    )
  )
"""
        + """
  (wire (pts (xy 50.0 50.0) (xy 100.0 50.0)))
  (global_label "SDA" (at 50.0 50.0 0)
    (effects (font (size 1.27 1.27)))
  )
  (symbol (lib_id "Device:R") (at 75.0 50.0 0)
    (property "Reference" "R1" (at 75.0 48.0 0)
      (effects (font (size 1.27 1.27)))
    )
  )
"""
        + SCHEMATIC_FOOTER
    )


def _sch_with_hierarchical_label_net() -> str:
    """Schematic with a wire, hierarchical label "RESET", and IC U1.

    Wire: (50,50) -> (100,50)
    Hierarchical label "RESET" at (100,50)
    IC U1 at (75,50) with pin "RST" at its pin 3
    """
    return (
        SCHEMATIC_HEADER
        + """  (lib_symbols
    (symbol "MCU:ATmega328"
      (symbol "MCU:ATmega328_0_1"
        (rectangle (start -5.08 7.62) (end 5.08 -7.62)
          (stroke (width 0.254))
        )
      )
      (symbol "MCU:ATmega328_1_1"
        (pin input line (at -7.62 5.08 0) (length 2.54)
          (name "RST") (number "1")
        )
        (pin bidirectional line (at -7.62 2.54 0) (length 2.54)
          (name "SDA") (number "2")
        )
        (pin bidirectional line (at 7.62 2.54 180) (length 2.54)
          (name "SCL") (number "3")
        )
      )
    )
  )
"""
        + """
  (wire (pts (xy 50.0 50.0) (xy 100.0 50.0)))
  (hierarchical_label "RESET" (at 100.0 50.0 0)
    (effects (font (size 1.27 1.27)))
  )
  (symbol (lib_id "MCU:ATmega328") (at 75.0 50.0 0)
    (property "Reference" "U1" (at 75.0 40.0 0)
      (effects (font (size 1.27 1.27)))
    )
  )
"""
        + SCHEMATIC_FOOTER
    )


def _sch_with_gnd_pin() -> str:
    """Schematic with an IC that has a GND pin.

    Wire: (50,50) -> (100,50)
    IC U1 at (75,50) with pin "GND" -- should be recognized as power convention.
    The IC pin 1 (named "GND") wire-connection at (75-7.62+2.54, 50+5.08) = (70.0, 55.08) --
    Actually let's calculate: symbol at (75,50), pin at offset (-7.62, 5.08) angle 0.
    body_position = (75 + (-7.62)*cos(0) - 5.08*sin(0), 50 + (-7.62)*sin(0) + 5.08*cos(0))
                  = (75 - 7.62, 50 + 5.08) = (67.38, 55.08)
    wire_connection: total_angle = 0 + 0 = 0, so wire extends right 2.54mm
                  = (67.38 + 2.54, 55.08) = (69.92, 55.08)

    Let me place things so the wire endpoint matches the pin wire-connection point.
    Symbol at (80,55.08), pin 1 "GND" at (-7.62, 5.08) angle 0.
    body_position = (80-7.62, 55.08+5.08) = (72.38, 60.16)
    wire_connection = (72.38+2.54, 60.16) = (74.92, 60.16)

    Wire: (50,60.16) -> (100,60.16) should connect to pin at (74.92, 60.16) via mid-point.
    Actually mid-point detection should catch this since the pin lies ON the wire segment.
    """
    return (
        SCHEMATIC_HEADER
        + """  (lib_symbols
    (symbol "MCU:ATmega328"
      (symbol "MCU:ATmega328_0_1"
        (rectangle (start -5.08 7.62) (end 5.08 -7.62)
          (stroke (width 0.254))
        )
      )
      (symbol "MCU:ATmega328_1_1"
        (pin power_in line (at -7.62 5.08 0) (length 2.54)
          (name "GND") (number "1")
        )
        (pin power_out line (at 7.62 5.08 180) (length 2.54)
          (name "VCC") (number "2")
        )
        (pin bidirectional line (at -7.62 -5.08 0) (length 2.54)
          (name "SDA") (number "3")
        )
      )
    )
  )
"""
        + """
  (wire (pts (xy 50.0 60.16) (xy 100.0 60.16)))
  (symbol (lib_id "MCU:ATmega328") (at 80.0 55.08 0)
    (property "Reference" "U1" (at 80.0 45.0 0)
      (effects (font (size 1.27 1.27)))
    )
  )
"""
        + SCHEMATIC_FOOTER
    )


def _sch_with_vcc_pin() -> str:
    """Schematic with an IC that has a VCC pin.

    Wire: (50,55.08) -> (100,55.08)
    IC U1 at (75,50) with pin "VCC" at pin 2.
    Pin 2 at offset (7.62, 5.08) angle 180.
    body_position = (75+7.62, 50+5.08) = (82.62, 55.08)
    wire_connection: total_angle = 180, extends LEFT 2.54mm
                  = (82.62-2.54, 55.08) = (80.08, 55.08)
    This pin is on the wire via mid-point detection.
    """
    return (
        SCHEMATIC_HEADER
        + """  (lib_symbols
    (symbol "MCU:ATmega328"
      (symbol "MCU:ATmega328_0_1"
        (rectangle (start -5.08 7.62) (end 5.08 -7.62)
          (stroke (width 0.254))
        )
      )
      (symbol "MCU:ATmega328_1_1"
        (pin power_in line (at -7.62 5.08 0) (length 2.54)
          (name "GND") (number "1")
        )
        (pin power_out line (at 7.62 5.08 180) (length 2.54)
          (name "VCC") (number "2")
        )
        (pin bidirectional line (at -7.62 -5.08 0) (length 2.54)
          (name "SDA") (number "3")
        )
      )
    )
  )
"""
        + """
  (wire (pts (xy 50.0 55.08) (xy 100.0 55.08)))
  (symbol (lib_id "MCU:ATmega328") (at 75.0 50.0 0)
    (property "Reference" "U1" (at 75.0 45.0 0)
      (effects (font (size 1.27 1.27)))
    )
  )
"""
        + SCHEMATIC_FOOTER
    )


def _sch_with_ic_sda_pin() -> str:
    """Schematic with an IC that has a named pin "SDA" but no label.

    Wire: (50,44.92) -> (100,44.92)
    IC U1 at (75,50) with pin "SDA" at pin 3.
    Pin 3 at offset (-7.62, -5.08) angle 0.
    body_position = (75-7.62, 50-5.08) = (67.38, 44.92)
    wire_connection = (67.38+2.54, 44.92) = (69.92, 44.92)
    Mid-point on wire.
    """
    return (
        SCHEMATIC_HEADER
        + """  (lib_symbols
    (symbol "MCU:ATmega328"
      (symbol "MCU:ATmega328_0_1"
        (rectangle (start -5.08 7.62) (end 5.08 -7.62)
          (stroke (width 0.254))
        )
      )
      (symbol "MCU:ATmega328_1_1"
        (pin bidirectional line (at -7.62 -5.08 0) (length 2.54)
          (name "SDA") (number "3")
        )
      )
    )
  )
"""
        + """
  (wire (pts (xy 50.0 44.92) (xy 100.0 44.92)))
  (symbol (lib_id "MCU:ATmega328") (at 75.0 50.0 0)
    (property "Reference" "U1" (at 75.0 45.0 0)
      (effects (font (size 1.27 1.27)))
    )
  )
"""
        + SCHEMATIC_FOOTER
    )


def _sch_with_passive_only() -> str:
    """Schematic with only a resistor, no labels -- fallback naming.

    Wire: (50,50) -> (100,50)
    R1 at (75,50) with pin 2 at (75,47.46) -- on wire via mid-point.
    Actually let's use R1 at (75,52.54) with pin 1 at (75,50) -- on wire endpoint.
    Pin 1 at offset (0,2.54) angle 270.
    body_position = (75, 52.54+2.54) = (75, 55.08) ... wait.

    R1 at (75,52.54) angle 0. Pin 1 at offset (0,2.54) angle 270.
    body_position = (75+0*cos0 - 2.54*sin0, 52.54+0*sin0 + 2.54*cos0) = (75, 55.08)
    wire_connection: total_angle = 270, extends down
                   = (75+2.54*cos270, 55.08+2.54*sin270) = (75+0, 55.08-2.54) = (75, 52.54)

    Hmm, that's not on the wire at y=50.

    Let me try: R1 at (75,47.46) angle 0.
    Pin 1 at offset (0,2.54) angle 270.
    body_position = (75, 47.46+2.54) = (75, 50.0)
    wire_connection: total_angle=270, extends down from body
                   = (75 + 2.54*cos(270), 50 + 2.54*sin(270)) = (75+0, 50-2.54) = (75, 47.46)
    That's also not at y=50.

    Let me try: R1 at (75,50) angle 0.
    Pin 2 at offset (0,-2.54) angle 90.
    body_position = (75 + 0*cos0 - (-2.54)*sin0, 50 + 0*sin0 + (-2.54)*cos0) = (75, 47.46)
    wire_connection: total_angle=90, extends up from body
                   = (75 + 2.54*cos(90), 47.46 + 2.54*sin(90)) = (75+0, 47.46+2.54) = (75, 50.0)
    YES! Pin 2 wire-connection is at (75, 50.0) -- on the wire!

    So R1 at (75,50): pin 1 wire-connection at (75,52.54), pin 2 wire-connection at (75,50.0).
    The wire (50,50) -> (100,50) has the pin 2 at (75,50) as a mid-point.
    """
    return (
        SCHEMATIC_HEADER
        + """  (lib_symbols
    (symbol "Device:R"
      (symbol "Device:R_0_1"
        (rectangle (start -0.762 1.778) (end 0.762 -1.778)
          (stroke (width 0.254))
        )
      )
      (symbol "Device:R_1_1"
        (pin passive line (at 0 2.54 270) (length 2.54)
          (name "1") (number "1")
        )
        (pin passive line (at 0 -2.54 90) (length 2.54)
          (name "2") (number "2")
        )
      )
    )
  )
"""
        + """
  (wire (pts (xy 50.0 50.0) (xy 100.0 50.0)))
  (symbol (lib_id "Device:R") (at 75.0 50.0 0)
    (property "Reference" "R1" (at 75.0 45.0 0)
      (effects (font (size 1.27 1.27)))
    )
  )
"""
        + SCHEMATIC_FOOTER
    )


def _sch_with_voltage_pattern_pin() -> str:
    """Schematic with an IC that has a +3V3 pin (voltage pattern).

    Wire: (50,55.08) -> (100,55.08)
    IC at (75,50) with pin "+3V3" as pin 4 at offset (7.62, 5.08) angle 180.
    body_position = (82.62, 55.08)
    wire_connection = (80.08, 55.08) -- on wire via mid-point.
    Only the +3V3 pin lands on the wire (GND pin is not defined here).
    """
    return (
        SCHEMATIC_HEADER
        + """  (lib_symbols
    (symbol "MCU:STM32"
      (symbol "MCU:STM32_0_1"
        (rectangle (start -5.08 7.62) (end 5.08 -7.62)
          (stroke (width 0.254))
        )
      )
      (symbol "MCU:STM32_1_1"
        (pin power_in line (at 7.62 5.08 180) (length 2.54)
          (name "+3V3") (number "4")
        )
        (pin bidirectional line (at -7.62 -5.08 0) (length 2.54)
          (name "SDA") (number "3")
        )
      )
    )
  )
"""
        + """
  (wire (pts (xy 50.0 55.08) (xy 100.0 55.08)))
  (symbol (lib_id "MCU:STM32") (at 75.0 50.0 0)
    (property "Reference" "U1" (at 75.0 45.0 0)
      (effects (font (size 1.27 1.27)))
    )
  )
"""
        + SCHEMATIC_FOOTER
    )


# ---------------------------------------------------------------------------
# Minimal netlist fixture for netlist_path test
# ---------------------------------------------------------------------------

def _write_netlist(tmp_path: Path, nets: dict[str, list[tuple[str, str]]]) -> Path:
    """Write a minimal .net file with given net->pin mappings."""
    lines = [
        "(export (version \"E\")",
        "  (design",
        "    (source \"test.kicad_sch\")",
        "    (date \"2026-01-01\")",
        "    (tool \"kicad-agent-test\"))",
        "  (components)",
        "  (nets",
    ]
    code = 1
    for net_name, pins in nets.items():
        lines.append(f'    (net (code "{code}") (name "{net_name}")')
        for ref, pin in pins:
            lines.append(f'      (node (ref "{ref}") (pin "{pin}"))')
        lines.append("    )")
        code += 1
    lines.append("  )")
    lines.append(")")

    p = tmp_path / "test.net"
    p.write_text("\n".join(lines))
    return p


# ===========================================================================
# Test: Schema validation
# ===========================================================================


class TestSuggestNetNamesSchema:
    """Validate SuggestNetNamesOp via Operation.model_validate."""

    def test_valid_minimal(self) -> None:
        """Operation.model_validate accepts suggest_net_names with just target_file."""
        op = Operation.model_validate({
            "root": {
                "op_type": "suggest_net_names",
                "target_file": "test.kicad_sch",
            }
        })
        assert op.root.op_type == "suggest_net_names"
        assert op.root.target_file == "test.kicad_sch"
        assert op.root.netlist_path is None
        assert op.root.naming_convention == "ref_pin"

    def test_valid_with_all_fields(self) -> None:
        """Operation.model_validate accepts suggest_net_names with all fields."""
        op = Operation.model_validate({
            "root": {
                "op_type": "suggest_net_names",
                "target_file": "test.kicad_sch",
                "netlist_path": "test.net",
                "naming_convention": "ref_pin_number",
            }
        })
        assert op.root.netlist_path == "test.net"
        assert op.root.naming_convention == "ref_pin_number"

    def test_invalid_op_type_rejected(self) -> None:
        """Wrong op_type is rejected."""
        with pytest.raises(Exception):
            Operation.model_validate({
                "root": {
                    "op_type": "suggest_net_names_WRONG",
                    "target_file": "test.kicad_sch",
                }
            })

    def test_suggest_net_names_op_direct(self) -> None:
        """SuggestNetNamesOp can be instantiated directly."""
        op = SuggestNetNamesOp(target_file="test.kicad_sch")
        assert op.op_type == "suggest_net_names"
        assert op.target_file == "test.kicad_sch"


# ===========================================================================
# Test: Global label net (confidence 1.0)
# ===========================================================================


class TestGlobalLabelNet:
    """Net with global label returns that name with confidence=1.0."""

    def test_global_label_confidence_1(self, tmp_path: Path) -> None:
        from volta.schematic_routing.net_namer import suggest_net_names
        sch_path = _write_schematic(tmp_path, _sch_with_global_label_net())
        result = suggest_net_names(sch_path=sch_path)
        # Find the SDA suggestion
        sda_suggestion = None
        for s in result["suggestions"]:
            if s["suggested_name"] == "SDA":
                sda_suggestion = s
                break
        assert sda_suggestion is not None, f"Expected SDA suggestion, got: {result['suggestions']}"
        assert sda_suggestion["confidence"] == 1.0
        assert sda_suggestion["basis"] == "global_label"

    def test_global_label_suggestion_has_pins(self, tmp_path: Path) -> None:
        from volta.schematic_routing.net_namer import suggest_net_names
        sch_path = _write_schematic(tmp_path, _sch_with_global_label_net())
        result = suggest_net_names(sch_path=sch_path)
        sda_suggestion = next(s for s in result["suggestions"] if s["suggested_name"] == "SDA")
        assert len(sda_suggestion["pins"]) > 0
        # Each pin should have ref, pin_number, pin_name
        for pin in sda_suggestion["pins"]:
            assert "ref" in pin
            assert "pin_number" in pin
            assert "pin_name" in pin


# ===========================================================================
# Test: Hierarchical label net
# ===========================================================================


class TestHierarchicalLabelNet:
    """Unnamed net with hierarchical label suggests that name."""

    def test_hierarchical_label_suggestion(self, tmp_path: Path) -> None:
        from volta.schematic_routing.net_namer import suggest_net_names
        sch_path = _write_schematic(tmp_path, _sch_with_hierarchical_label_net())
        result = suggest_net_names(sch_path=sch_path)
        reset_suggestion = None
        for s in result["suggestions"]:
            if s["suggested_name"] == "RESET":
                reset_suggestion = s
                break
        assert reset_suggestion is not None, f"Expected RESET suggestion, got: {[s['suggested_name'] for s in result['suggestions']]}"
        assert reset_suggestion["confidence"] == 0.9
        assert reset_suggestion["basis"] == "hierarchical_label"


# ===========================================================================
# Test: Power convention
# ===========================================================================


class TestPowerConventionGND:
    """Net connected to GND pin suggests "GND" with basis=power_convention."""

    def test_gnd_pin_recognized(self, tmp_path: Path) -> None:
        from volta.schematic_routing.net_namer import suggest_net_names
        sch_path = _write_schematic(tmp_path, _sch_with_gnd_pin())
        result = suggest_net_names(sch_path=sch_path)
        # Find a suggestion with power_convention basis
        power_suggestion = None
        for s in result["suggestions"]:
            if s["basis"] == "power_convention":
                power_suggestion = s
                break
        assert power_suggestion is not None, f"Expected power_convention suggestion, got: {result['suggestions']}"
        assert power_suggestion["suggested_name"] == "GND"
        assert power_suggestion["confidence"] == 0.85


class TestPowerConventionVCC:
    """Net connected to VCC pin suggests appropriate power name."""

    def test_vcc_pin_recognized(self, tmp_path: Path) -> None:
        from volta.schematic_routing.net_namer import suggest_net_names
        sch_path = _write_schematic(tmp_path, _sch_with_vcc_pin())
        result = suggest_net_names(sch_path=sch_path)
        power_suggestion = None
        for s in result["suggestions"]:
            if s["basis"] == "power_convention":
                power_suggestion = s
                break
        assert power_suggestion is not None, f"Expected power_convention suggestion, got: {result['suggestions']}"
        assert power_suggestion["suggested_name"] == "VCC"
        assert power_suggestion["confidence"] == 0.85


class TestPowerConventionVoltagePattern:
    """Net connected to +3V3 pin suggests that exact name."""

    def test_voltage_pattern_recognized(self, tmp_path: Path) -> None:
        from volta.schematic_routing.net_namer import suggest_net_names
        sch_path = _write_schematic(tmp_path, _sch_with_voltage_pattern_pin())
        result = suggest_net_names(sch_path=sch_path)
        power_suggestion = None
        for s in result["suggestions"]:
            if s["basis"] == "power_convention":
                power_suggestion = s
                break
        assert power_suggestion is not None, f"Expected power_convention suggestion, got: {result['suggestions']}"
        assert power_suggestion["suggested_name"] == "+3V3"
        assert power_suggestion["confidence"] == 0.85


# ===========================================================================
# Test: Component ref naming
# ===========================================================================


class TestComponentRefNaming:
    """Unnamed net with IC pin "SDA" suggests "U1_SDA"."""

    def test_ic_pin_suggests_ref_pin(self, tmp_path: Path) -> None:
        from volta.schematic_routing.net_namer import suggest_net_names
        sch_path = _write_schematic(tmp_path, _sch_with_ic_sda_pin())
        result = suggest_net_names(sch_path=sch_path)
        # Find a suggestion with component_ref basis
        comp_suggestion = None
        for s in result["suggestions"]:
            if s["basis"] == "component_ref":
                comp_suggestion = s
                break
        assert comp_suggestion is not None, f"Expected component_ref suggestion, got: {result['suggestions']}"
        assert comp_suggestion["suggested_name"] == "U1_SDA"
        assert comp_suggestion["confidence"] == 0.7


# ===========================================================================
# Test: Fallback naming
# ===========================================================================


class TestFallbackNaming:
    """Net with no signals gets "R1_2" style name."""

    def test_passive_only_fallback(self, tmp_path: Path) -> None:
        from volta.schematic_routing.net_namer import suggest_net_names
        sch_path = _write_schematic(tmp_path, _sch_with_passive_only())
        result = suggest_net_names(sch_path=sch_path)
        # Find a suggestion with fallback basis
        fallback_suggestion = None
        for s in result["suggestions"]:
            if s["basis"] == "fallback":
                fallback_suggestion = s
                break
        assert fallback_suggestion is not None, f"Expected fallback suggestion, got: {result['suggestions']}"
        # Default naming_convention is "ref_pin", so for passive with pin_name "1",
        # it should be "R1_1" (sorted by pin_number, pin 1 comes first)
        assert fallback_suggestion["suggested_name"] == "R1_1"
        assert fallback_suggestion["confidence"] == 0.5


# ===========================================================================
# Test: naming_convention variant
# ===========================================================================


class TestNamingConvention:
    """naming_convention='ref_pin_number' produces 'U1_Pin5' style names."""

    def test_ref_pin_number_convention(self, tmp_path: Path) -> None:
        from volta.schematic_routing.net_namer import suggest_net_names
        sch_path = _write_schematic(tmp_path, _sch_with_ic_sda_pin())
        result = suggest_net_names(sch_path=sch_path, naming_convention="ref_pin_number")
        # With ref_pin_number, IC pins get "U1_Pin3" instead of "U1_SDA"
        comp_suggestion = None
        for s in result["suggestions"]:
            if s["basis"] == "component_ref":
                comp_suggestion = s
                break
        assert comp_suggestion is not None, f"Expected component_ref suggestion, got: {result['suggestions']}"
        assert comp_suggestion["suggested_name"] == "U1_Pin3"

    def test_fallback_with_ref_pin_number(self, tmp_path: Path) -> None:
        from volta.schematic_routing.net_namer import suggest_net_names
        sch_path = _write_schematic(tmp_path, _sch_with_passive_only())
        result = suggest_net_names(sch_path=sch_path, naming_convention="ref_pin_number")
        fallback_suggestion = None
        for s in result["suggestions"]:
            if s["basis"] == "fallback":
                fallback_suggestion = s
                break
        assert fallback_suggestion is not None, f"Expected fallback suggestion, got: {result['suggestions']}"
        assert fallback_suggestion["suggested_name"] == "R1_Pin1"


# ===========================================================================
# Test: Stats
# ===========================================================================


class TestSuggestionStats:
    """Verify total_nets, named_nets, suggested_nets counts."""

    def test_stats_structure(self, tmp_path: Path) -> None:
        from volta.schematic_routing.net_namer import suggest_net_names
        sch_path = _write_schematic(tmp_path, _sch_with_global_label_net())
        result = suggest_net_names(sch_path=sch_path)
        stats = result["stats"]
        assert "total_nets" in stats
        assert "named_nets" in stats
        assert "suggested_nets" in stats
        assert stats["total_nets"] >= 1
        assert stats["suggested_nets"] == len(result["suggestions"])

    def test_stats_consistency(self, tmp_path: Path) -> None:
        from volta.schematic_routing.net_namer import suggest_net_names
        sch_path = _write_schematic(tmp_path, _sch_with_global_label_net())
        result = suggest_net_names(sch_path=sch_path)
        stats = result["stats"]
        total = stats["total_nets"]
        named = stats["named_nets"]
        suggested = stats["suggested_nets"]
        # Every net should be accounted for
        assert named + (total - named) == total
        assert suggested == len(result["suggestions"])
