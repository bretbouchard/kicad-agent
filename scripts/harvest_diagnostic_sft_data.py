#!/usr/bin/env python3
"""Phase 106 prep: Harvest SFT training data from Phase 104 diagnostics.

The deterministic BlockerDiagnostician (Phase 104) generates ground-truth
labels for blocker classification. This script harvests those labels into
ChatML SFT examples that match the model's existing training format
(spatial Q&A with coordinate-grounded reasoning).

Output: JSONL of ChatML examples, one per diagnosed failure:
  {
    "messages": [
      {"role": "user", "content": "<board context + failure description>"},
      {"role": "assistant", "content": "<blocker diagnosis with classification>"}
    ]
  }

Council Q4 guidance: start with SFT on harvested traces, defer GRPO.

Usage:
    python3 scripts/harvest_diagnostic_sft_data.py \
        --pcb tests/fixtures/backplane/backplane.kicad_pcb \
        --output training_output/diagnostic_sft.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add project root to path for imports.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from volta.parser.pcb_native_parser import NativeParser
from volta.ir.pcb_ir import PcbIR
from volta.routing.constraints import RoutingConstraints
from volta.routing.diagnostician import BlockerDiagnostician
from volta.routing.pathfinder import RouteFailure, route_net
from volta.routing.graph import RoutingGraph


def harvest_sft_data(
    pcb_path: Path,
    output_path: Path,
    grid_resolution: float = 0.5,
    max_nets: int = 50,
) -> int:
    """Harvest diagnostic SFT data from a real PCB.

    Args:
        pcb_path: Path to the .kicad_pcb file.
        output_path: Where to write the JSONL SFT data.
        grid_resolution: Routing grid resolution in mm.
        max_nets: Maximum nets to process (for large boards).

    Returns:
        Number of SFT examples written.
    """
    print(f"Loading PCB: {pcb_path}")
    content = pcb_path.read_text(encoding="utf-8")
    board = NativeParser.parse_pcb_content(content, str(pcb_path))

    # Build PcbIR from the native board (no file path needed).
    ir = PcbIR.from_native(board)
    bounds = ir.get_board_bounds()
    if not bounds:
        print("ERROR: Could not determine board bounds (no Edge.Cuts)")
        return 0

    obstacles = ir.extract_obstacles()
    track_obstacles = ir.extract_track_obstacles()
    all_obstacles = obstacles + track_obstacles

    print(f"Board bounds: {bounds}")
    print(f"Obstacles: {len(obstacles)} footprints + {len(track_obstacles)} tracks")

    # Extract netlist from pads.
    netlist: dict[str, list[tuple[float, float]]] = {}
    for fp in board.footprints:
        ref = fp.properties.get("Reference", "")
        for pad in fp.pads:
            if pad.net_name and pad.net_name not in ("", "0"):
                # Compute world position.
                wx = fp.position[0] + pad.position[0]
                wy = fp.position[1] + pad.position[1]
                netlist.setdefault(pad.net_name, []).append((wx, wy))

    print(f"Nets found: {len(netlist)}")

    # Build routing graph and route each net.
    constraints = RoutingConstraints(grid_resolution_mm=grid_resolution)
    graph = RoutingGraph(
        board_bounds=bounds,
        obstacles=all_obstacles,
        constraints=constraints,
    )

    # Route nets, collecting failures.
    failures: list[RouteFailure] = []
    routed_count = 0
    for i, (net_name, pins) in enumerate(netlist.items()):
        if i >= max_nets:
            break
        if len(pins) < 2:
            continue
        result = route_net(graph, pins[0], pins[-1], net_name)
        if result:
            routed_count += 1
        else:
            failures.append(result)

    print(f"Routed: {routed_count}, Failed: {len(failures)}")

    if not failures:
        print("No failures to diagnose — no SFT data harvested.")
        return 0

    # Diagnose failures.
    diag = BlockerDiagnostician(
        board_bounds=bounds,
        obstacles=all_obstacles,
        constraints=constraints,
        board_raw_content=content,
    )

    # Write SFT examples.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for failure in failures:
            diagnosis = diag.diagnose(failure)
            if not diagnosis.blockers:
                continue

            # Format as ChatML SFT example.
            user_msg = _format_user_message(failure, bounds)
            assistant_msg = _format_assistant_message(diagnosis)

            example = {
                "messages": [
                    {"role": "user", "content": user_msg},
                    {"role": "assistant", "content": assistant_msg},
                ]
            }
            f.write(json.dumps(example) + "\n")
            count += 1

    print(f"SFT examples written: {count} → {output_path}")
    return count


def _format_user_message(failure: RouteFailure, bounds: tuple) -> str:
    """Format the user prompt for the SFT example."""
    return (
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


def _format_assistant_message(diagnosis) -> str:
    """Format the assistant response with the diagnosis."""
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
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Harvest SFT training data from Phase 104 diagnostics."
    )
    parser.add_argument(
        "--pcb", required=True, type=Path,
        help="Path to .kicad_pcb file to diagnose."
    )
    parser.add_argument(
        "--output", default=Path("training_output/diagnostic_sft.jsonl"),
        type=Path, help="Output JSONL path."
    )
    parser.add_argument(
        "--grid", default=0.5, type=float,
        help="Routing grid resolution in mm (default 0.5)."
    )
    parser.add_argument(
        "--max-nets", default=50, type=int,
        help="Maximum nets to process (default 50)."
    )
    args = parser.parse_args()

    count = harvest_sft_data(
        pcb_path=args.pcb,
        output_path=args.output,
        grid_resolution=args.grid,
        max_nets=args.max_nets,
    )
    print(f"\nDone. {count} SFT examples harvested.")


if __name__ == "__main__":
    main()
