"""Scale test: convert SchGen API-format circuits to SKIDL and test legibility.

Samples N circuits from the SchGen 8.4K dataset, converts each to SKIDL,
runs the SKIDL→schematic emitter, and runs ERC to verify the emitter
scales to real-world circuits.

Conversion: SchGen API → SKIDL
  add_schematic_symbol(lib, name, ref, value) → Part(lib, name, ref, value)
  connect_pins(ref1, pin1, ref2, pin2)        → net += part1[pin1], part2[pin2]
  add_label(text, ref)                         → Net(text)
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import skidl

_KICAD_SYMBOLS_DIR = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"
skidl.lib_search_paths[skidl.KICAD] = [_KICAD_SYMBOLS_DIR]

from kicad_agent.circuit_ir import circuit_to_kicad_sch


def schgen_to_skidl(code: str, name: str) -> skidl.Circuit | None:
    """Convert a SchGen API-format Python script to a skidl.Circuit.

    Returns None if conversion fails.
    """
    c = skidl.Circuit()
    c.name = name

    # Extract add_schematic_symbol calls.
    # Format: add_schematic_symbol(symbol_lib="Device", symbol_name="R",
    #          pos_x=..., pos_y=..., reference="R1", value="1k", ...)
    symbol_re = re.compile(
        r'add_schematic_symbol\s*\(\s*'
        r'symbol_lib="([^"]*)"\s*,\s*'
        r'symbol_name="([^"]*)"\s*,\s*'
        r'[^)]*?'
        r'reference="([^"]*)"\s*,?\s*'
        r'[^)]*?'
        r'value="([^"]*)"',
        re.DOTALL,
    )

    # Extract connect_pins calls.
    # Format: connect_pins("R1", "1", "R2", "2")
    # OR: connect_pins("LABEL_0", "1", "R1", "2")
    connect_re = re.compile(
        r'connect_pins\s*\(\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"',
    )

    # Extract add_label calls for net names.
    # Format: add_label(label_pos=[...], label_text="NAME", label_ref="NAME_0", ...)
    label_re = re.compile(
        r'add_label\s*\([^)]*?label_text="([^"]*)"\s*,?\s*[^)]*?label_ref="([^"]*)"',
        re.DOTALL,
    )

    with c:
        # Create parts.
        parts: dict[str, skidl.Part] = {}
        for m in symbol_re.finditer(code):
            lib, sym_name, ref, value = m.group(1), m.group(2), m.group(3), m.group(4)
            # Skip power symbols — SKIDL handles them as stub nets.
            if lib == "power":
                continue
            try:
                p = skidl.Part(lib, sym_name, value=value)
                p.ref = ref
                parts[ref] = p
            except Exception:
                pass  # Skip parts that can't be created

        # Create labels (nets with names).
        label_nets: dict[str, skidl.Net] = {}
        for m in label_re.finditer(code):
            text, ref = m.group(1), m.group(2)
            if text and text not in label_nets:
                # Clean net name (SchGen uses {slash} for /).
                clean = text.replace("{slash}", "/")
                try:
                    label_nets[ref] = skidl.Net(clean)
                except Exception:
                    pass

        # Wire connections.
        for m in connect_re.finditer(code):
            src_ref, src_pin, tgt_ref, tgt_pin = m.groups()
            # Handle label-as-source connections.
            if src_ref in label_nets and tgt_ref in parts:
                try:
                    label_nets[src_ref] += parts[tgt_ref][tgt_pin]
                except (KeyError, IndexError):
                    pass
            elif src_ref in parts and tgt_ref in parts:
                try:
                    net = skidl.Net(f"{src_ref}_{src_pin}_{tgt_ref}_{tgt_pin}")
                    net += parts[src_ref][src_pin], parts[tgt_ref][tgt_pin]
                except (KeyError, IndexError):
                    pass

    if not parts:
        return None
    return c


def run_erc(sch_path: Path) -> tuple[int, int]:
    """Run kicad-cli ERC, return (errors, warnings)."""
    import subprocess
    rpt_path = sch_path.parent / f"{sch_path.stem}-erc.rpt"
    try:
        result = subprocess.run(
            ["kicad-cli", "sch", "erc", str(sch_path), "-o", str(rpt_path)],
            capture_output=True, text=True, timeout=60,
        )
        if "Failed to load" in result.stderr:
            return -1, -1
        if rpt_path.exists():
            rpt = rpt_path.read_text()
            m = re.search(r"ERC messages:\s+(\d+)\s+Errors\s+(\d+)\s+Warnings\s+(\d+)", rpt)
            if m:
                return int(m.group(2)), int(m.group(3))
        return -1, -1
    except Exception:
        return -1, -1


def main() -> None:
    from huggingface_hub import hf_hub_download

    # Download SchGen dataset.
    path = hf_hub_download(
        repo_id="microsoft/SchGen_dataset",
        filename="SchGen_dataset.jsonl",
        repo_type="dataset",
    )
    with open(path) as f:
        examples = [json.loads(l) for l in f]

    print(f"SchGen dataset: {len(examples)} examples")

    # Sample N examples, evenly spaced.
    sample_size = 20
    step = len(examples) // sample_size
    sample = [examples[i] for i in range(0, len(examples), step)][:sample_size]
    print(f"Sampling {len(sample)} circuits (every {step}th)")

    out_dir = Path("/tmp/schgen_scale_test")
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    success = 0
    fail_convert = 0
    fail_emit = 0
    fail_erc = 0

    for i, ex in enumerate(sample):
        module = ex.get("meta", {}).get("module", f"example_{i}")
        code = next((m["content"] for m in ex["messages"] if m["role"] == "assistant"), "")
        if not code:
            continue

        # Convert to SKIDL.
        try:
            circuit = schgen_to_skidl(code, module)
            if circuit is None:
                fail_convert += 1
                results.append({"module": module, "status": "FAIL_CONVERT", "parts": 0})
                continue
        except Exception as e:
            fail_convert += 1
            results.append({"module": module, "status": f"FAIL_CONVERT: {e}"[:100], "parts": 0})
            continue

        n_parts = len(circuit.parts)

        # Emit schematic.
        try:
            sch_path = out_dir / f"schgen_{i:03d}.kicad_sch"
            t0 = time.perf_counter()
            circuit_to_kicad_sch(circuit, sch_path, use_sugiyama=True)
            emit_time = time.perf_counter() - t0
        except Exception as e:
            fail_emit += 1
            results.append({"module": module, "status": f"FAIL_EMIT: {e}"[:100], "parts": n_parts})
            continue

        # Run ERC.
        errors, warnings = run_erc(sch_path)
        if errors < 0:
            fail_erc += 1
            results.append({"module": module, "status": "FAIL_ERC", "parts": n_parts, "emit_time": emit_time})
            continue

        success += 1
        results.append({
            "module": module,
            "status": "OK",
            "parts": n_parts,
            "errors": errors,
            "warnings": warnings,
            "emit_time": round(emit_time, 3),
        })

    # Summary.
    print(f"\n{'='*70}")
    print(f"SCALE TEST RESULTS ({len(sample)} circuits)")
    print(f"{'='*70}")
    print(f"Success:        {success}/{len(sample)}")
    print(f"Fail convert:   {fail_convert}")
    print(f"Fail emit:      {fail_emit}")
    print(f"Fail ERC:       {fail_erc}")

    if success > 0:
        ok_results = [r for r in results if r["status"] == "OK"]
        parts_counts = [r["parts"] for r in ok_results]
        error_counts = [r["errors"] for r in ok_results]
        warn_counts = [r["warnings"] for r in ok_results]
        emit_times = [r["emit_time"] for r in ok_results]

        print(f"\nCircuit complexity:")
        print(f"  Parts:     min={min(parts_counts)}  median={sorted(parts_counts)[len(parts_counts)//2]}  max={max(parts_counts)}")
        print(f"\nERC results (successful circuits):")
        print(f"  Errors:    min={min(error_counts)}  median={sorted(error_counts)[len(error_counts)//2]}  max={max(error_counts)}")
        print(f"  Warnings:  min={min(warn_counts)}  median={sorted(warn_counts)[len(warn_counts)//2]}  max={max(warn_counts)}")
        print(f"\nPerformance:")
        print(f"  Emit time: min={min(emit_times):.3f}s  median={sorted(emit_times)[len(emit_times)//2]:.3f}s  max={max(emit_times):.3f}s")

    # Write detailed results.
    report_path = out_dir / "scale_test_report.json"
    report_path.write_text(json.dumps(results, indent=2))
    print(f"\nDetailed report: {report_path}")

    # Show some examples.
    print(f"\n{'='*70}")
    print("SAMPLE RESULTS")
    print(f"{'='*70}")
    print(f"{'Module':<50} {'Parts':>5} {'Errors':>7} {'Warns':>6} {'Time':>7}")
    print("-" * 80)
    for r in results[:15]:
        if r["status"] == "OK":
            print(f"{r['module'][:50]:<50} {r['parts']:>5} {r['errors']:>7} {r['warnings']:>6} {r['emit_time']:>6.3f}s")
        else:
            print(f"{r['module'][:50]:<50} {r['parts']:>5} {r['status'][:30]}")


if __name__ == "__main__":
    main()
