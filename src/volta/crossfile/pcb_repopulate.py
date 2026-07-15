"""PCB repopulation utilities -- footprint cloning, placement, and net rebuild.

Extracts core logic from the repopulate pipeline into reusable functions
parameterized against board-specific values. All S-expression editing is
raw text -- no kiutils -- to avoid Board serialization corruption.

KiCad 10 segment/via format uses (net "NAME") (name-only, no number).
"""

import logging
import re
import uuid

logger = logging.getLogger(__name__)

from volta.crossfile.schematic_sync import _find_matching_close

# ---------------------------------------------------------------------------
# Precompiled patterns
# ---------------------------------------------------------------------------

_FP_BLOCK_RE = re.compile(r'\n  \(footprint "')
_FP_LIB_RE = re.compile(r'\(footprint\s+"([^"]+)"')
_REF_PROP_RE = re.compile(r'\(property\s+"Reference"\s+"([^"]+)"')
_VAL_PROP_RE = re.compile(r'\(property\s+"Value"\s+"([^"]*)"')
_UUID_RE = re.compile(r'\(uuid\s+"[^"]*"')
_PAD_NET_RE = re.compile(r'(\(net\s+)\d+(\s+")[^"]*(")')
_SEGMENT_RE = re.compile(r'^\s*\(segment\b', re.MULTILINE)
_VIA_RE = re.compile(r'^\s*\(via\b', re.MULTILINE)
_ZONE_RE = re.compile(r'^\s*\(zone\b', re.MULTILINE)
_ROOT_NET_DECL_RE = re.compile(r'^  \(net \d+\s+"[^"]*"', re.MULTILINE)
_PAD_LEVEL_NET_RE = re.compile(r'^\t\t\(net\s+\d+\s+"([^"]*)"', re.MULTILINE)

# Combined size estimation pattern -- group numbers index into _FP_SIZES.
# Group 1: 0603 passives, 2: 0805 passives, 3: 1210, 4: SOIC-8, 5: SOIC-14,
# 6: SOIC-16, 7: MSOP-10, 8: SOT-23, 9: SOT-223, 10: TestPoint, 11: SMA,
# 12: Crystal.
_FP_SIZE_PATTERN = re.compile(
    r'(C|R|Fuse|L)_0603|(C|R|L|LED)_0805|C_1210|SOIC-8|SOIC-14|'
    r'SOIC-16|MSOP-10|SOT-23|SOT-223|TestPoint_Pad|D_SMA|Crystal'
)
_FP_SIZES: list[tuple[float, float]] = [
    (1.6, 0.8),   # 0603
    (2.0, 1.2),   # 0805
    (3.2, 2.5),   # 1210
    (4.5, 6.0),   # SOIC-8
    (4.5, 10.0),  # SOIC-14
    (4.5, 11.0),  # SOIC-16
    (3.5, 4.0),   # MSOP-10
    (1.5, 3.0),   # SOT-23
    (4.0, 7.0),   # SOT-223
    (1.5, 1.5),   # TestPoint
    (3.8, 2.6),   # SMA
    (3.5, 3.0),   # Crystal
]
_DEFAULT_FP_SIZE = (1.6, 0.8)


# ---------------------------------------------------------------------------
# 1. Template library
# ---------------------------------------------------------------------------


def build_fp_template_library(content: str) -> dict[str, str]:
    """Extract footprint templates keyed by lib_id from PCB content.

    Returns ``{lib_id: block_text}`` for every ``(footprint ...)`` block.
    """
    templates: dict[str, str] = {}
    pos = 0
    while True:
        m = _FP_BLOCK_RE.search(content, pos)
        if m is None:
            break
        open_pos = m.start() + 1
        close_pos = _find_matching_close(content, open_pos)
        if close_pos is None:
            logger.warning("Unmatched footprint block at offset %d", open_pos)
            pos = open_pos + 1
            continue
        block = content[open_pos:close_pos + 1]
        fp_m = _FP_LIB_RE.search(block)
        if fp_m is not None:
            templates[fp_m.group(1)] = block
        pos = close_pos + 1
    return templates


# ---------------------------------------------------------------------------
# 2. Footprint cloning
# ---------------------------------------------------------------------------


def clone_footprint(
    template: str, ref: str, value: str, x: float, y: float, angle: float = 0.0,
) -> str:
    """Clone a footprint template with new ref, value, position, and UUIDs.

    Resets all pad nets to (net 0 "") for later assignment.
    """
    block = template

    # Replace Reference
    old_ref_m = _REF_PROP_RE.search(block)
    if old_ref_m:
        block = block.replace(
            f'(property "Reference" "{old_ref_m.group(1)}"',
            f'(property "Reference" "{ref}"', 1,
        )

    # Replace Value
    old_val_m = _VAL_PROP_RE.search(block)
    if old_val_m:
        block = block.replace(
            f'(property "Value" "{old_val_m.group(1)}"',
            f'(property "Value" "{value}"', 1,
        )

    # Replace (at X Y [angle])
    at_m = re.search(r'\(\s*at\s+[-\d.]+\s+[-\d.]+(\s+[-\d.]+)?\)', block)
    if at_m:
        keep = at_m.group(1) if angle == 0.0 else f" {angle}"
        replacement = f"(at {x:.6f} {y:.6f}{keep})"
        block = block[:at_m.start()] + replacement + block[at_m.end():]

    # Replace all UUIDs with fresh ones
    block = _UUID_RE.sub(lambda _: f'(uuid "{str(uuid.uuid4())}"', block)

    # Reset pad nets to (net 0 "")
    block = _PAD_NET_RE.sub(r'\g<1>0\g<2>\g<3>', block)

    bal = block.count("(") - block.count(")")
    if bal != 0:
        logger.warning("clone_footprint paren imbalance for %s: %d", ref, bal)
    return block


# ---------------------------------------------------------------------------
# 3 & 6. Block stripping (routing + zones)
# ---------------------------------------------------------------------------


def _strip_blocks(content: str, start_pattern: re.Pattern) -> str:
    """Remove all blocks matching *start_pattern* via string-aware paren tracking."""
    result = content
    while True:
        m = start_pattern.search(result)
        if m is None:
            break
        open_pos = m.start() + result[m.start():].index("(")
        close_pos = _find_matching_close(result, open_pos)
        if close_pos is None:
            logger.warning("Unmatched block at offset %d", open_pos)
            result = result[:open_pos] + result[open_pos + 1:]
            continue
        trim_start = open_pos - (1 if open_pos > 0 and result[open_pos - 1] == '\n' else 0)
        trim_end = close_pos + 1 + (1 if close_pos + 1 < len(result) and result[close_pos + 1] == '\n' else 0)
        result = result[:trim_start] + result[trim_end:]
    return result


def strip_routing(content: str) -> str:
    """Remove all (segment ...) and (via ...) blocks from PCB content."""
    content = _strip_blocks(content, _SEGMENT_RE)
    return _strip_blocks(content, _VIA_RE)


def strip_zones(content: str) -> str:
    """Remove all (zone ...) blocks from PCB content."""
    return _strip_blocks(content, _ZONE_RE)


# ---------------------------------------------------------------------------
# 4. Root net declarations rebuild
# ---------------------------------------------------------------------------


def rebuild_root_declarations(
    content: str, ref_pin_nets: dict[str, dict[str, str]],
) -> tuple[str, dict[str, int]]:
    """Rebuild root (net N "NAME") declarations from pad-level assignments.

    Returns (modified_content, net_name_to_number mapping).
    """
    names_seen: list[str] = []
    seen: set[str] = set()

    if ref_pin_nets:
        for pin_map in ref_pin_nets.values():
            for net_name in pin_map.values():
                if net_name and net_name not in seen:
                    seen.add(net_name)
                    names_seen.append(net_name)
    else:
        for m in _PAD_LEVEL_NET_RE.finditer(content):
            name = m.group(1)
            if name and name not in seen:
                seen.add(name)
                names_seen.append(name)

    name_to_num: dict[str, int] = {n: i + 1 for i, n in enumerate(names_seen)}

    net_start = content.find('  (net 0 ""')
    if net_start == -1:
        logger.warning("Could not find root net section anchor")
        return content, name_to_num
    if net_start > 0 and content[net_start - 1] == '\n':
        net_start -= 1

    lines = content[net_start:].split("\n")
    end_line = 1
    for idx in range(1, len(lines)):
        if _ROOT_NET_DECL_RE.match(lines[idx]):
            end_line = idx + 1
        else:
            break
    net_end = net_start + len("\n".join(lines[:end_line]))

    new_decls = ['  (net 0 "")']
    max_num = max(name_to_num.values()) if name_to_num else 0
    for n in range(1, max_num + 1):
        for name, num in name_to_num.items():
            if num == n:
                new_decls.append(f'  (net {n} "{name}")')
                break

    content = content[:net_start] + "\n".join(new_decls) + "\n" + content[net_end:]
    return content, name_to_num


# ---------------------------------------------------------------------------
# 5. Auto-placement
# ---------------------------------------------------------------------------


def _estimate_footprint_size(fp_lib_id: str) -> tuple[float, float]:
    """Estimate bounding box from footprint library path."""
    if "QFN" in fp_lib_id:
        qfn_m = re.search(r"(\d+)x(\d+)mm", fp_lib_id)
        if qfn_m:
            return float(qfn_m.group(1)) + 1.0, float(qfn_m.group(2)) + 1.0
        return 6.0, 6.0
    if "JST_PH" in fp_lib_id:
        if "S6B" in fp_lib_id:
            return 13.0, 6.0
        if "S3B" in fp_lib_id:
            return 7.0, 6.0
    m = _FP_SIZE_PATTERN.search(fp_lib_id)
    if m:
        for i, g in enumerate(m.groups(), 1):
            if g:
                return _FP_SIZES[i - 1]
    return _DEFAULT_FP_SIZE


def auto_place_missing(
    content: str, missing_refs: list[str], comp_info: dict[str, str],
    templates: dict[str, str], board_w: float, board_h: float,
    margin: float = 3.0, clearance: float = 4.0,
) -> tuple[str, dict[str, tuple[float, float]]]:
    """Auto-place missing footprints on a grid using template cloning.

    Returns (modified_content, placement_dict mapping ref -> (x, y)).
    """
    # Collect existing occupied extents.
    occupied: list[tuple[float, float, float, float]] = []
    pos = 0
    last_fp_end = 0
    while True:
        m = _FP_BLOCK_RE.search(content, pos)
        if m is None:
            break
        open_pos = m.start() + 1
        close_pos = _find_matching_close(content, open_pos)
        if close_pos is None:
            pos = open_pos + 1
            continue
        block = content[open_pos:close_pos + 1]
        at_m = re.search(r'\(at\s+([-\d.]+)\s+([-\d.]+)', block)
        if at_m:
            cx, cy = float(at_m.group(1)), float(at_m.group(2))
            est = _estimate_footprint_size(block)
            occupied.append((cx - est[0]/2, cy - est[1]/2, cx + est[0]/2, cy + est[1]/2))
        last_fp_end = close_pos + 1
        pos = close_pos + 1

    # Sort refs: ICs -> connectors -> passives -> test points.
    def _pri(r: str) -> tuple[int, str]:
        if r.startswith("U"): return (0, r)
        if r.startswith("J"): return (1, r)
        if r.startswith("L"): return (2, r)
        if r[0] in "CRDFQY": return (3, r)
        if r.startswith("TP"): return (4, r)
        return (5, r)

    new_blocks: list[str] = []
    placements: dict[str, tuple[float, float]] = {}

    for ref in sorted(missing_refs, key=_pri):
        fp_lib_id = comp_info.get(ref, "")
        # Find template with fallback substring match.
        template = templates.get(fp_lib_id)
        if template is None:
            fp_name = fp_lib_id.split(":")[-1] if ":" in fp_lib_id else fp_lib_id
            for key, blk in templates.items():
                tname = key.split(":")[-1] if ":" in key else key
                if tname == fp_name or fp_name in tname:
                    template = blk
                    break

        size_w, size_h = _estimate_footprint_size(fp_lib_id)
        step = max(size_w, size_h, 2.5) + clearance
        placed = False

        x = margin
        while x + size_w <= board_w - margin:
            y = margin
            while y + size_h <= board_h - margin:
                cand = (x - clearance/2, y - clearance/2,
                        x + size_w + clearance/2, y + size_h + clearance/2)
                overlap = any(
                    cand[0] < o[2] and cand[2] > o[0] and cand[1] < o[3] and cand[3] > o[1]
                    for o in occupied
                )
                if not overlap:
                    if template:
                        new_blocks.append(clone_footprint(template, ref, "", x, y))
                    else:
                        logger.warning("No template for %s (%s), skipping", ref, fp_lib_id)
                        break
                    placements[ref] = (x, y)
                    occupied.append(cand)
                    placed = True
                    break
                y += step
            if placed:
                break
            x += step

        if not placed:
            logger.warning("Could not place %s (%s)", ref, fp_lib_id)

    if new_blocks and last_fp_end > 0:
        content = content[:last_fp_end] + "\n".join(new_blocks) + "\n" + content[last_fp_end:]

    return content, placements
