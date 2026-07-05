"""Generate routing strategy SFT corpus.

Creates training examples that teach the model to produce routing strategy
JSON given a board context. Strategies include:
- Net priority ordering (which nets to route first)
- Layer assignment hints (signal layers, power layers)
- Keepout zones (avoid areas near sensitive components)
- Router assignment (which nets need manual vs auto routing)

Two generation approaches:
1. SYNTHETIC: Generate diverse board contexts + ground-truth strategy JSON
2. MINED: Run the router on real boards and extract what worked

Usage:
    python3 generate_strategy_data.py \
        --corpus-manifest /Volumes/Storage/schgen/our_corpus/manifest.jsonl \
        --out /Volumes/Storage/schgen/strategy_data \
        --target 1000
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


STRATEGY_SYSTEM = """\
You are a PCB routing strategist. Given a board context and netlist, output a routing strategy in JSON format.

The strategy tells the router:
- Which nets to route first (priority ordering)
- Which layer to prefer for each net class
- Areas to avoid (keepouts near sensitive components)
- Whether to use auto-routing or manual routing

Output JSON schema:
{
  "net_priorities": [
    {"net": "GND", "priority": 1, "reason": "Power ground — pour first"},
    {"net": "+3V3", "priority": 2, "reason": "Power rail — route before signals"},
    {"net": "SDA", "priority": 5, "reason": "I2C signal — length-match with SCL"}
  ],
  "layer_hints": {
    "GND": "B.Cu",
    "+3V3": "F.Cu",
    "SDA": "F.Cu",
    "SCL": "F.Cu"
  },
  "keepouts": [
    {"x": 50.0, "y": 50.0, "w": 10.0, "h": 5.0, "reason": "Crystal keepout"}
  ],
  "router_assignment": {
    "GND": "auto_pour",
    "+3V3": "auto",
    "SDA": "manual_length_match",
    "high_speed": "manual_impedance"
  },
  "routing_notes": "Route power first (pour GND), then clocks, then signals. Length-match I2C."
}
"""


def render_pcb_png(pcb_path: Path, out_png: Path) -> bool:
    """Render PCB to PNG."""
    try:
        out_png.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            ["kicad-cli", "pcb", "render", str(pcb_path),
             "-o", str(out_png), "--quality", "basic"],
            capture_output=True, text=True, timeout=60,
        )
        return r.returncode == 0 and out_png.exists()
    except Exception:
        return False


def _classify_net(net_name: str) -> str:
    """Classify a net for routing priority."""
    upper = net_name.upper()
    if upper in ("GND", "AGND", "DGND", "PGND", "VSS"):
        return "power_ground"
    elif any(p in upper for p in ("VCC", "VDD", "+3V3", "+5V", "+12V", "-12V", "VBUS", "VBAT", "VIN")):
        return "power_rail"
    elif any(p in upper for p in ("SDA", "SCL", "MOSI", "MISO", "SCK", "CLK")):
        return "digital_bus"
    elif any(p in upper for p in ("USB", "DP", "DM")):
        return "usb"
    elif any(p in upper for p in ("XTAL", "OSC")):
        return "clock"
    elif any(p in upper for p in ("ANALOG", "AUDIO", "AIN", "AOUT")):
        return "analog"
    elif any(p in upper for p in ("RX", "TX", "UART")):
        return "serial"
    elif any(p in upper for p in ("LED",)):
        return "indicator"
    return "signal"


def _priority_for_class(net_class: str) -> tuple[int, str]:
    """Return (priority, reason) for a net class."""
    priorities = {
        "power_ground": (1, "Power ground — pour first for solid reference plane"),
        "power_rail": (2, "Power rail — route before signals to establish power distribution"),
        "clock": (3, "Clock signal — route early to minimize trace length"),
        "usb": (3, "USB differential pair — route early for impedance control"),
        "analog": (4, "Analog signal — route before digital to avoid noise coupling"),
        "digital_bus": (5, "Digital bus — length-match related signals"),
        "serial": (6, "Serial communication — moderate priority"),
        "indicator": (8, "LED indicator — low priority, non-critical"),
        "signal": (7, "General signal — route after critical nets"),
    }
    return priorities.get(net_class, (7, "General signal"))


def _layer_for_class(net_class: str) -> str:
    """Return preferred layer for a net class."""
    layers = {
        "power_ground": "B.Cu",
        "power_rail": "F.Cu",
        "clock": "F.Cu",
        "usb": "F.Cu",
        "analog": "F.Cu",
        "digital_bus": "F.Cu",
        "serial": "F.Cu",
        "indicator": "B.Cu",
        "signal": "F.Cu",
    }
    return layers.get(net_class, "F.Cu")


def _router_for_class(net_class: str) -> str:
    """Return router assignment for a net class."""
    routers = {
        "power_ground": "auto_pour",
        "power_rail": "auto",
        "clock": "manual_short",
        "usb": "manual_impedance",
        "analog": "manual_short",
        "digital_bus": "manual_length_match",
        "serial": "auto",
        "indicator": "auto",
        "signal": "auto",
    }
    return routers.get(net_class, "auto")


def extract_board_context(pcb_path: Path) -> dict | None:
    """Extract board context from a PCB file using regex."""
    import re

    try:
        content = pcb_path.read_text()

        # Extract nets from pads
        nets = set()
        for m in re.finditer(r'\(net\s+(\d+)\s+"([^"]+)"', content):
            nets.add(m.group(2))

        # Extract board bounds
        edge_pts = re.findall(r'\(gr_line\s+\(start\s+([\d.\-]+)\s+([\d.\-]+)\).*?Edge\.Cuts', content, re.DOTALL)
        if edge_pts:
            xs = [float(p[0]) for p in edge_pts]
            ys = [float(p[1]) for p in edge_pts]
            bounds = (min(xs), min(ys), max(xs), max(ys))
        else:
            # Estimate from component positions
            ats = re.findall(r'\(at\s+([\d.\-]+)\s+([\d.\-]+)', content)
            if ats:
                xs = [float(a[0]) for a in ats]
                ys = [float(a[1]) for a in ats]
                bounds = (min(xs) - 5, min(ys) - 5, max(xs) + 5, max(ys) + 5)
            else:
                return None

        # Extract component count
        comp_count = len(re.findall(r'\(footprint\s+"', content))

        # Extract layers
        layers = set(re.findall(r'\(layer\s+"([^"]+)"', content))

        return {
            "nets": sorted(nets)[:30],  # Limit to 30 nets for readability
            "bounds": bounds,
            "n_components": comp_count,
            "layers": sorted(layers),
        }
    except Exception:
        return None


def generate_strategy(board_context: dict, board_name: str) -> dict:
    """Generate a routing strategy JSON for the board context."""
    nets = board_context["nets"]
    bounds = board_context["bounds"]

    # Classify and prioritize each net
    net_priorities = []
    layer_hints = {}
    router_assignment = {}

    for net in nets:
        net_class = _classify_net(net)
        priority, reason = _priority_for_class(net_class)
        net_priorities.append({"net": net, "priority": priority, "reason": reason})
        layer_hints[net] = _layer_for_class(net_class)
        router_assignment[net] = _router_for_class(net_class)

    # Sort by priority
    net_priorities.sort(key=lambda x: x["priority"])

    # Generate keepouts (near clock/crystal components if present)
    keepouts = []

    # Routing notes
    has_power = any(_classify_net(n) in ("power_ground", "power_rail") for n in nets)
    has_diffpair = any(_classify_net(n) in ("usb", "digital_bus") for n in nets)
    has_analog = any(_classify_net(n) == "analog" for n in nets)

    notes_parts = []
    if has_power:
        notes_parts.append("Route power first (pour GND plane, then power rails)")
    if has_diffpair:
        notes_parts.append("Length-match differential pairs (USB/I2C)")
    if has_analog:
        notes_parts.append("Keep analog traces short and away from digital switching")

    return {
        "net_priorities": net_priorities,
        "layer_hints": layer_hints,
        "keepouts": keepouts,
        "router_assignment": router_assignment,
        "routing_notes": ". ".join(notes_parts) if notes_parts else "Route power first, then critical signals, then general signals.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-manifest", default="/Volumes/Storage/schgen/our_corpus/manifest.jsonl")
    parser.add_argument("--out", default="/Volumes/Storage/schgen/strategy_data")
    parser.add_argument("--target", type=int, default=1000)
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir = out_dir / "images"
    images_dir.mkdir(exist_ok=True)

    manifest_path = Path(args.corpus_manifest)
    if not manifest_path.exists():
        print(f"ERROR: Manifest not found: {manifest_path}")
        sys.exit(1)

    # Load corpus entries with PCBs
    entries = []
    with manifest_path.open() as f:
        for line in f:
            try:
                e = json.loads(line)
            except:
                continue
            if not e.get("ok"):
                continue
            sch_path = e.get("sch_path", "")
            pcb_path = sch_path.replace(".kicad_sch", ".kicad_pcb")
            if Path(pcb_path).exists():
                entries.append({
                    "pcb_path": pcb_path,
                    "repo": e.get("repo", ""),
                    "sch_stem": Path(sch_path).stem,
                    "pcb_png": e.get("out_pcb_png"),
                })

    print(f"Found {len(entries)} corpus PCBs")

    rng = random.Random(42)
    rng.shuffle(entries)

    examples: list[dict] = []
    success = 0
    fail = 0

    for i, entry in enumerate(entries):
        if success >= args.target:
            break

        pcb_path = Path(entry["pcb_path"])
        board_name = f"{entry['repo']}__{entry['sch_stem']}"

        context = extract_board_context(pcb_path)
        if not context or len(context["nets"]) < 3:
            fail += 1
            continue

        strategy = generate_strategy(context, board_name)

        # Build board description for the user message
        bounds = context["bounds"]
        board_w = bounds[2] - bounds[0]
        board_h = bounds[3] - bounds[1]
        n_nets = len(context["nets"])
        n_comp = context["n_components"]

        user_msg = (
            f"Board: {board_name}\n"
            f"Size: {board_w:.1f} × {board_h:.1f} mm\n"
            f"Components: {n_comp}\n"
            f"Nets: {n_nets}\n"
            f"Net list: {', '.join(context['nets'][:20])}\n"
            f"Layers: {', '.join(context['layers'][:6])}\n\n"
            f"Output a routing strategy for this board."
        )

        # PCB image
        pcb_png = entry.get("pcb_png")
        if not pcb_png or not Path(pcb_png).exists():
            pcb_png_path = images_dir / f"{board_name}.png"
            if render_pcb_png(pcb_path, pcb_png_path):
                pcb_png = str(pcb_png_path)
            else:
                pcb_png = None

        example = {
            "messages": [
                {"role": "system", "content": STRATEGY_SYSTEM.strip()},
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": json.dumps(strategy, indent=2)},
            ],
            "task_type": "routing_strategy",
            "source_file": f"pcb/{board_name}",
            "image_path": pcb_png,
            "metadata": {
                "n_components": n_comp,
                "n_nets": n_nets,
                "board_size": f"{board_w:.1f}x{board_h:.1f}",
            },
        }
        examples.append(example)
        success += 1

        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(entries)}] examples={success} fail={fail}")

    # Write output
    out_file = out_dir / "strategy_training_pairs.jsonl"
    with out_file.open("w") as f:
        for ex in examples:
            f.write(json.dumps(ex) + "\n")

    print(f"\nDone. Generated {len(examples)} routing strategy examples.")
    print(f"  Success: {success}")
    print(f"  Failed: {fail}")
    print(f"  With images: {sum(1 for e in examples if e.get('image_path'))}")
    print(f"  Output: {out_file}")


if __name__ == "__main__":
    main()
