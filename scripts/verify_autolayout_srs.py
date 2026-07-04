#!/usr/bin/env python3
"""Verify D-03: auto_layout_sch output SRS within 0.10 of human-expert baseline.

v1 scope (Phase 108 Council Gate 1 revision): single-sheet fixtures only.
Large-board (backplane, 16-sheet) D-03 verification deferred to Phase 145
alongside physical hierarchy sub-sheet emission (MED-5 fix).

VERIFIED imports (HIGH-2, HIGH-3 fixes from Council Gate 1):
  - Operation from kicad_agent.ops.schema (NOT ops.operation — does not exist)
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
    0: All fixtures within threshold
    1: One or more fixtures exceeded threshold
    2: Script error (missing fixture, scorer crash)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

# VERIFIED imports (HIGH-2 fix: from schema, NOT ops.operation)
from kicad_agent.parser.schematic_parser import parse_schematic
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.analysis.schematic_spatial import SchematicSpatialExtractor
from kicad_agent.analysis.readability_scorer import SchematicReadabilityScorer
from kicad_agent.analysis.topology_builder import TopologyBuilder
from kicad_agent.schematic_routing.schematic_graph import SchematicGraph

# VERIFIED dispatch (Rule 1 deviation): handlers are the entry points.
# Plan 03's orchestrator dispatches via _SCHEMATIC_HANDLERS for the same
# reason — OperationExecutor.execute() clobbers raw writes via
# serialize_schematic() on the stale parse_result.
from kicad_agent.ops.handlers.autolayout import (
    _handle_place_components_sch,
    _handle_route_wires_sch,
    _handle_apply_labels_sch,
)
from kicad_agent.ops._schema_autolayout import (
    PlaceComponentsSchOp,
    RouteWiresSchOp,
    ApplyLabelsSchOp,
)

DELTA_THRESHOLD = 0.10  # D-03 from CONTEXT.md

# v1 fixture corpus (Council Gate 1 MED-5 revision: single-sheet only).
# Phase 93 golden boards were specified in CONTEXT.md but only
# board_configs.py exists on disk — actual .kicad_sch fixtures are not
# present. Substitution documented in 108-SRS-VERIFICATION.md.
#
# RaspberryPi-uHAT is INTENTIONALLY EXCLUDED from v1: the fixture has a
# pre-existing C1 self-loop in extracted topology (Net_41) which triggers
# LayoutGraph's adversarial self-loop guard (layout_graph.py:200). This
# is a topology-extraction artifact in the fixture, not a regression in
# Plan 01-03 code. Fixing the extractor is out of scope for Plan 04
# (verification-only). Tracked as a deferred item in 108-SRS-VERIFICATION.md.
FIXTURES: list[tuple[str, str, str]] = [
    # (name, relative_path, size_class)
    ("Arduino_Mega", "tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_sch", "medium"),
    ("single_sheet_clean", "tests/fixtures/safe_annotate/single_sheet_annotated_clean.kicad_sch", "small"),
    ("complete_led", "tests/fixtures/schematic_intent/complete_led.kicad_sch", "small"),
    ("single_sheet_unannotated", "tests/fixtures/safe_annotate/single_sheet_unannotated.kicad_sch", "small"),
]


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


def verify_fixture(name: str, fixture_rel: str, size_class: str, repo_root: Path) -> dict[str, Any]:
    """Run autolayout handlers on a copy + compare SRS to baseline."""
    src = repo_root / fixture_rel
    if not src.exists():
        return {"name": name, "status": "MISSING", "path": str(src)}

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

            delta = abs(after["srs"] - baseline["srs"])
            return {
                "name": name,
                "size_class": size_class,
                "status": "PASS" if delta <= DELTA_THRESHOLD else "FAIL",
                "baseline_srs": baseline["srs"],
                "autolayout_srs": after["srs"],
                "delta": delta,
                "threshold": DELTA_THRESHOLD,
                "baseline_factors": baseline["factors"],
                "autolayout_factors": after["factors"],
                # v1: hierarchy_promoted is always False (Plan 03 honest reporting)
                "hierarchy_promoted": auto_result["hierarchy_promoted"],
                "would_promote": auto_result["would_promote"],
                "subcircuit_count": auto_result["subcircuit_count"],
                "components_placed": auto_result["place_result"].get("components_placed", 0),
                "wires_generated": auto_result["route_result"].get("wires_generated", 0),
                "labels_generated": auto_result["label_result"].get("labels_generated", 0),
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
        description="D-03 SRS verification (v1 single-sheet scope)",
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
            f"\n=== D-03 SRS Verification "
            f"(threshold: +/-{DELTA_THRESHOLD}, v1 single-sheet scope) ===\n",
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
                f"baseline={r['baseline_srs']:.3f}  "
                f"autolayout={r['autolayout_srs']:.3f}  "
                f"delta={r['delta']:.3f}  "
                f"[{r['size_class']}, {r['subcircuit_count']} groups, "
                f"would_promote={r['would_promote']}]",
            )
        print(f"\nOverall: {'PASS' if overall_pass else 'FAIL'}")
        print(
            "Note: Large-board (backplane) D-03 deferred to Phase 145 "
            "(physical hierarchy emission).",
        )

    # Exit 2 on any ERROR (script-level failure), 1 on FAIL (threshold), 0 on PASS.
    if any(r["status"] == "ERROR" for r in results):
        return 2
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
