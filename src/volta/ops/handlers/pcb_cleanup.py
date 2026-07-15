"""PCB cleanup handlers: strip_shorts and remove_dangling_tracks.

Ports the proven strip_shorts.py and remove_dangling.py workaround scripts
into volta's handler system. Both use raw S-expression text manipulation
(NOT kiutils -- kiutils corrupts PCBs).

strip_shorts: Removes track segments that cause DRC shorting_items violations.
  - Matches by net name + exact endpoint coordinates within tolerance
  - Also removes zero-length artifacts (start == end)

remove_dangling_tracks: Iteratively removes orphaned tracks and vias.
  - ONLY removes fully-dangling segments (both ends orphaned)
  - Half-connected segments at pads are NOT removed (false positives)
  - Iterates with DRC re-run until convergence

See: strip_shorts.py and remove_dangling.py reference implementations.
"""

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from volta.ir.pcb_ir import PcbIR

logger = logging.getLogger(__name__)

_CLEANUP_HANDLERS: dict[str, Callable] = {}


def register_cleanup(op_type: str) -> Callable:
    """Decorator to register a cleanup operation handler."""
    def decorator(fn: Callable) -> Callable:
        _CLEANUP_HANDLERS[op_type] = fn
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------


def parse_segments(pcb_text: str) -> list[dict]:
    """Parse all (segment ...) blocks from PCB text.

    Returns list of dicts with line_start, line_end, start_x, start_y,
    end_x, end_y, layer, net.
    """
    segments: list[dict] = []
    lines = pcb_text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if line == '\t(segment':
            seg: dict = {'line_start': i, 'line_end': i}
            fields: dict = {}
            j = i + 1
            while j < len(lines):
                sline = lines[j].rstrip()
                if sline == '\t)':
                    seg['line_end'] = j
                    seg.update(fields)
                    segments.append(seg)
                    i = j
                    break
                m = re.match(r'\t\t\((\w+)\s+(.+)\)', sline)
                if m:
                    key = m.group(1)
                    val = m.group(2).strip()
                    if key in ('start', 'end'):
                        parts = val.split()
                        fields[f'{key}_x'] = float(parts[0])
                        fields[f'{key}_y'] = float(parts[1])
                    elif key == 'layer':
                        fields['layer'] = val.strip('"')
                    elif key == 'net':
                        fields['net'] = val.strip('"')
                    elif key == 'uuid':
                        fields['uuid'] = val.strip('"')
                j += 1
        i += 1
    return segments


def parse_vias(pcb_text: str) -> list[dict]:
    """Parse all (via ...) blocks from PCB text.

    Returns list of dicts with line_start, line_end, x, y, size, drill,
    layers, net.
    """
    vias: list[dict] = []
    lines = pcb_text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if line == '\t(via':
            via: dict = {'line_start': i, 'line_end': i}
            fields: dict = {}
            j = i + 1
            while j < len(lines):
                sline = lines[j].rstrip()
                if sline == '\t)':
                    via['line_end'] = j
                    via.update(fields)
                    vias.append(via)
                    i = j
                    break
                m = re.match(r'\t\t\((\w+)\s+(.+)\)', sline)
                if m:
                    key = m.group(1)
                    val = m.group(2).strip()
                    if key == 'at':
                        parts = val.split()
                        fields['x'] = float(parts[0])
                        fields['y'] = float(parts[1])
                    elif key == 'size':
                        fields['size'] = float(val)
                    elif key == 'drill':
                        fields['drill'] = float(val)
                    elif key == 'layers':
                        fields['layers'] = val.strip('"')
                    elif key == 'net':
                        fields['net'] = val.strip('"')
                    elif key == 'uuid':
                        fields['uuid'] = val.strip('"')
                j += 1
        i += 1
    return vias


def validate_paren_balance(text: str) -> bool:
    """Check that S-expression parentheses are balanced."""
    depth = 0
    for ch in text:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def run_drc(pcb_path: Path, output_path: Path) -> bool:
    """Run kicad-cli DRC on a PCB file.

    Returns True if report file was created and is non-empty.
    """
    result = subprocess.run(
        ['kicad-cli', 'pcb', 'drc', str(pcb_path), '--output', str(output_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return output_path.exists() and output_path.stat().st_size > 0


def count_drc_categories(report_path: Path) -> dict[str, int]:
    """Count violations by category from a DRC report."""
    text = report_path.read_text()
    counts: dict[str, int] = {}
    for m in re.finditer(r'^\[([^\]]+)\]:', text, re.MULTILINE):
        cat = m.group(1)
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def parse_drc_dangling_endpoints(
    report_path: Path,
) -> set[tuple[str, str, float, float]]:
    """Parse DRC report for track_dangling and via_dangling violations.

    Returns set of (net, layer, x, y) tuples.
    Deduplicates -- DRC may report same endpoint multiple times.
    """
    text = report_path.read_text()
    endpoints: set[tuple[str, str, float, float]] = set()

    # Track dangling: @(X mm, Y mm): Track [NET] on LAYER, length ...
    pat_track = re.compile(
        r'\[track_dangling\]:\s*Track has unconnected end\s*\n'
        r'\s*Local override; warning\s*\n'
        r'\s*@[\(]([\d.]+)\s*mm,\s*([\d.]+)\s*mm[\)]:\s*Track\s*\[([^\]]+)\]\s*on\s*(\S+)',
        re.MULTILINE,
    )

    # Via dangling: @(X mm, Y mm): Via [NET] on LAYER1 - LAYER2
    pat_via = re.compile(
        r'\[via_dangling\]:\s*Via is not connected or connected on only one layer\s*\n'
        r'\s*Local override; warning\s*\n'
        r'\s*@[\(]([\d.]+)\s*mm,\s*([\d.]+)\s*mm[\)]:\s*Via\s*\[([^\]]+)\]\s*on\s*(\S+)',
        re.MULTILINE,
    )

    for m in pat_track.finditer(text):
        net = m.group(3).strip()
        layer = m.group(4).strip().rstrip(',')
        x, y = float(m.group(1)), float(m.group(2))
        endpoints.add((net, layer, x, y))

    for m in pat_via.finditer(text):
        net = m.group(3).strip()
        layer = m.group(4).strip().rstrip(',')
        x, y = float(m.group(1)), float(m.group(2))
        endpoints.add((net, layer, x, y))

    return endpoints


def parse_drc_shorting_items(
    report_path: Path,
) -> list[tuple[str, float, float]]:
    """Parse DRC report for shorting_items violations.

    Returns list of (net, track_endpoint_x, track_endpoint_y) tuples.
    Handles both quoted and unquoted net names in DRC output.
    """
    text = report_path.read_text()
    shorts: list[tuple[str, float, float]] = []

    # KiCad 10 DRC text format (verified against kicad-cli 10.0.3):
    #   [shorting_items]: Items shorting two nets (nets NET1 and NET2)
    #       Local override; error          ← may or may not be present
    #       @(X mm, Y mm): Track/Via [NET] on LAYER, length ...
    #       @(X2 mm, Y2 mm): Track/Via [NET2] on LAYER2, length ...
    #
    # Each shorting_items block contains TWO coordinate lines (the two shorted
    # items). We capture both, but only keep the ones that reference a "Track"
    # (vias are not removable by this op). Net names may be quoted, unquoted,
    # or contain slashes (e.g. /Codec Stage/adc_in1_filter).
    pat = re.compile(
        r'\[shorting_items\]:\s*[^\n]*\n'
        r'(?:\s*Local override;[^\n]*\n)?'
        r'(\s*@[\(]([\d.]+)\s*mm,\s*([\d.]+)\s*mm[\)]:\s*(Track|Via)\s*\[([^\]]+)\][^\n]*\n'
        r'\s*@[\(]([\d.]+)\s*mm,\s*([\d.]+)\s*mm[\)]:\s*(Track|Via)\s*\[([^\]]+)\][^\n]*\n)',
        re.MULTILINE,
    )

    for m in pat.finditer(text):
        # First shorted item
        kind1 = m.group(4)
        if kind1 == "Track":
            x, y = float(m.group(2)), float(m.group(3))
            net = m.group(5).strip()
            shorts.append((net, x, y))
        # Second shorted item
        kind2 = m.group(8)
        if kind2 == "Track":
            x, y = float(m.group(6)), float(m.group(7))
            net = m.group(9).strip()
            shorts.append((net, x, y))

    # Deduplicate (DRC may report the same track in multiple shorting_items)
    seen = set()
    deduped: list[tuple[str, float, float]] = []
    for net, x, y in shorts:
        key = (net, round(x, 4), round(y, 4))
        if key not in seen:
            seen.add(key)
            deduped.append((net, x, y))

    return deduped


def remove_elements(
    pcb_text: str,
    segments: list[dict],
    vias: list[dict],
    seg_indices: set[int],
    via_indices: set[int],
) -> str:
    """Remove specified segments and vias from PCB text by line range."""
    remove_ranges: set[int] = set()
    for seg in segments:
        if seg['line_start'] in seg_indices:
            remove_ranges.update(range(seg['line_start'], seg['line_end'] + 1))
    for via in vias:
        if via['line_start'] in via_indices:
            remove_ranges.update(range(via['line_start'], via['line_end'] + 1))

    lines = pcb_text.split('\n')
    return '\n'.join(l for i, l in enumerate(lines) if i not in remove_ranges)


# ---------------------------------------------------------------------------
# Importable inner functions for pipeline use
# ---------------------------------------------------------------------------


def _do_strip_shorts(
    file_path: Path,
    ir: PcbIR,
    *,
    tolerance_mm: float = 0.01,
) -> dict[str, Any]:
    """Remove shorting track segments identified by DRC shorting_items.

    Importable inner function that can be called directly by pipeline handlers
    without going through the full handler dispatch. Creates a backup, runs DRC,
    parses shorting_items, matches by net + coordinates, removes segments.

    Args:
        file_path: Resolved path to the .kicad_pcb file.
        ir: PcbIR providing raw PCB text.
        tolerance_mm: Coordinate matching tolerance in mm.

    Returns:
        Dict with success, removed, shorts_found, artifacts_removed counts.
    """
    # Create backup
    backup_path = Path(str(file_path) + ".bak")
    try:
        shutil.copy2(file_path, backup_path)
        logger.info("Backup created: %s", backup_path)
    except OSError as exc:
        return {
            "success": False,
            "error": f"Failed to create backup: {exc}",
            "removed": 0,
            "shorts_found": 0,
            "artifacts_removed": 0,
        }

    # Auto-run DRC
    with tempfile.NamedTemporaryFile(
        suffix=".rpt", prefix="strip_shorts_drc_", delete=False,
    ) as tmp:
        drc_report = Path(tmp.name)
    try:
        if not run_drc(file_path, drc_report):
            return {
                "success": False,
                "error": "kicad-cli pcb drc failed or produced empty report",
                "removed": 0,
                "shorts_found": 0,
                "artifacts_removed": 0,
            }
    except Exception as exc:
        logger.warning("DRC subprocess raised: %s", exc)
        return {
            "success": False,
            "error": f"DRC subprocess raised: {exc}",
            "removed": 0,
            "shorts_found": 0,
            "artifacts_removed": 0,
        }

    # Parse shorting items
    drc_endpoints = parse_drc_shorting_items(drc_report)
    logger.info("DRC shorting_items found: %d", len(drc_endpoints))

    if not drc_endpoints:
        return {
            "success": True,
            "removed": 0,
            "shorts_found": 0,
            "artifacts_removed": 0,
        }

    # Parse PCB segments
    pcb_text = ir.raw_content if ir.raw_content else file_path.read_text()
    segments = parse_segments(pcb_text)
    logger.info("PCB segments: %d", len(segments))

    tol = tolerance_mm
    to_remove: list[dict] = []

    # Match segments by net + endpoint coordinates
    for target_net, tx, ty in drc_endpoints:
        for seg in segments:
            if seg.get('net', '') != target_net:
                continue
            for ex, ey in [
                (seg.get('start_x', 0), seg.get('start_y', 0)),
                (seg.get('end_x', 0), seg.get('end_y', 0)),
            ]:
                if abs(ex - tx) < tol and abs(ey - ty) < tol:
                    if seg not in to_remove:
                        to_remove.append(seg)

    # Also identify zero-length artifacts
    artifacts_removed = 0
    for seg in segments:
        if seg in to_remove:
            continue
        sx = seg.get('start_x', 0)
        sy = seg.get('start_y', 0)
        ex = seg.get('end_x', 0)
        ey = seg.get('end_y', 0)
        if abs(sx - ex) < tol and abs(sy - ey) < tol:
            to_remove.append(seg)
            artifacts_removed += 1

    if not to_remove:
        return {
            "success": True,
            "removed": 0,
            "shorts_found": len(drc_endpoints),
            "artifacts_removed": 0,
        }

    # Remove matched segments
    pcb_lines = pcb_text.split('\n')
    lines_to_remove: set[int] = set()
    for seg in to_remove:
        for ln in range(seg['line_start'], seg['line_end'] + 1):
            lines_to_remove.add(ln)

    new_text = '\n'.join(
        l for i, l in enumerate(pcb_lines) if i not in lines_to_remove
    )

    # Validate paren balance
    if not validate_paren_balance(new_text):
        logger.error("Paren balance check FAILED after strip_shorts. Restoring backup.")
        shutil.copy2(backup_path, file_path)
        return {
            "success": False,
            "error": "Paren balance check failed after removal. Backup restored.",
            "removed": 0,
            "shorts_found": len(drc_endpoints),
            "artifacts_removed": 0,
        }

    # Commit modified content
    ir.commit_raw_content(new_text)

    return {
        "success": True,
        "removed": len(to_remove),
        "shorts_found": len(drc_endpoints),
        "artifacts_removed": artifacts_removed,
    }


def _do_remove_dangling(
    file_path: Path,
    ir: PcbIR,
    *,
    max_iterations: int = 30,
    tolerance_mm: float = 0.001,
) -> dict[str, Any]:
    """Iteratively remove dangling tracks and vias from a PCB.

    Importable inner function that can be called directly by pipeline handlers.
    Runs DRC each iteration, parses track_dangling and via_dangling violations,
    removes fully-dangling segments (both endpoints orphaned), iterates until
    convergence.

    Args:
        file_path: Resolved path to the .kicad_pcb file.
        ir: PcbIR providing raw PCB text.
        max_iterations: Maximum cleanup iterations.
        tolerance_mm: Coordinate matching tolerance in mm.

    Returns:
        Dict with success, iterations, tracks_removed, vias_removed, remaining_dangling.
    """
    # Create backup
    backup_path = Path(str(file_path) + ".bak")
    try:
        shutil.copy2(file_path, backup_path)
        logger.info("Backup created: %s", backup_path)
    except OSError as exc:
        return {
            "success": False,
            "error": f"Failed to create backup: {exc}",
            "iterations": 0,
            "tracks_removed": 0,
            "vias_removed": 0,
            "remaining_dangling": 0,
        }

    tol = tolerance_mm
    max_iter = max_iterations
    total_tracks_removed = 0
    total_vias_removed = 0
    pcb_text = ir.raw_content if ir.raw_content else file_path.read_text()

    # DRC report tempfile
    drc_report = Path(tempfile.mktemp(suffix=".rpt", prefix="dangling_drc_"))

    iteration = 0
    try:
        for iteration in range(1, max_iter + 1):
            logger.info("Dangling cleanup iteration %d/%d", iteration, max_iter)

            # Run DRC
            if not run_drc(file_path, drc_report):
                return {
                    "success": False,
                    "error": "kicad-cli pcb drc failed during iteration "
                    f"{iteration}",
                    "iterations": iteration,
                    "tracks_removed": total_tracks_removed,
                    "vias_removed": total_vias_removed,
                    "remaining_dangling": -1,
                }

            # Parse dangling endpoints
            dangling = parse_drc_dangling_endpoints(drc_report)
            drc_counts = count_drc_categories(drc_report)
            cur_track = drc_counts.get('track_dangling', 0)
            cur_via = drc_counts.get('via_dangling', 0)
            cur_total = cur_track + cur_via

            logger.info(
                "Dangling: %d track_dangling, %d via_dangling (%d unique endpoints)",
                cur_track, cur_via, len(dangling),
            )

            if cur_total == 0:
                logger.info("No dangling violations. Done.")
                break

            # Parse elements from current PCB text
            segments = parse_segments(pcb_text)
            vias = parse_vias(pcb_text)

            # Find fully-dangling segments: BOTH endpoints at dangling coords
            seg_to_remove: set[int] = set()
            for seg in segments:
                net = seg.get('net', '')
                layer = seg.get('layer', '')
                start_match = False
                end_match = False
                sx, sy = seg.get('start_x', 0), seg.get('start_y', 0)
                ex, ey = seg.get('end_x', 0), seg.get('end_y', 0)

                for dnet, dlayer, dx, dy in dangling:
                    if net == dnet and layer == dlayer and abs(sx - dx) < tol and abs(sy - dy) < tol:
                        start_match = True
                    if net == dnet and layer == dlayer and abs(ex - dx) < tol and abs(ey - dy) < tol:
                        end_match = True

                # ONLY remove fully-dangling (both ends orphaned)
                if start_match and end_match:
                    seg_to_remove.add(seg['line_start'])

            # Find vias at dangling coordinates (layer-agnostic)
            via_to_remove: set[int] = set()
            for via in vias:
                net = via.get('net', '')
                vx, vy = via.get('x', 0), via.get('y', 0)
                for dnet, _, dx, dy in dangling:
                    if net == dnet and abs(vx - dx) < tol and abs(vy - dy) < tol:
                        via_to_remove.add(via['line_start'])
                        break

            logger.info(
                "To remove: %d segments, %d vias",
                len(seg_to_remove), len(via_to_remove),
            )

            if not seg_to_remove and not via_to_remove:
                logger.info("No matching elements found. Stopping iteration.")
                break

            # Remove elements
            new_text = remove_elements(pcb_text, segments, vias, seg_to_remove, via_to_remove)

            # Validate paren balance
            if not validate_paren_balance(new_text):
                logger.error(
                    "Paren balance check FAILED in iteration %d. Restoring backup.",
                    iteration,
                )
                shutil.copy2(backup_path, file_path)
                return {
                    "success": False,
                    "error": (
                        "Paren balance check failed in iteration "
                        f"{iteration}. Backup restored."
                    ),
                    "iterations": iteration,
                    "tracks_removed": total_tracks_removed,
                    "vias_removed": total_vias_removed,
                    "remaining_dangling": cur_total,
                }

            # Write updated PCB
            file_path.write_text(new_text)
            removed_segs = len(seg_to_remove)
            removed_vias = len(via_to_remove)
            total_tracks_removed += removed_segs
            total_vias_removed += removed_vias
            pcb_text = new_text
            logger.info(
                "Removed %d segments, %d vias (cumulative: %d, %d)",
                removed_segs, removed_vias,
                total_tracks_removed, total_vias_removed,
            )

            # Check convergence: re-run DRC and compare counts
            if not run_drc(file_path, drc_report):
                logger.warning("DRC failed after removal. Stopping iteration.")
                break

            new_counts = count_drc_categories(drc_report)
            new_total = new_counts.get('track_dangling', 0) + new_counts.get('via_dangling', 0)
            if new_total >= cur_total:
                logger.info("No reduction or increase. Stopping iteration.")
                break

    except subprocess.TimeoutExpired:
        logger.error("DRC subprocess timed out")
        shutil.copy2(backup_path, file_path)
        return {
            "success": False,
            "error": "DRC subprocess timed out (120s)",
            "iterations": 0,
            "tracks_removed": 0,
            "vias_removed": 0,
            "remaining_dangling": -1,
        }
    finally:
        # Cleanup temp report
        try:
            drc_report.unlink(missing_ok=True)
        except OSError:
            pass

    # Final dangling count
    final_report = Path(tempfile.mktemp(suffix=".rpt", prefix="final_drc_"))
    remaining = 0
    try:
        if run_drc(file_path, final_report):
            final_counts = count_drc_categories(final_report)
            remaining = final_counts.get('track_dangling', 0) + final_counts.get('via_dangling', 0)
    finally:
        try:
            final_report.unlink(missing_ok=True)
        except OSError:
            pass

    # Commit final state to IR
    ir.commit_raw_content(pcb_text)

    return {
        "success": True,
        "iterations": iteration,
        "tracks_removed": total_tracks_removed,
        "vias_removed": total_vias_removed,
        "remaining_dangling": remaining,
    }


# ---------------------------------------------------------------------------
# strip_shorts handler (delegates to _do_strip_shorts)
# ---------------------------------------------------------------------------


@register_cleanup("strip_shorts")
def _handle_strip_shorts(
    op: Any,
    ir: PcbIR,
    file_path: Path,
) -> dict[str, Any]:
    """Remove shorting track segments identified by DRC shorting_items.

    Handler wrapper that delegates to _do_strip_shorts with op parameters.
    """
    drc_report = getattr(op, "drc_report", None)
    tolerance = getattr(op, "tolerance_mm", 0.01)

    if drc_report:
        # Use provided DRC report path -- create a compatibility wrapper
        report_path = Path(drc_report)
        if not report_path.exists():
            return {
                "success": False,
                "error": f"DRC report not found: {drc_report}",
                "removed": 0,
                "shorts_found": 0,
                "artifacts_removed": 0,
            }
        # Parse directly from provided report
        return _strip_shorts_from_report(file_path, ir, report_path, tolerance)

    return _do_strip_shorts(file_path, ir, tolerance_mm=tolerance)


def _strip_shorts_from_report(
    file_path: Path,
    ir: PcbIR,
    drc_report: Path,
    tolerance_mm: float = 0.01,
) -> dict[str, Any]:
    """Strip shorts using a pre-existing DRC report."""
    backup_path = Path(str(file_path) + ".bak")
    try:
        shutil.copy2(file_path, backup_path)
    except OSError as exc:
        return {
            "success": False,
            "error": f"Failed to create backup: {exc}",
            "removed": 0,
            "shorts_found": 0,
            "artifacts_removed": 0,
        }

    drc_endpoints = parse_drc_shorting_items(drc_report)
    if not drc_endpoints:
        return {"success": True, "removed": 0, "shorts_found": 0, "artifacts_removed": 0}

    pcb_text = ir.raw_content if ir.raw_content else file_path.read_text()
    segments = parse_segments(pcb_text)

    # TODO(M-3): This short-matching logic duplicates _do_strip_shorts above.
    # Extract into a shared helper to keep the two paths in sync.
    to_remove: list[dict] = []
    for target_net, tx, ty in drc_endpoints:
        for seg in segments:
            if seg.get('net', '') != target_net:
                continue
            for ex, ey in [
                (seg.get('start_x', 0), seg.get('start_y', 0)),
                (seg.get('end_x', 0), seg.get('end_y', 0)),
            ]:
                if abs(ex - tx) < tolerance_mm and abs(ey - ty) < tolerance_mm:
                    if seg not in to_remove:
                        to_remove.append(seg)

    artifacts_removed = 0
    for seg in segments:
        if seg in to_remove:
            continue
        sx, sy = seg.get('start_x', 0), seg.get('start_y', 0)
        ex, ey = seg.get('end_x', 0), seg.get('end_y', 0)
        if abs(sx - ex) < tolerance_mm and abs(sy - ey) < tolerance_mm:
            to_remove.append(seg)
            artifacts_removed += 1

    if not to_remove:
        return {"success": True, "removed": 0, "shorts_found": len(drc_endpoints), "artifacts_removed": 0}

    lines_to_remove: set[int] = set()
    for seg in to_remove:
        for ln in range(seg['line_start'], seg['line_end'] + 1):
            lines_to_remove.add(ln)

    new_text = '\n'.join(
        l for i, l in enumerate(pcb_text.split('\n')) if i not in lines_to_remove
    )

    if not validate_paren_balance(new_text):
        shutil.copy2(backup_path, file_path)
        return {
            "success": False,
            "error": "Paren balance check failed after removal. Backup restored.",
            "removed": 0,
            "shorts_found": len(drc_endpoints),
            "artifacts_removed": 0,
        }

    ir.commit_raw_content(new_text)
    return {
        "success": True,
        "removed": len(to_remove),
        "shorts_found": len(drc_endpoints),
        "artifacts_removed": artifacts_removed,
    }


# ---------------------------------------------------------------------------
# remove_dangling_tracks handler (delegates to _do_remove_dangling)
# ---------------------------------------------------------------------------


@register_cleanup("remove_dangling_tracks")
def _handle_remove_dangling_tracks(
    op: Any,
    ir: PcbIR,
    file_path: Path,
) -> dict[str, Any]:
    """Iteratively remove dangling tracks and vias from a PCB.

    Handler wrapper that delegates to _do_remove_dangling with op parameters.
    """
    max_iter = getattr(op, "max_iterations", 30)
    tol = getattr(op, "tolerance_mm", 0.001)
    return _do_remove_dangling(file_path, ir, max_iterations=max_iter, tolerance_mm=tol)
