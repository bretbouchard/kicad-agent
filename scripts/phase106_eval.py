#!/usr/bin/env python3
"""Phase 106: Evaluate the model-based blocker diagnostician.

Compares the AI model diagnostician against the deterministic ground truth
on real routing failures. Reports parse-success rate, classification-match
rate, and fallback rate.

Gate (council R-6): if model <50% classification accuracy, use deterministic.

Usage:
    python3 scripts/phase106_eval.py
    python3 scripts/phase106_eval.py --adapter output/phase106_adapter_mlx
    python3 scripts/phase106_eval.py --quick  # fewer eval cases
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from volta.parser.pcb_native_parser import NativeParser
from volta.ir.pcb_ir import PcbIR
from volta.routing.constraints import RoutingConstraints
from volta.routing.diagnostician import BlockerDiagnostician
from volta.routing.diagnostician_model import BlockerDiagnosticianModel
from volta.routing.pathfinder import RouteFailure
from volta.spatial.primitives import SpatialBox

_FIXTURES = [
    PROJECT_ROOT / "tests" / "fixtures" / "Arduino_Mega" / "Arduino_Mega.kicad_pcb",
    PROJECT_ROOT / "tests" / "fixtures" / "smd_test_board.kicad_pcb",
]

_DEFAULT_ADAPTER = PROJECT_ROOT / "output" / "phase106_adapter_mlx"


@dataclass
class EvalResult:
    """Result of evaluating one failure case."""
    net_name: str
    fixture: str
    det_blockers: int  # deterministic blocker count
    model_blockers: int  # model blocker count
    model_parsed: bool  # did the model output parse?
    classification_match: bool  # did classifications match?
    action_match: bool  # did actions match?
    fell_back: bool  # did it use deterministic fallback?
    elapsed_s: float


def load_model_diagnostician(
    pcb_path: Path,
    adapter_path: Path,
) -> BlockerDiagnosticianModel:
    """Load the model-based diagnostician with the phase106 adapter."""
    from volta.inference.vision_pipeline import (
        KiCadVisionConfig,
        KiCadVisionPipeline,
    )

    config = KiCadVisionConfig(adapter_path=adapter_path)
    pipeline = KiCadVisionPipeline(config)

    content = pcb_path.read_text(encoding="utf-8")
    board = NativeParser.parse_pcb_content(content, str(pcb_path))
    ir = PcbIR.from_native(board)
    bounds = ir.get_board_bounds()
    obstacles = ir.extract_obstacles()

    fallback = BlockerDiagnostician(
        board_bounds=bounds,
        obstacles=obstacles,
        constraints=RoutingConstraints(grid_resolution_mm=1.0),
        board_raw_content=content,
    )

    return BlockerDiagnosticianModel(
        pipeline=pipeline,
        pcb_path=pcb_path,
        fallback=fallback,
        board_bounds=bounds,
    )


def generate_eval_failures(
    pcb_path: Path,
    grid: float = 1.0,
    max_nets: int = 10,
) -> list[RouteFailure]:
    """Generate routing failures via keepout injection."""
    import math
    import random

    content = pcb_path.read_text(encoding="utf-8")
    board = NativeParser.parse_pcb_content(content, str(pcb_path))
    ir = PcbIR.from_native(board)
    bounds = ir.get_board_bounds()
    if not bounds:
        return []

    x_min, y_min, x_max, y_max = bounds
    width = x_max - x_min
    real_obstacles = ir.extract_obstacles()

    netlist: dict[str, list[tuple[float, float]]] = {}
    for fp in board.footprints:
        for pad in fp.pads:
            if pad.net_name and pad.net_name not in ("", "0"):
                wx = fp.position[0] + pad.position[0]
                wy = fp.position[1] + pad.position[1]
                netlist.setdefault(pad.net_name, []).append((wx, wy))

    rng = random.Random(42)
    failures: list[RouteFailure] = []

    from volta.routing.graph import RoutingGraph
    from volta.routing.pathfinder import route_net

    for i in range(5):
        kx = x_min + width * (0.3 + 0.4 * rng.random())
        keepout = SpatialBox(
            kx - 0.5, y_min, kx + 0.5, y_max,
            "footprint", f"KEEPOUT_{i}", layer="", reference=f"KEEP{i}",
        )
        obstacles = real_obstacles + [keepout]

        try:
            graph = RoutingGraph(
                board_bounds=bounds, obstacles=obstacles,
                constraints=RoutingConstraints(grid_resolution_mm=grid),
            )
        except ValueError:
            continue

        for net_name, pins in list(netlist.items())[:max_nets]:
            if len(pins) < 2:
                continue
            result = route_net(graph, pins[0], pins[-1], net_name)
            if not result and isinstance(result, RouteFailure):
                failures.append(result)

    return failures


def evaluate(
    pcb_path: Path,
    model_diag: BlockerDiagnosticianModel,
    det_diag: BlockerDiagnostician,
    failures: list[RouteFailure],
) -> list[EvalResult]:
    """Run both diagnosticians on each failure and compare."""
    results: list[EvalResult] = []

    for failure in failures:
        t0 = time.time()

        # Ground truth: deterministic.
        det_result = det_diag.diagnose(failure)
        det_blockers = len(det_result.blockers)

        # Model: AI diagnostician.
        model_result = model_diag.diagnose(failure)
        model_blockers = len(model_result.blockers)

        # Did the model parse successfully (not fall back)?
        # Heuristic: if model_blockers > 0 and elapsed > 1s, it used the model.
        elapsed = time.time() - t0
        model_parsed = model_blockers > 0 and elapsed > 0.5
        fell_back = model_blockers == 0 or elapsed < 0.5

        # Compare classifications.
        det_classes = {b.classification for b in det_result.blockers}
        model_classes = {b.classification for b in model_result.blockers}
        class_match = bool(det_classes & model_classes) if det_classes else False

        det_actions = {b.recommended_action for b in det_result.blockers}
        model_actions = {b.recommended_action for b in model_result.blockers}
        action_match = bool(det_actions & model_actions) if det_actions else False

        results.append(EvalResult(
            net_name=failure.net_name,
            fixture=pcb_path.name,
            det_blockers=det_blockers,
            model_blockers=model_blockers,
            model_parsed=model_parsed,
            classification_match=class_match,
            action_match=action_match,
            fell_back=fell_back,
            elapsed_s=elapsed,
        ))

    return results


def format_report(results: list[EvalResult]) -> str:
    """Format results as a markdown report."""
    total = len(results)
    if total == 0:
        return "No eval cases generated."

    parsed = sum(1 for r in results if r.model_parsed)
    class_matches = sum(1 for r in results if r.classification_match)
    action_matches = sum(1 for r in results if r.action_match)
    fallbacks = sum(1 for r in results if r.fell_back)

    lines = [
        "# Phase 106 Model Diagnostician Evaluation",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total cases | {total} |",
        f"| Model parsed | {parsed}/{total} ({100*parsed/total:.0f}%) |",
        f"| Classification match | {class_matches}/{total} ({100*class_matches/total:.0f}%) |",
        f"| Action match | {action_matches}/{total} ({100*action_matches/total:.0f}%) |",
        f"| Fell back to deterministic | {fallbacks}/{total} ({100*fallbacks/total:.0f}%) |",
        "",
        "## R-6 Gate",
        "",
    ]

    class_rate = class_matches / total if total else 0
    if class_rate >= 0.5:
        lines.append(f"✅ **PASS** — classification accuracy {class_rate:.0%} ≥ 50% threshold")
    else:
        lines.append(f"❌ **FAIL** — classification accuracy {class_rate:.0%} < 50% threshold")
        lines.append("   Use deterministic diagnostician (graceful degradation).")

    lines.extend([
        "",
        "## Per-case detail",
        "",
        "| Net | Fixture | Det | Model | Parsed | Class | Action | Fallback | Time |",
        "|-----|---------|-----|-------|--------|-------|--------|----------|------|",
    ])
    for r in results:
        lines.append(
            f"| {r.net_name[:12]} | {r.fixture[:16]} | {r.det_blockers} | "
            f"{r.model_blockers} | {'✅' if r.model_parsed else '❌'} | "
            f"{'✅' if r.classification_match else '❌'} | "
            f"{'✅' if r.action_match else '❌'} | "
            f"{'⚠️' if r.fell_back else ''} | {r.elapsed_s:.1f}s |"
        )

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate Phase 106 model diagnostician."
    )
    parser.add_argument(
        "--adapter", default=_DEFAULT_ADAPTER, type=Path,
        help="Path to MLX adapter directory.",
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Fewer eval cases (faster).",
    )
    parser.add_argument(
        "--output", default=None, type=Path,
        help="Write report to file (default: stdout).",
    )
    args = parser.parse_args()

    if not args.adapter.exists():
        print(f"ERROR: Adapter not found at {args.adapter}")
        print("Run scripts/fetch_gemma_vision_adapter.sh first.")
        sys.exit(1)

    max_nets = 5 if args.quick else 15
    all_results: list[EvalResult] = []

    for fixture in _FIXTURES:
        if not fixture.exists():
            print(f"Skipping {fixture} (not found)")
            continue

        print(f"\n=== {fixture.name} ===")
        failures = generate_eval_failures(fixture, max_nets=max_nets)
        print(f"  Generated {len(failures)} failures")

        if not failures:
            continue

        print(f"  Loading model (this takes ~60s for the 24GB model)...")
        model_diag = load_model_diagnostician(fixture, args.adapter)

        content = fixture.read_text(encoding="utf-8")
        board = NativeParser.parse_pcb_content(content, str(fixture))
        ir = PcbIR.from_native(board)
        bounds = ir.get_board_bounds()
        det_diag = BlockerDiagnostician(
            board_bounds=bounds,
            obstacles=ir.extract_obstacles(),
            constraints=RoutingConstraints(grid_resolution_mm=1.0),
            board_raw_content=content,
        )

        results = evaluate(fixture, model_diag, det_diag, failures)
        all_results.extend(results)

    report = format_report(all_results)
    print("\n" + report)

    if args.output:
        args.output.write_text(report, encoding="utf-8")
        print(f"\nReport saved to {args.output}")


if __name__ == "__main__":
    main()
