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

from kicad_agent.crossfile.pcb_populate import (
    _add_net_to_pad,
    _replace_property_value,
    dedupe_pad_nets_multi_unit,
    map_alphanumeric_pin_to_pad,
    instantiate_footprint,
)


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


# ---------------------------------------------------------------------------
# Patch P2: instantiate_footprint preserves full library fidelity
# ---------------------------------------------------------------------------

# Minimal .kicad_mod fixture matching KiCad 10 library format
_SAMPLE_KICAD_MOD = '''(footprint "Test_FP"
\t(version 20260206)
\t(generator "test")
\t(layer "F.Cu")
\t(descr "A test footprint")
\t(tags "test")
\t(property "Reference" "REF**"
\t\t(at 0 -1.5 0)
\t\t(layer "F.SilkS")
\t\t(effects (font (size 1 1) (thickness 0.15)))
\t)
\t(property "Value" "Test_FP"
\t\t(at 0 1.5 0)
\t\t(layer "F.Fab")
\t\t(effects (font (size 1 1) (thickness 0.15)))
\t)
\t(attr smd)
\t(fp_line (start -1 -0.5) (end 1 -0.5) (stroke (width 0.1) (type solid)) (layer "F.SilkS"))
\t(pad "1" smd roundrect
\t\t(at -0.5 0)
\t\t(size 0.5 0.5)
\t\t(layers "F.Cu" "F.Mask" "F.Paste")
\t)
\t(pad "2" smd roundrect
\t\t(at 0.5 0)
\t\t(size 0.5 0.5)
\t\t(layers "F.Cu" "F.Mask" "F.Paste")
\t)
\t(model ":/test.step"
\t\t(offset (xyz 0 0 0))
\t)
)
'''


def test_instantiate_footprint_preserves_library_elements():
    """instantiate_footprint must preserve descr, tags, attr, model, geometry.

    Patch P2 (Phase 144 Wave 4). The original implementation reconstructed the
    footprint block from scratch, losing library elements and causing
    kicad-cli DRC 'lib_footprint_mismatch' warnings on every footprint.
    """
    result = instantiate_footprint(
        fp_content=_SAMPLE_KICAD_MOD,
        lib_id="TestLib:Test_FP",
        ref="R1",
        value="10k",
        x=25.0,
        y=30.0,
        angle=0.0,
        layer="F.Cu",
        pad_nets={"1": "GND", "2": "+3V3"},
    )
    # Library fidelity elements preserved
    assert "(descr" in result, f"descr element lost: {result}"
    assert "(tags" in result, f"tags element lost: {result}"
    assert "(attr smd" in result, f"attr element lost: {result}"
    assert "(fp_line" in result, f"fp_line geometry lost: {result}"
    assert "(model" in result, f"model element lost: {result}"


def test_instantiate_footprint_uses_full_lib_id():
    """Footprint header must use the full lib_id, not just the footprint name.
    Patch P2 (Phase 144 Wave 4)."""
    result = instantiate_footprint(
        fp_content=_SAMPLE_KICAD_MOD,
        lib_id="TestLib:Test_FP",
        ref="R1",
        value="10k",
        x=25.0,
        y=30.0,
    )
    assert '(footprint "TestLib:Test_FP"' in result, (
        f"Expected full lib_id in header, got: {result.splitlines()[0] if result else 'empty'}"
    )


def test_instantiate_footprint_injects_uuid_and_position():
    """PCB footprint blocks need (uuid ...) and (at X Y ANGLE).
    Patch P2 (Phase 144 Wave 4)."""
    result = instantiate_footprint(
        fp_content=_SAMPLE_KICAD_MOD,
        lib_id="TestLib:Test_FP",
        ref="C1",
        value="100nF",
        x=45.5,
        y=67.0,
        angle=90.0,
    )
    assert '(uuid "' in result, "uuid not injected"
    assert "(at 45.5 67.0 90.0)" in result, f"position not injected correctly: {result}"


def test_instantiate_footprint_replaces_ref_and_value():
    """Reference and Value properties must use component ref/value, not library placeholders.
    Patch P2 (Phase 144 Wave 4)."""
    result = instantiate_footprint(
        fp_content=_SAMPLE_KICAD_MOD,
        lib_id="TestLib:Test_FP",
        ref="U7",
        value="NE5532",
        x=0.0,
        y=0.0,
    )
    assert '(property "Reference" "U7"' in result, f"Reference not replaced: {result}"
    assert '(property "Value" "NE5532"' in result, f"Value not replaced: {result}"
    assert "REF**" not in result, "Library placeholder REF** leaked into output"
    assert '"Test_FP"' not in result.split("Value")[1] if "Value" in result else True, (
        "Library footprint name leaked into Value property"
    )


def test_instantiate_footprint_injects_pad_nets():
    """Pad nets must be injected in KiCad 10 (net "NAME") format.
    Patch P2 (Phase 144 Wave 4) — combined with P1 format fix."""
    result = instantiate_footprint(
        fp_content=_SAMPLE_KICAD_MOD,
        lib_id="TestLib:Test_FP",
        ref="R1",
        value="10k",
        x=0.0,
        y=0.0,
        pad_nets={"1": "GND", "2": "+3V3"},
    )
    assert '(net "GND")' in result, f"Pad 1 net not injected: {result}"
    assert '(net "+3V3")' in result, f"Pad 2 net not injected: {result}"
    assert '(net 0 ' not in result, "Old (net 0 ...) format leaked"


def test_replace_property_value_replaces_value_only():
    """_replace_property_value must replace the value, not the property name.
    Patch P2 (Phase 144 Wave 4)."""
    content = '(property "Reference" "REF**" (at 0 0) (layer "F.SilkS"))'
    result = _replace_property_value(content, "Reference", "R5", "abc-123")
    assert '(property "Reference" "R5"' in result
    assert "REF**" not in result
    assert '(uuid "abc-123")' in result


def test_replace_property_value_adds_uuid_to_block():
    """_replace_property_value must inject (uuid ...) inside the property block.
    Patch P2 (Phase 144 Wave 4)."""
    content = '(property "Value" "OLD" (at 0 0) (layer "F.Fab"))'
    result = _replace_property_value(content, "Value", "NEW", "dead-beef")
    assert '(uuid "dead-beef")' in result
    # The uuid must be INSIDE the property block (before the closing paren)
    prop_block = result[result.index("(property"):result.rindex(")") + 1]
    assert '(uuid "dead-beef")' in prop_block


# ---------------------------------------------------------------------------
# Patch P3: alphanumeric pin name → numeric pad number mapping
# ---------------------------------------------------------------------------
# KiCad Q_NPN/Q_PNP symbols use pin names B/C/E. SOT-23 and SOT-223 footprints
# use numeric pad numbers 1/2/3. Without a mapping, populate silently skips
# these pads, leaving transistors unrouted.
# Verified mapping (Phase 144 Wave 5, from original analog-board.kicad_pcb
# cross-reference): SOT-23 B=1, E=2, C=3 (JEDEC TO-236).


def test_map_alphanumeric_pin_sot23_bce_to_123():
    """SOT-23 NPN transistor: B->1, E->2, C->3.
    Patch P3 (Phase 144 Wave 5). Derived from analog-board.kicad_pcb Q4
    where pin E -> net Q4C and pad 2 carries Q4C."""
    assert map_alphanumeric_pin_to_pad("B", "Package_TO_SOT_SMD:SOT-23") == "1"
    assert map_alphanumeric_pin_to_pad("E", "Package_TO_SOT_SMD:SOT-23") == "2"
    assert map_alphanumeric_pin_to_pad("C", "Package_TO_SOT_SMD:SOT-23") == "3"


def test_map_alphanumeric_pin_sot223_bce_to_123():
    """SOT-223-3_TabPin2 NPN: B->1, C->2(tab), E->3.
    Patch P3 (Phase 144 Wave 5)."""
    assert map_alphanumeric_pin_to_pad("B", "Package_TO_SOT_SMD:SOT-223-3_TabPin2") == "1"
    assert map_alphanumeric_pin_to_pad("C", "Package_TO_SOT_SMD:SOT-223-3_TabPin2") == "2"
    assert map_alphanumeric_pin_to_pad("E", "Package_TO_SOT_SMD:SOT-223-3_TabPin2") == "3"


def test_map_alphanumeric_pin_numeric_passthrough():
    """Numeric pin names pass through unchanged (no mapping needed).
    Patch P3 (Phase 144 Wave 5)."""
    assert map_alphanumeric_pin_to_pad("1", "Package_TO_SOT_SMD:SOT-23") == "1"
    assert map_alphanumeric_pin_to_pad("2", "Resistor_SMD:R_0805_2012Metric") == "2"
    assert map_alphanumeric_pin_to_pad("14", "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm") == "14"


def test_map_alphanumeric_pin_unknown_returns_none():
    """Unknown alphanumeric pins (no mapping available) return None.
    Caller should log a warning and skip the pad rather than crash.
    Patch P3 (Phase 144 Wave 5)."""
    assert map_alphanumeric_pin_to_pad("X", "Package_TO_SOT_SMD:SOT-23") is None
    assert map_alphanumeric_pin_to_pad("A", "Some_Unknown:Footprint") is None


def test_instantiate_footprint_maps_alphanumeric_pins_sot23():
    """instantiate_footprint must assign nets to SOT-23 pads when pad_nets
    uses B/C/E keys. Without P3, the pads would be silently skipped.
    Patch P3 (Phase 144 Wave 5)."""
    # SOT-23-like fixture with 3 numeric pads
    sot23_fixture = '''(footprint "SOT-23"
\t(version 20260206)
\t(layer "F.Cu")
\t(property "Reference" "REF**"
\t\t(at 0 -2.4 0)
\t\t(layer "F.SilkS")
\t)
\t(property "Value" "SOT-23"
\t\t(at 0 2.4 0)
\t\t(layer "F.Fab")
\t)
\t(attr smd)
\t(pad "1" smd roundrect
\t\t(at -0.95 -0.95)
\t\t(size 1.475 0.6)
\t\t(layers "F.Cu" "F.Mask" "F.Paste")
\t)
\t(pad "2" smd roundrect
\t\t(at -0.95 0.95)
\t\t(size 1.475 0.6)
\t\t(layers "F.Cu" "F.Mask" "F.Paste")
\t)
\t(pad "3" smd roundrect
\t\t(at 0.95 0)
\t\t(size 1.475 0.6)
\t\t(layers "F.Cu" "F.Mask" "F.Paste")
\t)
)
'''
    result = instantiate_footprint(
        fp_content=sot23_fixture,
        lib_id="Package_TO_SOT_SMD:SOT-23",
        ref="Q1",
        value="BC847C",
        x=50.0,
        y=60.0,
        pad_nets={"B": "BASE_NET", "E": "EMITTER_NET", "C": "COLLECTOR_NET"},
    )
    # Pad 1 = B, Pad 2 = E, Pad 3 = C
    assert '(net "BASE_NET")' in result, f"Pad 1 (B) net missing: {result}"
    assert '(net "EMITTER_NET")' in result, f"Pad 2 (E) net missing: {result}"
    assert '(net "COLLECTOR_NET")' in result, f"Pad 3 (C) net missing: {result}"


# ---------------------------------------------------------------------------
# Patch P4: multi-unit netlist deduplication
# ---------------------------------------------------------------------------
# Components like CD4066 export 5 unit instances (A-E) to the netlist.
# Unused units emit `unconnected-(U8-PadN)` entries which are APPENDED to the
# net blocks. The naive populate loop assigns the last matching entry to each
# pad, so phantom unconnected- entries overwrite real nets.
# Fix: prefer real nets over `unconnected-` entries when both exist.


def test_dedupe_pad_nets_prefers_real_over_unconnected():
    """When a pad has both a real net and unconnected- entries, keep the real net.
    Patch P4 (Phase 144 Wave 5). U8 CD4066 case: pad 1 has both
    /Preamp Stage/FB_AC and unconnected-(U8-Pad1) entries."""
    raw_pad_nets = {
        "1": [
            "/Preamp Stage/FB_AC",
            "unconnected-(U8-Pad1)",
            "unconnected-(U8-Pad1)_1",
            "unconnected-(U8-Pad1)_2",
        ],
        "2": [
            "/Preamp Stage/GAIN_SW",
            "unconnected-(U8-Pad2)",
            "unconnected-(U8-Pad2)_1",
        ],
        "13": [
            "/Preamp Stage/U8_CTRL",
            "unconnected-(U8-Pad13)",
        ],
        "14": ["+9V"],
        "7": ["+9V"],
    }
    result = dedupe_pad_nets_multi_unit(raw_pad_nets)
    assert result["1"] == "/Preamp Stage/FB_AC", f"Real net overwritten by phantom: {result['1']}"
    assert result["2"] == "/Preamp Stage/GAIN_SW"
    assert result["13"] == "/Preamp Stage/U8_CTRL"
    assert result["14"] == "+9V"
    assert result["7"] == "+9V"


def test_dedupe_pad_nets_keeps_unconnected_when_only_option():
    """When a pad has ONLY unconnected- entries (truly unused), keep the last one.
    Patch P4 (Phase 144 Wave 5). This is the correct behavior for genuinely
    unused pins on multi-unit ICs."""
    raw_pad_nets = {
        "3": [
            "unconnected-(U8-Pad3)",
            "unconnected-(U8-Pad3)_1",
        ],
        "4": ["unconnected-(U8-Pad4)"],
    }
    result = dedupe_pad_nets_multi_unit(raw_pad_nets)
    # These pads are genuinely unused — no real net to assign
    assert result["3"] == "unconnected-(U8-Pad3)_1"
    assert result["4"] == "unconnected-(U8-Pad4)"


def test_dedupe_pad_nets_single_entry_passthrough():
    """Pads with a single net entry pass through as the resolved net.
    Patch P4 (Phase 144 Wave 5). Input is {pad: [net]}, output is {pad: net}."""
    raw_pad_nets = {
        "1": ["GND"],
        "2": ["+3V3"],
        "3": ["SIG_IN"],
    }
    result = dedupe_pad_nets_multi_unit(raw_pad_nets)
    assert result == {"1": "GND", "2": "+3V3", "3": "SIG_IN"}


def test_dedupe_pad_nets_multiple_real_nets_keeps_first():
    """When a pad has multiple REAL net entries (shouldn't happen in a valid
    netlist, but defensive), keep the first one rather than crashing.
    Patch P4 (Phase 144 Wave 5)."""
    raw_pad_nets = {
        "1": ["NET_A", "NET_B", "unconnected-(X-Pad1)"],
    }
    result = dedupe_pad_nets_multi_unit(raw_pad_nets)
    assert result["1"] == "NET_A"
