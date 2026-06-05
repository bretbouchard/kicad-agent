"""Schematic-to-PCB synchronization -- update PCB from schematic netlist.

Exports a netlist from the schematic via kicad-cli, parses component
references and net assignments, and updates the PCB's pad-to-net
connections and net list accordingly.

All PCB modifications use raw S-expression manipulation to avoid
kiutils Board serialization corruption (known issue from Phase 24).
"""

import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes for parsed netlist
# ---------------------------------------------------------------------------


@dataclass
class NetlistComponent:
    """A component extracted from a KiCad netlist."""

    ref: str
    value: str
    footprint_lib_id: str


@dataclass
class NetlistNet:
    """A net extracted from a KiCad netlist."""

    code: int
    name: str
    nodes: list[tuple[str, str]] = field(default_factory=list)  # [(ref, pin_number)]


@dataclass
class SyncResult:
    """Result of schematic-to-PCB synchronization."""

    added_footprints: list[str] = field(default_factory=list)
    updated_nets: list[str] = field(default_factory=list)
    removed_orphans: list[str] = field(default_factory=list)
    added_net_defs: list[str] = field(default_factory=list)
    footprint_ref_updates: list[tuple[str, str]] = field(default_factory=list)
    pad_net_updates: int = 0

    @property
    def has_changes(self) -> bool:
        return bool(
            self.added_footprints
            or self.updated_nets
            or self.removed_orphans
            or self.added_net_defs
            or self.footprint_ref_updates
            or self.pad_net_updates
        )


# ---------------------------------------------------------------------------
# Netlist export and parsing
# ---------------------------------------------------------------------------


def export_netlist(schematic_path: Path, base_dir: Path) -> str:
    """Export a netlist from a schematic via kicad-cli.

    Args:
        schematic_path: Path to the .kicad_sch file.
        base_dir: Working directory for kicad-cli (project root).

    Returns:
        KiCad netlist S-expression string.

    Raises:
        RuntimeError: If kicad-cli fails.
        FileNotFoundError: If kicad-cli not found.
    """
    import tempfile

    try:
        with tempfile.NamedTemporaryFile(suffix=".net", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            result = subprocess.run(
                ["kicad-cli", "sch", "export", "netlist",
                 str(schematic_path), "-o", tmp_path],
                capture_output=True,
                text=True,
                cwd=str(base_dir),
                timeout=30,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "kicad-cli not found. kicad-cli is required for netlist export. "
                "Install KiCad 8+ or add kicad-cli to PATH."
            )
        if result.returncode != 0:
            raise RuntimeError(
                f"kicad-cli netlist export failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )
        tmp_file = Path(tmp_path)
        if not tmp_file.exists() or tmp_file.stat().st_size == 0:
            raise RuntimeError(
                "kicad-cli netlist export produced empty output"
            )
        return tmp_file.read_text(encoding="utf-8")
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass


def _find_matching_close(content: str, open_pos: int) -> Optional[int]:
    """Find the matching closing paren for an S-expression.

    Handles nested parens and KiCad's doubled-quote escaping.
    """
    depth = 0
    in_quote = False
    i = open_pos
    length = len(content)
    while i < length:
        c = content[i]
        if in_quote:
            if c == '"':
                # Check for doubled quote (KiCad escape)
                if i + 1 < length and content[i + 1] == '"':
                    i += 2
                    continue
                in_quote = False
        else:
            if c == '"':
                in_quote = True
            elif c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return None


def parse_netlist(
    netlist_sexpr: str,
) -> tuple[list[NetlistComponent], list[NetlistNet]]:
    """Parse KiCad S-expression netlist into components and nets.

    Args:
        netlist_sexpr: Raw S-expression string from kicad-cli netlist export.

    Returns:
        Tuple of (components, nets).
    """
    components: list[NetlistComponent] = []

    # Parse (comp ...) blocks
    for m in re.finditer(r'^\t\t\(comp\b', netlist_sexpr, re.MULTILINE):
        comp_start = m.start()
        comp_end = _find_matching_close(netlist_sexpr, comp_start)
        if comp_end is None:
            continue
        block = netlist_sexpr[comp_start:comp_end + 1]

        ref_m = re.search(r'\(ref "([^"]*)"', block)
        val_m = re.search(r'\(value "([^"]*)"', block)
        fp_m = re.search(r'\(footprint "([^"]*)"', block)

        if ref_m:
            components.append(NetlistComponent(
                ref=ref_m.group(1),
                value=val_m.group(1) if val_m else "",
                footprint_lib_id=fp_m.group(1) if fp_m else "",
            ))

    nets: list[NetlistNet] = []

    # Parse (net ...) blocks
    for m in re.finditer(r'^\t\t\(net\b', netlist_sexpr, re.MULTILINE):
        net_start = m.start()
        net_end = _find_matching_close(netlist_sexpr, net_start)
        if net_end is None:
            continue
        block = netlist_sexpr[net_start:net_end + 1]

        code_m = re.search(r'\(code "(\d+)"', block)
        name_m = re.search(r'\(name "([^"]*)"', block)

        code = int(code_m.group(1)) if code_m else 0
        name = name_m.group(1) if name_m else ""

        nodes: list[tuple[str, str]] = []
        for node_m in re.finditer(r'\(node\b', block):
            node_start = node_m.start()
            node_end = _find_matching_close(block, node_start)
            if node_end is None:
                continue
            node_block = block[node_start:node_end + 1]
            ref_m = re.search(r'\(ref "([^"]*)"', node_block)
            pin_m = re.search(r'\(pin "([^"]*)"', node_block)
            if ref_m and pin_m:
                nodes.append((ref_m.group(1), pin_m.group(1)))

        nets.append(NetlistNet(code=code, name=name, nodes=nodes))

    return components, nets


# ---------------------------------------------------------------------------
# Raw S-expression helpers for PCB manipulation
# ---------------------------------------------------------------------------


def _find_footprint_block(
    content: str, reference: str
) -> tuple[Optional[int], Optional[int]]:
    """Find byte offsets of a footprint block by its Reference property.

    Returns (start, end) where end is the position after the closing paren.
    Returns (None, None) if not found.
    """
    pattern = re.compile(
        r'\(property "Reference" "' + re.escape(reference) + r'"',
    )
    # Scan for (footprint blocks that contain the Reference property
    fp_starts: list[int] = []
    for m in re.finditer(r'^\t\(footprint "', content, re.MULTILINE):
        fp_starts.append(m.start())

    for start in fp_starts:
        # Find the matching close paren
        close = _find_matching_close(content, start)
        if close is None:
            continue
        block = content[start:close + 1]
        if pattern.search(block):
            return start, close + 1

    return None, None


def _find_pad_in_footprint(
    fp_block: str, pad_number: str
) -> tuple[Optional[int], Optional[int]]:
    """Find byte offsets of a pad block within a footprint by pad number.

    Returns (start, end) within the fp_block string.
    """
    pattern = re.compile(r'\(pad "' + re.escape(pad_number) + r'"')
    for m in pattern.finditer(fp_block):
        pad_start = m.start()
        pad_end = _find_matching_close(fp_block, pad_start)
        if pad_end is not None:
            return pad_start, pad_end + 1
    return None, None


def _inject_pad_net(fp_block: str, pad_number: str, net_name: str) -> str:
    """Inject or replace the (net ...) assignment in a specific pad.

    Args:
        fp_block: The footprint S-expression block string.
        pad_number: Pad number to target.
        net_name: Net name to assign.

    Returns:
        Modified fp_block string, or original if pad not found.
    """
    safe_net = net_name.replace('"', '""')

    pad_start, pad_end = _find_pad_in_footprint(fp_block, pad_number)
    if pad_start is None:
        return fp_block

    pad_block = fp_block[pad_start:pad_end]

    # Check if pad already has a net assignment
    if "(net " in pad_block:
        new_pad = re.sub(
            r'\(net "[^"]*"\)',
            f'(net "{safe_net}")',
            pad_block,
            count=1,
        )
    else:
        # Insert net before the closing paren
        trimmed = pad_block.rstrip()
        new_pad = trimmed[:-1] + f'\n\t\t(net "{safe_net}")\n\t)'

    return fp_block[:pad_start] + new_pad + fp_block[pad_end:]


def _update_footprint_lib_id(content: str, reference: str, new_lib_id: str) -> str:
    """Update the lib_id in a footprint's (footprint "LIB:NAME" ...) header.

    Args:
        content: Full PCB raw content.
        reference: Footprint reference designator.
        new_lib_id: New footprint library reference.

    Returns:
        Modified content, or original if footprint not found.
    """
    start, end = _find_footprint_block(content, reference)
    if start is None:
        return content

    fp_block = content[start:end]
    safe = new_lib_id.replace('"', '""')
    new_block = re.sub(
        r'^\t\(footprint "[^"]*"',
        f'\t(footprint "{safe}"',
        fp_block,
        count=1,
    )
    if new_block != fp_block:
        return content[:start] + new_block + content[end:]
    return content


def _remove_footprint_block(content: str, reference: str) -> str:
    """Remove a footprint block from PCB raw content.

    Returns:
        Content with the footprint block removed.
    """
    start, end = _find_footprint_block(content, reference)
    if start is None:
        return content
    return content[:start] + content[end:]


def _extract_pcb_footprint_refs(content: str) -> list[str]:
    """Extract all footprint reference designators from PCB raw content.

    Returns:
        List of reference strings.
    """
    return re.findall(r'\(property "Reference" "([^"]+)"', content)


def _extract_pcb_net_names(content: str) -> set[str]:
    """Extract net names from PCB (net ...) definitions.

    Matches both (net N "Name") and (net N "Name" "Extra").
    """
    return set(re.findall(r'\(net \d+ "([^"]*)"', content))


def _add_net_to_content(content: str, net_code: int, net_name: str) -> str:
    """Add a (net ...) definition to the PCB content.

    Inserts after the last existing (net ...) line in the (net section ...).
    """
    safe_name = net_name.replace('"', '""')
    net_line = f'\t\t(net {net_code} "{safe_name}")'

    # Find the last (net ...) line
    net_matches = list(re.finditer(r'^\t\t\(net \d+', content, re.MULTILINE))
    if net_matches:
        last_match = net_matches[-1]
        # Find the end of this line
        line_end = content.find("\n", last_match.start())
        if line_end == -1:
            line_end = len(content)
        return content[:line_end] + "\n" + net_line + content[line_end:]

    # No nets found — find (net section ...) and insert after it
    section_match = re.search(r'\(net_section', content)
    if section_match:
        close = _find_matching_close(content, section_match.start())
        if close is not None:
            return content[:close] + "\n" + net_line + "\n" + content[close:]

    return content


def _remove_empty_net_from_content(content: str, net_name: str) -> str:
    """Remove a net definition from the PCB if it has no connected pads."""
    safe_name = re.escape(net_name.replace('"', '""'))
    # Remove the (net N "name") line
    pattern = re.compile(r'^\t\t\(net \d+ "' + safe_name + r'"\s*(?:\("[^"]*"\))?\s*\)\n?', re.MULTILINE)
    return pattern.sub("", content)


# ---------------------------------------------------------------------------
# Main sync logic
# ---------------------------------------------------------------------------


def sync_pcb_from_netlist(
    pcb_raw: str,
    schematic_path: Path,
    base_dir: Path,
    *,
    sync_netlist: bool = True,
    sync_footprints: bool = True,
    add_new_components: bool = True,
    remove_orphans: bool = False,
) -> tuple[str, SyncResult]:
    """Synchronize PCB raw content from schematic netlist.

    Workflow:
    1. Export netlist from schematic via kicad-cli
    2. Parse netlist S-expressions for components and nets
    3. Update existing PCB footprint pad-to-net assignments
    4. Update footprint lib_id references
    5. Report new components (requires library resolution — separate step)
    6. Optionally remove orphaned footprints
    7. Add missing net definitions to PCB

    Args:
        pcb_raw: Raw PCB file content.
        schematic_path: Path to the schematic .kicad_sch file.
        base_dir: Working directory (project root).
        sync_netlist: Update pad-to-net assignments.
        sync_footprints: Update footprint lib_id references.
        add_new_components: Report new components needed (actual addition
            requires separate library resolution pass).
        remove_orphans: Remove PCB footprints not in schematic.
        sync_netlist: Update pad-to-net assignments.

    Returns:
        Tuple of (modified_raw_content, SyncResult).
    """
    result = SyncResult()

    # Phase 1: Export and parse netlist
    netlist_sexpr = export_netlist(schematic_path, base_dir)
    components, nets = parse_netlist(netlist_sexpr)

    if not components:
        logger.warning("Netlist has no components — nothing to sync")
        return pcb_raw, result

    # Build lookup maps
    sch_components: dict[str, NetlistComponent] = {c.ref: c for c in components}

    # ref -> {pin_number: net_name}
    ref_pin_nets: dict[str, dict[str, str]] = {}
    for net in nets:
        for ref, pin in net.nodes:
            ref_pin_nets.setdefault(ref, {})[pin] = net.name

    # net_name -> net_code
    net_codes: dict[str, int] = {n.name: n.code for n in nets}

    # Get existing PCB state
    pcb_refs = set(_extract_pcb_footprint_refs(pcb_raw))
    pcb_net_names = _extract_pcb_net_names(pcb_raw)

    # Phase 2: Update pad-to-net assignments on existing footprints
    if sync_netlist:
        for ref, pin_nets in ref_pin_nets.items():
            if ref not in pcb_refs:
                continue
            for pad_num, net_name in pin_nets.items():
                fp_start, fp_end = _find_footprint_block(pcb_raw, ref)
                if fp_start is None:
                    continue
                fp_block = pcb_raw[fp_start:fp_end]
                new_block = _inject_pad_net(fp_block, pad_num, net_name)
                if new_block != fp_block:
                    pcb_raw = pcb_raw[:fp_start] + new_block + pcb_raw[fp_end:]
                    result.pad_net_updates += 1
                    if net_name not in result.updated_nets:
                        result.updated_nets.append(net_name)

    # Phase 3: Update footprint lib_id references
    if sync_footprints:
        for ref, comp in sch_components.items():
            if ref in pcb_refs and comp.footprint_lib_id:
                new_raw = _update_footprint_lib_id(pcb_raw, ref, comp.footprint_lib_id)
                if new_raw != pcb_raw:
                    result.footprint_ref_updates.append((ref, comp.footprint_lib_id))
                    pcb_raw = new_raw

    # Phase 4: Report new components needed
    if add_new_components:
        for ref, comp in sch_components.items():
            if ref not in pcb_refs:
                result.added_footprints.append(ref)
                logger.info(
                    "Component %s (%s) in schematic but not in PCB",
                    ref,
                    comp.footprint_lib_id,
                )

    # Phase 5: Remove orphaned footprints
    if remove_orphans:
        for ref in sorted(pcb_refs):
            if ref not in sch_components:
                new_raw = _remove_footprint_block(pcb_raw, ref)
                if new_raw != pcb_raw:
                    result.removed_orphans.append(ref)
                    pcb_raw = new_raw
                    logger.info("Removed orphaned footprint: %s", ref)

    # Phase 6: Add missing net definitions to PCB
    for net_name, net_code in net_codes.items():
        if net_name and net_name not in pcb_net_names:
            pcb_raw = _add_net_to_content(pcb_raw, net_code, net_name)
            result.added_net_defs.append(net_name)
            logger.info("Added net definition: %s (code %d)", net_name, net_code)

    return pcb_raw, result
