"""Tests for pcb_populate.py — KiCad 10 format compliance.

Covers the push-then-engineer patches applied during Phase 144 analog-board
populate (analog-board has 189 footprints target; backplane had 94).
Each patch has a test fixture that locks in the expected behavior and
prevents regression on Phase 145 digital-board rebuild.
"""
import sys
from pathlib import Path

# Add src to path if running standalone
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from kicad_agent.crossfile.pcb_populate import _add_net_to_pad


def test_add_net_to_pad_emits_kicad10_string_only_format():
    """KiCad 10 pads use (net "NAME") not (net 0 "NAME").
    Memory: kicad10-pcb-generation.md Rule 2. Verified 2026-06-23 on x64-smart-grid.
    Patch P1 (Phase 144 Wave 4)."""
    pad = '(pad "1" thru_hole circle (at 0 0) (size 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))'
    result = _add_net_to_pad(pad, "GND")
    assert '(net "GND")' in result, f"Expected (net \"GND\") in result, got: {result}"
    assert '(net 0 "GND")' not in result, f"Old format (net 0 \"GND\") leaked into result: {result}"


def test_add_net_to_pad_preserves_pad_structure():
    """Patch should not corrupt the pad block — closing paren still present, pad content intact.
    Patch P1 (Phase 144 Wave 4)."""
    pad = '(pad "1" thru_hole circle (at 0 0) (size 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))'
    result = _add_net_to_pad(pad, "VCC")
    assert result.rstrip().endswith(")"), f"Result should end with closing paren: {result}"
    assert "(size 1.7)" in result, "Original pad fields should be preserved"
    assert "(drill 1.0)" in result, "Original pad fields should be preserved"


def test_add_net_to_pad_special_chars_in_name():
    """Net names with spaces or special chars should still be quoted correctly.
    Patch P1 (Phase 144 Wave 4)."""
    pad = '(pad "1" smd roundrect (at 0 0) (size 1 1) (layers "F.Cu" "F.Mask"))'
    result = _add_net_to_pad(pad, "Net-(R1-Pad1)")
    assert '(net "Net-(R1-Pad1)")' in result
