"""Generate multimodal diagnostic vision data for blocker diagnosis training.

Takes the existing text-only diagnostic_sft_combined.jsonl and:
1. Renders the source PCB to a PNG
2. Adds the PCB image to each diagnostic example
3. Scales up by running the harvester on multiple PCB fixtures

Output: JSONL with {messages, task_type, image_path} for each diagnostic example.

Usage:
    python3 generate_diagnostic_vision_data.py \
        --pcb-fixtures "tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_pcb" \
        --out /Volumes/Storage/schgen/diagnostic_vision_data \
        --target 500
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from volta.routing.diagnostician import BlockerDiagnostician
from volta.routing.pathfinder import route_net, RoutingGraph


def render_pcb_png(pcb_path: Path, out_png: Path, side: str = "top") -> bool:
    """Render PCB to PNG via kicad-cli."""
    try:
        out_png.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "kicad-cli", "pcb", "render", str(pcb_path),
            "-o", str(out_png),
            "--quality", "basic",
        ]
        if side == "bottom":
            cmd.extend(["--side", "bottom"])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return r.returncode == 0 and out_png.exists()
    except Exception:
        return False


def harvest_routing_failures(pcb_path: Path, max_nets: int = 30,
                              inject_keepouts: int = 0) -> tuple[list[dict], tuple]:
    """Route nets on a PCB and harvest failures for diagnostic data.

    Args:
        pcb_path: Path to the .kicad_pcb file.
        max_nets: Maximum nets to process.
        inject_keepouts: Number of random keepout corridors to inject to force
            routing failures. Each keepout is a vertical wall across the board.

    Returns (failures, board_bounds).
    """
    from volta.parser.pcb_native_parser import NativeParser
    from volta.ir.pcb_ir import PcbIR
    from volta.routing.constraints import RoutingConstraints
    from volta.routing.diagnostician import BlockerDiagnostician
    from volta.routing.pathfinder import route_net
    from volta.routing.graph import RoutingGraph
    from volta.spatial.primitives import SpatialBox

    print(f"  Loading PCB: {pcb_path.name}")
    content = pcb_path.read_text(encoding="utf-8")
    board = NativeParser.parse_pcb_content(content, str(pcb_path))

    ir = PcbIR.from_native(board)
    bounds = ir.get_board_bounds()
    if not bounds:
        print("  ERROR: Could not determine board bounds")
        return [], (0, 0, 100, 100)

    obstacles = ir.extract_obstacles()
    track_obstacles = ir.extract_track_obstacles()
    all_obstacles = obstacles + track_obstacles

    print(f"  Bounds: {bounds}, Obstacles: {len(obstacles)} + {len(track_obstacles)} tracks")

    # Extract netlist from pads.
    netlist: dict[str, list[tuple[float, float]]] = {}
    for fp in ir.footprints:
        for pad in fp.pads:
            if pad.net_name and pad.net_name != "":
                netlist.setdefault(pad.net_name, []).append(
                    (fp.position[0] + pad.position[0],
                     fp.position[1] + pad.position[1])
                )

    # Inject keepout corridors to force failures.
    import random
    rng = random.Random(42)
    injected_obstacles = list(all_obstacles)
    for _ in range(inject_keepouts):
        # Create a vertical wall at a random X position
        wall_x = rng.uniform(bounds[0] + 5, bounds[2] - 5)
        wall = SpatialBox(
            x1=wall_x - 0.5, y1=bounds[1],
            x2=wall_x + 0.5, y2=bounds[3],
            entity_type="keepout", entity_id=f"keepout_{_}",
            layer="F.Cu",
        )
        injected_obstacles.append(wall)

    if inject_keepouts:
        all_obstacles = injected_obstacles
        print(f"  Injected {inject_keepouts} keepout walls")

    constraints = RoutingConstraints(
        clearance_mm=0.25,
        grid_resolution_mm=1.0,
        trace_width_mm=0.2,
        via_diameter_mm=0.6,
    )

    graph = RoutingGraph(
        board_bounds=bounds,
        obstacles=all_obstacles,
        constraints=constraints,
    )
    diagnostician = BlockerDiagnostician(
        board_bounds=bounds,
        obstacles=all_obstacles,
        constraints=constraints,
        board_raw_content=content,
    )

    failures: list[dict] = []
    nets_processed = 0

    for net_name, pins in list(netlist.items())[:max_nets]:
        if len(pins) < 2:
            continue
        source = pins[0]
        target = pins[-1]

        try:
            result = route_net(graph, source, target, net_name)
        except Exception:
            result = None

        if not result or (hasattr(result, '__bool__') and not result):
            # Routing failed — diagnose the blocker
            try:
                dead_end = result.dead_end if result and hasattr(result, 'dead_end') else source
                diagnosis = diagnostician.diagnose(
                    graph=graph,
                    net_name=net_name,
                    source=source,
                    target=target,
                    dead_end=dead_end,
                )
            except Exception:
                diagnosis = {
                    "failure_type": "no_path",
                    "blockers": [],
                    "dead_end": source,
                    "reachable_count": 0,
                }

            failures.append({
                "net_name": net_name,
                "source": source,
                "target": target,
                "diagnosis": diagnosis,
            })

        nets_processed += 1

    print(f"  Processed {nets_processed} nets, {len(failures)} failures")
    return failures, bounds


def format_diagnostic_example(failure: dict, board_bounds: tuple, pcb_name: str) -> dict:
    """Format a routing failure as a ChatML diagnostic example."""
    diag = failure["diagnosis"]
    net_name = failure["net_name"]
    source = failure["source"]
    target = failure["target"]

    user_msg = (
        f"PCB routing failure analysis.\n\n"
        f"Board: {pcb_name}\n"
        f"Board bounds: ({board_bounds[0]:.1f}, {board_bounds[1]:.1f}) to "
        f"({board_bounds[2]:.1f}, {board_bounds[3]:.1f}) mm\n"
        f"Net '{net_name}' failed to route.\n"
        f"Source: ({source[0]:.2f}, {source[1]:.2f})\n"
        f"Target: ({target[0]:.2f}, {target[1]:.2f})\n"
        f"Failure type: {diag.get('failure_type', 'no_path')}\n"
        f"Reachable nodes from source: {diag.get('reachable_count', 0)}\n"
    )

    assistant_msg = f"Blocker diagnosis for net '{net_name}':\n"
    assistant_msg += f"Dead-end point: ({diag.get('dead_end', source)[0]:.2f}, {diag.get('dead_end', source)[1]:.2f})\n"
    assistant_msg += f"Target point: ({target[0]:.2f}, {target[1]:.2f})\n"
    assistant_msg += f"Failure type: {diag.get('failure_type', 'no_path')}\n\n"

    blockers = diag.get("blockers", [])
    if blockers:
        assistant_msg += f"Blockers identified (ranked by relevance):\n"
        for i, b in enumerate(blockers[:5], 1):
            assistant_msg += (
                f"{i}. {b.get('ref', '?')} at ({b.get('position', (0,0))[0]:.2f}, "
                f"{b.get('position', (0,0))[1]:.2f})\n"
                f"   Classification: {b.get('classification', 'UNKNOWN')}\n"
                f"   Cause: {b.get('cause', 'Unknown')}\n"
                f"   Suggested action: {b.get('action', 'Investigate')}\n"
                f"   Benefit: {b.get('benefit', 'May unblock path')}\n"
            )
    else:
        assistant_msg += "No specific blockers identified. The path may require layer changes or component relocation.\n"

    return {
        "messages": [
            {"role": "system", "content": "You are a PCB routing diagnostician. Analyze routing failures and identify the component(s) blocking the path."},
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": assistant_msg},
        ],
        "task_type": "blocker_diagnosis",
        "source_file": f"pcb/{pcb_name}",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pcb-fixtures", nargs="+", required=True,
                        help="PCB files to harvest failures from")
    parser.add_argument("--out", default="/Volumes/Storage/schgen/diagnostic_vision_data")
    parser.add_argument("--target", type=int, default=500)
    parser.add_argument("--max-nets", type=int, default=30)
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir = out_dir / "images"
    images_dir.mkdir(exist_ok=True)

    # Also load existing diagnostic data
    existing_path = PROJECT_ROOT / "training_output" / "diagnostic_sft_combined.jsonl"
    existing_examples = []
    if existing_path.exists():
        with existing_path.open() as f:
            for line in f:
                existing_examples.append(json.loads(line))
    print(f"Loaded {len(existing_examples)} existing diagnostic examples")

    # Render PCBs and harvest failures
    all_examples: list[dict] = []
    pcb_images: dict[str, str] = {}

    for pcb_path_str in args.pcb_fixtures:
        pcb_path = Path(pcb_path_str)
        if not pcb_path.exists():
            print(f"  SKIP: {pcb_path} not found")
            continue

        pcb_name = pcb_path.stem
        print(f"\nProcessing {pcb_name}...")

        # Render PCB
        pcb_png = images_dir / f"{pcb_name}.png"
        if not pcb_png.exists():
            ok = render_pcb_png(pcb_path, pcb_png)
            if not ok:
                print(f"  PCB render failed, skipping")
                continue
        pcb_images[pcb_name] = str(pcb_png)
        print(f"  Rendered: {pcb_png.name}")

        # Harvest failures — natural + injected
        # Run multiple rounds with different keepout injection counts to maximize yield
        keepout_rounds = [0, 3, 5, 8, 12] if args.target > 100 else [0, 5]
        for round_idx, n_keepouts in enumerate(keepout_rounds):
            if len(all_examples) >= args.target:
                break
            print(f"  Round {round_idx}: {n_keepouts} keepouts...")
            failures, bounds = harvest_routing_failures(
                pcb_path, max_nets=args.max_nets, inject_keepouts=n_keepouts,
            )
            print(f"  Harvested {len(failures)} routing failures")

            for failure in failures:
                ex = format_diagnostic_example(failure, bounds, pcb_name)
                ex["image_path"] = str(pcb_png)
                ex["round"] = round_idx
                ex["keepouts"] = n_keepouts
                all_examples.append(ex)

    # Add existing text-only examples with placeholder images
    for ex in existing_examples:
        ex["image_path"] = None  # text-only — collator will use placeholder
        all_examples.append(ex)

    # Write output
    out_file = out_dir / "diagnostic_vision_pairs.jsonl"
    with out_file.open("w") as f:
        for ex in all_examples:
            f.write(json.dumps(ex) + "\n")

    print(f"\nDone. Generated {len(all_examples)} diagnostic examples.")
    print(f"  With images: {sum(1 for e in all_examples if e.get('image_path'))}")
    print(f"  Text-only: {sum(1 for e in all_examples if not e.get('image_path'))}")
    print(f"  Output: {out_file}")


if __name__ == "__main__":
    main()
