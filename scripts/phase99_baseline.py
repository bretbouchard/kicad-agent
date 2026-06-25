#!/usr/bin/env python3
"""Phase 99 SC-4: Freerouting baseline metrics across 3 fixture boards.

Collects per-fixture routing metrics:
  - total_nets: count of routable nets in the source PCB
  - routed_nets: distinct nets appearing in the SES output
  - via_count: vias in the SES output
  - total_trace_length_mm: sum of Euclidean segment lengths
  - drc_pass: True if kicad-cli pcb drc reports zero unconnected_items
  - drc_unconnected: count of unconnected_items violations (post-filter)

Usage:
    python3 scripts/phase99_baseline.py
    python3 scripts/phase99_baseline.py --output phase99_baseline.md
    python3 scripts/phase99_baseline.py --quick   # smd_test_board only
    python3 scripts/phase99_baseline.py --json    # JSON for Phase 100 dispatch

Exits 0 when Freerouting is available and all fixtures run; exits 1 when
Freerouting JAR / Java is missing (so CI can distinguish env-missing from
real failures).
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kicad_agent.routing.freerouting import (
    import_ses_into_pcb,
    is_freerouting_available,
    parse_ses,
    route_with_freerouting,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_FIXTURES = [
    _REPO_ROOT / "tests" / "fixtures" / "smd_test_board.kicad_pcb",
    _REPO_ROOT / "tests" / "fixtures" / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_pcb",
    _REPO_ROOT / "tests" / "fixtures" / "phase99_synthetic_4layer_mixedsignal.kicad_pcb",
]


@dataclass
class FixtureMetrics:
    name: str
    total_nets: int
    routed_nets: int
    via_count: int
    total_trace_length_mm: float
    drc_pass: bool
    drc_unconnected: int
    error: str = ""

    @property
    def completion_pct(self) -> float:
        if self.total_nets == 0:
            return 0.0
        return round(100.0 * self.routed_nets / self.total_nets, 1)


def _count_routable_nets(pcb_content: str) -> int:
    """Count distinct named nets in the PCB (excludes empty net 0)."""
    import re
    names = set()
    for m in re.finditer(r'\(net\s+\d+\s+"([^"]+)"', pcb_content):
        names.add(m.group(1))
    return len(names)


def _total_trace_length_mm(ses_text: str) -> float:
    result = parse_ses(ses_text)
    total = 0.0
    for wire in result.wires:
        for i in range(len(wire.points) - 1):
            x1, y1 = wire.points[i]
            x2, y2 = wire.points[i + 1]
            total += math.hypot(x2 - x1, y2 - y1)
    return round(total, 2)


def _filter_false_positives(violations: list[dict]) -> list[dict]:
    """Filter Phase 26 Device:R/C off-grid + library-lookup noise."""
    filtered = []
    for v in violations:
        desc = str(v.get("description", ""))
        vtype = str(v.get("type", ""))
        full = f"{vtype} {desc}"
        if "3.81" in full or "off-grid" in full.lower():
            continue
        if vtype in ("lib_footprint_issues", "lib_footprint_mismatch"):
            continue
        filtered.append(v)
    return filtered


def _run_drc(temp_pcb: Path) -> tuple[bool, int]:
    """Run kicad-cli pcb drc; return (drc_loaded, unconnected_count).

    Returns (False, -1) when kicad-cli cannot load the board (structural
    issue). Returns (True, N) when the report parses, N = unconnected count.
    """
    out_path = temp_pcb.with_suffix(".drc.json")
    try:
        result = subprocess.run(
            [
                "kicad-cli", "pcb", "drc", str(temp_pcb),
                "--output", str(out_path),
                "--format", "json",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, -1
    if result.returncode != 0 or not out_path.exists():
        return False, -1
    try:
        report = json.loads(out_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False, -1
    violations = _filter_false_positives(report.get("violations", []))
    unconnected = sum(
        1 for v in violations
        if v.get("type") == "unconnected_items"
        or "unconnected" in v.get("description", "").lower()
    )
    return True, unconnected


def _collect_metrics(fixture: Path, max_passes: int = 3) -> FixtureMetrics:
    """Route a single fixture and collect all metrics."""
    name = fixture.stem
    if not fixture.exists():
        return FixtureMetrics(
            name=name, total_nets=0, routed_nets=0, via_count=0,
            total_trace_length_mm=0.0, drc_pass=False, drc_unconnected=-1,
            error=f"Fixture not found: {fixture}",
        )
    pcb_content = fixture.read_text(encoding="utf-8")
    total_nets = _count_routable_nets(pcb_content)
    try:
        route_result = route_with_freerouting(fixture, max_passes=max_passes)
    except Exception as exc:
        return FixtureMetrics(
            name=name, total_nets=total_nets, routed_nets=0, via_count=0,
            total_trace_length_mm=0.0, drc_pass=False, drc_unconnected=-1,
            error=f"Route exception: {exc}",
        )
    if not route_result.success or route_result.ses_path is None:
        return FixtureMetrics(
            name=name, total_nets=total_nets, routed_nets=0, via_count=0,
            total_trace_length_mm=0.0, drc_pass=False, drc_unconnected=-1,
            error=f"Freerouting failed: {(route_result.stderr or '')[:150]}",
        )
    ses_text = route_result.ses_path.read_text(encoding="utf-8")
    parsed = parse_ses(ses_text)
    routed_nets = len({w.net for w in parsed.wires if w.net})
    via_count = len(parsed.vias)
    trace_len = _total_trace_length_mm(ses_text)
    # DRC round-trip
    drc_pass = False
    drc_unconnected = -1
    try:
        routed_pcb, _ = import_ses_into_pcb(route_result.ses_path, pcb_content)
        with tempfile.NamedTemporaryFile(
            suffix=".kicad_pcb", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(routed_pcb)
            temp_path = Path(f.name)
        try:
            drc_loaded, drc_unconnected = _run_drc(temp_path)
            drc_pass = drc_loaded and drc_unconnected == 0
            if not drc_loaded:
                drc_unconnected = -1
        finally:
            temp_path.unlink(missing_ok=True)
            temp_path.with_suffix(".drc.json").unlink(missing_ok=True)
    except Exception:
        drc_pass = False
        drc_unconnected = -1
    return FixtureMetrics(
        name=name, total_nets=total_nets, routed_nets=routed_nets,
        via_count=via_count, total_trace_length_mm=trace_len,
        drc_pass=drc_pass, drc_unconnected=drc_unconnected,
    )


def _render_markdown(metrics: list[FixtureMetrics]) -> str:
    """Render a markdown table from collected metrics."""
    lines = [
        "# Phase 99 Freerouting Baseline Metrics",
        "",
        f"Generated: Phase 99-03 SC-4",
        "",
        "| Fixture | Total Nets | Routed Nets | Completion % | Via Count | Trace Length (mm) | DRC Pass | Unconnected |",
        "|---------|------------|-------------|--------------|-----------|-------------------|----------|-------------|",
    ]
    for m in metrics:
        if m.error:
            lines.append(
                f"| {m.name} | {m.total_nets} | - | - | - | - | ERROR | - |"
            )
            lines.append(f"  _error: {m.error}_")
        else:
            lines.append(
                f"| {m.name} | {m.total_nets} | {m.routed_nets} | "
                f"{m.completion_pct}% | {m.via_count} | "
                f"{m.total_trace_length_mm:.2f} | "
                f"{'PASS' if m.drc_pass else 'FAIL'} | "
                f"{m.drc_unconnected} |"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Output file (default: stdout)",
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Only run smd_test_board (fast iteration)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit JSON array of FixtureMetrics (for Phase 100 dispatch)",
    )
    parser.add_argument(
        "--passes", type=int, default=3,
        help="Max Freerouting passes (default 3)",
    )
    args = parser.parse_args()

    if not is_freerouting_available():
        print(
            "ERROR: Freerouting JAR or Java not available. "
            "Set FREEROUTING_JAR or install Freerouting.",
            file=sys.stderr,
        )
        return 1

    fixtures = [_DEFAULT_FIXTURES[0]] if args.quick else _DEFAULT_FIXTURES
    print(f"Collecting baseline on {len(fixtures)} fixture(s)...", file=sys.stderr)
    all_metrics = [_collect_metrics(f, max_passes=args.passes) for f in fixtures]

    if args.json:
        payload = json.dumps([asdict(m) for m in all_metrics], indent=2)
        if args.output:
            args.output.write_text(payload)
            print(f"JSON baseline written to {args.output}", file=sys.stderr)
        else:
            print(payload)
    else:
        markdown = _render_markdown(all_metrics)
        if args.output:
            args.output.write_text(markdown)
            print(f"Baseline written to {args.output}")
        else:
            print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
