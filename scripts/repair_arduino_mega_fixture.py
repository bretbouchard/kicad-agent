#!/usr/bin/env python3
"""Repair Arduino_Mega fixture: malformed placed symbols (one-shot).

Phase 108 Task 2 follow-up (Bead volta-25). The Arduino_Mega
fixture accumulated corrupt symbols across multiple generation scripts.
KiCad 10's strict parser rejects symbols missing required fields:
``(dnp no)``, non-empty ``(property "Value" ...)``, ``(pin ...)`` UUID
blocks, ``(instances ...)``, and rotation on ``(at X Y R)``.

This script delegates to the canonical normalizer at
``volta.schematic_autolayout.symbol_normalizer`` — the SAME module
the autolayout pipeline uses internally. One source of truth for the
repair logic; this script is just a CLI wrapper for one-off fixture repair.

Idempotent: re-running on an already-normalized file is a no-op.

Usage:
    python3 scripts/repair_arduino_mega_fixture.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add src to path so the import works when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from volta.schematic_autolayout.symbol_normalizer import normalize_placed_symbols

FIXTURE = Path(__file__).resolve().parent.parent / "tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_sch"


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair malformed placed symbols in Arduino_Mega fixture")
    parser.add_argument('--dry-run', action='store_true', help='Show what would be repaired without writing')
    parser.add_argument('--fixture', type=Path, default=FIXTURE, help='Fixture file to repair')
    args = parser.parse_args()

    fixture: Path = args.fixture
    print(f"Repairing: {fixture}")
    content = fixture.read_text()
    new_content, stats = normalize_placed_symbols(content)

    print(f"  symbols_normalized: {stats.symbols_normalized}")
    print(f"  wildcards_annotated: {stats.wildcards_annotated} (R? -> R1, R2, ...)")
    print(f"  rotation_fixes:     {stats.rotation_fixes} ((at X Y) -> (at X Y 0))")
    print(f"  instances_added:    {stats.instances_added}")
    print(f"  pin_uuids_added:    {stats.pin_uuids_added}")
    print(f"  dnp_added:          {stats.dnp_added}")
    print(f"  values_populated:   {stats.values_populated}")

    if stats.symbols_normalized == 0:
        print("  (no malformed symbols found — already repaired)")
        return 0

    if args.dry_run:
        print("  (dry-run — no file written)")
    else:
        fixture.write_text(new_content)
        print(f"  written to:         {fixture}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
