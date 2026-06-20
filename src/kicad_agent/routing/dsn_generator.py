"""Generate Specctra DSN files from KiCad PCB data.

KiCad 10 removed ``kicad-cli pcb export dsn``, so we generate DSN
directly from PCB content for Freerouting integration.

The DSN format follows Freerouting 2.2.4's Specctra parser (verified
by reading Freerouting source: Component.java, Package.java, Library.java,
Network.java, DsnFile.java).

Key format requirements (verified against working Freerouting v2.2.4):
- (structure): layers + boundary (NO via padstack here)
- (placement): grouped by footprint name, each (place REF X Y SIDE ROTATION)
- (library): (image "FP" (side ...) (pin PADSTACK NAME X Y) ...) + (padstack ...)
- (network): (class ... (circuit (use_layer ...)(use_via ...))(rule ...)) then
  (net "NAME" (pins REF-PAD REF-PAD ...))

Usage::

    from kicad_agent.routing.dsn_generator import generate_dsn

    dsn_text = generate_dsn(pcb_raw_content, pcb_path)
"""

from __future__ import annotations

import re
from pathlib import Path

# 1mm = 1000um; Specctra DSN uses um (micrometers)
_MM_TO_UM = 1000.0

# Default via padstack name
_VIA_PADSTACK_NAME = "Via[0-1]"


def generate_dsn(
    pcb_content: str,
    pcb_path: Path | None = None,
    *,
    layers: list[str] | None = None,
    pad_via_drill_um: int = 400,
    pad_via_size_um: int = 800,
    wire_width_um: int = 250,
    clearance_um: int = 250,
) -> str:
    """Generate a Specctra DSN file from KiCad PCB raw content.

    Coordinates are converted from KiCad mm to Specctra um.

    Args:
        pcb_content: Raw .kicad_pcb S-expression text.
        pcb_path: Path to the PCB file (for source reference).
        layers: Copper layers to include. Default ["F.Cu", "B.Cu"].
        pad_via_drill_um: Via drill size in micrometers.
        pad_via_size_um: Via pad size in micrometers.
        wire_width_um: Default trace width in micrometers.
        clearance_um: Default clearance in micrometers.

    Returns:
        DSN file content as a string.
    """
    if layers is None:
        layers = ["F.Cu", "B.Cu"]

    components = _extract_components(pcb_content)
    nets = _extract_nets(pcb_content)
    boundary = _extract_board_outline(pcb_content)
    if boundary is None:
        boundary = _compute_boundary_from_components(components)

    # Build library data
    padstacks, images = _build_library(components, layers)

    source = pcb_path.stem if pcb_path else "board"
    lines: list[str] = []

    # Top-level header
    lines.append(f"(pcb {source}")

    # Parser info
    lines.append("  (parser")
    lines.append('    (string_quote ")')
    lines.append("    (space_in_quoted_tokens on)")
    lines.append('    (host_cad "KiCad")')
    lines.append('    (host_version "10.0")')
    lines.append("  )")

    # Resolution and units
    lines.append("  (resolution um 10)")
    lines.append("  (unit um)")

    # Structure — layers + boundary (NO via padstack)
    lines.append("  (structure")
    for idx, layer in enumerate(layers):
        lines.append(f"    (layer {layer}")
        lines.append("      (type signal)")
        lines.append("      (property")
        lines.append(f"        (index {idx})")
        lines.append("      )")
        lines.append("    )")

    if boundary and len(boundary) >= 4:
        bx1, by1, bx2, by2 = boundary
        ux1 = int(bx1 * _MM_TO_UM)
        uy1 = int(by1 * _MM_TO_UM)
        ux2 = int(bx2 * _MM_TO_UM)
        uy2 = int(by2 * _MM_TO_UM)
        lines.append("    (boundary")
        pts = (
            f"      (path pcb 0  {ux1} {uy1}  {ux2} {uy1}"
            f"  {ux2} {uy2}  {ux1} {uy2}  {ux1} {uy1})"
        )
        lines.append(pts)
        lines.append("    )")

    lines.append("  )")  # end structure

    # Placement — grouped by footprint/package name
    if components:
        lines.append("  (placement")
        # Group components by footprint
        fp_groups: dict[str, list[dict]] = {}
        for comp in components:
            fp = comp.get("footprint", comp["reference"])
            fp_groups.setdefault(fp, []).append(comp)

        for fp_name, comps in sorted(fp_groups.items()):
            lines.append(f'    (component "{fp_name}"')
            for comp in comps:
                ref = comp["reference"]
                x_um = int(comp["x"] * _MM_TO_UM)
                y_um = int(comp["y"] * _MM_TO_UM)
                angle = int(comp["angle"])
                side = "front" if comp.get("side", "front") == "front" else "back"
                lines.append(f"      (place {ref} {x_um} {y_um} {side} {angle})")
            lines.append("    )")
        lines.append("  )")  # end placement

    # Library — via padstack + package images + SMD padstacks
    lines.append("  (library")
    # Via padstack
    lines.append(f'    (padstack "{_VIA_PADSTACK_NAME}"')
    for layer in layers:
        lines.append(f"      (shape (circle {layer} {pad_via_size_um}))")
    lines.append("      (attach off)")
    lines.append("    )")
    # Package images
    for img_name, img_data in sorted(images.items()):
        side = img_data["side"]
        pins = img_data["pins"]
        lines.append(f'    (image "{img_name}"')
        lines.append(f"      (side {side})")
        for pin in pins:
            lines.append(
                f"      (pin {pin['padstack']} {pin['name']}"
                f" {int(pin['x'] * _MM_TO_UM)} {int(pin['y'] * _MM_TO_UM)})"
            )
        lines.append("    )")
    # SMD padstacks
    for ps_name, ps_data in sorted(padstacks.items()):
        shapes = ps_data["shapes"]
        attach = ps_data["attach"]
        lines.append(f'    (padstack "{ps_name}"')
        for layer_name, size_um in shapes:
            lines.append(f"      (shape (circle {layer_name} {size_um}))")
        lines.append(f"      (attach {attach})")
        lines.append("    )")
    lines.append("  )")  # end library

    # Network — class + nets
    lines.append("  (network")
    # Default class with via rule
    lines.append('    (class default ""')
    lines.append("      (circuit")
    layer_str = " ".join(layers)
    lines.append(f"        (use_layer {layer_str})")
    lines.append(f"        (use_via {_VIA_PADSTACK_NAME})")
    lines.append("      )")
    lines.append("      (rule")
    lines.append(f"        (width {wire_width_um})")
    lines.append(f"        (clearance {clearance_um})")
    lines.append("      )")
    lines.append("    )")
    # Nets with space-separated pins
    for net_name, pins in sorted(nets.items()):
        if not net_name or not pins:
            continue
        pins_str = " ".join(pins)
        lines.append(f'    (net "{net_name}"')
        lines.append(f"      (pins {pins_str})")
        lines.append("    )")
    lines.append("  )")  # end network

    lines.append(")")  # end pcb
    return "\n".join(lines) + "\n"


def _build_library(
    components: list[dict],
    layers: list[str],
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Build padstacks and package images from components.

    Returns:
        Tuple of (padstacks, images) where:
        - padstacks: {name: {"shapes": [(layer, size_um), ...], "attach": str}}
        - images: {name: {"side": str, "pins": [{...}]}}
    """
    padstacks: dict[str, dict] = {}
    images: dict[str, dict] = {}

    # Deduplicate components by reference (hierarchical sheets produce copies)
    seen_refs: set[str] = set()

    for comp in components:
        ref = comp["reference"]
        if ref in seen_refs:
            continue
        seen_refs.add(ref)

        fp = comp.get("footprint", ref)
        side = comp.get("side", "front")

        if fp not in images:
            images[fp] = {"side": side, "pins": []}

        for pad in comp.get("pads", []):
            size_um = int(pad.get("size", 0.8) * _MM_TO_UM)
            drill = pad.get("drill", 0.0)
            pad_layers = pad.get("layers", "F.Cu")

            # Map KiCad pad layers to DSN layer names
            # KiCad "*.Cu" means all copper; for SMD use component side,
            # for TH use all layers
            if drill > 0:
                drill_um = int(drill * _MM_TO_UM)
                ps_key = f"TH_{size_um}:{drill_um}_um"
                attach = "off"
                shapes = [(layer, size_um) for layer in layers]
            else:
                # Resolve pad layer to a specific DSN layer
                if pad_layers == "*.Cu" or pad_layers == "*":
                    dsn_layer = layers[0] if side == "front" else layers[-1]
                else:
                    dsn_layer = pad_layers
                ps_key = f"SMD_{dsn_layer}_{size_um}_um"
                attach = "on"
                shapes = [(dsn_layer, size_um)]

            if ps_key not in padstacks:
                padstacks[ps_key] = {"shapes": shapes, "attach": attach}

            images[fp]["pins"].append({
                "padstack": ps_key,
                "name": pad["name"],
                "x": pad["x"],
                "y": pad["y"],
            })

    return padstacks, images


def _extract_components(pcb_content: str) -> list[dict]:
    """Extract component placement and pad positions from PCB content."""
    components = []

    for fp_match in re.finditer(r"^\s+\(footprint ", pcb_content, re.MULTILINE):
        fp_start = fp_match.start()
        fp_end = _find_matching_close(pcb_content, fp_start)
        if fp_end is None:
            continue

        block = pcb_content[fp_start:fp_end + 1]

        lib_match = re.search(r'\(footprint\s+"([^"]+)"', block)
        if not lib_match:
            continue
        lib_id = lib_match.group(1)

        ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
        if not ref_match:
            continue
        reference = ref_match.group(1)

        at_match = re.search(
            r"\(at\s+([-\d.]+)\s+([-\d.]+)(?:\s+([-\d.]+))?\s*\)", block
        )
        if not at_match:
            continue
        x, y = float(at_match.group(1)), float(at_match.group(2))
        angle = float(at_match.group(3)) if at_match.group(3) else 0.0

        side = "front"
        layer_match = re.search(r'\(layer\s+"([^"]+)"', block)
        if layer_match and layer_match.group(1).startswith("B."):
            side = "back"

        pads = _extract_pads(block, fp_start, pcb_content)

        components.append({
            "reference": reference,
            "footprint": lib_id,
            "x": x,
            "y": y,
            "angle": angle,
            "side": side,
            "pads": pads,
        })

    return components


def _extract_pads(
    block: str, fp_start: int, pcb_content: str
) -> list[dict]:
    """Extract pad data from a footprint block."""
    pads = []
    for pad_match in re.finditer(r'\(pad\s+"([^"]+)"', block):
        pad_name = pad_match.group(1)
        pad_abs_start = fp_start + pad_match.start()
        pad_abs_end = _find_matching_close(pcb_content, pad_abs_start)
        if pad_abs_end is None:
            continue
        pad_block = pcb_content[pad_abs_start:pad_abs_end + 1]

        pad_at = re.search(r"\(at\s+([-\d.]+)\s+([-\d.]+)", pad_block)
        if not pad_at:
            continue

        px = float(pad_at.group(1))
        py = float(pad_at.group(2))

        pad_size = 0.8
        size_match = re.search(r'\(size\s+([-\d.]+)\s+([-\d.]+)', pad_block)
        if size_match:
            pad_size = max(float(size_match.group(1)), float(size_match.group(2)))

        drill = 0.0
        drill_match = re.search(r'\(drill\s+([-\d.]+)', pad_block)
        if drill_match:
            drill = float(drill_match.group(1))

        pad_layers = "F.Cu"
        pad_layer_match = re.search(r'\(layers\s+"([^"]+)"', pad_block)
        if pad_layer_match:
            pad_layers = pad_layer_match.group(1)

        pads.append({
            "name": pad_name,
            "x": px,
            "y": py,
            "size": pad_size,
            "drill": drill,
            "layers": pad_layers,
        })

    return pads


def _extract_nets(pcb_content: str) -> dict[str, list[str]]:
    """Extract net connectivity as {net_name: [ref-pad, ...]}.

    Deduplicates pin references — PCB files with hierarchical sheets or
    board variants may contain duplicate footprint blocks.
    """
    nets: dict[str, set[str]] = {}

    for fp_match in re.finditer(r"^\s+\(footprint ", pcb_content, re.MULTILINE):
        fp_start = fp_match.start()
        fp_end = _find_matching_close(pcb_content, fp_start)
        if fp_end is None:
            continue

        block = pcb_content[fp_start:fp_end + 1]

        ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
        if not ref_match:
            continue
        reference = ref_match.group(1)

        for pad_match in re.finditer(r'\(pad\s+"([^"]+)"', block):
            pad_name = pad_match.group(1)
            pad_abs_start = fp_start + pad_match.start()
            pad_abs_end = _find_matching_close(pcb_content, pad_abs_start)
            if pad_abs_end is None:
                continue
            pad_block = pcb_content[pad_abs_start:pad_abs_end + 1]
            net_match = re.search(r'\(net\s+(?:\d+\s+)?"([^"]+)"', pad_block)
            if net_match:
                net_name = net_match.group(1)
                pin_ref = f"{reference}-{pad_name}"
                if net_name not in nets:
                    nets[net_name] = set()
                nets[net_name].add(pin_ref)

    return {name: sorted(pins) for name, pins in nets.items()}


def _extract_board_outline(pcb_content: str) -> list[float] | None:
    """Extract board outline as [x1, y1, x2, y2] from Edge.Cuts."""
    edges = []

    for match in re.finditer(r"\(gr_line\s", pcb_content):
        start = match.start()
        end = _find_matching_close(pcb_content, start)
        if end is None:
            continue
        block = pcb_content[start:end + 1]
        layer_match = re.search(r'\(layer\s+"([^"]+)"', block)
        if not layer_match or layer_match.group(1) != "Edge.Cuts":
            continue
        coords = re.findall(r"\(start\s+([-\d.]+)\s+([-\d.]+)\)", block)
        ends = re.findall(r"\(end\s+([-\d.]+)\s+([-\d.]+)\)", block)
        if coords:
            edges.append((float(coords[0][0]), float(coords[0][1])))
        if ends:
            edges.append((float(ends[0][0]), float(ends[0][1])))

    if not edges:
        return None

    xs = [p[0] for p in edges]
    ys = [p[1] for p in edges]
    return [min(xs), min(ys), max(xs), max(ys)]


def _compute_boundary_from_components(
    components: list[dict],
    margin_mm: float = 5.0,
) -> list[float]:
    """Compute board boundary from component positions."""
    if not components:
        return [0.0, 0.0, 100.0, 100.0]
    xs = [c["x"] for c in components]
    ys = [c["y"] for c in components]
    return [
        min(xs) - margin_mm,
        min(ys) - margin_mm,
        max(xs) + margin_mm,
        max(ys) + margin_mm,
    ]


def _find_matching_close(content: str, open_pos: int) -> int | None:
    """Find matching close paren for an S-expression, respecting quoted strings."""
    depth = 0
    i = open_pos
    in_string = False
    while i < len(content):
        c = content[i]
        if in_string:
            if c == '"':
                if i + 1 < len(content) and content[i + 1] == '"':
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None
