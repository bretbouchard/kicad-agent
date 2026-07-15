#!/usr/bin/env python3
"""
Phase 234A Task 2: Python parity driver for Swift NativeERC vs Python native_erc.

Subcommands:
  parity-test --schematic PATH       Run both engines on a single file, print side-by-side
  parity-test --manifest PATH --sample N  Run on the first N entries of a manifest

For Swift invocation, Phase 234A creates the driver structure. Phase 234B will
fill in the Swift CLI invocation (build a small Swift harness that imports
NativeERC and prints JSON; or shell out via xcodebuild test).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Repo paths
REPO_ROOT = Path("/Users/bretbouchard/apps/volta")
PYTHON_SRC = REPO_ROOT / "src"
SWIFT_APP = REPO_ROOT / "macos-app"
PHASE_DIR = REPO_ROOT / ".planning" / "phases" / "234a-corpus-and-driver"
SWIFT_CLI_BIN = REPO_ROOT / ".planning" / "phases" / "234b-parity-execute" / "erc-cli"


# ---------------------------------------------------------------------------
# Python engine
# ---------------------------------------------------------------------------

def run_python_erc(schematic_path: Path) -> dict:
    """Invoke Python native_erc via in-process import.

    Adds the daemon source to sys.path so we don't need a venv.
    Returns a normalized dict.
    """
    sys.path.insert(0, str(PYTHON_SRC))
    from volta.validation.native_erc import run_native_erc

    try:
        result = run_native_erc(schematic_path)
        d = result.to_dict()
        return normalize_python_result(d)
    except Exception as e:
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "violations": [],
            "error_count": 0,
            "warning_count": 0,
            "passed": False,
        }


def normalize_python_result(raw: dict) -> dict:
    """Normalize Python native_erc output to a common shape.

    The Python NativeErcResult.to_dict() emits key `clean` (not `passed`).
    Map it to `passed` for parity with the Swift engine's output shape.
    """
    violations = raw.get("violations", []) or []
    return {
        "ok": True,
        "violations": [
            {
                "check_id": v.get("check_id", v.get("rule", "unknown")),
                "severity": v.get("severity", "error"),
                "ref": v.get("ref", v.get("component", "")),
                "net": v.get("net", ""),
                "message": v.get("message", ""),
            }
            for v in violations
        ],
        "error_count": raw.get("error_count", 0) or 0,
        "warning_count": raw.get("warning_count", 0) or 0,
        # native_erc.to_dict() uses "clean" — accept both for robustness.
        "passed": raw.get("passed", raw.get("clean", False)),
        "checks_run": raw.get("checks_run", []),
        "checks_skipped": raw.get("checks_skipped", []),
    }


# ---------------------------------------------------------------------------
# Swift engine (placeholder for Phase 234B)
# ---------------------------------------------------------------------------

def run_swift_erc(schematic_path: Path) -> dict:
    """Invoke Swift NativeERC via subprocess.

    Phase 234B: builds a Swift CLI harness that imports NativeERC and prints JSON.
    Invokes the binary at SWIFT_CLI_BIN, parses stdout JSON.
    """
    import subprocess

    if not SWIFT_CLI_BIN.exists():
        return {
            "ok": False,
            "error": f"swift_erc_binary_not_found: build it with `bash {REPO_ROOT}/.planning/phases/234b-parity-execute/scripts/build_erc_cli.sh`",
            "violations": [],
            "error_count": 0,
            "warning_count": 0,
            "passed": False,
            "pending": True,
        }

    try:
        proc = subprocess.run(
            [str(SWIFT_CLI_BIN), str(schematic_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"swift_erc_timeout: 30s exceeded for {schematic_path.name}",
            "violations": [],
            "error_count": 0,
            "warning_count": 0,
            "passed": False,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"swift_erc_subprocess_error: {type(e).__name__}: {e}",
            "violations": [],
            "error_count": 0,
            "warning_count": 0,
            "passed": False,
        }

    if proc.returncode != 0 and not proc.stdout.strip().startswith("{"):
        return {
            "ok": False,
            "error": f"swift_erc_exit_{proc.returncode}: {proc.stderr.strip()[:200]}",
            "violations": [],
            "error_count": 0,
            "warning_count": 0,
            "passed": False,
        }

    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        return {
            "ok": False,
            "error": f"swift_erc_invalid_json: {e}; stdout[:200]={proc.stdout[:200]!r}",
            "violations": [],
            "error_count": 0,
            "warning_count": 0,
            "passed": False,
        }

    return result


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def compare_results(python_result: dict, swift_result: dict) -> dict:
    """Compare two normalized results.

    Returns:
      {
        "agreed": bool,
        "python_passed": bool,
        "swift_passed": bool,
        "error_count_match": bool,
        "warning_count_match": bool,
        "violation_overlap": int,
        "fp_count": int,
        "fn_count": int,
        "notes": str,
      }
    """
    py_passed = python_result.get("passed", False)
    sw_passed = swift_result.get("passed", False)
    py_ec = python_result.get("error_count", 0)
    sw_ec = swift_result.get("error_count", 0)
    py_wc = python_result.get("warning_count", 0)
    sw_wc = swift_result.get("warning_count", 0)

    py_keys = {(v["check_id"], v.get("ref", ""), v.get("net", ""))
               for v in python_result.get("violations", [])}
    sw_keys = {(v["check_id"], v.get("ref", ""), v.get("net", ""))
               for v in swift_result.get("violations", [])}
    overlap = len(py_keys & sw_keys)
    fp = len(sw_keys - py_keys)
    fn = len(py_keys - sw_keys)

    notes_parts = []
    if swift_result.get("pending"):
        notes_parts.append("swift engine not yet wired (Phase 234B)")
    if not python_result.get("ok"):
        notes_parts.append(f"python engine error: {python_result.get('error', '')}")
    if py_ec != sw_ec:
        notes_parts.append(f"error_count diff: py={py_ec} sw={sw_ec}")
    if py_wc != sw_wc:
        notes_parts.append(f"warning_count diff: py={py_wc} sw={sw_wc}")

    return {
        "agreed": py_passed == sw_passed and py_ec == sw_ec,
        "python_passed": py_passed,
        "swift_passed": sw_passed,
        "error_count_match": py_ec == sw_ec,
        "warning_count_match": py_wc == sw_wc,
        "violation_overlap": overlap,
        "fp_count": fp,
        "fn_count": fn,
        "notes": "; ".join(notes_parts) if notes_parts else "ok",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_parity_test(args) -> int:
    """Run a parity test on a single schematic or a sample from a manifest."""
    targets: list[Path] = []

    if args.schematic:
        targets.append(Path(args.schematic))
    elif args.manifest:
        manifest = json.loads(Path(args.manifest).read_text())
        sample = manifest["schematics"][:args.sample]
        targets = [Path(s["absolute_path"]) for s in sample]
    else:
        print("error: provide --schematic or --manifest", file=sys.stderr)
        return 2

    results = []
    for sch in targets:
        py = run_python_erc(sch)
        sw = run_swift_erc(sch)
        cmp = compare_results(py, sw)
        results.append({
            "schematic": (str(sch.relative_to(REPO_ROOT))
                          if sch.is_relative_to(REPO_ROOT) else str(sch)),
            "python": py,
            "swift": sw,
            "comparison": cmp,
        })

    out = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "sample_count": len(results),
        "engine": {
            "python": "volta.validation.native_erc.run_native_erc",
            "swift": "NativeERC.run (Phase 234A: pending wire-up)",
        },
        "results": results,
    }

    if args.output:
        Path(args.output).write_text(json.dumps(out, indent=2))
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        print(json.dumps(out, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Swift vs Python ERC parity driver")
    sub = parser.add_subparsers(dest="cmd")

    pt = sub.add_parser("parity-test", help="Run parity test on one or more schematics")
    pt.add_argument("--schematic", help="Single .kicad_sch to test")
    pt.add_argument("--manifest", help="manifest.json with multiple schematics")
    pt.add_argument("--sample", type=int, default=3, help="Number from manifest (default 3)")
    pt.add_argument("--output", help="Write JSON to this file (else stdout)")

    args = parser.parse_args()
    if args.cmd == "parity-test":
        return cmd_parity_test(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
