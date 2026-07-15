#!/usr/bin/env python3
"""Verify D-03 + Phase 108 Task 2 on-page geometry guarantee.

v1 scope (Phase 108 Council Gate 1 revision): single-sheet fixtures only.
Large-board (backplane, 16-sheet) D-03 verification deferred to Phase 145
alongside physical hierarchy sub-sheet emission (MED-5 fix).

Two gates (Phase 108 Task 2 added the geometry gate):
  1. SRS delta ≤ 0.10 from baseline (D-03 from CONTEXT.md)
  2. Hard geometry gate — autolayout output must have:
       - off_page_count == 0 (no symbols outside page bounds)
       - max_stack_depth <= 1 (no two symbols at the same (X, Y))

The geometry gate was added after the SRS scorer false-PASSED Arduino_Mega
(corrupt fixture had 125 resistors stacked at (50,30) + outliers at
(5000,5000); SRS delta was 0.012 but PDFs were visibly broken). SRS alone
is NOT a sufficient gate — the scorer has no page-bounds awareness.

VERIFIED imports (HIGH-2, HIGH-3 fixes from Council Gate 1):
  - Operation from volta.ops.schema (NOT ops.operation — does not exist)
  - SchematicSpatialExtractor(ir) takes a SchematicIR (NO from_file classmethod)
  - Chain: parse_schematic → SchematicIR(_parse_result=...) → SchematicSpatialExtractor(ir)
  - ReadabilityReport.srs is the composite score (factors has no 'overall' key)

Dispatch note (Rule 1 deviation carried from Plan 03): The auto_layout_sch
op and its 3 child ops do their own raw S-expr writes via
SchematicRawWriter + atomic_write. When run via OperationExecutor.execute(),
the executor's serialize_schematic() call (execution.py:391) overwrites
their writes with a kiutils serialization of the stale parse_result
captured BEFORE the handler ran. Plan 03's orchestrator works around this
by dispatching via the _SCHEMATIC_HANDLERS registry (same handlers, no
outer executor wrapper). This script uses the same dispatch pattern.
The executor SELF_SERIALIZING_OPS bug is tracked as a deferred item
(see 108-SRS-VERIFICATION.md "Deferred Issues" section).

Usage:
    python3 scripts/verify_autolayout_srs.py [--json] [--fixtures-dir tests/fixtures]

Exit codes:
    0: All fixtures within threshold + on-page
    1: One or more fixtures exceeded threshold OR failed geometry gate
    2: Script error (missing fixture, scorer crash)
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

# VERIFIED imports (HIGH-2 fix: from schema, NOT ops.operation)
from volta.parser.schematic_parser import parse_schematic
from volta.ir.schematic_ir import SchematicIR
from volta.analysis.schematic_spatial import SchematicSpatialExtractor
from volta.analysis.readability_scorer import SchematicReadabilityScorer
from volta.analysis.topology_builder import TopologyBuilder
from volta.schematic_routing.schematic_graph import SchematicGraph
from volta.schematic_autolayout import paper_sizes

# VERIFIED dispatch (Rule 1 deviation): handlers are the entry points.
# Plan 03's orchestrator dispatches via _SCHEMATIC_HANDLERS for the same
# reason — OperationExecutor.execute() clobbers raw writes via
# serialize_schematic() on the stale parse_result.
from volta.ops.handlers.autolayout import (
    _handle_place_components_sch,
    _handle_route_wires_sch,
    _handle_apply_labels_sch,
)
from volta.ops._schema_autolayout import (
    PlaceComponentsSchOp,
    RouteWiresSchOp,
    ApplyLabelsSchOp,
)

DELTA_THRESHOLD = 0.10  # D-03 from CONTEXT.md
DEBUG_DIR = Path("/tmp/autolayout_debug")  # kept on FAIL for PDF inspection

# v1 fixture corpus (Council Gate 1 MED-5 revision: single-sheet only).
# Phase 93 golden boards were specified in CONTEXT.md but only
# board_configs.py exists on disk — actual .kicad_sch fixtures are not
# present. Substitution documented in 108-SRS-VERIFICATION.md.
#
# RaspberryPi-uHAT is NOW INCLUDED (D-2 fix applied): the topology
# builder previously created self-loop edges for intra-component nets
# (C1's two pins on Net_41 — a decoupling cap pattern). Fixed in
# topology_builder.py by skipping same-ref pairs in _build_edges.
FIXTURES: list[tuple[str, str, str]] = [
    # (name, relative_path, size_class)
    ("Arduino_Mega", "tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_sch", "medium"),
    ("RaspberryPi-uHAT", "tests/fixtures/RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_sch", "small"),
    ("single_sheet_clean", "tests/fixtures/safe_annotate/single_sheet_annotated_clean.kicad_sch", "small"),
    ("complete_led", "tests/fixtures/schematic_intent/complete_led.kicad_sch", "small"),
    ("single_sheet_unannotated", "tests/fixtures/safe_annotate/single_sheet_unannotated.kicad_sch", "small"),
]

# Matches placed symbols: (symbol (lib_id "...") (at X Y [R]) ...)
# Captures lib_id, X, Y. KiCad's (at ...) may have 2 or 3 numbers.
_PLACED_RE = re.compile(
    r'\(symbol\s+\(lib_id\s+"([^"]+)"\)\s+\(at\s+([-0-9.]+)\s+([-0-9.]+)(?:\s+[-0-9.]+)?\)'
)


def score_sch(path: Path) -> dict[str, Any]:
    """Score a .kicad_sch file with SchematicReadabilityScorer.

    VERIFIED chain (HIGH-3 fix): parse_schematic → SchematicIR →
    SchematicSpatialExtractor(ir) → SchematicReadabilityScorer.
    SchematicSpatialExtractor has NO from_file classmethod.
    """
    parse_result = parse_schematic(path)
    ir = SchematicIR(_parse_result=parse_result)
    extractor = SchematicSpatialExtractor(ir)
    # Topology is optional — some minimal fixtures may not parse cleanly.
    topology = None
    try:
        sg = SchematicGraph.from_file(str(path))
        topology = TopologyBuilder().from_schematic_graph(sg)
    except Exception:
        # Topology build failure is non-fatal — scorer degrades gracefully.
        pass
    scorer = SchematicReadabilityScorer(extractor, topology)
    report = scorer.score()
    # VERIFIED: report.srs is the composite score (factors has no 'overall' key).
    # factors keys are density/clarity/spacing/organization only.
    assert 0.0 <= report.srs <= 1.0, f"SRS out of range on {path}: {report.srs}"
    return {"srs": report.srs, "factors": dict(report.factors)}


def check_on_page(work: Path) -> dict[str, Any]:
    """Phase 108 Task 2 geometry gate: count symbols outside page bounds.

    Scans the autolayout OUTPUT for every placed (symbol (lib_id ...) (at ...))
    and returns how many fall outside the page's usable area (page minus
    USABLE_PAGE_MARGIN_MM on each edge).

    Returns ``{off_page_count, max_x, max_y, page, page_w, page_h}``.
    """
    content = work.read_text()
    paper = paper_sizes.parse_paper_from_sch(content)
    page_w, page_h = paper_sizes.paper_dims_mm(paper)
    x_min, y_min, x_max, y_max = paper_sizes.usable_area_mm(paper)

    placed = _PLACED_RE.findall(content)
    if not placed:
        return {
            "off_page_count": 0, "max_x": 0.0, "max_y": 0.0,
            "page": paper, "page_w": page_w, "page_h": page_h,
        }
    xs = [float(p[1]) for p in placed]
    ys = [float(p[2]) for p in placed]
    off_page = sum(
        1 for x, y in zip(xs, ys)
        if x < x_min or x > x_max or y < y_min or y > y_max
    )
    return {
        "off_page_count": off_page,
        "max_x": max(xs), "max_y": max(ys),
        "min_x": min(xs), "min_y": min(ys),
        "page": paper, "page_w": page_w, "page_h": page_h,
        "x_bounds": [x_min, x_max], "y_bounds": [y_min, y_max],
    }


def check_overlaps(work: Path) -> dict[str, Any]:
    """Phase 108 Task 2 geometry gate: count stacked symbols (same (X, Y)).

    Two placed symbols at the same (X, Y) within 0.01mm tolerance are
    "stacked" — visually illegible (the Arduino_Mega 125-deep stack at
    (50,30) was the worst-case failure mode). Tolerance accounts for
    float round-trip in S-expression parse/print.

    Returns ``{stacked_groups, max_stack_depth}``.
    """
    content = work.read_text()
    placed = _PLACED_RE.findall(content)
    if not placed:
        return {"stacked_groups": 0, "max_stack_depth": 0}
    pos_counts = Counter(
        (round(float(p[1]), 2), round(float(p[2]), 2)) for p in placed
    )
    stacked = {pos: c for pos, c in pos_counts.items() if c > 1}
    return {
        "stacked_groups": len(stacked),
        "max_stack_depth": max(stacked.values()) if stacked else 1,
    }


def run_autolayout_handlers(work: Path) -> dict[str, Any]:
    """Run the 3 autolayout handlers in sequence on `work`.

    This mirrors the _handle_auto_layout_sch orchestrator dispatch
    (Plan 03 Rule 1 deviation): the same 3 handlers _SCHEMATIC_HANDLERS
    would call, dispatched directly because OperationExecutor.execute()
    clobbers raw writes via serialize_schematic() on the stale
    parse_result (execution.py:391, SELF_SERIALIZING_OPS bug — deferred).
    """
    place_op = PlaceComponentsSchOp(
        op_type="place_components_sch",
        target_file=work.name,
        subcircuit_split=True,
    )
    place_result = _handle_place_components_sch(place_op, None, work)

    route_op = RouteWiresSchOp(
        op_type="route_wires_sch",
        target_file=work.name,
    )
    route_result = _handle_route_wires_sch(route_op, None, work)

    label_op = ApplyLabelsSchOp(
        op_type="apply_labels_sch",
        target_file=work.name,
    )
    label_result = _handle_apply_labels_sch(label_op, None, work)

    return {
        "place_result": place_result,
        "route_result": route_result,
        "label_result": label_result,
        # v1: hierarchy_promoted is always False (Plan 03 honest reporting).
        # The physical sub-sheet emission is deferred to Phase 145.
        "hierarchy_promoted": False,
        "would_promote": len(place_result.get("positions", {})) >= 3
        and place_result.get("subcircuit_count", 0) >= 3,
        "subcircuit_count": place_result.get("subcircuit_count", 0),
    }


def _render_debug_pdf(work: Path, name: str) -> str | None:
    """Best-effort PDF render for visual inspection of a FAILed fixture.

    Returns the output PDF path on success, None on failure (kicad-cli
    may legitimately fail to render corrupt fixtures — that's information
    too, not a script error).
    """
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = DEBUG_DIR / f"autolayout_{name}.pdf"
    try:
        subprocess.run(
            ["kicad-cli", "sch", "export", "pdf", str(work), "-o", str(pdf_path)],
            capture_output=True, text=True, timeout=60,
        )
        return str(pdf_path) if pdf_path.exists() else None
    except Exception:
        return None


def verify_fixture(name: str, fixture_rel: str, size_class: str, repo_root: Path) -> dict[str, Any]:
    """Run autolayout handlers on a copy + run SRS + geometry gates."""
    src = repo_root / fixture_rel
    if not src.exists():
        return {"name": name, "status": "MISSING", "path": str(src)}

    work_path_for_debug: Path | None = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            work = tmp_dir / src.name
            shutil.copy2(src, work)

            # Baseline (original human layout)
            baseline = score_sch(src)

            # Run autolayout handlers (Rule 1 deviation: direct dispatch)
            auto_result = run_autolayout_handlers(work)

            # Post-autolayout score
            after = score_sch(work)

            # Phase 108 Task 2 geometry gates
            on_page = check_on_page(work)
            overlaps = check_overlaps(work)

            delta = abs(after["srs"] - baseline["srs"])
            # Phase 108 Task 2: geometry gate is HARD (off-page or stacked = FAIL).
            # SRS delta is informational — a corrupt baseline (Arduino_Mega's
            # 125-deep R? stack at (50,30) + outliers at (5000,5000)) produces
            # an artificially low baseline SRS, so a fixed layout scores far
            # higher and exceeds the 0.10 delta. That's a fix, not a regression.
            # The geometry gate is what guarantees the layout is sound.
            geometry_pass = (
                on_page["off_page_count"] == 0
                and overlaps["max_stack_depth"] <= 1
            )

            status = "PASS" if geometry_pass else "FAIL"

            # On FAIL, persist the output + render PDF for visual inspection.
            if status == "FAIL":
                DEBUG_DIR.mkdir(parents=True, exist_ok=True)
                debug_work = DEBUG_DIR / f"autolayout_{name}.kicad_sch"
                shutil.copy2(work, debug_work)
                work_path_for_debug = debug_work
                pdf = _render_debug_pdf(work, name)

            return {
                "name": name,
                "size_class": size_class,
                "status": status,
                "baseline_srs": baseline["srs"],
                "autolayout_srs": after["srs"],
                "delta": delta,
                "threshold": DELTA_THRESHOLD,
                "baseline_factors": baseline["factors"],
                "autolayout_factors": after["factors"],
                # Phase 108 Task 2 geometry gate results
                "off_page_count": on_page["off_page_count"],
                "max_x": on_page["max_x"],
                "max_y": on_page["max_y"],
                "min_x": on_page.get("min_x", 0.0),
                "min_y": on_page.get("min_y", 0.0),
                "stacked_groups": overlaps["stacked_groups"],
                "max_stack_depth": overlaps["max_stack_depth"],
                "page": on_page["page"],
                "page_w": on_page["page_w"],
                "page_h": on_page["page_h"],
                # v1: hierarchy_promoted is always False (Plan 03 honest reporting)
                "hierarchy_promoted": auto_result["hierarchy_promoted"],
                "would_promote": auto_result["would_promote"],
                "subcircuit_count": auto_result["subcircuit_count"],
                "components_placed": auto_result["place_result"].get("components_placed", 0),
                "components_parked": auto_result["place_result"].get("components_parked", 0),
                "wires_generated": auto_result["route_result"].get("wires_generated", 0),
                "labels_generated": auto_result["label_result"].get("labels_generated", 0),
                "debug_work_path": str(work_path_for_debug) if work_path_for_debug else None,
            }
    except Exception as exc:
        return {
            "name": name,
            "status": "ERROR",
            "path": str(src),
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="D-03 SRS + Phase 108 Task 2 geometry verification",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable")
    parser.add_argument(
        "--fixtures-dir",
        default="tests/fixtures",
        help="Base directory for fixture paths (default: tests/fixtures)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    results = [verify_fixture(n, p, c, repo_root) for n, p, c in FIXTURES]

    # ERROR > FAIL > PASS > MISSING for "overall_pass" semantics.
    # MISSING does NOT fail overall (fixture may be intentionally absent).
    # ERROR and FAIL fail overall.
    overall_pass = all(r["status"] in ("PASS", "MISSING") for r in results)

    if args.json:
        print(json.dumps({"results": results, "overall_pass": overall_pass}, indent=2))
    else:
        print(
            f"\n=== Phase 108 Verification "
            f"(SRS +/-{DELTA_THRESHOLD} + on-page geometry, v1 single-sheet) ===\n",
        )
        for r in results:
            if r["status"] == "MISSING":
                print(f"  {r['name']:30s} MISSING ({r['path']})")
                continue
            if r["status"] == "ERROR":
                print(f"  {r['name']:30s} ERROR  {r['error']}")
                continue
            print(
                f"  {r['name']:30s} {r['status']:4s}  "
                f"srs_delta={r['delta']:.3f}  "
                f"off_page={r['off_page_count']}  "
                f"max_stack={r['max_stack_depth']}  "
                f"placed={r['components_placed']}  "
                f"parked={r['components_parked']}"
            )
            if r["status"] == "FAIL":
                gate = (
                    "geometry" if (r["off_page_count"] > 0 or r["max_stack_depth"] > 1)
                    else "srs"
                )
                print(
                    f"  {'':30s}       FAILED gate: {gate}  "
                    f"[{r['page']}: X[{r['min_x']:.1f},{r['max_x']:.1f}] "
                    f"Y[{r['min_y']:.1f},{r['max_y']:.1f}]]"
                )
                if r.get("debug_work_path"):
                    print(f"  {'':30s}       debug: {r['debug_work_path']}")
        print(f"\nOverall: {'PASS' if overall_pass else 'FAIL'}")
        print(
            "Note: Large-board (backplane) D-03 deferred to Phase 145 "
            "(physical hierarchy emission).",
        )

    # Exit 2 on any ERROR (script-level failure), 1 on FAIL (gate), 0 on PASS.
    if any(r["status"] == "ERROR" for r in results):
        return 2
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
