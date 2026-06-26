"""Generate Specctra DSN files from KiCad PCB data.

KiCad 10 removed ``kicad-cli pcb export dsn``, so we generate DSN
directly from PCB content for Freerouting integration.

The DSN format follows Freerouting 2.2.4's Specctra parser (verified
by reading Freerouting source: Component.java, Package.java, Library.java,
Network.java, DsnFile.java).

Phase 99 refactor: consumes NativeBoard (from NativeParser) instead of
brittle regex extraction. Emits courtyard-accurate footprint obstacles
(R-1), per-net-class rules (R-2, Task 2b), copper zones + keepouts
(R-3, Task 2b), and 45deg trace mode (R-5).

Key format requirements (verified against working Freerouting v2.2.4):
- (structure): layers + boundary + (plane/keepout) + (control snap_angle)
- (placement): grouped by footprint name, each (place REF X Y SIDE ROTATION)
- (library): (image "FP" (side ...) (outline (rect ...)) (pin ...) ...) + padstacks
- (network): (class ... (circuit (use_layer ...)(use_via ...))(rule ...)) then
  (net "NAME" (pins REF-PAD REF-PAD ...))

Usage::

    from kicad_agent.routing.dsn_generator import generate_dsn

    dsn_text = generate_dsn(pcb_raw_content, pcb_path)
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from kicad_agent.parser.pcb_native_parser import NativeParser
from kicad_agent.parser.pcb_native_types import (
    NativeBoard,
    NativeFootprint,
    NativeGraphicItem,
    NativeNetClass,
    NativePad,
)

# 1mm = 1000um; Specctra DSN uses um (micrometers)
_MM_TO_UM = 1000.0

# Default via padstack name
_VIA_PADSTACK_NAME = "Via[0-1]"

# T-99-01-04 mitigation: fixed enum for snap_angle (prevents string injection).
_VALID_SNAP_ANGLES = {"none", "fortyfive_degree", "ninety_degree"}


def generate_dsn(
    pcb_content: str,
    pcb_path: Path | None = None,
    *,
    layers: list[str] | None = None,
    pad_via_drill_um: int = 400,
    pad_via_size_um: int = 800,
    wire_width_um: int = 250,
    clearance_um: int = 250,
    snap_angle: str = "none",
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
        snap_angle: Trace angle mode. One of "none" (default),
            "fortyfive_degree", or "ninety_degree". Invalid values raise
            ValueError (T-99-01-04 mitigation).

    Returns:
        DSN file content as a string.
    """
    # L-1 fix: validate UNCONDITIONALLY as the first statement (defense-in-depth).
    if snap_angle not in _VALID_SNAP_ANGLES:
        raise ValueError(
            f"Invalid snap_angle: {snap_angle!r}. Must be one of {_VALID_SNAP_ANGLES}"
        )

    _layers_were_default = layers is None
    if layers is None:
        layers = ["F.Cu", "B.Cu"]

    # M-3 fix: consume NativeBoard for footprints/pads/net_classes/zones.
    # Board outline stays on regex for now (deferred via Bead — see SUMMARY).
    board = NativeParser.parse_pcb_content(
        pcb_content, file_path=str(pcb_path) if pcb_path else ""
    )

    # R-4: when caller used default layers but board has a richer stackup,
    # extend the DSN layer list with inner copper layers so padstack shapes
    # on In1.Cu/In2.Cu reference declared (layer ...) entries. Without this,
    # Freerouting rejects blind/buried padstacks whose shapes land on undeclared
    # layers. Only kicks in for the default path (explicit layers override).
    if _layers_were_default:
        copper = _copper_signal_layers(board, layers)
        if len(copper) > len(layers):
            layers = copper

    boundary = _extract_board_outline(pcb_content)
    if boundary is None:
        boundary = _compute_boundary_from_components(board.footprints)

    # Build library data from NativeBoard footprints (R-1 outlines included).
    padstacks, images = _build_library_from_native(board.footprints, layers)

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

    # Structure — layers + boundary + zones + snap_angle control
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

    # R-3 zones (Task 2b): emitted between boundary and snap_angle control.
    _emit_zones(lines, board)

    # R-5 snap_angle (M-2 fix: emit AFTER boundary and zones, canonical DSN order).
    if snap_angle != "none":
        lines.append(f"    (control (snap_angle {snap_angle}))")

    lines.append("  )")  # end structure

    # Placement — grouped by footprint/package name
    if board.footprints:
        lines.append("  (placement")
        # Group components by footprint
        fp_groups: dict[str, list[NativeFootprint]] = {}
        for fp in board.footprints:
            fp_groups.setdefault(fp.lib_id, []).append(fp)

        for fp_name, fps in sorted(fp_groups.items()):
            lines.append(f'    (component "{fp_name}"')
            for fp in fps:
                ref = fp.properties.get("Reference", "")
                if not ref:
                    continue
                x_um = int(fp.position[0] * _MM_TO_UM)
                y_um = int(fp.position[1] * _MM_TO_UM)
                angle = int(fp.position[2])
                side = "front" if not fp.layer.startswith("B.") else "back"
                lines.append(f"      (place {ref} {x_um} {y_um} {side} {angle})")
            lines.append("    )")
        lines.append("  )")  # end placement

    # Library — via padstack + package images (with outlines) + SMD padstacks
    # + per-class via padstacks (H-2 fix, Task 2b)
    lines.append("  (library")
    # R-4: stackup-based via padstacks (THT always, blind/buried when 4+ copper layers).
    _emit_via_padstacks(lines, board, layers, pad_via_size_um)

    # H-2 fix (Task 2b): per-class via padstacks emitted alongside (use_via ...).
    _emit_per_class_padstacks(lines, board, layers)

    # Package images (R-1: each has an (outline ...))
    for img_name, img_data in sorted(images.items()):
        side = img_data["side"]
        pins = img_data["pins"]
        outline = img_data["outline"]  # (x1_um, y1_um, x2_um, y2_um) or None
        lines.append(f'    (image "{img_name}"')
        lines.append(f"      (side {side})")
        # R-1: emit outline BEFORE pins. Never emit an image without one.
        if outline is not None:
            ox1, oy1, ox2, oy2 = outline
            lines.append(
                f"      (outline (rect F.Cu {ox1} {oy1} {ox2} {oy2}))"
            )
        for pin in pins:
            # Rule 1 fix: Freerouting's Specctra parser expects exactly 4 tokens
            # after `pin` (padstack, name, x, y). Empty pad numbers collapse the
            # f-string to 3 numeric tokens, causing a parse error on the next
            # image. Substitute a stable placeholder when pad number is empty.
            # Council WR-03: quote pin name with DSN doubled-quote escaping so
            # pad numbers containing whitespace/quotes don't break the parser.
            raw_name = pin['name'] if pin['name'] else "pad"
            safe_name = raw_name.replace('"', '""')
            lines.append(
                f'      (pin {pin["padstack"]} "{safe_name}"'
                f' {int(pin["x"] * _MM_TO_UM)} {int(pin["y"] * _MM_TO_UM)})'
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

    # Network — classes (R-2, Task 2b) + nets
    lines.append("  (network")
    _emit_net_classes(
        lines,
        board,
        layers,
        wire_width_um=wire_width_um,
        clearance_um=clearance_um,
    )
    # Nets with space-separated pins
    nets = _extract_nets_from_board(board)
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


# ---------------------------------------------------------------------------
# Library building (NativeBoard-backed, R-1 courtyard outlines)
# ---------------------------------------------------------------------------


def _build_library_from_native(
    footprints: list[NativeFootprint],
    layers: list[str],
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Build padstacks and package images from NativeFootprint list.

    R-1: each image includes an (outline ...) rect derived from courtyard
    F.CrtYd graphic items (rotation-aware, L-2 fix) with pad-bbox fallback.

    Returns:
        Tuple of (padstacks, images) where:
        - padstacks: {name: {"shapes": [(layer, size_um), ...], "attach": str}}
        - images: {name: {"side": str, "pins": [{...}], "outline": (x1,y1,x2,y2)_um|None}}
    """
    padstacks: dict[str, dict] = {}
    images: dict[str, dict] = {}

    seen_refs: set[str] = set()

    for fp in footprints:
        ref = fp.properties.get("Reference", "")
        if not ref or ref in seen_refs:
            continue
        seen_refs.add(ref)

        lib_id = fp.lib_id or ref
        side = "back" if fp.layer.startswith("B.") else "front"

        if lib_id not in images:
            images[lib_id] = {"side": side, "pins": [], "outline": None}

        for pad in fp.pads:
            size_um = int(max(pad.size[0], pad.size[1]) * _MM_TO_UM) if pad.size else int(0.8 * _MM_TO_UM)
            drill = pad.drill
            pad_layers = pad.layers or "F.Cu"

            # Bead analog-ecosystem-27 fix: resolve pad layer to a DECLARED
            # copper layer. Freerouting rejects shapes on undeclared layers
            # (*.Cu wildcard, F.Paste, F.Mask). Strategy: take first token,
            # if it's wildcard or not in declared layers, fall back to side-
            # appropriate copper layer.
            declared = set(layers)
            front_layer = layers[0] if layers else "F.Cu"
            back_layer = layers[-1] if layers else "B.Cu"
            default_layer = front_layer if side == "front" else back_layer

            tokens = pad_layers.split() if pad_layers else []
            first_token = tokens[0] if tokens else default_layer

            # Resolve to a declared copper layer
            if first_token in declared:
                dsn_layer = first_token
            elif first_token in ("*.Cu", "*", "&1Cu", "*.CuB"):
                # Wildcard — use side-appropriate layer
                dsn_layer = default_layer
            else:
                # F.Paste, F.Mask, F.SilkS, B.Mask, etc. — not copper, use default
                # Check if ANY declared copper layer is in tokens (multi-layer pad)
                copper_token = next((t for t in tokens if t in declared), None)
                if copper_token:
                    dsn_layer = copper_token
                else:
                    dsn_layer = default_layer

            if drill > 0:
                drill_um = int(drill * _MM_TO_UM)
                ps_key = f"TH_{size_um}:{drill_um}_um"
                attach = "off"
                # TH pads span all declared layers
                shapes = [(layer, size_um) for layer in layers] if layers else [(default_layer, size_um)]
            else:
                ps_key = f"SMD_{dsn_layer}_{size_um}_um"
                attach = "on"
                shapes = [(dsn_layer, size_um)]

            if ps_key not in padstacks:
                padstacks[ps_key] = {"shapes": shapes, "attach": attach}

            # Pad positions are footprint-local (unrotated); store as-is.
            # The placement (place ...) block carries footprint rotation.
            images[lib_id]["pins"].append({
                "padstack": ps_key,
                "name": pad.number,
                "x": pad.position[0],
                "y": pad.position[1],
            })

        # R-1: compute outline (courtyard preferred, pad-bbox fallback).
        # L-2 fix: apply footprint rotation to local coords before AABB.
        outline = _compute_footprint_outline(fp)
        if outline is not None:
            # Keep the first non-None outline (all instances of same lib_id
            # share the same footprint geometry, so any one is representative).
            if images[lib_id]["outline"] is None:
                images[lib_id]["outline"] = outline

    return padstacks, images


def _compute_footprint_outline(
    fp: NativeFootprint,
) -> tuple[int, int, int, int] | None:
    """R-1 + L-2 fix: rotation-aware AABB of courtyard graphics (pad-bbox fallback).

    Footprint graphic_items and pad positions are in footprint-LOCAL coordinates.
    The (at X Y ANGLE) from fp.position rotates the whole footprint. We transform
    each local point by the rotation, then compute the axis-aligned bounding box
    (AABB) in world coordinates, converted to micrometers.

    Returns:
        (x1_um, y1_um, x2_um, y2_um) or None if footprint has no geometry.
    """
    angle_deg = fp.position[2] if len(fp.position) >= 3 else 0.0
    angle_rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)

    def _transform(lx: float, ly: float) -> tuple[float, float]:
        wx = fp.position[0] + lx * cos_a - ly * sin_a
        wy = fp.position[1] + lx * sin_a + ly * cos_a
        return wx, wy

    points: list[tuple[float, float]] = []

    # Courtyard graphics first (preferred source for outline).
    crtyd_items = [g for g in fp.graphic_items if _is_crtyd(g)]
    for g in crtyd_items:
        points.extend(_graphic_points(g))

    if not points:
        # Fallback: pad bounding box (transformed ± half pad size).
        for pad in fp.pads:
            px, py = _transform(pad.position[0], pad.position[1])
            sx = pad.size[0] / 2.0 if pad.size else 0.4
            sy = pad.size[1] / 2.0 if pad.size else 0.4
            points.append((px - sx, py - sy))
            points.append((px + sx, py + sy))

    if not points:
        return None

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (
        int(min(xs) * _MM_TO_UM),
        int(min(ys) * _MM_TO_UM),
        int(max(xs) * _MM_TO_UM),
        int(max(ys) * _MM_TO_UM),
    )


def _is_crtyd(g: NativeGraphicItem) -> bool:
    """True if the graphic item is on a courtyard layer (F.CrtYd or B.CrtYd)."""
    return bool(g.layer) and g.layer.endswith(".CrtYd")


def _graphic_points(g: NativeGraphicItem) -> list[tuple[float, float]]:
    """Extract representative points from a NativeGraphicItem for AABB computation.

    NativeGraphicItem fields use _NativePosition NamedTuples (support .X/.Y and
    tuple indexing). We extract corner/edge points depending on type.
    """
    pts: list[tuple[float, float]] = []
    # Rect: start + end define opposite corners.
    if g.start is not None and g.end is not None:
        pts.append((float(g.start[0]), float(g.start[1])))
        pts.append((float(g.end[0]), float(g.end[1])))
    # Line: same as rect (start/end).
    elif g.start is not None:
        pts.append((float(g.start[0]), float(g.start[1])))
        if g.end is not None:
            pts.append((float(g.end[0]), float(g.end[1])))
    # Circle: center ± radius on both axes (bounding square).
    if g.center is not None and g.radius > 0:
        cx, cy = float(g.center[0]), float(g.center[1])
        r = g.radius
        pts.append((cx - r, cy - r))
        pts.append((cx + r, cy + r))
    return pts


# ---------------------------------------------------------------------------
# Zones (R-3, Task 2b — 3-way classification)
# ---------------------------------------------------------------------------


def _emit_zones(lines: list[str], board: NativeBoard) -> None:
    """R-3: emit copper zones as (plane ...) or (keepout ...) per C-1 classification.

    Category 1 (copper pour, net_name != ""): SKIP plane emission.
        Bead analog-ecosystem-24 fix: previously emitted (plane "NET" (layer L) (polygon ...))
        but Freerouting's DSN parser NPEs on plane_info.area = null when the zone polygon
        extends even slightly outside the board boundary (which happens routinely because
        _get_board_bbox_points and _extract_board_outline use different parsing paths).
        Freerouting treats copper pours as routing obstacles implicitly via pad clearances,
        so plane emission is not required for routing to succeed. The plane construct in
        Specctra DSN is for power-plane routing algorithms which Freerouting does not
        perform on this board.
    Category 2 (routing keepout, is_routing_keepout): emit (keepout "NAME" (polygon ...)).
    Category 3 (placement-only keepout): SKIP — Freerouting does not place footprints.
    """
    for zone in board.zones:
        poly_um = [
            (int(x * _MM_TO_UM), int(y * _MM_TO_UM))
            for x, y in zone.polygon_points
        ]
        if not poly_um:
            continue
        poly_str = " ".join(f"{x} {y}" for x, y in poly_um)

        net_name = zone.net_name or getattr(zone, "netName", "")
        if net_name:
            # Category 1: copper pour -> SKIP plane emission (Bead #24 fix).
            # Freerouting routes around copper pours via pad clearances.
            continue
        elif getattr(zone, "is_routing_keepout", False):
            # Category 2: routing keepout (tracks or vias not_allowed).
            label = f"ZONE_{zone.uuid[:8]}" if zone.uuid else f"ZONE_{id(zone) & 0xFFFFFFFF:08x}"
            layer = zone.layer or (zone.layers[0] if zone.layers else "F.Cu")
            lines.append(
                f'    (keepout "{label}" (polygon {layer} 0 {poly_str}))'
            )
        # Category 3: placement-only keepout -> skip (C-1 fix).


# ---------------------------------------------------------------------------
# Stackup-based via padstacks (R-4, Task 1 Step C)
# ---------------------------------------------------------------------------


def _copper_signal_layers(board: NativeBoard, fallback_layers: list[str]) -> list[str]:
    """R-4: return the ordered list of copper signal layers from the board stackup.

    Reads board.setup.stackup.layers and filters to type == "copper" AND name
    ends in ".Cu" (excludes copper-derived planes/mask layers that some KiCad
    stackups annotate with type "copper"). Falls back to fallback_layers
    (typically ["F.Cu", "B.Cu"]) when stackup is absent or has <2 copper entries.

    The fallback also kicks in for 2-layer boards that omit explicit stackup
    metadata (common for hobby boards) — in that case we cannot distinguish
    blind/buried feasibility, so THT-only is the safe default.
    """
    if board.setup and board.setup.stackup and board.setup.stackup.layers:
        copper = [
            sl.name for sl in board.setup.stackup.layers
            if getattr(sl, "type", "") == "copper"
            and isinstance(sl.name, str)
            and sl.name.endswith(".Cu")
        ]
        if len(copper) >= 2:
            return copper
    return list(fallback_layers)


def _emit_via_padstacks(
    lines: list[str],
    board: NativeBoard,
    layers: list[str],
    default_size_um: int,
) -> None:
    """R-4: emit via padstacks based on board stackup (THT/blind/buried).

    - THT via (Via[0-1]): always emitted, shapes on all copper layers.
    - Blind via (Via[0-In1]): emitted only when stackup has >=4 copper layers.
      Spans F.Cu + first inner copper layer.
    - Buried via (Via[In1-In2]): emitted only when stackup has >=4 copper layers.
      Spans first two inner copper layers.

    H-2 fix: per-net-class via padstacks ((padstack "Via[NAME]" ...)) are emitted
    by _emit_per_class_padstacks (Plan 99-01 Task 2b Step A2), NOT here.
    This helper covers stackup-based padstacks only (THT/blind/buried).

    H-1 fix: microvia padstacks are deferred (see 99-02-SUMMARY.md). Rationale:
    microvias are rare in hobby boards, Freerouting v2.2.4 microvia support is
    unverified, and no fixture exercises them.
    """
    copper_layers = _copper_signal_layers(board, layers)

    # THT via (always emitted, spans all copper layers).
    lines.append(f'    (padstack "{_VIA_PADSTACK_NAME}"')
    for layer in copper_layers:
        lines.append(f"      (shape (circle {layer} {default_size_um}))")
    lines.append("      (attach off)")
    lines.append("    )")

    # Blind/buried padstacks (only if 4+ copper layers).
    if len(copper_layers) >= 4:
        # Via[0-In1] — blind from outer to first inner.
        lines.append('    (padstack "Via[0-In1]"')
        lines.append(f"      (shape (circle {copper_layers[0]} {default_size_um}))")
        lines.append(f"      (shape (circle {copper_layers[1]} {default_size_um}))")
        lines.append("      (attach off)")
        lines.append("    )")
        # Via[In1-In2] — buried between first two inner layers.
        lines.append('    (padstack "Via[In1-In2]"')
        lines.append(f"      (shape (circle {copper_layers[1]} {default_size_um}))")
        lines.append(f"      (shape (circle {copper_layers[2]} {default_size_um}))")
        lines.append("      (attach off)")
        lines.append("    )")


# ---------------------------------------------------------------------------
# Per-class via padstacks (H-2 fix, Task 2b)
# ---------------------------------------------------------------------------


def _emit_per_class_padstacks(
    lines: list[str], board: NativeBoard, layers: list[str]
) -> None:
    """H-2 fix: emit (padstack "Via[NAME]" ...) for each named net class with via_diameter.

    This guarantees the DSN is self-contained: every (use_via "Via[NAME]") reference
    inside a (class ...) block has a matching padstack in the library block, emitted
    in the SAME plan (Plan 99-01). Plan 99-02 handles stackup-based via padstacks.
    """
    for nc in board.net_classes:
        if nc.via_diameter <= 0:
            continue
        via_name = f"Via[{nc.name}]"
        size_um = int(nc.via_diameter * _MM_TO_UM)
        lines.append(f'    (padstack "{via_name}"')
        for layer in layers:
            lines.append(f"      (shape (circle {layer} {size_um}))")
        lines.append("      (attach off)")
        lines.append("    )")


# ---------------------------------------------------------------------------
# Net classes (R-2, Task 2b)
# ---------------------------------------------------------------------------


def _emit_net_classes(
    lines: list[str],
    board: NativeBoard,
    layers: list[str],
    *,
    wire_width_um: int,
    clearance_um: int,
) -> None:
    """R-2: emit (class ...) blocks for each named net_class + a trailing default class.

    H-2 fix: each named class with via_diameter > 0 emits
    (circuit (use_via "Via[NAME]")) AND references a padstack emitted by
    _emit_per_class_padstacks (same plan).
    """
    layer_str = " ".join(layers)
    nets_in_named_classes: set[str] = set()

    for nc in board.net_classes:
        width_um = int(nc.track_width * _MM_TO_UM) if nc.track_width > 0 else wire_width_um
        cls_clearance_um = int(nc.clearance * _MM_TO_UM) if nc.clearance > 0 else clearance_um
        members_str = " ".join(nc.add_nets) if nc.add_nets else ""
        nets_in_named_classes.update(nc.add_nets)

        via_ref = _VIA_PADSTACK_NAME
        if nc.via_diameter > 0:
            via_ref = f"Via[{nc.name}]"

        lines.append(f'    (class "{nc.name}" {members_str}')
        lines.append("      (circuit")
        lines.append(f"        (use_layer {layer_str})")
        lines.append(f'        (use_via "{via_ref}")')
        lines.append("      )")
        lines.append("      (rule")
        lines.append(f"        (width {width_um})")
        lines.append(f"        (clearance {cls_clearance_um})")
        lines.append("      )")
        lines.append("    )")

    # Default class: nets not in any named class (backward compat).
    # Rule 1 fix (Phase 99-03): board.nets is often empty on boards whose
    # top-level (net ...) declarations aren't populated by NativeParser.
    # _extract_nets_from_board is the authoritative source (it walks
    # footprint->pad->net_name). Without this, default_members is empty and
    # Freerouting sees a network with no nets to route.
    routed_nets = set(_extract_nets_from_board(board).keys())
    all_nets = {n.name for n in board.nets if n.name} | routed_nets
    default_members = all_nets - nets_in_named_classes
    members_str = " ".join(sorted(default_members))
    # Rule 1 fix (Phase 99-03): the previous code emitted the class header
    # TWICE when members_str was empty (once unconditionally on the line
    # below, once inside the `if not members_str` block). Freerouting then
    # saw a nested (class default "" (class default "" ...)) and aborted
    # with "Parse error". Emit exactly one header line.
    if members_str:
        lines.append(f'    (class default "" {members_str}')
    else:
        lines.append('    (class default "")')
    lines.append("      (circuit")
    lines.append(f"        (use_layer {layer_str})")
    lines.append(f'        (use_via "{_VIA_PADSTACK_NAME}")')
    lines.append("      )")
    lines.append("      (rule")
    lines.append(f"        (width {wire_width_um})")
    lines.append(f"        (clearance {clearance_um})")
    lines.append("      )")
    lines.append("    )")


# ---------------------------------------------------------------------------
# Net extraction (NativeBoard-backed)
# ---------------------------------------------------------------------------


def _extract_nets_from_board(board: NativeBoard) -> dict[str, list[str]]:
    """Extract net connectivity as {net_name: [ref-pad, ...]} from NativeBoard.

    Iterates footprints -> pads -> net_name. Deduplicates pin references.
    """
    nets: dict[str, set[str]] = {}
    for fp in board.footprints:
        ref = fp.properties.get("Reference", "")
        if not ref:
            continue
        for pad in fp.pads:
            if pad.net_name:
                pin_ref = f"{ref}-{pad.number}"
                nets.setdefault(pad.net_name, set()).add(pin_ref)
    return {name: sorted(pins) for name, pins in nets.items()}


# ---------------------------------------------------------------------------
# Board outline (M-3 fix: deferred regex -> NativeBoard.outline migration)
# ---------------------------------------------------------------------------


def _extract_board_outline(pcb_content: str) -> list[float] | None:
    """Extract board outline as [x1, y1, x2, y2] from Edge.Cuts.

    M-3 fix: kept as regex for now. Migration to NativeBoard.outline is tracked
    by a deferred Bead (see 99-01-SUMMARY.md). The hybrid state is intentional:
    footprint/net/zone data comes from NativeBoard, board boundary from regex.
    """
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
    footprints: list[NativeFootprint],
    margin_mm: float = 5.0,
) -> list[float]:
    """Compute board boundary from footprint positions."""
    if not footprints:
        return [0.0, 0.0, 100.0, 100.0]
    xs = [fp.position[0] for fp in footprints]
    ys = [fp.position[1] for fp in footprints]
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
