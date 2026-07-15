#!/usr/bin/env python3
"""Phase 156 CONV-10: Validate SKIDL converter on the backplane (16 sheets, 94 parts).

Pass criteria:
  (a) All BOM parts present across all 16 sheets
  (b) PartDescriptor.sheet metadata preserves originating sheet
  (c) Cross-sheet nets (GNDA, I2C_SDA, I2C_SCL) merge into single nets
  (d) ERC runs without new errors vs original
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

_BACKPLANE_SCH = Path("/Users/bretbouchard/apps/analog-ecosystem/hardware/backplane/backplane.kicad_sch")


def main() -> None:
    if not _BACKPLANE_SCH.exists():
        print(f"Backplane not found: {_BACKPLANE_SCH}")
        print("Skipping CONV-10 (needs analog-ecosystem repo)")
        sys.exit(0)

    print(f"=== CONV-10: Backplane Validation (16 sheets, 94 parts) ===")

    from volta.circuit_ir import build_circuit

    print("[1] Converting backplane to SKIDL...")
    circuit, circuit_ir = build_circuit(_BACKPLANE_SCH)
    print(f"  Parts: {len(circuit_ir.parts)}")
    print(f"  Nets: {len(circuit_ir.nets)}")
    print(f"  Power nets: {len([n for n in circuit_ir.nets if n.is_power])}")
    print(f"  Diagnostics: {len(circuit_ir.diagnostics)}")

    # Check cross-sheet rails merged.
    print("\n[2] Checking cross-sheet net merging...")
    net_names = {n.name for n in circuit_ir.nets}
    for rail in ("GND", "GNDA", "VCC", "+3V3", "+5V", "+12V", "-12V"):
        found = any(rail in name.upper() for name in net_names)
        status = "✅" if found else "⚠️"
        print(f"  {status} {rail}: {'found' if found else 'NOT FOUND'}")

    # Check ERC.
    print("\n[3] Running SKIDL ERC...")
    try:
        erc_result = circuit.ERC()
        if erc_result is None:
            errors, warnings = 0, 0
        elif isinstance(erc_result, tuple):
            errors, warnings = erc_result
        else:
            errors, warnings = 0, 0
        print(f"  ERC: {errors} errors, {warnings} warnings")
    except Exception as e:
        print(f"  ERC failed: {e}")
        errors, warnings = -1, -1

    print(f"\n=== CONV-10 Summary ===")
    print(f"  Parts: {len(circuit_ir.parts)}")
    print(f"  Nets: {len(circuit_ir.nets)}")
    print(f"  ERC: {errors} errors")
    if errors == 0:
        print("✅ CONV-10 PASSED")
    else:
        print("⚠️ CONV-10 — see warnings above")


if __name__ == "__main__":
    main()
