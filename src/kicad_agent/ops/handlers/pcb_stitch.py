"""DRC-aware power-net via stitching (ae-37).

Places vias to connect unconnected power pads to their inner-layer planes.
Unlike add_via / add_stitching_via_pattern (blind insertion), this op runs
DRC first, identifies unconnected power-pad pairs, and places vias ONLY at
positions that clear all existing copper (pads, tracks, vias).

The collision check is the key difference: we sample N candidate positions
along the line between the two unconnected endpoints and place the via at
the first position that clears all copper elements.
"""

from __future__ import annotations

import json
import logging
import math
import re
import shutil
import subprocess
import tempfile
import uuid as uuidlib
from pathlib import Path
from typing import Any, Callable

from kicad_agent.ir.pcb_ir import PcbIR

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry (matches pcb_cleanup.py pattern)
# ---------------------------------------------------------------------------

_STITCH_HANDLERS: dict[str, Callable] = {}


def register_stitch(op_type: str) -> Callable:
    """Decorator to register a stitching operation handler."""
    def decorator(fn: Callable) -> Callable:
        _STITCH_HANDLERS[op_type] = fn
        return fn
    return decorator


# ---------------------------------------------------------------------------
# DRC JSON parsing for unconnected_items
# ---------------------------------------------------------------------------

# Common power-net prefixes for auto-detection
_POWER_NET_PREFIXES = (
    "GND", "GNDA", "DGND", "AGND",
    "+3V3", "+5V", "+9V", "+12V", "-9V", "-12V",
    "VCC", "VBUS", "VDD", "VSS",
    "N12V",  # Power_N12V
)


def run_drc_json(pcb_path: Path, output_path: Path) -> bool:
    """Run kicad-cli DRC with JSON output format.

    Returns True if the JSON file was created and parseable.
    """
    result = subprocess.run(
        [
            'kicad-cli', 'pcb', 'drc', str(pcb_path),
            '--output', str(output_path),
            '--format', 'json',
        ],
        capture_output=True,
        text=True,
        timeout=300,  # 5 min for large boards
    )
    if not output_path.exists() or output_path.stat().st_size == 0:
        return False
    try:
        json.loads(output_path.read_text())
        return True
    except json.JSONDecodeError:
        return False


def parse_unconnected_pairs(
    drc_json_path: Path,
    target_nets: list[str],
) -> list[dict[str, Any]]:
    """Parse DRC JSON for unconnected pairs involving target power nets.

    Returns list of dicts: {net, p1: {x,y,desc}, p2: {x,y,desc}}.
    Each pair represents two endpoints that should be connected but aren't.
    """
    with open(drc_json_path) as f:
        drc = json.load(f)

    unconn = drc.get('unconnected_items', [])
    pairs: list[dict[str, Any]] = []

    for item in unconn:
        items = item.get('items', [])
        if len(items) < 2:
            continue

        # Extract net from either endpoint's description
        net = None
        endpoints = []
        for ei in items:
            desc = ei.get('description', '')
            pos = ei.get('pos', {})
            x = pos.get('x', 0.0)
            y = pos.get('y', 0.0)
            # Extract net from description like "Pad 1 [+3V3] of FB1 on F.Cu"
            net_m = re.search(r'\[([^\]]+)\]', desc)
            ep_net = net_m.group(1) if net_m else None
            if ep_net and net is None:
                net = ep_net
            endpoints.append({'x': x, 'y': y, 'desc': desc, 'net': ep_net})

        if net is None:
            continue

        # Filter by target nets
        if target_nets and net not in target_nets:
            continue

        pairs.append({
            'net': net,
            'p1': endpoints[0],
            'p2': endpoints[1],
        })

    return pairs


# ---------------------------------------------------------------------------
# Copper element extraction (for collision detection)
# ---------------------------------------------------------------------------

def extract_copper_obstacles(pcb_text: str) -> list[dict]:
    """Extract all copper obstacles from the PCB for collision checking.

    Returns list of dicts:
      {type: 'pad', x, y, dx, dy}     -- pad center + half-extents
      {type: 'track', x1, y1, x2, y2} -- track segment
      {type: 'via', x, y}             -- via center
    """
    obstacles: list[dict] = []

    # Parse pads from footprints
    # Pad format: (pad "N" smd/ thruhole (at X Y) (size DX DY) (layers ...) ...)
    # Pads have ABSOLUTE coordinates (footprint at + pad at).
    # We need footprint-relative pad positions + footprint (at).
    fp_pattern = re.compile(
        r'\(footprint\s+"[^"]*".*?\(at\s+([\d.eE+-]+)\s+([\d.eE+-]+)(?:\s+([\d.eE+-]+))?',
        re.DOTALL,
    )

    # Split into footprint blocks
    fp_starts = [m.start() for m in re.finditer(r'\(footprint\s', pcb_text)]
    fp_starts.append(len(pcb_text))  # sentinel

    for i in range(len(fp_starts) - 1):
        fp_start = fp_starts[i]
        fp_end = fp_starts[i + 1]
        block = pcb_text[fp_start:fp_end]

        # Footprint position
        at_m = re.search(
            r'\(at\s+([\d.eE+-]+)\s+([\d.eE+-]+)(?:\s+([\d.eE+-]+))?', block[:500]
        )
        if not at_m:
            continue
        fp_x = float(at_m.group(1))
        fp_y = float(at_m.group(2))
        fp_rot = float(at_m.group(3)) if at_m.group(3) else 0.0
        rot_rad = math.radians(fp_rot)
        cos_r = math.cos(rot_rad)
        sin_r = math.sin(rot_rad)

        # Pads within this footprint
        for pad_m in re.finditer(
            r'\(pad\s+"[^"]*"\s+(\w+)\s+\(at\s+([\d.eE+-]+)\s+([\d.eE+-]+)',
            block,
        ):
            pad_type = pad_m.group(1)
            pad_rx = float(pad_m.group(2))  # relative to footprint
            pad_ry = float(pad_m.group(3))

            # Apply footprint rotation
            abs_x = fp_x + pad_rx * cos_r - pad_ry * sin_r
            abs_y = fp_y + pad_rx * sin_r + pad_ry * cos_r

            # Get pad size
            size_m = re.search(
                r'\(size\s+([\d.eE+-]+)\s+([\d.eE+-]+)', block[pad_m.end():pad_m.end()+200]
            )
            if size_m:
                dx = float(size_m.group(1)) / 2.0
                dy = float(size_m.group(2)) / 2.0
            else:
                dx = dy = 0.3  # default pad half-size

            # Get pad net (if any)
            net_m = re.search(r'\(net\s+"([^"]+)"', block[pad_m.end():pad_m.end()+400])
            pad_net = net_m.group(1) if net_m else None

            obstacles.append({
                'type': 'pad',
                'x': abs_x,
                'y': abs_y,
                'dx': dx,
                'dy': dy,
                'net': pad_net,
            })

    # Parse tracks (segments)
    # Format: (segment (start X Y) (end X Y) (width W) ... (net "NAME") ...)
    for seg_m in re.finditer(
        r'\(segment\s+\(start\s+([\d.eE+-]+)\s+([\d.eE+-]+)\)\s+'
        r'\(end\s+([\d.eE+-]+)\s+([\d.eE+-]+)\)\s+'
        r'\(width\s+([\d.eE+-]+)\)'
        r'[^)]*?\(net\s+"([^"]+)"\)',
        pcb_text, re.DOTALL,
    ):
        x1, y1 = float(seg_m.group(1)), float(seg_m.group(2))
        x2, y2 = float(seg_m.group(3)), float(seg_m.group(4))
        w = float(seg_m.group(5)) / 2.0  # half-width
        track_net = seg_m.group(6)
        obstacles.append({
            'type': 'track',
            'x1': x1, 'y1': y1,
            'x2': x2, 'y2': y2,
            'hw': w,
            'net': track_net,
        })

    # Parse vias
    # Format: (via (at X Y) (size S) ... (net "NAME") ...)
    for via_m in re.finditer(
        r'\(via\s+\(at\s+([\d.eE+-]+)\s+([\d.eE+-]+)\)\s+\(size\s+([\d.eE+-]+)\)'
        r'[^)]*?\(net\s+"([^"]+)"\)',
        pcb_text, re.DOTALL,
    ):
        obstacles.append({
            'type': 'via',
            'x': float(via_m.group(1)),
            'y': float(via_m.group(2)),
            'radius': float(via_m.group(3)) / 2.0,
            'net': via_m.group(4),
        })

    logger.info("Extracted %d copper obstacles (pads+tracks+vias)", len(obstacles))
    return obstacles


# ---------------------------------------------------------------------------
# Collision detection
# ---------------------------------------------------------------------------

def _dist_point_to_segment(
    px: float, py: float,
    x1: float, y1: float, x2: float, y2: float,
) -> float:
    """Minimum distance from point (px,py) to segment (x1,y1)-(x2,y2)."""
    dx = x2 - x1
    dy = y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-12:
        # Degenerate segment (point)
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def via_clears_obstacles(
    via_x: float,
    via_y: float,
    via_radius: float,
    clearance: float,
    obstacles: list[dict],
    via_net: str | None = None,
) -> bool:
    """Check if a via at (via_x, via_y) clears all existing copper.

    Uses via_radius + clearance as the minimum distance to copper edges.
    When ``via_net`` is provided, obstacles on the SAME net are skipped
    (a via for +3V3 may overlap +3V3 pads/tracks — that's a connection,
    not a collision).
    """
    min_dist = via_radius + clearance

    for obs in obstacles:
        # Skip same-net obstacles (via-through-pad is a connection, not a short)
        if via_net and obs.get('net') == via_net:
            continue

        if obs['type'] == 'pad':
            # Treat pad as a rectangle centered at (x,y) with half-extents dx,dy.
            # Check if via center is inside the expanded rectangle.
            # For rotated pads this is approximate (ignores pad rotation), but
            # pads are overwhelmingly axis-aligned 0402/0603 SMD.
            expand_x = obs['dx'] + min_dist
            expand_y = obs['dy'] + min_dist
            if (abs(via_x - obs['x']) < expand_x and
                    abs(via_y - obs['y']) < expand_y):
                return False

        elif obs['type'] == 'track':
            # Point-to-segment distance, minus track half-width
            dist = _dist_point_to_segment(
                via_x, via_y,
                obs['x1'], obs['y1'], obs['x2'], obs['y2'],
            )
            if dist < obs['hw'] + min_dist:
                return False

        elif obs['type'] == 'via':
            # Point-to-point distance
            dist = math.hypot(via_x - obs['x'], via_y - obs['y'])
            if dist < obs['radius'] + min_dist:
                return False

    return True


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

@register_stitch("stitch_power_nets")
def _handle_stitch_power_nets(
    op: Any, ir: PcbIR, file_path: Path,
) -> dict[str, Any]:
    """DRC-aware via stitching for power-net completion (ae-37).

    Runs DRC, finds unconnected power-pad pairs, places vias at DRC-cleared
    positions to bridge signal-layer pads to inner-layer power planes.
    """
    # Lazy import (matches pcb_cleanup.py pattern to avoid circulars)
    from kicad_agent.ops.handlers.pcb_cleanup import validate_paren_balance
    from kicad_agent.ops.pcb_raw_writer import PcbRawWriter

    # Resolve nets (auto-detect if empty)
    nets = list(op.nets) if op.nets else []
    if not nets:
        # Auto-detect: scan PCB for power-net names
        pcb_text_scan = ir.raw_content if ir.raw_content else file_path.read_text()
        all_nets = set(re.findall(r'\(net\s+"([^"]+)"\)', pcb_text_scan))
        nets = [n for n in sorted(all_nets) if n.startswith(_POWER_NET_PREFIXES)]
        if not nets:
            return {
                "success": False,
                "error": "No power nets found in PCB and none specified",
                "vias_placed": 0,
                "vias_skipped": 0,
                "unconnected_before": 0,
                "unconnected_after": 0,
            }
        logger.info("Auto-detected power nets: %s", nets)

    # Create backup
    backup_path = Path(str(file_path) + ".bak")
    try:
        shutil.copy2(file_path, backup_path)
        logger.info("Backup created: %s", backup_path)
    except OSError as exc:
        return {
            "success": False,
            "error": f"Failed to create backup: {exc}",
            "vias_placed": 0,
            "vias_skipped": 0,
            "unconnected_before": 0,
            "unconnected_after": 0,
        }

    # Run DRC to find unconnected pairs
    with tempfile.NamedTemporaryFile(
        suffix=".json", prefix="stitch_drc_", delete=False,
    ) as tmp:
        drc_json_path = Path(tmp.name)

    try:
        if not run_drc_json(file_path, drc_json_path):
            return {
                "success": False,
                "error": "kicad-cli pcb drc failed or produced unparseable JSON",
                "vias_placed": 0,
                "vias_skipped": 0,
                "unconnected_before": 0,
                "unconnected_after": 0,
            }
    except Exception as exc:
        logger.warning("DRC subprocess raised: %s", exc)
        return {
            "success": False,
            "error": f"DRC subprocess raised: {exc}",
            "vias_placed": 0,
            "vias_skipped": 0,
            "unconnected_before": 0,
            "unconnected_after": 0,
        }

    # Parse unconnected pairs for our target nets
    pairs = parse_unconnected_pairs(drc_json_path, nets)
    unconnected_before = len(pairs)
    logger.info(
        "DRC unconnected pairs for power nets: %d (nets: %s)",
        unconnected_before, nets,
    )

    if not pairs:
        return {
            "success": True,
            "vias_placed": 0,
            "vias_skipped": 0,
            "unconnected_before": 0,
            "unconnected_after": 0,
            "message": "No unconnected power-net pairs found",
        }

    # Extract copper obstacles for collision detection
    pcb_text = ir.raw_content if ir.raw_content else file_path.read_text()
    obstacles = extract_copper_obstacles(pcb_text)

    # Place vias
    via_radius = op.via_size / 2.0
    clearance = op.clearance
    max_vias = op.max_vias
    candidate_count = op.candidate_count

    via_sexprs: list[str] = []
    vias_placed = 0
    vias_skipped = 0
    skip_reasons: dict[str, int] = {
        'clearance_conflict': 0,
        'no_valid_candidate': 0,
        'max_vias_reached': 0,
    }

    for pair in pairs:
        if vias_placed >= max_vias:
            skip_reasons['max_vias_reached'] += 1
            continue

        p1 = pair['p1']
        p2 = pair['p2']

        # Distance between the two endpoints
        dx = p2['x'] - p1['x']
        dy = p2['y'] - p1['y']
        pair_length = math.hypot(dx, dy)

        # SHORT-DISTANCE PAIRS: if endpoints are within via_size of each other,
        # they're on different layers at nearly the same XY. Place the via at
        # the midpoint directly — it connects through the pad. This is the
        # common case for power pads that need a via to reach an inner plane.
        # We skip the pad collision check for these (the via goes through the
        # pad intentionally), but still check tracks/vias.
        if pair_length < op.via_size:
            mid_x = (p1['x'] + p2['x']) / 2.0
            mid_y = (p1['y'] + p2['y']) / 2.0
            # Check only tracks and vias (NOT pads — via-through-pad is OK)
            non_pad_obstacles = [o for o in obstacles if o['type'] != 'pad']
            if via_clears_obstacles(mid_x, mid_y, via_radius, clearance, non_pad_obstacles, via_net=pair['net']):
                via_uuid = str(uuidlib.uuid4())
                sexp = PcbRawWriter.build_via_sexp(
                    at=(mid_x, mid_y),
                    size=op.via_size,
                    drill=op.via_drill,
                    layers=["F.Cu", "B.Cu"],
                    net_name=pair['net'],
                    uuid_str=via_uuid,
                )
                via_sexprs.append(sexp)
                vias_placed += 1
                obstacles.append({'type': 'via', 'x': mid_x, 'y': mid_y, 'radius': via_radius})
                continue
            # else fall through to normal candidate search

        # NORMAL PAIRS: generate candidate positions along the line p1 -> p2
        # Sample candidate_count points between the two endpoints
        placed = False
        for i in range(1, candidate_count + 1):
            t = i / (candidate_count + 1)  # avoid exact endpoints
            cx = p1['x'] + t * (p2['x'] - p1['x'])
            cy = p1['y'] + t * (p2['y'] - p1['y'])

            # Offset perpendicular to the line to try alternate positions
            # if the direct line is blocked. Try t along line first, then
            # +/- 0.5mm perpendicular offsets.
            length = pair_length
            if length > 1e-6:
                perp_x = -dy / length
                perp_y = dx / length
            else:
                perp_x = perp_y = 0.0

            for offset in (0.0, 0.5, -0.5, 1.0, -1.0):
                test_x = cx + offset * perp_x
                test_y = cy + offset * perp_y

                if via_clears_obstacles(
                    test_x, test_y, via_radius, clearance, obstacles,
                    via_net=pair['net'],
                ):
                    # Place the via here
                    via_uuid = str(uuidlib.uuid4())
                    sexp = PcbRawWriter.build_via_sexp(
                        at=(test_x, test_y),
                        size=op.via_size,
                        drill=op.via_drill,
                        layers=["F.Cu", "B.Cu"],
                        net_name=pair['net'],
                        uuid_str=via_uuid,
                    )
                    via_sexprs.append(sexp)
                    vias_placed += 1
                    placed = True
                    # Add this via to obstacles so subsequent checks avoid it
                    obstacles.append({
                        'type': 'via',
                        'x': test_x,
                        'y': test_y,
                        'radius': via_radius,
                    })
                    break  # found a valid position for this pair

            if placed:
                break

        if not placed:
            vias_skipped += 1
            skip_reasons['no_valid_candidate'] += 1

    logger.info(
        "Stitching complete: %d vias placed, %d skipped (reasons: %s)",
        vias_placed, vias_skipped, skip_reasons,
    )

    if not via_sexprs:
        return {
            "success": True,
            "vias_placed": 0,
            "vias_skipped": vias_skipped,
            "skip_reasons": skip_reasons,
            "unconnected_before": unconnected_before,
            "unconnected_after": unconnected_before,  # no change
            "message": "No valid via positions found for any unconnected pair",
        }

    # Insert vias into PCB
    all_vias_text = "".join(via_sexprs)
    new_content = PcbRawWriter.insert_segments(ir.raw_content, all_vias_text)

    # Validate paren balance before commit
    if not validate_paren_balance(new_content):
        logger.error(
            "Paren balance check FAILED after stitch_power_nets. Restoring backup."
        )
        shutil.copy2(backup_path, file_path)
        return {
            "success": False,
            "error": "Paren balance check failed after via insertion. Backup restored.",
            "vias_placed": 0,
            "vias_skipped": vias_skipped,
            "unconnected_before": unconnected_before,
            "unconnected_after": unconnected_before,
        }

    ir.commit_raw_content(new_content)

    # Re-run DRC to measure improvement
    unconnected_after = unconnected_before
    try:
        if run_drc_json(file_path, drc_json_path):
            remaining_pairs = parse_unconnected_pairs(drc_json_path, nets)
            unconnected_after = len(remaining_pairs)
    except Exception as exc:
        logger.warning("Post-stitch DRC failed: %s", exc)

    return {
        "success": True,
        "vias_placed": vias_placed,
        "vias_skipped": vias_skipped,
        "skip_reasons": skip_reasons,
        "unconnected_before": unconnected_before,
        "unconnected_after": unconnected_after,
        "nets_stitched": nets,
    }
