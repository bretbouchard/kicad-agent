#!/usr/bin/env python3
"""Phase 106: Generate SFT training data by injecting routing failures.

The deterministic BlockerDiagnostician needs actual routing failures to
produce SFT data. On clean boards, routing succeeds (no failures = no data).
This script injects keepout zones that force failures, then harvests the
diagnostic output as ChatML SFT examples.

Strategy: for each board, inject a vertical keepout corridor that splits
some nets from their targets. The router fails, the diagnostician identifies
the keepout as the blocker, and we record the (failure, diagnosis) pair.

Output: JSONL of ChatML examples, one per diagnosed failure.

Usage:
    python3 scripts/generate_diagnostic_training_data.py \
        --pcb tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_pcb \
        --output training_output/diagnostic_sft.jsonl \
        --grid 1.0 --keepout-count 5
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from volta.parser.pcb_native_parser import NativeParser
from volta.ir.pcb_ir import PcbIR
from volta.routing.constraints import RoutingConstraints
from volta.routing.diagnostician import BlockerDiagnostician
from volta.routing.pathfinder import RouteFailure, route_net
from volta.routing.graph import RoutingGraph
from volta.spatial.primitives import SpatialBox


def generate_failures(
    pcb_path: Path,
    grid: float = 1.0,
    keepout_count: int = 5,
    max_nets: int = 30,
) -> list[tuple[RouteFailure, str]]:
    """Generate routing failures by injecting keepout zones.

    Returns list of (RouteFailure, raw_pcb_content) pairs.
    """
    content = pcb_path.read_text(encoding="utf-8")
    board = NativeParser.parse_pcb_content(content, str(pcb_path))
    ir = PcbIR.from_native(board)
    bounds = ir.get_board_bounds()
    if not bounds:
        print("ERROR: No board bounds found")
        return []

    x_min, y_min, x_max, y_max = bounds
    width = x_max - x_min
    height = y_max - y_min

    # Extract real obstacles (footprints).
    real_obstacles = ir.extract_obstacles()
    print(f"Board: {pcb_path.name} ({width:.0f}×{height:.0f}mm)")
    print(f"Real obstacles: {len(real_obstacles)}")

    # Extract netlist.
    netlist: dict[str, list[tuple[float, float]]] = {}
    for fp in board.footprints:
        for pad in fp.pads:
            if pad.net_name and pad.net_name not in ("", "0"):
                wx = fp.position[0] + pad.position[0]
                wy = fp.position[1] + pad.position[1]
                netlist.setdefault(pad.net_name, []).append((wx, wy))

    print(f"Nets: {len(netlist)}")

    all_failures: list[tuple[RouteFailure, str]] = []
    rng = random.Random(42)

    # Strategy 1: Inject keepout corridors at random X positions.
    for i in range(keepout_count):
        # Place a keepout at a random X that bisects the board.
        kx = x_min + width * (0.3 + 0.4 * rng.random())
        keepout = SpatialBox(
            kx - 0.5, y_min, kx + 0.5, y_max,
            "footprint", f"KEEPOUT_{i}",
            layer="", reference=f"KEEP{i}",
        )
        obstacles = real_obstacles + [keepout]

        constraints = RoutingConstraints(grid_resolution_mm=grid)
        try:
            graph = RoutingGraph(
                board_bounds=bounds,
                obstacles=obstacles,
                constraints=constraints,
            )
        except ValueError:
            print(f"  Keepout {i}: graph too large at grid={grid}, skipping")
            continue

        failures_this = 0
        for net_name, pins in list(netlist.items())[:max_nets]:
            if len(pins) < 2:
                continue
            result = route_net(graph, pins[0], pins[-1], net_name)
            if not result:
                assert isinstance(result, RouteFailure)
                all_failures.append((result, content))
                failures_this += 1

        print(f"  Keepout {i} at x={kx:.1f}: {failures_this} failures")

    # Strategy 2: Use real obstacles at a finer grid (more likely to fail).
    if not all_failures:
        print("No failures from keepouts — trying finer grid on real obstacles...")
        for grid_try in [0.5, 0.25]:
            constraints = RoutingConstraints(grid_resolution_mm=grid_try)
            try:
                graph = RoutingGraph(
                    board_bounds=bounds,
                    obstacles=real_obstacles,
                    constraints=constraints,
                )
            except ValueError:
                continue

            failures_this = 0
            for net_name, pins in list(netlist.items())[:max_nets]:
                if len(pins) < 2:
                    continue
                result = route_net(graph, pins[0], pins[-1], net_name)
                if not result:
                    assert isinstance(result, RouteFailure)
                    all_failures.append((result, content))
                    failures_this += 1

            print(f"  Grid {grid_try}mm: {failures_this} failures")
            if all_failures:
                break

    return all_failures


def format_sft_example(
    failure: RouteFailure,
    diagnosis,
    bounds: tuple[float, float, float, float],
) -> dict:
    """Format a (failure, diagnosis) pair as a ChatML SFT example."""
    user_msg = (
        f"PCB routing failure analysis.\n\n"
        f"Board bounds: ({bounds[0]:.1f}, {bounds[1]:.1f}) to "
        f"({bounds[2]:.1f}, {bounds[3]:.1f}) mm\n"
        f"Net '{failure.net_name}' failed to route.\n"
        f"Source: ({failure.source_point[0]:.2f}, {failure.source_point[1]:.2f})\n"
        f"Target: ({failure.target_point[0]:.2f}, {failure.target_point[1]:.2f})\n"
        f"Router dead-end: ({failure.dead_end_point[0]:.2f}, "
        f"{failure.dead_end_point[1]:.2f})\n"
        f"Failure type: {failure.failure_type}\n"
        f"Reachable nodes from source: {failure.reachable_count}\n\n"
        f"What is blocking this net's path? Classify the blocker and "
        f"recommend an action."
    )

    lines = [
        f"Blocker diagnosis for net '{diagnosis.net_name}':",
        f"Dead-end point: ({diagnosis.dead_end_point[0]:.2f}, "
        f"{diagnosis.dead_end_point[1]:.2f})",
        f"Target point: ({diagnosis.target_point[0]:.2f}, "
        f"{diagnosis.target_point[1]:.2f})",
        f"Failure type: {diagnosis.failure_type}",
        "",
        "Blockers identified (ranked by removal benefit):",
    ]
    for i, b in enumerate(diagnosis.blockers, 1):
        lines.append(
            f"  {i}. {b.entity_type} '{b.reference}' "
            f"({b.entity_id[:8]}...)"
        )
        lines.append(f"     Classification: {b.classification}")
        lines.append(f"     Causal blocker: {b.blocks_path}")
        lines.append(f"     Recommended action: {b.recommended_action}")
        lines.append(f"     Removal benefit: {b.removal_benefit}")
    assistant_msg = "\n".join(lines)

    return {
        "messages": [
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": assistant_msg},
        ],
        "task_type": "blocker_diagnosis",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate SFT training data via failure injection."
    )
    parser.add_argument(
        "--pcb", required=True, type=Path,
        help="Path to .kicad_pcb file."
    )
    parser.add_argument(
        "--output", default=Path("training_output/diagnostic_sft.jsonl"),
        type=Path,
    )
    parser.add_argument("--grid", type=float, default=1.0)
    parser.add_argument("--keepout-count", type=int, default=5)
    parser.add_argument("--max-nets", type=int, default=30)
    args = parser.parse_args()

    # Generate failures. Each failure carries the pcb_content with the
    # keepout that caused it, so we can rebuild the diagnostician with
    # the correct obstacle set per failure.
    failures = generate_failures(
        pcb_path=args.pcb,
        grid=args.grid,
        keepout_count=args.keepout_count,
        max_nets=args.max_nets,
    )

    if not failures:
        print("\nNo failures generated — cannot produce SFT data.")
        return

    print(f"\nTotal failures: {len(failures)}")

    # Diagnose and write SFT examples.
    content = args.pcb.read_text(encoding="utf-8")
    board = NativeParser.parse_pcb_content(content, str(args.pcb))
    ir = PcbIR.from_native(board)
    bounds = ir.get_board_bounds()
    real_obstacles = ir.extract_obstacles()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    # Note: we intentionally DON'T deduplicate by net name — each keepout
    # position creates a different failure scenario for the same net, which
    # is valuable training diversity.

    with open(args.output, "w", encoding="utf-8") as f:
        for failure, _ in failures:

            # Build a diagnostician with real obstacles + a keepout at
            # the dead-end→target corridor to find what's blocking.
            # The dead_end point tells us where the keepout is.
            dead_end = failure.dead_end_point
            target = failure.target_point
            # Create a synthetic keepout spanning the gap.
            mid_x = (dead_end[0] + target[0]) / 2
            diag_obstacles = list(real_obstacles)
            diag_obstacles.append(SpatialBox(
                mid_x - 1.0, bounds[1], mid_x + 1.0, bounds[3],
                "footprint", f"KEEPOUT_{failure.net_name}",
                layer="", reference=f"KEEP_{failure.net_name}",
            ))

            diag = BlockerDiagnostician(
                board_bounds=bounds,
                obstacles=diag_obstacles,
                constraints=RoutingConstraints(grid_resolution_mm=args.grid),
                board_raw_content=content,
            )
            diagnosis = diag.diagnose(failure)
            if not diagnosis.blockers:
                continue
            example = format_sft_example(failure, diagnosis, bounds)
            f.write(json.dumps(example) + "\n")
            count += 1

    print(f"SFT examples written: {count} → {args.output}")


if __name__ == "__main__":
    main()
