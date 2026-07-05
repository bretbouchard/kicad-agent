"""Generate placement intelligence training data.

Creates SFT pairs that teach the model WHERE components should be placed
based on contextual rules (edge affinity, decoupling proximity, EMI avoidance).

Two kinds of examples per circuit:
1. GOOD placement: components placed with floor plan rules applied
2. BAD placement: components placed randomly (no rules)
Each pair includes a PCB render + the placement decision + rationale.

Also generates "component knowledge" pairs: given a component type + its
neighbors, predict the optimal placement rationale.

Usage:
    python3 generate_placement_data.py \
        --corpus-manifest /Volumes/Storage/schgen/our_corpus/manifest.jsonl \
        --out /Volumes/Storage/schgen/placement_data \
        --target 1500
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


PLACEMENT_SYSTEM = """\
You are a PCB placement expert. Analyze component placement and provide reasoning for optimal positioning.

Consider these contextual rules:
- Decoupling caps: place within 5mm of IC power pins
- Connectors: place at board edge for accessibility
- Crystals: place close to MCU clock pins, away from high-speed signals
- Power components: group together, away from sensitive analog
- EMI-sensitive: keep analog traces short, away from digital switching
- Thermal: hot components need spacing and copper pour relief

Output format:
PLACEMENT ANALYSIS:
- Component: [ref] [lib_id] at (x, y)
  Rule: [which placement rule applies]
  Decision: [GOOD/BAD/OPTIMAL]
  Rationale: [why this placement is correct/incorrect]
  Suggestion: [if not optimal, where it should go]
SCORE: [0-100 placement quality]
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


def _classify_component(lib_id: str) -> str:
    """Classify component for placement rules."""
    lib_lower = lib_id.lower()
    if "capacitor" in lib_lower or lib_id.startswith("Device:C"):
        return "capacitor"
    elif "connector" in lib_lower or lib_id.startswith("Connector"):
        return "connector"
    elif "crystal" in lib_lower:
        return "crystal"
    elif "regulator" in lib_lower or "regulator_linear" in lib_lower:
        return "regulator"
    elif any(x in lib_lower for x in ("mcu", "stm32", "esp32", "atmega", "rp2040")):
        return "mcu"
    elif "opamp" in lib_lower or "amplifier" in lib_lower:
        return "amplifier"
    elif "led" in lib_lower:
        return "led"
    elif "resistor" in lib_lower or lib_id.startswith("Device:R"):
        return "resistor"
    elif "switch" in lib_lower:
        return "switch"
    elif "usb" in lib_lower:
        return "usb"
    elif "transistor" in lib_lower or "mosfet" in lib_lower:
        return "transistor"
    return "generic"


def _generate_placement_rationale(
    components: list[dict],
    board_width: float,
    board_height: float,
    is_good: bool,
) -> str:
    """Generate placement rationale text for a set of components."""
    lines = ["PLACEMENT ANALYSIS:"]

    # Find the MCU/IC if present
    ic = next((c for c in components if c["type"] in ("mcu", "amplifier")), None)
    connectors = [c for c in components if c["type"] == "connector"]
    caps = [c for c in components if c["type"] == "capacitor"]
    crystals = [c for c in components if c["type"] == "crystal"]

    score = 85 if is_good else 35
    reasons_good = []
    reasons_bad = []

    for c in components[:15]:  # Limit to first 15 for readability
        ctype = c["type"]
        ref = c["ref"]
        x, y = c["x"], c["y"]
        lib_id = c["lib_id"]

        if ctype == "connector":
            edge_dist = min(x, y, board_width - x, board_height - y)
            if is_good:
                if edge_dist < 10:
                    lines.append(f"- Component: {ref} [{lib_id}] at ({x:.1f}, {y:.1f})")
                    lines.append(f"  Rule: edge_affinity")
                    lines.append(f"  Decision: GOOD")
                    lines.append(f"  Rationale: Connector placed {edge_dist:.1f}mm from board edge — accessible for cable insertion")
                    reasons_good.append(f"{ref} at edge")
                else:
                    lines.append(f"- Component: {ref} [{lib_id}] at ({x:.1f}, {y:.1f})")
                    lines.append(f"  Rule: edge_affinity")
                    lines.append(f"  Decision: SUBOPTIMAL")
                    lines.append(f"  Rationale: Connector {edge_dist:.1f}mm from edge — could be closer for accessibility")
            else:
                lines.append(f"- Component: {ref} [{lib_id}] at ({x:.1f}, {y:.1f})")
                lines.append(f"  Rule: edge_affinity")
                lines.append(f"  Decision: BAD")
                lines.append(f"  Rationale: Connector placed in board interior ({edge_dist:.1f}mm from edge) — difficult to access")
                lines.append(f"  Suggestion: Move to within 5mm of board edge")
                reasons_bad.append(f"{ref} not at edge")
                score -= 5

        elif ctype == "capacitor" and ic:
            # Distance to IC
            ic_x, ic_y = ic["x"], ic["y"]
            dist = ((x - ic_x)**2 + (y - ic_y)**2)**0.5
            if is_good:
                if dist < 10:
                    lines.append(f"- Component: {ref} [{lib_id}] at ({x:.1f}, {y:.1f})")
                    lines.append(f"  Rule: decoupling_proximity")
                    lines.append(f"  Decision: GOOD")
                    lines.append(f"  Rationale: Decoupling cap {dist:.1f}mm from {ic['ref']} — effective noise suppression")
                    reasons_good.append(f"{ref} near {ic['ref']}")
            else:
                lines.append(f"- Component: {ref} [{lib_id}] at ({x:.1f}, {y:.1f})")
                lines.append(f"  Rule: decoupling_proximity")
                lines.append(f"  Decision: BAD")
                lines.append(f"  Rationale: Decoupling cap {dist:.1f}mm from {ic['ref']} — too far for effective decoupling")
                lines.append(f"  Suggestion: Place within 5mm of IC power pins")
                reasons_bad.append(f"{ref} far from {ic['ref']}")
                score -= 8

        elif ctype == "crystal" and ic:
            dist = ((x - ic["x"])**2 + (y - ic["y"])**2)**0.5
            if is_good:
                lines.append(f"- Component: {ref} [{lib_id}] at ({x:.1f}, {y:.1f})")
                lines.append(f"  Rule: clock_proximity")
                lines.append(f"  Decision: GOOD")
                lines.append(f"  Rationale: Crystal {dist:.1f}mm from MCU clock pins — minimal clock trace length")
            else:
                lines.append(f"- Component: {ref} [{lib_id}] at ({x:.1f}, {y:.1f})")
                lines.append(f"  Rule: clock_proximity")
                lines.append(f"  Decision: BAD")
                lines.append(f"  Rationale: Crystal {dist:.1f}mm from MCU — long clock traces invite noise")
                lines.append(f"  Suggestion: Place within 10mm of MCU")
                reasons_bad.append(f"{ref} far from MCU")
                score -= 10

        elif ctype in ("regulator", "transistor"):
            # Check thermal spacing
            nearest = min(((x - oc["x"])**2 + (y - oc["y"])**2)**0.5
                         for oc in components if oc["ref"] != ref) if len(components) > 1 else 50
            if is_good and nearest > 5:
                lines.append(f"- Component: {ref} [{lib_id}] at ({x:.1f}, {y:.1f})")
                lines.append(f"  Rule: thermal_spacing")
                lines.append(f"  Decision: GOOD")
                lines.append(f"  Rationale: {ctype.title()} has {nearest:.1f}mm clearance — adequate thermal dissipation")
            elif not is_good and nearest < 3:
                lines.append(f"- Component: {ref} [{lib_id}] at ({x:.1f}, {y:.1f})")
                lines.append(f"  Rule: thermal_spacing")
                lines.append(f"  Decision: BAD")
                lines.append(f"  Rationale: Power component only {nearest:.1f}mm from neighbor — thermal interference risk")
                reasons_bad.append(f"{ref} thermally crowded")
                score -= 5

    lines.append(f"SCORE: {max(0, min(100, score))}")

    if is_good:
        lines.append(f"\nSummary: Good placement — {', '.join(reasons_good[:5]) if reasons_good else 'components well-distributed'}")
    else:
        lines.append(f"\nSummary: Poor placement — {', '.join(reasons_bad[:5]) if reasons_bad else 'components poorly distributed'}")

    return "\n".join(lines)


def parse_pcb_components(pcb_path: Path) -> list[dict] | None:
    """Extract component list with positions from a PCB file.

    Uses regex on the raw .kicad_pcb content because the native parser
    doesn't extract Reference designators from footprint properties.
    """
    import re

    try:
        content = pcb_path.read_text(encoding="utf-8")

        # Extract footprint blocks: (footprint (lib_id "...") ... (at X Y ROT) ... (property "Reference" "R1") ...)
        # Match each footprint block
        components = []
        for fp_match in re.finditer(r'\(footprint\s+"([^"]+)"[^)]*?\)', content):
            lib_id = fp_match.group(1)
            # Find the block boundaries
            block_start = fp_match.start()
            depth = 0
            block_end = block_start
            for i in range(block_start, len(content)):
                if content[i] == '(':
                    depth += 1
                elif content[i] == ')':
                    depth -= 1
                    if depth == 0:
                        block_end = i + 1
                        break
            block = content[block_start:block_end]

            # Extract position (at X Y ROT)
            at_match = re.search(r'\(at\s+([\d.\-]+)\s+([\d.\-]+)', block)
            # Extract reference
            ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)

            if at_match and ref_match:
                ref = ref_match.group(1)
                if ref == "?" or not ref:
                    continue
                x, y = float(at_match.group(1)), float(at_match.group(2))
                components.append({
                    "ref": ref,
                    "lib_id": lib_id,
                    "type": _classify_component(lib_id),
                    "x": x,
                    "y": y,
                })

        return components if len(components) >= 3 else None
    except Exception:
        return None


def generate_placement_pairs(
    components: list[dict],
    bounds: tuple[float, float, float, float],
    pcb_name: str,
    pcb_png: str | None,
) -> list[dict]:
    """Generate good and bad placement examples for a set of components."""
    examples = []
    board_w = bounds[2] - bounds[0]
    board_h = bounds[3] - bounds[1]

    # GOOD placement: use actual positions (from a well-designed board)
    good_text = _generate_placement_rationale(components, board_w, board_h, is_good=True)
    examples.append({
        "messages": [
            {"role": "system", "content": PLACEMENT_SYSTEM.strip()},
            {"role": "user", "content": f"Analyze the placement quality of this PCB: {pcb_name}. Board size: {board_w:.1f}×{board_h:.1f}mm. {len(components)} components."},
            {"role": "assistant", "content": good_text},
        ],
        "task_type": "placement_intelligence",
        "source_file": f"pcb/{pcb_name}",
        "image_path": pcb_png,
        "metadata": {"placement": "actual", "n_components": len(components)},
    })

    # BAD placement: shuffle positions randomly
    rng = random.Random(42)
    shuffled = []
    positions = [(c["x"], c["y"]) for c in components]
    rng.shuffle(positions)
    for i, c in enumerate(components):
        bad_c = dict(c)
        bad_c["x"], bad_c["y"] = positions[i]
        shuffled.append(bad_c)

    bad_text = _generate_placement_rationale(shuffled, board_w, board_h, is_good=False)
    examples.append({
        "messages": [
            {"role": "system", "content": PLACEMENT_SYSTEM.strip()},
            {"role": "user", "content": f"Analyze the placement quality of this PCB: {pcb_name} (modified). Board size: {board_w:.1f}×{board_h:.1f}mm. {len(components)} components."},
            {"role": "assistant", "content": bad_text},
        ],
        "task_type": "placement_intelligence",
        "source_file": f"pcb/{pcb_name}_modified",
        "image_path": pcb_png,
        "metadata": {"placement": "shuffled", "n_components": len(components)},
    })

    return examples


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-manifest", default="/Volumes/Storage/schgen/our_corpus/manifest.jsonl")
    parser.add_argument("--out", default="/Volumes/Storage/schgen/placement_data")
    parser.add_argument("--target", type=int, default=1500)
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir = out_dir / "images"
    images_dir.mkdir(exist_ok=True)

    manifest_path = Path(args.corpus_manifest)
    if not manifest_path.exists():
        print(f"ERROR: Manifest not found: {manifest_path}")
        sys.exit(1)

    # Load corpus entries that have PCBs
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

    print(f"Found {len(entries)} corpus PCBs with components")

    # We generate 2 examples per PCB (good + bad), so target/2 PCBs needed
    max_pcbs = args.target // 2 + 50
    rng = random.Random(42)
    rng.shuffle(entries)
    entries = entries[:max_pcbs]

    examples: list[dict] = []
    success = 0
    fail = 0

    for i, entry in enumerate(entries):
        if success >= args.target:
            break

        pcb_path = Path(entry["pcb_path"])
        pcb_name = f"{entry['repo']}__{entry['sch_stem']}"

        components = parse_pcb_components(pcb_path)
        if not components or len(components) < 3:
            fail += 1
            continue

        # Get board bounds from raw content (Edge.Cuts line)
        try:
            import re as _re
            raw = pcb_path.read_text()
            # Find the bounding box from gr_line or gr_rect on Edge.Cuts
            edge_pts = _re.findall(r'\(gr_line\s+\(start\s+([\d.\-]+)\s+([\d.\-]+)\).*?Edge\.Cuts', raw, _re.DOTALL)
            if edge_pts:
                xs = [float(p[0]) for p in edge_pts]
                ys = [float(p[1]) for p in edge_pts]
                bounds = (min(xs), min(ys), max(xs), max(ys))
            else:
                # Fallback: use component positions to estimate bounds
                xs = [c["x"] for c in components]
                ys = [c["y"] for c in components]
                margin = 5.0
                bounds = (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)
        except Exception:
            fail += 1
            continue

        # Use existing PCB render if available, otherwise render
        pcb_png = entry.get("pcb_png")
        if not pcb_png or not Path(pcb_png).exists():
            pcb_png_path = images_dir / f"{pcb_name}.png"
            if render_pcb_png(pcb_path, pcb_png_path):
                pcb_png = str(pcb_png_path)
            else:
                pcb_png = None  # Text-only example

        pairs = generate_placement_pairs(components, bounds, pcb_name, pcb_png)
        examples.extend(pairs)
        success += len(pairs)

        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(entries)}] examples={success} fail={fail}")

    # Write output
    out_file = out_dir / "placement_training_pairs.jsonl"
    with out_file.open("w") as f:
        for ex in examples:
            f.write(json.dumps(ex) + "\n")

    print(f"\nDone. Generated {len(examples)} placement examples.")
    print(f"  Success: {success}")
    print(f"  Failed: {fail}")
    print(f"  With images: {sum(1 for e in examples if e.get('image_path'))}")
    print(f"  Output: {out_file}")


if __name__ == "__main__":
    main()
