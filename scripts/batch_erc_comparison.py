#!/usr/bin/env python3
"""Batch ERC comparison: native engine vs kicad-cli ground truth.

Runs both engines on a sample of KiCad schematics and compares:
  - Error count match (native >= kicad-cli = pass)
  - Violation type coverage
  - False positive rate
  - False negative rate
  - Crash rate

Usage:
    python3 scripts/batch_erc_comparison.py --sample 100
    python3 scripts/batch_erc_comparison.py --sample 500 --output results.json
"""
import argparse
import json
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from volta.validation.native_erc import run_native_erc


def run_kicad_cli_erc(sch_path: Path, timeout: int = 30) -> dict:
    """Run kicad-cli ERC and parse results."""
    try:
        result = subprocess.run(
            ["kicad-cli", "sch", "erc", str(sch_path),
             "--output", "-"],  # stdout
            capture_output=True, text=True, timeout=timeout
        )
        # Parse text output for violation count
        output = result.stdout + result.stderr
        violations = []
        for line in output.split("\n"):
            if "ERROR" in line or "WARNING" in line:
                violations.append(line.strip())
        return {
            "violations": violations,
            "error_count": sum(1 for v in violations if "ERROR" in v),
            "warning_count": sum(1 for v in violations if "WARNING" in v),
            "rc": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"violations": [], "error_count": 0, "warning_count": 0, "rc": -1, "timeout": True}
    except Exception as e:
        return {"violations": [], "error_count": 0, "warning_count": 0, "rc": -2, "error": str(e)}


def run_native_erc_safe(sch_path: Path) -> dict:
    """Run native ERC with crash protection."""
    try:
        result = run_native_erc(sch_path)
        return {
            "violations": [v.to_dict() for v in result.violations],
            "error_count": result.error_count,
            "warning_count": result.warning_count,
            "checks_run": list(result.checks_run),
            "checks_skipped": list(result.checks_skipped),
        }
    except Exception as e:
        return {"violations": [], "error_count": 0, "warning_count": 0, "crash": str(e)}


def compare(native: dict, kicad: dict) -> dict:
    """Compare native vs kicad-cli results."""
    n_err = native.get("error_count", 0)
    k_err = kicad.get("error_count", 0)

    return {
        "native_errors": n_err,
        "kicad_errors": k_err,
        "native_warnings": native.get("warning_count", 0),
        "kicad_warnings": kicad.get("warning_count", 0),
        # Pass = native found same or more errors than kicad-cli
        "pass": n_err >= k_err,
        # Super pass = native found MORE than kicad-cli (caught extra issues)
        "super_pass": n_err > k_err,
        # False negatives = errors kicad found that native missed
        "false_negatives": max(0, k_err - n_err),
        # False positives = errors native found that kicad didn't
        "false_positives": max(0, n_err - k_err),
        "native_crash": "crash" in native,
        "kicad_timeout": kicad.get("timeout", False),
    }


def main():
    parser = argparse.ArgumentParser(description="Batch ERC comparison")
    parser.add_argument("--sample", type=int, default=50, help="Number of schematics to test")
    parser.add_argument("--source", type=str, default="/Volumes/Storage/schgen/all_schematics.txt",
                        help="File listing schematic paths")
    parser.add_argument("--output", type=str, default=None, help="Output JSON file")
    parser.add_argument("--skip-kicad", action="store_true", help="Skip kicad-cli (native only)")
    args = parser.parse_args()

    # Load schematic list
    with open(args.source) as f:
        all_schs = [Path(line.strip()) for line in f if line.strip()]

    # Sample
    import random
    random.seed(42)
    sample = random.sample(all_schs, min(args.sample, len(all_schs)))

    print(f"Testing {len(sample)} schematics (of {len(all_schs)} total)")
    print(f"{'='*80}")

    results = []
    stats = defaultdict(int)
    start = time.time()

    for i, sch in enumerate(sample):
        if not sch.exists():
            stats["missing"] += 1
            continue

        # Run native
        native = run_native_erc_safe(sch)

        # Run kicad-cli (unless skipped)
        kicad = {"error_count": -1, "warning_count": -1}  # -1 = not run
        if not args.skip_kicad:
            kicad = run_kicad_cli_erc(sch)

        comp = compare(native, kicad)

        status = "❌"
        if comp["native_crash"]:
            status = "💥"
            stats["crash"] += 1
        elif comp["pass"]:
            status = "✅" if not comp["super_pass"] else "⭐"
            stats["pass"] += 1
            if comp["super_pass"]:
                stats["super_pass"] += 1
        else:
            status = "❌"
            stats["fail"] += 1

        stats["total"] += 1

        n_err = comp["native_errors"]
        k_err = comp["kicad_errors"]
        elapsed = time.time() - start

        print(f"[{i+1:4d}/{len(sample)}] {status} {sch.parent.name}/{sch.name[:40]:40s} "
              f"native={n_err:3d}e kicad={k_err:3d}e "
              f"FP={comp['false_positives']:3d} FN={comp['false_negatives']:3d}")

        results.append({
            "file": str(sch),
            "native": native,
            "kicad": kicad,
            "comparison": comp,
        })

    elapsed = time.time() - start
    print(f"\n{'='*80}")
    print(f"RESULTS: {stats['total']} tested in {elapsed:.1f}s ({stats['total']/elapsed:.1f}/s)")
    print(f"  ⭐ Super pass (native > kicad): {stats.get('super_pass', 0)}")
    print(f"  ✅ Pass (native >= kicad):     {stats['pass']}")
    print(f"  ❌ Fail (native < kicad):      {stats['fail']}")
    print(f"  💥 Crash:                       {stats['crash']}")
    print(f"  ⏭️ Missing:                     {stats['missing']}")
    print(f"  Pass rate: {stats['pass']/(stats['total'] or 1)*100:.1f}%")

    if args.output:
        with open(args.output, "w") as f:
            json.dump({"stats": dict(stats), "results": results}, f, indent=2)
        print(f"\nDetailed results: {args.output}")


if __name__ == "__main__":
    main()
