"""Populate an empty PCB with footprints from a schematic netlist.

Unlike repopulate_pcb_from_schematic (which clones EXISTING footprints),
this module instantiates footprints from LIBRARY FILES — reading .kicad_mod
files, wrapping them as PCB footprint instances with correct refs, values,
positions, pad nets, and UUIDs.

This bridges the gap: an empty PCB with only net declarations can be
fully populated from scratch without needing KiCad GUI.
"""

import re
import uuid
import logging
from pathlib import Path
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


# Pin-name → pad-number mapping for footprints whose library symbols use
# alphanumeric pin names (B/C/E for transistors) but whose .kicad_mod pads are
# numbered 1/2/3. Derived from the original analog-board.kicad_pcb cross-
# reference (Phase 144 Wave 5): Q4 pad 2 carries net Q4C which the netlist
# maps to pin E, confirming SOT-23 B=1, E=2, C=3 (JEDEC TO-236).
#
# Keys are footprint lib_id prefixes. When a pin name isn't found in the
# table, the caller logs a warning and skips the pad (preserves old behavior
# for numeric pin names which pass through unchanged).
_PIN_TO_PAD_MAP: dict[str, dict[str, str]] = {
    # SOT-23 NPN/PNP — JEDEC TO-236 Var AB
    # NPN (Q_NPN): B=1, E=2, C=3
    # PNP (Q_PNP): B=1, E=2, C=3 (same footprint, different symbol polarity)
    "Package_TO_SOT_SMD:SOT-23": {"B": "1", "E": "2", "C": "3"},
    # SOT-223-3 with tab as pin 2 — B=1, C=2 (tab=collector), E=3
    "Package_TO_SOT_SMD:SOT-223-3_TabPin2": {"B": "1", "C": "2", "E": "3"},
    # SOT-223-3 with tab as pin 1 — C=1 (tab), B=2, E=3 (less common variant)
    "Package_TO_SOT_SMD:SOT-223-3_TabPin1": {"C": "1", "B": "2", "E": "3"},
    # Through-hole TO-92 — B=1, C=2, E=3 (common JEDEC assignment)
    "Package_TO_SOT_THT:TO-92_Inline": {"B": "1", "C": "2", "E": "3"},
    "Package_TO_SOT_THT:TO-92_Horizontal1": {"B": "1", "C": "2", "E": "3"},
}


def map_alphanumeric_pin_to_pad(pin_name: str, footprint_lib_id: str) -> str | None:
    """Map an alphanumeric pin name (B/C/E) to a numeric pad number.

    KiCad transistor symbols (Q_NPN, Q_PNP) export pin numbers as B, C, E.
    The corresponding footprints (SOT-23, SOT-223) have pads numbered 1, 2, 3.
    Without this mapping, populate_pcb_from_netlist silently skips these pads.

    Args:
        pin_name: Pin name/number from netlist (e.g. "B", "E", "C", or "1").
        footprint_lib_id: Full footprint library ID (e.g. "Package_TO_SOT_SMD:SOT-23").

    Returns:
        Pad number string, or None if no mapping exists.
        Numeric pin names pass through unchanged.
    """
    # Numeric pin names pass through (common case for resistors, caps, ICs)
    if pin_name.isdigit():
        return pin_name

    # Look up the footprint in the mapping table
    footprint_map = _PIN_TO_PAD_MAP.get(footprint_lib_id)
    if footprint_map is None:
        logger.warning(
            "No alphanumeric pin mapping for footprint %s (pin %s) — skipping",
            footprint_lib_id,
            pin_name,
        )
        return None

    pad_num = footprint_map.get(pin_name)
    if pad_num is None:
        logger.warning(
            "Pin %s not in mapping table for %s — skipping",
            pin_name,
            footprint_lib_id,
        )
        return None

    return pad_num


def dedupe_pad_nets_multi_unit(
    raw_pad_nets: dict[str, list[str]],
) -> dict[str, str]:
    """Deduplicate net assignments for multi-unit components.

    KiCad exports one net entry per (unit, pin) pair. For a multi-unit component
    like CD4066 (5 units A-E), unused units emit `unconnected-(REF-PadN)` entries
    that APPEND to the net blocks. The naive populate loop assigns the last
    matching entry, so phantom unconnected- entries overwrite real nets.

    This function prefers real nets over `unconnected-` entries when both exist.
    If only `unconnected-` entries are present (genuinely unused pin), keeps the
    last one.

    Args:
        raw_pad_nets: Dict of {pad_name: [net_name, ...]} with duplicates.

    Returns:
        Dict of {pad_name: single_net_name} with conflicts resolved.
    """
    result: dict[str, str] = {}
    for pad_name, net_list in raw_pad_nets.items():
        if not net_list:
            continue
        # Separate real nets from phantom unconnected- entries
        real_nets = [n for n in net_list if not n.startswith("unconnected-")]
        unconnected_nets = [n for n in net_list if n.startswith("unconnected-")]

        if real_nets:
            # Prefer the first real net (deterministic)
            result[pad_name] = real_nets[0]
        elif unconnected_nets:
            # Genuinely unused pin — keep last unconnected entry
            result[pad_name] = unconnected_nets[-1]
    return result


def parse_netlist_xml(netlist_path: Path) -> list[dict]:
    """Parse KiCad S-expression or XML netlist → list of component dicts.

    Returns: [{"ref": "R30", "value": "10k", "footprint": "Resistor_SMD:R_0805_2012Metric", "pad_nets": {"1": "GND", "2": "+3V3"}}, ...]
    """
    content = Path(netlist_path).read_text()

    if content.lstrip().startswith("(export"):
        return _parse_netlist_sexpr(content)
    else:
        return _parse_netlist_xml(content, netlist_path)


def _parse_netlist_sexpr(content: str) -> list[dict]:
    """Parse KiCad S-expression (legacy) netlist format."""
    components = []

    # Parse components section
    comp_section = re.search(r'\(components(.*?)\)\s*\(libparts', content, re.DOTALL)
    if not comp_section:
        comp_section = re.search(r'\(components(.*?)\)\s*\(nets', content, re.DOTALL)

    if comp_section:
        comp_text = comp_section.group(1)
        # Match: (comp (ref "X") (value "Y") (footprint "Z") ...)
        comps = re.findall(
            r'\(comp\s+\(ref "([^"]+)"\)\s+\(value "([^"]*)"\)\s+\(footprint "([^"]*)"\)',
            comp_text,
        )
    else:
        comps = []

    # Parse nets section for pad mapping
    net_to_pads: dict[str, list[tuple[str, str]]] = {}
    nets_section = re.search(r'\(nets(.*?)\)\s*\)$', content, re.DOTALL)
    if nets_section:
        net_text = nets_section.group(1)
        for net_match in re.finditer(
            r'\(net\s+\(code "[^"]*"\)\s+\(name "([^"]*)"\)(.*?)\)\s*(?=\(net|\Z)',
            net_text,
            re.DOTALL,
        ):
            net_name = net_match.group(1)
            node_text = net_match.group(2)
            for node in re.finditer(r'\(node\s+\(ref "([^"]+)"\)\s+\(pin "([^"]+)"\)', node_text):
                net_to_pads.setdefault(net_name, []).append((node.group(1), node.group(2)))

    for ref, value, fp in comps:
        if not fp:
            logger.warning("Component %s has no footprint, skipping", ref)
            continue

        # Collect ALL net entries per pad (multi-unit dedup)
        # KiCad multi-unit components (e.g. CD4066 with 5 units) emit duplicate
        # `unconnected-(REF-PadN)` entries from unused units. Without dedup,
        # these phantom entries overwrite real net assignments.
        raw_pad_nets: dict[str, list[str]] = {}
        for net_name, nodes in net_to_pads.items():
            for n_ref, n_pin in nodes:
                if n_ref == ref:
                    raw_pad_nets.setdefault(n_pin, []).append(net_name)

        pad_nets = dedupe_pad_nets_multi_unit(raw_pad_nets)

        components.append({
            "ref": ref,
            "value": value,
            "footprint": fp,
            "pad_nets": pad_nets,
        })

    return components


def _parse_netlist_xml(content: str, netlist_path: Path) -> list[dict]:
    """Parse KiCad XML netlist format."""
    tree = ET.parse(netlist_path)
    root = tree.getroot()

    # Build net → pad mapping from nets section
    net_to_pads: dict[str, list[tuple[str, str]]] = {}  # net_name → [(ref, pad), ...]
    for net_elem in root.findall(".//net"):
        net_name = net_elem.get("name", "")
        if not net_name:
            continue
        for node in net_elem.findall("node"):
            ref = node.get("ref", "")
            pad = node.get("pad", "")
            if ref and pad:
                net_to_pads.setdefault(net_name, []).append((ref, pad))

    # Build component list from components section
    components = []
    for comp in root.findall(".//comp"):
        ref = comp.get("ref", "")
        if not ref:
            continue

        value_elem = comp.find("value")
        value = value_elem.text if value_elem is not None else ""

        fp_elem = comp.find("footprint")
        fp = fp_elem.text if fp_elem is not None else ""

        if not fp:
            logger.warning("Component %s has no footprint, skipping", ref)
            continue

        # Collect ALL net entries per pad (multi-unit dedup)
        # KiCad multi-unit components (e.g. CD4066 with 5 units) emit duplicate
        # `unconnected-(REF-PadN)` entries from unused units. Without dedup,
        # these phantom entries overwrite real net assignments.
        raw_pad_nets: dict[str, list[str]] = {}
        for net_name, nodes in net_to_pads.items():
            for c_ref, c_pad in nodes:
                if c_ref == ref:
                    raw_pad_nets.setdefault(c_pad, []).append(net_name)

        pad_nets = dedupe_pad_nets_multi_unit(raw_pad_nets)

        components.append({
            "ref": ref,
            "value": value,
            "footprint": fp,
            "pad_nets": pad_nets,
        })

    return components


def resolve_footprint_file(lib_id: str, library_paths: list[Path]) -> Path | None:
    """Resolve a footprint library ID to a .kicad_mod file path.

    Args:
        lib_id: e.g. "Capacitor_SMD:C_0805_2012Metric"
        library_paths: List of parent directories containing .pretty libraries

    Returns: Path to .kicad_mod file, or None if not found.
    """
    if ":" not in lib_id:
        return None

    lib_name, fp_name = lib_id.split(":", 1)

    for base in library_paths:
        fp_file = base / f"{lib_name}.pretty" / f"{fp_name}.kicad_mod"
        if fp_file.exists():
            return fp_file

    return None


def instantiate_footprint(
    fp_content: str,
    lib_id: str,
    ref: str,
    value: str,
    x: float,
    y: float,
    angle: float = 0.0,
    layer: str = "F.Cu",
    pad_nets: dict[str, str] | None = None,
) -> str:
    """Construct a PCB (footprint ...) block from .kicad_mod library content.

    Transforms the .kicad_mod in-place to preserve full library fidelity
    (descr, tags, attr, model, geometry) rather than reconstructing from
    scratch. This avoids kicad-cli DRC 'lib_footprint_mismatch' warnings
    that occur when the PCB footprint block differs from the library version.

    Transformations applied:
    1. Replace the opening (footprint "NAME" ...) header to use lib_id
    2. Inject (uuid ...) after the (layer ...) line
    3. Inject (at X Y ANGLE) after the uuid
    4. Replace the Reference property value with the component ref + uuid
    5. Replace the Value property value with the component value + uuid
    6. Inject pad nets into each pad block
    7. Re-indent the block for PCB context (2-space base indent)
    """
    fp_uuid = str(uuid.uuid4())
    ref_uuid = str(uuid.uuid4())
    val_uuid = str(uuid.uuid4())
    pad_nets = pad_nets or {}

    # Work on a copy of the library content
    content = fp_content

    # 1. Replace the footprint name in the opening line with the full lib_id
    #    .kicad_mod opens with (footprint "FP_NAME" ...) where FP_NAME is just
    #    the footprint name without the library prefix. PCB needs the full lib_id.
    content = re.sub(
        r'^(\(\s*footprint\s+)"[^"]*"',
        lambda m: f'{m.group(1)}"{lib_id}"',
        content,
        count=1,
    )

    # 2. Inject (uuid ...) and (at ...) after the (layer ...) line
    layer_pattern = re.compile(
        r'(\(\s*layer\s+"[^"]*"\s*\))',
        re.MULTILINE,
    )
    uuid_at_block = (
        f'\\1\n'
        f'\t(uuid "{fp_uuid}")\n'
        f'\t(at {x} {y} {angle})'
    )
    content = layer_pattern.sub(uuid_at_block, content, count=1)

    # 3. Replace Reference property value and add uuid
    #    Library form: (property "Reference" "REF**" ...) — replace "REF**" with ref
    #    and inject (uuid "...") before the closing paren of the property block.
    content = _replace_property_value(content, "Reference", ref, ref_uuid)

    # 4. Replace Value property value and add uuid
    #    Library form: (property "Value" "FP_NAME" ...) — replace with component value
    content = _replace_property_value(content, "Value", value, val_uuid)

    # 5. Inject pad nets
    #    pad_nets keys are netlist pin names (e.g. "1", "2", or "B", "E", "C").
    #    Map each pin name to its PCB pad number via the alphanumeric table
    #    (Phase 144 Wave 5 fix: transistors use B/C/E in netlist but 1/2/3 in footprint).
    pads = _extract_pad_blocks(content)
    pad_num_to_net: dict[str, str] = {}
    for pin_name, net_name in pad_nets.items():
        resolved_pad = map_alphanumeric_pin_to_pad(pin_name, lib_id)
        if resolved_pad is None:
            logger.warning(
                "Could not map pin '%s' on %s — pad will have no net",
                pin_name,
                lib_id,
            )
            continue
        pad_num_to_net[resolved_pad] = net_name

    for pad_block in pads:
        pad_num = pad_block["number"]
        if pad_num in pad_num_to_net:
            old_raw = pad_block["raw"]
            new_raw = _add_net_to_pad(old_raw, pad_num_to_net[pad_num])
            content = content.replace(old_raw, new_raw, 1)

    # 6. Re-indent: library uses tab indent; PCB needs 2-space base indent.
    #    Strategy: strip leading whitespace from each line, then prepend 2 spaces.
    lines = content.rstrip().split("\n")
    # First line is "(footprint ...)" — indent 2 spaces
    # All other lines: strip existing indent, add 4 spaces (2 for footprint block + 2 for content)
    indented_lines = []
    for i, line in enumerate(lines):
        if i == 0:
            indented_lines.append("  " + line.strip())
        else:
            stripped = line.lstrip()
            if stripped:
                indented_lines.append("    " + stripped)
            else:
                indented_lines.append("")
    return "\n".join(indented_lines)


def _replace_property_value(
    content: str, prop_name: str, new_value: str, prop_uuid: str
) -> str:
    """Replace a property's value and inject a uuid into its block.

    Library .kicad_mod properties look like:
        (property "Reference" "REF**"
            (at ...)
            (layer ...)
            ...
        )
    PCB needs:
        (property "Reference" "<ref>"
            (at ...)
            (layer ...)
            (uuid "<uuid>")
            ...
        )
    """
    # Find the (property "NAME" "OLD_VALUE" ...) and replace OLD_VALUE
    # The value is the second quoted string after the property name.
    pattern = re.compile(
        r'(\(\s*property\s+"' + re.escape(prop_name) + r'"\s+)"[^"]*"',
    )
    content = pattern.sub(rf'\1"{new_value}"', content, count=1)

    # Now inject (uuid "...") into this property block.
    # Find the property block and add uuid before its closing paren.
    # Match the full property block by tracking parens from the property start.
    prop_start_pattern = re.compile(
        r'\(\s*property\s+"' + re.escape(prop_name) + r'"',
    )
    match = prop_start_pattern.search(content)
    if not match:
        return content

    start = match.start()
    depth = 0
    end = None
    for i in range(start, len(content)):
        if content[i] == "(":
            depth += 1
        elif content[i] == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        return content

    # Find the last non-whitespace before the closing paren
    block = content[start:end + 1]
    block_stripped = block.rstrip()
    last_paren = block_stripped.rfind(")")
    if last_paren <= 0:
        return content
    new_block = (
        block_stripped[:last_paren]
        + f'\n\t\t(uuid "{prop_uuid}")\n\t'
        + block_stripped[last_paren:]
    )
    return content[:start] + new_block + content[end + 1:]


def _extract_pad_blocks(fp_content: str) -> list[dict]:
    """Extract pad definitions from .kicad_mod content."""
    pads = []
    lines = fp_content.split("\n")
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        pad_match = re.match(r'\(pad\s+"([^"]+)"', stripped)
        if pad_match:
            pad_num = pad_match.group(1)
            depth = 0
            pad_lines = []
            for j in range(i, len(lines)):
                line = lines[j]
                for char in line:
                    if char == "(":
                        depth += 1
                    elif char == ")":
                        depth -= 1
                pad_lines.append(line)
                if depth == 0:
                    break
            pads.append({"number": pad_num, "raw": "\n".join(pad_lines)})
            i = j + 1
        else:
            i += 1
    return pads


def _add_net_to_pad(pad_raw: str, net_name: str) -> str:
    """Insert (net "name") into a pad block before the closing paren.

    KiCad 10 format requires string-only net references: (net "NAME").
    The old (net 0 "NAME") form with a numeric net code is invalid in KiCad 10
    and causes kicad-cli pcb drc to fail with a parse error.
    See memory kicad10-pcb-generation.md Rule 2.
    """
    stripped = pad_raw.rstrip()
    last_paren = stripped.rfind(")")
    if last_paren > 0:
        return stripped[:last_paren] + f'\n      (net "{net_name}")\n    ' + stripped[last_paren:]
    return pad_raw


def auto_place_grid(
    components: list[dict],
    board_width: float,
    board_height: float,
    clearance: float = 5.0,
) -> dict[str, tuple[float, float, float]]:
    """Assign grid positions to components.

    Returns: {ref: (x, y, angle)} for each component.
    """
    positions = {}
    margin = 10.0  # mm from board edge
    col_width = 15.0  # mm per column
    row_height = 12.0  # mm per row

    cols = int((board_width - 2 * margin) / col_width)
    if cols < 1:
        cols = 1

    for idx, comp in enumerate(components):
        col = idx % cols
        row = idx // cols

        x = margin + col * col_width
        y = margin + row * row_height

        # Keep within board bounds
        if y > board_height - margin:
            y = board_height - margin

        positions[comp["ref"]] = (x, y, 0.0)

    return positions


def populate_pcb_from_netlist(
    pcb_raw: str,
    netlist_path: Path,
    base_dir: Path,
    library_paths: list[Path] | None = None,
    board_width: float = 200.0,
    board_height: float = 150.0,
    placement_clearance: float = 5.0,
    assign_nets: bool = True,
    side: str = "F",
) -> tuple[str, dict]:
    """Populate an empty (or sparse) PCB with footprints from netlist.

    Args:
        pcb_raw: Current PCB file content as string.
        netlist_path: Path to KiCad XML netlist file.
        base_dir: Project root directory.
        library_paths: List of directories containing .pretty libraries.
        board_width: Board width in mm for placement grid.
        board_height: Board height in mm for placement grid.
        placement_clearance: Min clearance between footprints in mm.
        assign_nets: If True, assign net names to pads.
        side: "F" for front, "B" for back.

    Returns:
        Tuple of (new_pcb_raw, result_dict) where result_dict contains:
        - placed: list of refs placed
        - skipped: list of refs skipped (footprint not found)
        - errors: list of error messages
    """
    if library_paths is None:
        # Default library search paths
        library_paths = [
            base_dir / "hardware" / "shared" / "footprints",
            base_dir / "hardware" / "footprints",
            Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"),
        ]

    # 1. Parse netlist
    components = parse_netlist_xml(netlist_path)
    logger.info("Netlist has %d components with footprints", len(components))

    # 2. Assign positions
    positions = auto_place_grid(components, board_width, board_height, placement_clearance)

    # 3. Instantiate each footprint
    footprint_blocks = []
    placed = []
    skipped = []
    errors = []

    layer = f"{side}.Cu"

    for comp in components:
        ref = comp["ref"]
        lib_id = comp["footprint"]

        # Resolve footprint file
        fp_file = resolve_footprint_file(lib_id, library_paths)
        if fp_file is None:
            logger.warning("Footprint not found for %s: %s", ref, lib_id)
            skipped.append({"ref": ref, "footprint": lib_id, "reason": "not_found"})
            continue

        # Read .kicad_mod content
        try:
            fp_content = fp_file.read_text()
        except Exception as e:
            errors.append({"ref": ref, "error": str(e)})
            continue

        # Get position
        x, y, angle = positions.get(ref, (10.0, 10.0, 0.0))

        # Instantiate
        block = instantiate_footprint(
            fp_content=fp_content,
            lib_id=lib_id,
            ref=ref,
            value=comp["value"],
            x=x,
            y=y,
            angle=angle,
            layer=layer,
            pad_nets=comp["pad_nets"] if assign_nets else None,
        )

        if block:
            footprint_blocks.append(block)
            placed.append(ref)
        else:
            errors.append({"ref": ref, "error": "instantiation_failed"})

    # 4. Insert footprint blocks into PCB
    # Find insertion point — before the closing ) of (kicad_pcb ...)
    # Insert after the last existing content but before the final )

    # Find the last ) that closes (kicad_pcb
    # Strategy: find the (embedded_fonts or gr_rect or net_class block, insert after it
    # Simpler: insert before the final line that is just ")"
    pcb_lines = pcb_raw.rstrip().split("\n")

    # Find the last non-empty line that's NOT the closing paren
    insert_line = len(pcb_lines) - 1
    for i in range(len(pcb_lines) - 1, -1, -1):
        if pcb_lines[i].strip() and pcb_lines[i].strip() != ")":
            insert_line = i + 1
            break

    # Insert footprint blocks
    for block in footprint_blocks:
        pcb_lines.insert(insert_line, block)
        insert_line += 1

    # Ensure trailing newline
    new_pcb = "\n".join(pcb_lines) + "\n"

    result = {
        "placed": placed,
        "placed_count": len(placed),
        "skipped": skipped,
        "skipped_count": len(skipped),
        "errors": errors,
        "total_components": len(components),
        "board_width": board_width,
        "board_height": board_height,
        "placement_clearance": placement_clearance,
    }

    logger.info(
        "Populated PCB: %d placed, %d skipped, %d errors out of %d components",
        len(placed), len(skipped), len(errors), len(components),
    )

    return new_pcb, result
