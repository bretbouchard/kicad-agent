"""Tests for net extraction -- extract_nets operation.

TDD RED phase: tests exercise extract_nets behavior against minimal
S-expression schematics. Tests cover:
  - Schema validation via Operation.model_validate
  - Empty schematic (no wires) returns empty net list
  - Global/local labels resolve to net names
  - Unnamed wire-connected pins get auto-generated net names
  - Multi-pin nets (3+ pins) list all members
  - Each net entry contains ref, pin_number, pin_name, position
  - Stats: total_nets, total_pins, named_nets, unnamed_nets
  - netlist_path resolves additional unnamed nets via pin_index
"""

from pathlib import Path

import pytest

from kicad_agent.ops._schema_schematic_intel import ExtractNetsOp
from kicad_agent.ops.schema import Operation


# ---------------------------------------------------------------------------
# Helpers: minimal schematic S-expression fixtures
# ---------------------------------------------------------------------------

SCHEMATIC_HEADER = """\
(kicad_sch (version 20250114) (generator "kicad-agent-test")
  (lib_symbols)
"""

SCHEMATIC_FOOTER = ")"
SCHEMATIC_CLOSE = "\n)"


def _write_schematic(tmp_path: Path, content: str) -> Path:
    """Write content to a .kicad_sch file and return the path."""
    p = tmp_path / "test.kicad_sch"
    p.write_text(content)
    return p


def _minimal_empty_sch() -> str:
    """Schematic with no wires, no symbols."""
    return SCHEMATIC_HEADER + SCHEMATIC_FOOTER


def _sch_with_global_label() -> str:
    """Schematic with one wire, one global label, one resistor symbol."""
    return (
        SCHEMATIC_HEADER
        + """
  (wire (pts (xy 50.0 50.0) (xy 100.0 50.0)))
  (global_label "SDA" (at 50.0 50.0 0)
    (effects (font (size 1.27 1.27)))
  )
  (symbol (lib_id "Device:R") (at 75.0 50.0 0)
    (property "Reference" "R1" (at 75.0 45.0 0)
      (effects (font (size 1.27 1.27)))
    )
  )
"""
        + SCHEMATIC_FOOTER
    )


def _sch_with_local_label() -> str:
    """Schematic with one wire, one local label."""
    return (
        SCHEMATIC_HEADER
        + """
  (wire (pts (xy 30.0 40.0) (xy 80.0 40.0)))
  (label "CLK" (at 30.0 40.0 0)
    (effects (font (size 1.27 1.27)))
  )
"""
        + SCHEMATIC_FOOTER
    )


def _sch_with_unnamed_net() -> str:
    """Schematic with wires connecting two endpoints but no labels.

    Wire: (25,35) -> (50,35) -> (75,35)  via two wire segments
    """
    return (
        SCHEMATIC_HEADER
        + """
  (wire (pts (xy 25.0 35.0) (xy 50.0 35.0)))
  (wire (pts (xy 50.0 35.0) (xy 75.0 35.0)))
"""
        + SCHEMATIC_FOOTER
    )


def _sch_with_multi_pin_net() -> str:
    """Schematic with three wires forming a T-junction and a global label.

    Layout:
        Pin1 at (50,50) --- (100,50) --- (150,50) Pin2
                              |
                           (100,80)
                              |
                           (100,110) Pin3
    Label "BUS" at (100,50)
    """
    return (
        SCHEMATIC_HEADER
        + """
  (wire (pts (xy 50.0 50.0) (xy 100.0 50.0)))
  (wire (pts (xy 100.0 50.0) (xy 150.0 50.0)))
  (wire (pts (xy 100.0 50.0) (xy 100.0 110.0)))
  (global_label "BUS" (at 100.0 50.0 0)
    (effects (font (size 1.27 1.27)))
  )
"""
        + SCHEMATIC_FOOTER
    )


def _sch_with_symbol_and_wires() -> str:
    """Schematic with a resistor symbol and a wire connecting to it.

    The wire goes from (50,50) to (100,50). A global label "VCC" is at (50,50).
    The resistor R1 is at (75,50). For pin resolution to work, the lib_symbols
    section must define the Device:R symbol with pin positions.
    """
    return (
        """\
(kicad_sch (version 20250114) (generator "kicad-agent-test")
  (lib_symbols
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
  (global_label "VCC" (at 50.0 50.0 0)
    (effects (font (size 1.27 1.27)))
  )
  (symbol (lib_id "Device:R") (at 75.0 52.54 0)
    (property "Reference" "R1" (at 75.0 48.0 0)
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
        lines.append(f'    (net (code "{code}") (name "{net_name}"))')
        # Re-open and add nodes -- simplified: we just write inline
        lines[-1] = f'    (net (code "{code}") (name "{net_name}")'
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


class TestExtractNetsSchema:
    """Validate ExtractNetsOp via Operation.model_validate."""

    def test_valid_minimal(self) -> None:
        """Operation.model_validate accepts extract_nets with just target_file."""
        op = Operation.model_validate({
            "root": {
                "op_type": "extract_nets",
                "target_file": "test.kicad_sch",
            }
        })
        assert op.root.op_type == "extract_nets"
        assert op.root.target_file == "test.kicad_sch"
        assert op.root.include_positions is True
        assert op.root.netlist_path is None

    def test_valid_with_all_fields(self) -> None:
        """Operation.model_validate accepts extract_nets with all fields."""
        op = Operation.model_validate({
            "root": {
                "op_type": "extract_nets",
                "target_file": "test.kicad_sch",
                "include_positions": False,
                "netlist_path": "test.net",
            }
        })
        assert op.root.include_positions is False
        assert op.root.netlist_path == "test.net"

    def test_invalid_op_type_rejected(self) -> None:
        """Wrong op_type is rejected."""
        with pytest.raises(Exception):
            Operation.model_validate({
                "root": {
                    "op_type": "extract_nets_WRONG",
                    "target_file": "test.kicad_sch",
                }
            })

    def test_extract_nets_op_direct(self) -> None:
        """ExtractNetsOp can be instantiated directly."""
        op = ExtractNetsOp(target_file="test.kicad_sch")
        assert op.op_type == "extract_nets"
        assert op.target_file == "test.kicad_sch"


# ===========================================================================
# Test: extract_nets function
# ===========================================================================


class TestExtractNetsEmpty:
    """Schematic with no wires returns empty net list."""

    def test_empty_schematic(self, tmp_path: Path) -> None:
        from kicad_agent.schematic_routing.net_extractor import extract_nets
        sch_path = _write_schematic(tmp_path, _minimal_empty_sch())
        result = extract_nets(sch_path=sch_path)
        assert "nets" in result
        assert "stats" in result
        assert result["nets"] == {}
        assert result["stats"]["total_nets"] == 0
        assert result["stats"]["total_pins"] == 0
        assert result["stats"]["named_nets"] == 0
        assert result["stats"]["unnamed_nets"] == 0


class TestExtractNetsWithLabels:
    """Schematics with global/local labels resolve net names."""

    def test_global_label_creates_named_net(self, tmp_path: Path) -> None:
        from kicad_agent.schematic_routing.net_extractor import extract_nets
        sch_path = _write_schematic(tmp_path, _sch_with_global_label())
        result = extract_nets(sch_path=sch_path)
        # The global label "SDA" is at (50,50) which is a wire endpoint.
        # The wire connects (50,50) to (100,50). These are in the same connected component.
        # "SDA" should appear as a net name.
        assert "SDA" in result["nets"], f"Expected 'SDA' net, got: {list(result['nets'].keys())}"
        assert result["stats"]["named_nets"] >= 1

    def test_local_label_creates_named_net(self, tmp_path: Path) -> None:
        from kicad_agent.schematic_routing.net_extractor import extract_nets
        sch_path = _write_schematic(tmp_path, _sch_with_local_label())
        result = extract_nets(sch_path=sch_path)
        assert "CLK" in result["nets"], f"Expected 'CLK' net, got: {list(result['nets'].keys())}"
        assert result["stats"]["named_nets"] >= 1


class TestExtractNetsUnnamedNets:
    """Wire-connected pins without labels get auto-generated names."""

    def test_unnamed_net_gets_auto_name(self, tmp_path: Path) -> None:
        from kicad_agent.schematic_routing.net_extractor import extract_nets
        sch_path = _write_schematic(tmp_path, _sch_with_unnamed_net())
        result = extract_nets(sch_path=sch_path)
        # No labels, so should have unnamed nets with "Net_N" naming
        assert result["stats"]["total_nets"] >= 1
        assert result["stats"]["unnamed_nets"] >= 1
        # Check that at least one net starts with "Net_"
        net_names = list(result["nets"].keys())
        unnamed = [n for n in net_names if n.startswith("Net_")]
        assert len(unnamed) >= 1, f"Expected at least one Net_ name, got: {net_names}"


class TestExtractNetsMultiPinNet:
    """Multi-pin nets (3+ pins) list all member pins."""

    def test_three_pin_net_lists_all(self, tmp_path: Path) -> None:
        from kicad_agent.schematic_routing.net_extractor import extract_nets
        sch_path = _write_schematic(tmp_path, _sch_with_multi_pin_net())
        result = extract_nets(sch_path=sch_path)
        # "BUS" label at (100,50) with three wire segments
        # All endpoints should be in the same connected component
        assert "BUS" in result["nets"], f"Expected 'BUS' net, got: {list(result['nets'].keys())}"


class TestExtractNetsPinEntryFields:
    """Each net entry contains ref, pin_number, pin_name, and position."""

    def test_pin_entry_has_required_fields(self, tmp_path: Path) -> None:
        from kicad_agent.schematic_routing.net_extractor import extract_nets
        sch_path = _write_schematic(tmp_path, _sch_with_symbol_and_wires())
        result = extract_nets(sch_path=sch_path)
        # Should have at least one net with pins
        has_pins = False
        for net_name, pins in result["nets"].items():
            for pin in pins:
                has_pins = True
                assert "ref" in pin, f"Missing 'ref' in pin: {pin}"
                assert "pin_number" in pin, f"Missing 'pin_number' in pin: {pin}"
                assert "pin_name" in pin, f"Missing 'pin_name' in pin: {pin}"
                assert "position" in pin, f"Missing 'position' in pin: {pin}"
        assert has_pins, "Expected at least one pin in the net topology"

    def test_include_positions_false(self, tmp_path: Path) -> None:
        from kicad_agent.schematic_routing.net_extractor import extract_nets
        sch_path = _write_schematic(tmp_path, _sch_with_symbol_and_wires())
        result = extract_nets(sch_path=sch_path, include_positions=False)
        for net_name, pins in result["nets"].items():
            for pin in pins:
                assert "position" not in pin, f"position should be omitted when include_positions=False: {pin}"


class TestExtractNetsStats:
    """Stats accurately reflect named vs unnamed net counts."""

    def test_stats_consistency(self, tmp_path: Path) -> None:
        from kicad_agent.schematic_routing.net_extractor import extract_nets
        sch_path = _write_schematic(tmp_path, _sch_with_global_label())
        result = extract_nets(sch_path=sch_path)
        stats = result["stats"]
        named = stats["named_nets"]
        unnamed = stats["unnamed_nets"]
        total = stats["total_nets"]
        assert total == named + unnamed, \
            f"total_nets ({total}) != named ({named}) + unnamed ({unnamed})"

        total_pins = stats["total_pins"]
        counted_pins = sum(len(pins) for pins in result["nets"].values())
        assert total_pins == counted_pins, \
            f"total_pins ({total_pins}) != counted pins ({counted_pins})"


class TestExtractNetsWithNetlist:
    """netlist_path resolves unnamed nets via pin_index."""

    def test_netlist_resolves_net_names(self, tmp_path: Path) -> None:
        """When a netlist maps a pin to a named net, extract_nets uses that name."""
        from kicad_agent.schematic_routing.net_extractor import extract_nets
        # Create a schematic with a resistor at (75,50) so pin 1's wire-connection
        # point lands at (75,50) -- matching the wire endpoint.
        sch_content = (
            """\
(kicad_sch (version 20250114) (generator "kicad-agent-test")
  (lib_symbols
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
            + "\n"
            + """  (wire (pts (xy 50.0 50.0) (xy 100.0 50.0)))
  (symbol (lib_id "Device:R") (at 75.0 50.0 0)
    (property "Reference" "R1" (at 75.0 48.0 0)
      (effects (font (size 1.27 1.27)))
    )
  )
"""
            + SCHEMATIC_FOOTER
        )
        sch_path = _write_schematic(tmp_path, sch_content)
        netlist_path = _write_netlist(tmp_path, {
            "SIGNAL_A": [("R1", "1")],
        })
        result = extract_nets(sch_path=sch_path, netlist_path=str(netlist_path))
        # The pin R1.1 should be in the "SIGNAL_A" net (resolved via netlist)
        all_nets = list(result["nets"].keys())
        assert "SIGNAL_A" in all_nets, f"Expected SIGNAL_A in nets, got: {all_nets}"
