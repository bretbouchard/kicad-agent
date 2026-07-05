#!/usr/bin/env python3
"""Generate the astable_555 test fixture (ERC-clean, 0 errors).

Uses the SKIDL→KiCad bridge (Phase 156 circuit_ir) to produce a valid
.kicad_sch from a SKIDL circuit description. The output passes KiCad 10
ERC with 0 errors — the first ERC-clean fixture in the test suite.

Circuit: 555 timer astable multivibrator with LED output.
  - U1: NE555P timer IC
  - R1 (10k), R2 (100k): timing resistors
  - R3 (330): LED current limit
  - C1 (10uF): timing capacitor
  - C2 (100nF): CTRL bypass
  - D1: LED
  - PWR_FLAG × 2, VCC, GND power symbols

Usage:
    KICAD_SYMBOL_DIR=/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/ \
    python3 scripts/generate_555_fixture.py
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

# Ensure KiCad symbol library is findable
_SYM_DIR = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/"
for v in ("KICAD_SYMBOL_DIR", "KICAD8_SYMBOL_DIR", "KICAD9_SYMBOL_DIR",
          "KICAD7_SYMBOL_DIR", "KICAD6_SYMBOL_DIR"):
    os.environ.setdefault(v, _SYM_DIR)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import skidl
skidl.lib_search_paths[skidl.KICAD] = [_SYM_DIR]

OUT_DIR = Path(__file__).resolve().parent.parent / "tests/fixtures/astable_555"


def generate() -> Path:
    with skidl.Circuit(name="astable_555") as ckt:
        u1 = skidl.Part("Timer", "NE555P", circuit=ckt)
        r1 = skidl.Part("Device", "R", circuit=ckt, value="10k")
        r2 = skidl.Part("Device", "R", circuit=ckt, value="100k")
        r3 = skidl.Part("Device", "R", circuit=ckt, value="330")
        c1 = skidl.Part("Device", "C", circuit=ckt, value="10uF")
        c2 = skidl.Part("Device", "C", circuit=ckt, value="100nF")
        d1 = skidl.Part("Device", "LED", circuit=ckt)
        pwr_vcc = skidl.Part("power", "PWR_FLAG", circuit=ckt)
        pwr_gnd = skidl.Part("power", "PWR_FLAG", circuit=ckt)
        vcc_sym = skidl.Part("power", "VCC", circuit=ckt)
        gnd_sym = skidl.Part("power", "GND", circuit=ckt)

        vcc = skidl.Net("+VCC", circuit=ckt)
        gnd = skidl.Net("GND", circuit=ckt)

        vcc += vcc_sym[1], pwr_vcc[1], u1['VCC'], r1[1], u1['4']
        gnd += gnd_sym[1], pwr_gnd[1], u1['GND']
        r1[2] += r2[1]
        r2[2] += u1['DISCH'], u1['THRES'], u1['TRIG'], c1[1]
        c1[2] += gnd
        u1['CONT'] += c2[1]
        c2[2] += gnd
        u1['OUT'] += r3[1]
        r3[2] += d1['A']
        d1['K'] += gnd

        from kicad_agent.circuit_ir.skidl_to_kicad import circuit_to_kicad_sch
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = circuit_to_kicad_sch(ckt, OUT_DIR / "astable_555.kicad_sch", emit_wires=True)

        # Write minimal .kicad_pro so kicad-cli can load it
        pro_path = OUT_DIR / "astable_555.kicad_pro"
        pro_path.write_text(
            '{"board": {}, "schematic": {"drawing": {"default_line_thickness": 6.0, '
            '"default_text_size": 1.27}}, "meta": {"filename": "astable_555.kicad_pro", '
            '"version": 1}, "nets": []}'
        )
        return out


if __name__ == "__main__":
    out = generate()
    print(f"Generated: {out} ({out.stat().st_size} bytes)")
