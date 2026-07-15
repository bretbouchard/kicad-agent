"""Tests for PCB netlist extractor (#41).

Covers:
- extract_pcb_netlist with minimal content
- Pre-processing of short-form net refs
- Integration with real .kicad_pcb fixtures
- Council F-06: short-form net ref handling
"""

from pathlib import Path

import pytest

from volta.parser.pcb_netlist import (
    extract_pcb_netlist,
    _preprocess_nets,
    _find_pad_net,
)


# ---------------------------------------------------------------------------
# Minimal PCB fixture
# ---------------------------------------------------------------------------

_MINIMAL_PCB = """\
(kicad_pcb
  (version 20240101)
  (generator "eeschema")
  (general (thickness 1.6))
  (net 0 "")
  (net 1 "GND")
  (net 2 "VCC")
\t(footprint "Resistor_SMD:R_0805" (layer "F.Cu")
\t  (property "Reference" "R1" (at 0 -1.5) (layer "F.SilkS"))
\t  (property "Value" "10k" (at 0 1.5) (layer "F.SilkS"))
\t  (pad 1 smd rect (at 10.0 20.0) (net 1 "GND") (layers "F.Cu" "F.Paste" "F.Mask"))
\t  (pad 2 smd rect (at 30.0 20.0) (net 2 "VCC") (layers "F.Cu" "F.Paste" "F.Mask"))
\t)
\t(footprint "Capacitor_SMD:C_0603" (layer "F.Cu")
\t  (property "Reference" "C1" (at 0 -1.2) (layer "F.SilkS"))
\t  (property "Value" "100nF" (at 0 1.2) (layer "F.SilkS"))
\t  (pad 1 smd rect (at 50.0 60.0) (net 1 "GND") (layers "F.Cu" "F.Paste" "F.Mask"))
\t  (pad 2 smd rect (at 70.0 60.0) (net 2 "VCC") (layers "F.Cu" "F.Paste" "F.Mask"))
\t)
)
"""


class TestPreprocessNets:
    """_preprocess_nets normalizes short-form net refs."""

    def test_normalizes_net_number_form(self):
        """(net N "NAME") is normalized to (net "NAME")."""
        content = '(pad 1 smd (at 10 20) (net 1 "GND"))'
        result = _preprocess_nets(content)
        assert '(net "GND")' in result
        assert '(net 1 "GND")' not in result

    def test_preserves_unconnected_net(self):
        """Unconnected nets (net 0 "") are preserved as (net "")."""
        content = '(pad 1 smd (at 10 20) (net 0 ""))'
        result = _preprocess_nets(content)
        assert '(net "")' in result

    def test_handles_multiple_nets(self):
        """Multiple net refs are all normalized."""
        content = '(net 1 "GND") (net 2 "VCC") (net 3 "SIG")'
        result = _preprocess_nets(content)
        assert '(net "GND")' in result
        assert '(net "VCC")' in result
        assert '(net "SIG")' in result


class TestExtractPcbNetlist:
    """extract_pcb_netlist — pad extraction from raw PCB content."""

    def test_extracts_gnd_pads(self):
        """GND pads are grouped under 'GND' key."""
        netlist = extract_pcb_netlist(_MINIMAL_PCB)
        assert "GND" in netlist
        assert len(netlist["GND"]) == 2

    def test_extracts_vcc_pads(self):
        """VCC pads are grouped under 'VCC' key."""
        netlist = extract_pcb_netlist(_MINIMAL_PCB)
        assert "VCC" in netlist
        assert len(netlist["VCC"]) == 2

    def test_pad_positions_are_tuples(self):
        """Pad positions are (x, y) tuples."""
        netlist = extract_pcb_netlist(_MINIMAL_PCB)
        gnd_pads = netlist["GND"]
        for pos in gnd_pads:
            assert isinstance(pos, tuple)
            assert len(pos) == 2

    def test_positions_rounded(self):
        """Positions are rounded to 4 decimal places."""
        netlist = extract_pcb_netlist(_MINIMAL_PCB)
        for net_name, pads in netlist.items():
            for x, y in pads:
                assert x == round(x, 4)
                assert y == round(y, 4)

    def test_empty_content_returns_empty(self):
        """Empty content returns empty dict."""
        result = extract_pcb_netlist("")
        assert result == {}

    def test_invalid_sexp_returns_empty(self):
        """Invalid S-expression returns empty dict."""
        result = extract_pcb_netlist("(((broken")
        assert result == {}

    def test_no_footprints_returns_empty(self):
        """PCB without footprints returns empty dict."""
        content = "(kicad_pcb (version 20240101) (net 0 \"\"))"
        result = extract_pcb_netlist(content)
        assert result == {}


class TestIntegrationWithRealPcb:
    """Integration tests with real .kicad_pcb fixtures."""

    def test_arduino_mega_netlist(self, arduino_mega_pcb: Path):
        """Extract netlist from Arduino Mega PCB — verify GND and VCC present."""
        content = arduino_mega_pcb.read_text(encoding="utf-8")
        netlist = extract_pcb_netlist(content)

        # GND is always present on real PCBs
        assert "GND" in netlist
        assert len(netlist["GND"]) > 0

        # Pads have valid numeric coordinates
        for net_name, pads in netlist.items():
            for x, y in pads:
                assert isinstance(x, float), f"{net_name}: x={x} is not float"
                assert isinstance(y, float), f"{net_name}: y={y} is not float"

    def test_raspberry_pi_netlist(self, raspberry_pi_pcb: Path):
        """Extract netlist from Raspberry Pi PCB — verify nets extracted."""
        content = raspberry_pi_pcb.read_text(encoding="utf-8")
        netlist = extract_pcb_netlist(content)

        # Should have multiple nets
        assert len(netlist) > 5
        # GND present
        assert "GND" in netlist
