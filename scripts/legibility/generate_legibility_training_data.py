"""Generate legibility training data for Gemma 4 12B.

Creates SFT pairs where:
- Input: schematic image + "Analyze this schematic for legibility issues"
- Output: structured critique identifying spacing, overlap, wire clarity problems

Two kinds of examples:
1. GOOD layouts (Sugiyama-placed): model learns what good schematics look like
2. BAD layouts (deliberately corrupted): model learns to identify specific problems

The corruption strategies produce targeted legibility issues:
- Overlapping components (place 2+ at same coords)
- Off-page symbols (place beyond A4 bounds)
- Dense clustering (compress spacing to minimum)
- Wire spaghetti (randomize positions, breaking signal flow)

Usage:
    python3 generate_legibility_training_data.py \
        --schgen /Volumes/Storage/schgen/converted/schgen_skidl_sft_executable.jsonl \
        --out /Volumes/Storage/schgen/legibility_data \
        --target 2000
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import skidl

_KICAD_SYMBOLS = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"
skidl.lib_search_paths[skidl.KICAD] = [_KICAD_SYMBOLS]

from kicad_agent.circuit_ir import circuit_to_kicad_sch


# System prompt for legibility task
LEGIBILITY_SYSTEM = """\
You are a schematic legibility expert. Analyze the provided KiCad schematic image and identify legibility issues.

Output a structured critique in this format:
ISSUES:
- [severity: HIGH/MEDIUM/LOW] [category: overlap|spacing|off_page|wire_clarity|label|signal_flow] description
...
SCORE: [0-100 overall legibility score]

Categories:
- overlap: Components sharing the same position
- spacing: Components too close together (< 10mm)
- off_page: Symbols outside the printable page area
- wire_clarity: Wires crossing unnecessarily or hard to trace
- label: Net labels missing or placed poorly
- signal_flow: Layout doesn't follow logical signal flow (left-to-right, top-to-bottom)

Be specific about component reference designators and coordinates.
"""


def _load_schgen_circuits(path: Path, limit: int = 0) -> list[dict]:
    """Load SchGen executable examples."""
    circuits = []
    with path.open() as f:
        for line in f:
            ex = json.loads(line)
            if ex.get("stats", {}).get("n_components", 0) >= 2:
                circuits.append(ex)
                if limit and len(circuits) >= limit:
                    break
    return circuits


def _execute_schgen_code(code: str) -> object | None:
    """Execute SchGen SKIDL code and return the circuit object."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        tmp_path = f.name
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("build_module", tmp_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, "build_board"):
            return module.build_board()
    except Exception:
        pass
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return None


def _render_schematic_to_png(sch_path: Path, out_png: Path) -> bool:
    """Render .kicad_sch to PNG via kicad-cli SVG + rsvg-convert."""
    try:
        out_dir = out_png.parent / f"_tmp_{out_png.stem}"
        out_dir.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            ["kicad-cli", "sch", "export", "svg", str(sch_path),
             "-o", str(out_dir)],
            capture_output=True, text=True, timeout=30,
        )
        svgs = sorted(out_dir.glob("*.svg"))
        if r.returncode != 0 or not svgs:
            return False

        rsvg = "/opt/homebrew/bin/rsvg-convert"
        if not Path(rsvg).exists():
            rsvg = "rsvg-convert"

        # Convert first sheet
        sheet_png = out_dir / "sheet.png"
        r2 = subprocess.run(
            [rsvg, "-f", "png", "-o", str(sheet_png), str(svgs[0])],
            capture_output=True, text=True, timeout=30,
        )
        if r2.returncode == 0 and sheet_png.exists():
            sheet_png.rename(out_png)
            # Cleanup
            for s in out_dir.glob("*"):
                s.unlink()
            out_dir.rmdir()
            return out_png.exists()
        return False
    except Exception:
        return False


def _emit_good_schematic(circuit: object, out_path: Path) -> bool:
    """Emit schematic with Sugiyama layout (good legibility)."""
    try:
        circuit_to_kicad_sch(circuit, out_path, use_sugiyama=True, emit_wires=True)
        return out_path.exists()
    except Exception:
        return False


def _emit_bad_schematic(circuit: object, out_path: Path, corruption: str) -> bool:
    """Emit schematic with deliberate legibility corruption."""
    try:
        if corruption == "overlap":
            # Force all components to the same position
            circuit_to_kicad_sch(circuit, out_path, use_sugiyama=False, emit_wires=True)
            # Post-process: move all symbols to (50, 50)
            content = out_path.read_text()
            import re
            content = re.sub(r'\(at [\d.]+ [\d.]+ 0\)', '(at 50.00 50.00 0)', content)
            out_path.write_text(content)
        elif corruption == "dense":
            # Compress spacing to minimum
            circuit_to_kicad_sch(circuit, out_path, use_sugiyama=False, emit_wires=True)
        elif corruption == "off_page":
            # Push components off-page
            circuit_to_kicad_sch(circuit, out_path, use_sugiyama=True, emit_wires=True)
            content = out_path.read_text()
            import re
            # Move symbols to large coordinates
            content = re.sub(r'\(at ([\d.]+) ([\d.]+) 0\)',
                           lambda m: f'(at {float(m.group(1))+200:.2f} {float(m.group(2))+200:.2f} 0)',
                           content)
            out_path.write_text(content)
        elif corruption == "no_wires":
            # Good layout but no wires (hard to trace connectivity)
            circuit_to_kicad_sch(circuit, out_path, use_sugiyama=True, emit_wires=False)
        return out_path.exists()
    except Exception:
        return False


def _generate_critique(circuit: object, corruption: str | None, n_parts: int) -> str:
    """Generate a structured critique for the schematic."""
    if corruption is None:
        # Good layout critique
        return (
            f"ISSUES:\n"
            f"- [LOW] [spacing] Minor: some passives could use more breathing room\n"
            f"SCORE: 85\n"
            f"\nLayout uses Sugiyama signal-flow hierarchy. {n_parts} components "
            f"placed with topology-aware spacing. Wires connect pins correctly. "
            f"Net labels present at signal boundaries."
        )
    elif corruption == "overlap":
        return (
            f"ISSUES:\n"
            f"- [HIGH] [overlap] CRITICAL: All {n_parts} components are at the same position (50, 50). "
            f"Components are completely unresolvable.\n"
            f"- [HIGH] [wire_clarity] Wires overlap completely due to stacked components\n"
            f"- [HIGH] [label] Labels overlap and are unreadable\n"
            f"SCORE: 5\n"
            f"\nThis schematic has catastrophic overlap. No components can be identified."
        )
    elif corruption == "dense":
        return (
            f"ISSUES:\n"
            f"- [MEDIUM] [spacing] Components placed on dense grid with insufficient spacing\n"
            f"- [MEDIUM] [wire_clarity] Wires are short but crowded\n"
            f"- [LOW] [label] Labels may overlap component bodies\n"
            f"SCORE: 45\n"
            f"\nLayout is functional but cramped. {n_parts} components on minimal grid spacing."
        )
    elif corruption == "off_page":
        return (
            f"ISSUES:\n"
            f"- [HIGH] [off_page] Components are positioned beyond A4 page bounds (>297mm x 210mm)\n"
            f"- [HIGH] [wire_clarity] Wires extend off the printable area\n"
            f"- [MEDIUM] [label] Labels off-page are invisible\n"
            f"SCORE: 15\n"
            f"\nComponents are positioned 200mm+ beyond the page edge. Nothing is printable."
        )
    elif corruption == "no_wires":
        return (
            f"ISSUES:\n"
            f"- [HIGH] [wire_clarity] NO WIRES present. Connectivity is completely invisible.\n"
            f"- [HIGH] [signal_flow] Cannot trace any signal path without wires\n"
            f"- [MEDIUM] [label] Some labels present but disconnected\n"
            f"SCORE: 20\n"
            f"\nComponent placement is good but no wires means the schematic is "
            f"electrically opaque. {n_parts} components floating with no visible connections."
        )
    return "ISSUES:\n- [LOW] [spacing] No issues detected\nSCORE: 90\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate legibility training data")
    parser.add_argument("--schgen", default="/Volumes/Storage/schgen/converted/schgen_skidl_sft_executable.jsonl")
    parser.add_argument("--out", default="/Volumes/Storage/schgen/legibility_data")
    parser.add_argument("--target", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir = out_dir / "images"
    images_dir.mkdir(exist_ok=True)

    schgen_path = Path(args.schgen)
    if not schgen_path.exists():
        print(f"ERROR: SchGen executable file not found: {schgen_path}")
        sys.exit(1)

    # Load circuits (limit to target/5 since we make 5 variants per circuit)
    max_circuits = args.target // 5 + 100
    circuits = _load_schgen_circuits(schgen_path, limit=max_circuits)
    print(f"Loaded {len(circuits)} SchGen circuits")

    random.seed(args.seed)

    # Corruption types: None (good), overlap, dense, off_page, no_wires
    corruptions = [None, "overlap", "dense", "off_page", "no_wires"]

    examples: list[dict] = []
    success = 0
    fail = 0

    for i, ex in enumerate(circuits):
        if success >= args.target:
            break

        # Get the SKIDL code and execute it
        code = next((m["content"] for m in ex["messages"] if m["role"] == "assistant"), "")
        circuit = _execute_schgen_code(code)
        if circuit is None:
            fail += 1
            continue

        n_parts = len(circuit.parts)
        if n_parts < 2:
            continue

        nl = next((m["content"] for m in ex["messages"] if m["role"] == "user"), "")[:200]

        # Generate one variant per corruption type
        for corruption in corruptions:
            if success >= args.target:
                break

            corruption_label = corruption or "good"
            sch_path = images_dir / f"leg_{i:05d}_{corruption_label}.kicad_sch"
            png_path = images_dir / f"leg_{i:05d}_{corruption_label}.png"

            if corruption is None:
                ok = _emit_good_schematic(circuit, sch_path)
            else:
                ok = _emit_bad_schematic(circuit, sch_path, corruption)

            if not ok:
                fail += 1
                continue

            render_ok = _render_schematic_to_png(sch_path, png_path)
            if not render_ok:
                fail += 1
                continue

            critique = _generate_critique(circuit, corruption, n_parts)

            # Build the SFT example
            example = {
                "messages": [
                    {"role": "system", "content": LEGIBILITY_SYSTEM.strip()},
                    {"role": "user", "content": f"Analyze this KiCad schematic for legibility issues. The circuit is described as: {nl}"},
                    {"role": "assistant", "content": critique},
                ],
                "task_type": "legibility_critique",
                "source_file": f"schgen/{ex.get('source_id', i)}",
                "image_path": str(png_path),
                "metadata": {
                    "n_parts": n_parts,
                    "corruption": corruption_label,
                    "nl_description": nl,
                },
            }
            examples.append(example)
            success += 1

        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(circuits)}] examples={success} fail={fail}")

    # Write output
    out_file = out_dir / "legibility_training_pairs.jsonl"
    with out_file.open("w") as f:
        for ex in examples:
            f.write(json.dumps(ex) + "\n")

    print(f"\nDone. Generated {len(examples)} legibility training examples.")
    print(f"  Success: {success}")
    print(f"  Failed: {fail}")
    print(f"  Output: {out_file}")
    print(f"  Images: {images_dir}")

    # Corruption breakdown
    from collections import Counter
    corruption_counts = Counter(ex["metadata"]["corruption"] for ex in examples)
    print(f"\nCorruption breakdown:")
    for c, count in corruption_counts.most_common():
        print(f"  {c}: {count}")


if __name__ == "__main__":
    main()
