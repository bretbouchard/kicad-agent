#!/usr/bin/env python3
"""
Phase 234A Task 1: Stage KiCad schematic corpus and emit manifest.

Scans fixture directories for .kicad_sch files, computes SHA256, and writes
manifest.json. Uses seed=42 for reproducibility. Targets >=100 schematics
(we currently have 107 in the local fixture tree).
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path("/Users/bretbouchard/apps/volta")
PHASE_DIR = REPO_ROOT / ".planning" / "phases" / "234a-corpus-and-driver"
CORPUS_DIR = PHASE_DIR / "corpus"
MANIFEST_PATH = CORPUS_DIR / "manifest.json"

FIXTURE_DIRS = [
    REPO_ROOT,  # x64-smart-grid.kicad_sch, x64-test.kicad_sch at repo root
    REPO_ROOT / "volta-0.1.0" / "tests" / "fixtures",
    REPO_ROOT / "volta-0.1.0" / "tests" / "data",
    REPO_ROOT / "src" / "volta" / "tests" / "fixtures",
    REPO_ROOT / "tests" / "fixtures",
    REPO_ROOT / "tests" / "data",
    REPO_ROOT / "output" / "legibility",
]

SEED = 42
TARGET = 1000  # plan target; we accept whatever's available


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    schematics: list[dict] = []
    for fdir in FIXTURE_DIRS:
        if not fdir.exists():
            continue
        for sch in fdir.rglob("*.kicad_sch"):
            schematics.append({
                "path": str(sch.relative_to(REPO_ROOT)),
                "absolute_path": str(sch),
                "sha256": sha256(sch),
                "size_bytes": sch.stat().st_size,
                "source_dir": str(fdir.relative_to(REPO_ROOT)),
            })

    # Dedupe by sha256 (some fixtures may be identical copies)
    by_hash: dict[str, dict] = {}
    for s in schematics:
        by_hash.setdefault(s["sha256"], s)
    deduped = list(by_hash.values())

    # Reproducible shuffle
    rng = random.Random(SEED)
    rng.shuffle(deduped)
    selected = deduped[:TARGET]

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": "234a-01",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "seed": SEED,
        "count": len(selected),
        "raw_count": len(schematics),
        "dedup_count": len(deduped),
        "fixture_dirs": [str(p.relative_to(REPO_ROOT)) for p in FIXTURE_DIRS if p.exists()],
        "schematics": selected,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))

    print(f"Staged {len(selected)} schematics (raw={len(schematics)}, dedup={len(deduped)})")
    print(f"Manifest: {MANIFEST_PATH.relative_to(REPO_ROOT)}")
    print(f"All have SHA256: {all('sha256' in s and len(s['sha256']) == 64 for s in selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
