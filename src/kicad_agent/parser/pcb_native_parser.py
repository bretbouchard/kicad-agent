"""Native sexpdata-based PCB parser for KiCad 10+ .kicad_pcb files.

Parses raw .kicad_pcb S-expression content into NativeBoard and typed
dataclasses. Uses sexpdata for parsing with depth pre-scan protection
(Council CRITICAL-1) to prevent RecursionError from deeply nested content.

Usage:
    from kicad_agent.parser.pcb_native_parser import NativeParser

    board = NativeParser.parse_pcb(Path("board.kicad_pcb"))
    board = NativeParser.parse_pcb_content(raw_string)

No kiutils dependency. Only sexpdata and the native types module.
"""

import logging
import sys
import threading
from pathlib import Path
from typing import Any

import sexpdata

from kicad_agent.parser.pcb_native_types import (
    NativeBoard,
    NativeBoardOutline,
    NativeFootprint,
    NativeGeneral,
    NativeGraphicItem,
    NativeNet,
    NativeNetClass,
    NativePad,
    NativeSegment,
    NativeSetup,
    NativeStackup,
    NativeVia,
    NativeZone,
    _NativePosition,
)

logger = logging.getLogger(__name__)

# Size limit from raw_parser.py: 50MB max (T-76-01)
_MAX_SIZE = 50 * 1024 * 1024

# Maximum S-expression nesting depth (CRITICAL-1)
_MAX_SEXP_DEPTH = 200

# PCB elements not yet parsed into typed fields.
# Data is preserved in raw_content but not accessible via NativeBoard attributes.
# Logged as warnings during parsing to inform users what is not structurally available.
_UNSUPPORTED_ELEMENTS: frozenset[str] = frozenset({
    "thermal_relief_pads",
    "keepout_areas",
    "soldermask_expansion",
    "paste_expansion",
    "courtyard",
    "fp_text",
    "3d_model_refs",
    "page_info",
    "title_block",
})

# P-BUG-003: Thread lock for recursion limit manipulation.
# sys.setrecursionlimit() is process-global. Without a lock, concurrent
# parsing threads can restore limits while another thread is still
# recursing with the elevated limit.
_RECURSION_LIMIT_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Tree-walking helpers (reuse pattern from pcb_netlist.py)
# ---------------------------------------------------------------------------


def _sym(item: Any) -> str:
    """Convert sexpdata Symbol or plain value to string for comparison."""
    if isinstance(item, sexpdata.Symbol):
        return str(item)
    return str(item) if item is not None else ""


def _find_symbol(tree: Any, name: str) -> Any | None:
    """Find a symbol by name in the tree (first match)."""
    if isinstance(tree, list):
        if len(tree) > 0 and _sym(tree[0]) == name:
            return tree
        for item in tree:
            result = _find_symbol(item, name)
            if result is not None:
                return result
    return None


def _find_all_symbols(tree: Any, name: str) -> list[Any]:
    """Find all symbols with given name in the tree."""
    results: list[Any] = []
    if isinstance(tree, list):
        if len(tree) > 0 and _sym(tree[0]) == name:
            results.append(tree)
        for item in tree:
            results.extend(_find_all_symbols(item, name))
    return results


def _build_symbol_index(tree: Any) -> dict[str, list[Any]]:
    """Build a single-pass index mapping symbol names to all matching subtrees.

    Walks the entire tree once and indexes every list whose first element
    is a symbol name. Lookups are then O(1) instead of O(n) per call.

    This is used to optimize parse_pcb_content where _find_all_symbols was
    called repeatedly for each element type (footprint, segment, via, zone,
    etc.), each call walking the entire tree -- O(types * N) total.
    With the index, building costs O(N) once, then all lookups are O(1).
    """
    index: dict[str, list[Any]] = {}

    def _walk(node: Any) -> None:
        if isinstance(node, list):
            if len(node) > 0 and _sym(node[0]):
                name = _sym(node[0])
                if name not in index:
                    index[name] = []
                index[name].append(node)
            for item in node:
                _walk(item)

    _walk(tree)
    return index


def _find_at(block: list) -> list[float] | None:
    """Find (at X Y ...) values in a block."""
    for item in block:
        if isinstance(item, list) and len(item) > 0 and _sym(item[0]) == "at":
            try:
                return [float(v) for v in item[1:]]
            except (ValueError, TypeError):
                return None
    return None


def _find_first_value(block: list, name: str, default: Any = None) -> Any:
    """Find the first value child with given symbol name.

    For (width 0.25) within block, returns 0.25.
    """
    for item in block:
        if isinstance(item, list) and len(item) >= 2 and _sym(item[0]) == name:
            return item[1]
    return default


def _find_string_child(block: list, name: str, default: str = "") -> str:
    """Find a string-valued child: (name "value") -> "value"."""
    for item in block:
        if isinstance(item, list) and len(item) >= 2 and _sym(item[0]) == name:
            val = item[1]
            if isinstance(val, str):
                return val
    return default


def _find_property(fp_block: list, prop_name: str, default: str = "") -> str:
    """Find a property value by name in a footprint block."""
    for item in fp_block:
        if isinstance(item, list) and len(item) >= 3 and _sym(item[0]) == "property":
            if isinstance(item[1], str) and item[1] == prop_name:
                return item[2] if isinstance(item[2], str) else default
    return default


# ---------------------------------------------------------------------------
# Unsupported element warning
# ---------------------------------------------------------------------------


def _check_unsupported(block_name: str, element_context: str = "") -> None:
    """Log a warning if block_name is an unsupported PCB element.

    Args:
        block_name: Name of the S-expression block being processed.
        element_context: Additional context (e.g., parent element name).
    """
    if block_name in _UNSUPPORTED_ELEMENTS:
        logger.warning(
            "Unsupported element '%s' encountered%s. "
            "Data preserved in raw_content but not available via NativeBoard attributes. "
            "See pcb_native_parser._UNSUPPORTED_ELEMENTS for full list of unsupported elements.",
            block_name,
            f" in {element_context}" if element_context else "",
        )


# ---------------------------------------------------------------------------
# Depth pre-scan (Council CRITICAL-1)
# ---------------------------------------------------------------------------


def _pre_scan_depth(content: str, max_depth: int = _MAX_SEXP_DEPTH) -> int:
    """Count maximum parenthesis nesting depth in O(n) without parsing.

    CRITICAL-1: Prevents RecursionError from sexpdata.loads() on deeply
    nested content. CPython's RecursionError is unsafe to catch -- it can
    leave the interpreter in an inconsistent state. This O(n) scan rejects
    malicious content BEFORE sexpdata touches it.

    Args:
        content: Raw S-expression text.
        max_depth: Maximum allowed nesting depth.

    Returns:
        Maximum nesting depth found.

    Raises:
        ValueError: If nesting depth exceeds max_depth.
    """
    depth = 0
    max_found = 0
    in_string = False
    escape_next = False

    for char in content:
        if escape_next:
            escape_next = False
            continue
        if char == "\\":
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "(":
            depth += 1
            if depth > max_found:
                max_found = depth
            if depth > max_depth:
                raise ValueError(
                    f"S-expression nesting depth {depth} exceeds maximum "
                    f"allowed depth of {max_depth}. Content may be malformed "
                    "or maliciously nested."
                )
        elif char == ")":
            if depth > 0:
                depth -= 1

    return max_found


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class NativeParser:
    """Native sexpdata-based PCB parser.

    Parses .kicad_pcb files into NativeBoard with typed element access.
    No kiutils dependency -- uses sexpdata for S-expression parsing with
    depth pre-scan protection (Council CRITICAL-1).
    """

    @classmethod
    def parse_pcb(cls, path: Path) -> NativeBoard:
        """Parse a .kicad_pcb file into a NativeBoard.

        Args:
            path: Path to the .kicad_pcb file.

        Returns:
            NativeBoard with all extracted elements.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If content exceeds 50MB size limit or depth pre-scan fails.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"PCB file not found: {path}")

        content = path.read_text(encoding="utf-8", errors="replace")
        return cls.parse_pcb_content(content, file_path=str(path))

    @classmethod
    def parse_pcb_content(cls, content: str, file_path: str = "") -> NativeBoard:
        """Parse raw .kicad_pcb S-expression content into a NativeBoard.

        Args:
            content: Raw .kicad_pcb S-expression text.
            file_path: Optional file path for error messages.

        Returns:
            NativeBoard with all extracted elements. Returns empty NativeBoard
            on parse failure (logs warning, does not raise).
        """
        # Size limit check (T-76-01)
        if len(content) > _MAX_SIZE:
            logger.warning(
                "PCB content exceeds 50MB limit (%d bytes), skipping parse",
                len(content),
            )
            return NativeBoard(raw_content=content, file_path=file_path)

        # Empty content
        if not content or not content.strip():
            return NativeBoard(raw_content=content, file_path=file_path)

        # CRITICAL-1: Depth pre-scan BEFORE sexpdata.loads()
        try:
            _pre_scan_depth(content)
        except ValueError as e:
            logger.warning("Depth pre-scan rejected PCB content: %s", e)
            return NativeBoard(raw_content=content, file_path=file_path)

        # Parse with defense-in-depth recursion limit.
        # P-BUG-003: Use thread lock to prevent concurrent parsing from
        # restoring the recursion limit while another thread is still
        # recursing with the elevated limit.
        tree: Any = None
        with _RECURSION_LIMIT_LOCK:
            old_limit = sys.getrecursionlimit()
            try:
                sys.setrecursionlimit(max(old_limit, _MAX_SEXP_DEPTH * 3))
                tree = sexpdata.loads(content)
            except Exception:
                logger.exception(
                    "Failed to parse PCB content with sexpdata (file: %s)",
                    file_path or "<string>",
                )
                return NativeBoard(raw_content=content, file_path=file_path)
            finally:
                sys.setrecursionlimit(old_limit)

        return cls._build_board(tree, content, file_path)

    @classmethod
    def _build_board(
        cls, tree: Any, content: str, file_path: str
    ) -> NativeBoard:
        """Walk the parsed S-expression tree and build a NativeBoard."""
        # Find (kicad_pcb ...) root
        root = _find_symbol(tree, "kicad_pcb")
        if root is None:
            logger.warning("No kicad_pcb root found in PCB content")
            return NativeBoard(raw_content=content, file_path=file_path)

        board = NativeBoard(raw_content=content, file_path=file_path)

        # Version and generator
        version_sym = _find_symbol(root, "version")
        if version_sym and len(version_sym) > 1:
            board.version = str(version_sym[1])

        generator_sym = _find_symbol(root, "generator")
        if generator_sym and len(generator_sym) > 1:
            board.generator = str(generator_sym[1])

        # Extract all element types
        board.nets = cls._extract_nets(root)
        board.net_classes = cls._extract_net_classes(root)
        board.footprints = cls._extract_footprints(root)
        board.segments = cls._extract_segments(root)
        board.vias = cls._extract_vias(root)
        board.zones = cls._extract_zones(root)
        board.graphic_items = cls._extract_graphic_items(root)
        board.general = cls._extract_general(root)
        board.setup = cls._extract_setup(root)

        # Warn about unsupported top-level elements.
        _KNOWN_TOP_LEVEL = {
            "version", "generator", "general", "layers", "setup",
            "net", "net_class", "footprint", "segment", "via",
            "zone", "gr_line", "gr_arc", "gr_circle", "gr_rect",
            "gr_poly", "gr_curve", "kicad_pcb",
        }
        for item in root:
            if isinstance(item, list) and len(item) > 0:
                block_name = _sym(item[0])
                if block_name and block_name not in _KNOWN_TOP_LEVEL:
                    _check_unsupported(block_name)

        # Build board outline from Edge.Cuts graphic items
        edge_items = [gi for gi in board.graphic_items if gi.layer == "Edge.Cuts"]
        if edge_items:
            board.board_outline = NativeBoardOutline(items=edge_items)

        return board

    # -----------------------------------------------------------------------
    # Element extractors
    # -----------------------------------------------------------------------

    @classmethod
    def _extract_nets(cls, root: list) -> list[NativeNet]:
        """Extract top-level (net N "NAME") declarations.

        Per D-08: Parse BEFORE normalization to preserve net numbers.
        Raw sexpdata tree has (net N "NAME") as [Symbol("net"), N, "NAME"].

        P-BUG-004: Only scans root's direct children to avoid O(n) waste
        from _find_all_symbols traversing the entire tree (including nested
        net declarations inside footprints/zones that we skip anyway).
        """
        nets: list[NativeNet] = []

        # Only extract top-level net declarations (direct children of root)
        for item in root:
            if (
                isinstance(item, list)
                and len(item) >= 3
                and _sym(item[0]) == "net"
            ):
                number = 0
                name = ""
                # (net N "NAME") -- N is int, NAME is string
                try:
                    number = int(item[1])
                except (ValueError, TypeError):
                    pass
                if len(item) >= 3 and isinstance(item[2], str):
                    name = item[2]
                nets.append(NativeNet(number=number, name=name))

        return nets

    @classmethod
    def _extract_net_classes(cls, root: list) -> list[NativeNetClass]:
        """Extract (net_class "Name" ...) declarations."""
        classes: list[NativeNetClass] = []
        for nc_block in _find_all_symbols(root, "net_class"):
            if len(nc_block) < 2:
                continue
            nc = NativeNetClass(name=str(nc_block[1]))

            # Extract parameters from children
            clearance = _find_first_value(nc_block, "clearance")
            if clearance is not None:
                try:
                    nc.clearance = float(clearance)
                except (ValueError, TypeError):
                    pass

            track_width = _find_first_value(nc_block, "trace_width")
            if track_width is not None:
                try:
                    nc.track_width = float(track_width)
                except (ValueError, TypeError):
                    pass

            via_diam = _find_first_value(nc_block, "via_diameter")
            if via_diam is not None:
                try:
                    nc.via_diameter = float(via_diam)
                except (ValueError, TypeError):
                    pass

            via_dr = _find_first_value(nc_block, "via_drill")
            if via_dr is not None:
                try:
                    nc.via_drill = float(via_dr)
                except (ValueError, TypeError):
                    pass

            # Extract (add_net "name") children
            for item in nc_block:
                if (
                    isinstance(item, list)
                    and len(item) >= 2
                    and _sym(item[0]) == "add_net"
                ):
                    net_name = item[1]
                    if isinstance(net_name, str):
                        nc.add_nets.append(net_name)

            classes.append(nc)

        return classes

    @classmethod
    def _extract_footprints(cls, root: list) -> list[NativeFootprint]:
        """Extract (footprint "lib:fp" ...) blocks."""
        footprints: list[NativeFootprint] = []
        for fp_block in _find_all_symbols(root, "footprint"):
            if len(fp_block) < 2:
                continue

            fp = NativeFootprint()
            fp.lib_id = str(fp_block[1]) if fp_block[1] is not None else ""

            # Position (at X Y [angle])
            at_vals = _find_at(fp_block)
            if at_vals and len(at_vals) >= 2:
                x, y = at_vals[0], at_vals[1]
                angle = at_vals[2] if len(at_vals) > 2 else 0.0
                fp.position = (x, y, angle)

            # UUID
            fp.uuid = _find_string_child(fp_block, "uuid")

            # Layer
            fp.layer = _find_string_child(fp_block, "layer")

            # Properties
            ref = _find_property(fp_block, "Reference")
            if ref:
                fp.properties["Reference"] = ref
            val = _find_property(fp_block, "Value")
            if val:
                fp.properties["Value"] = val

            # Extract all property keys (not just Reference/Value)
            for item in fp_block:
                if (
                    isinstance(item, list)
                    and len(item) >= 3
                    and _sym(item[0]) == "property"
                    and isinstance(item[1], str)
                    and isinstance(item[2], str)
                ):
                    fp.properties[item[1]] = item[2]

            # Pads
            fp.pads = cls._extract_pads(fp_block)

            # Graphic items (fp_line, fp_arc, fp_circle)
            for fp_item_type, native_type in [
                ("fp_line", "line"),
                ("fp_arc", "arc"),
                ("fp_circle", "circle"),
            ]:
                for gr_block in _find_all_symbols(fp_block, fp_item_type):
                    gi = cls._parse_graphic_block(gr_block, native_type)
                    if gi is not None:
                        fp.graphic_items.append(gi)

            footprints.append(fp)

        return footprints

    @classmethod
    def _extract_pads(cls, fp_block: list) -> list[NativePad]:
        """Extract pads from a footprint block."""
        pads: list[NativePad] = []
        for pad_block in _find_all_symbols(fp_block, "pad"):
            if len(pad_block) < 3:
                continue

            pad = NativePad()

            # Pad number (second element, string)
            pad.number = str(pad_block[1]) if pad_block[1] is not None else ""

            # Pad type (third element: "smd", "thru_hole", "np_thru_hole")
            pad.pad_type = str(pad_block[2]) if pad_block[2] is not None else ""

            # Shape (fourth element: "rect", "circle", "oval", etc.)
            if len(pad_block) > 3:
                pad.shape = str(pad_block[3])

            # Position
            at_vals = _find_at(pad_block)
            if at_vals and len(at_vals) >= 2:
                pad.position = (at_vals[0], at_vals[1])

            # Size (size W H)
            size_block = _find_symbol(pad_block, "size")
            if size_block and len(size_block) >= 3:
                try:
                    w = float(size_block[1])
                    h = float(size_block[2])
                    pad.size = (w, h)
                except (ValueError, TypeError):
                    pass

            # Layers
            layers_block = _find_symbol(pad_block, "layers")
            if layers_block and len(layers_block) > 1:
                # layers can have multiple values: (layers "*.Cu" "*.Mask")
                layer_parts = []
                for val in layers_block[1:]:
                    if isinstance(val, str):
                        layer_parts.append(val)
                pad.layers = " ".join(layer_parts)

            # Drill
            drill_block = _find_symbol(pad_block, "drill")
            if drill_block and len(drill_block) >= 2:
                try:
                    pad.drill = float(drill_block[1])
                except (ValueError, TypeError):
                    pass

            # Net (net N "NAME") or (net "NAME")
            for item in pad_block:
                if (
                    isinstance(item, list)
                    and len(item) >= 2
                    and _sym(item[0]) == "net"
                ):
                    if isinstance(item[1], str):
                        # (net "NAME") -- no number
                        pad.net_name = item[1]
                    elif len(item) >= 3:
                        # (net N "NAME") -- has number
                        try:
                            pad.net_number = int(item[1])
                        except (ValueError, TypeError):
                            pass
                        if isinstance(item[2], str):
                            pad.net_name = item[2]
                    break

            # Pin function (pinfunction "name") -- Council HIGH-3
            pad.pinfunction = _find_string_child(pad_block, "pinfunction")

            # Pin type (pintype "type") -- Council HIGH-3
            pad.pintype = _find_string_child(pad_block, "pintype")

            pads.append(pad)

        return pads

    @classmethod
    def _extract_segments(cls, root: list) -> list[NativeSegment]:
        """Extract (segment ...) blocks."""
        segments: list[NativeSegment] = []
        for seg_block in _find_all_symbols(root, "segment"):
            seg = NativeSegment()

            # Start
            start_block = _find_symbol(seg_block, "start")
            if start_block and len(start_block) >= 3:
                try:
                    seg.start = _NativePosition(
                        float(start_block[1]), float(start_block[2])
                    )
                except (ValueError, TypeError):
                    pass

            # End
            end_block = _find_symbol(seg_block, "end")
            if end_block and len(end_block) >= 3:
                try:
                    seg.end = _NativePosition(
                        float(end_block[1]), float(end_block[2])
                    )
                except (ValueError, TypeError):
                    pass

            # Width
            width_val = _find_first_value(seg_block, "width")
            if width_val is not None:
                try:
                    seg.width = float(width_val)
                except (ValueError, TypeError):
                    pass

            # Layer
            seg.layer = _find_string_child(seg_block, "layer")

            # Net
            # KiCad 10 format: (net "NAME")        -- string-only
            # KiCad 9 format:  (net NUMBER "NAME") -- number + name
            net_block = _find_symbol(seg_block, "net")
            if net_block and len(net_block) >= 2:
                # Phase 99 Gap 1: handle KiCad 10 string-only net format.
                if isinstance(net_block[1], str):
                    seg.net_name = net_block[1]
                    # No net_number in KiCad 10 string-only format; leave as 0.
                else:
                    try:
                        seg.net_number = int(net_block[1])
                    except (ValueError, TypeError):
                        pass
                    if len(net_block) >= 3 and isinstance(net_block[2], str):
                        seg.net_name = net_block[2]

            segments.append(seg)

        return segments

    @classmethod
    def _extract_vias(cls, root: list) -> list[NativeVia]:
        """Extract (via ...) blocks."""
        vias: list[NativeVia] = []
        for via_block in _find_all_symbols(root, "via"):
            via = NativeVia()

            # Position
            at_vals = _find_at(via_block)
            if at_vals and len(at_vals) >= 2:
                via.position = (at_vals[0], at_vals[1])

            # Size (diameter)
            size_val = _find_first_value(via_block, "size")
            if size_val is not None:
                try:
                    via.diameter = float(size_val)
                except (ValueError, TypeError):
                    pass

            # Drill
            drill_val = _find_first_value(via_block, "drill")
            if drill_val is not None:
                try:
                    via.drill = float(drill_val)
                except (ValueError, TypeError):
                    pass

            # Net (KiCad 10 string-only format supported, same as segments)
            net_block = _find_symbol(via_block, "net")
            if net_block and len(net_block) >= 2:
                if isinstance(net_block[1], str):
                    via.net_name = net_block[1]
                else:
                    try:
                        via.net_number = int(net_block[1])
                    except (ValueError, TypeError):
                        pass
                    if len(net_block) >= 3 and isinstance(net_block[2], str):
                        via.net_name = net_block[2]

            # Layers
            layers_block = _find_symbol(via_block, "layers")
            if layers_block and len(layers_block) >= 3:
                via.layers = (
                    str(layers_block[1]),
                    str(layers_block[2]),
                )

            vias.append(via)

        return vias

    @classmethod
    def _extract_zones(cls, root: list) -> list[NativeZone]:
        """Extract (zone ...) blocks with CRITICAL-2 compatibility fields."""
        zones: list[NativeZone] = []
        for zone_block in _find_all_symbols(root, "zone"):
            zone = NativeZone()

            # Net
            net_block = _find_symbol(zone_block, "net")
            if net_block and len(net_block) >= 2:
                try:
                    net_num = int(net_block[1])
                    zone.net_number = net_num
                    zone.net = net_num  # CRITICAL-2 compatibility
                except (ValueError, TypeError):
                    pass
                if len(net_block) >= 3 and isinstance(net_block[2], str):
                    zone.net_name = net_block[2]
                    zone.netName = net_block[2]  # CRITICAL-2 compatibility

            # Layer
            layer_block = _find_symbol(zone_block, "layer")
            if layer_block and len(layer_block) >= 2:
                zone.layer = str(layer_block[1])
                zone.layers = [zone.layer]  # CRITICAL-2 compatibility

            # Layers list (KiCad 10 zones can have multiple layers)
            layers_block = _find_symbol(zone_block, "layers")
            if layers_block and len(layers_block) > 1:
                zone.layers = [str(v) for v in layers_block[1:] if isinstance(v, str)]

            # UUID
            zone.uuid = _find_string_child(zone_block, "uuid")

            # Priority
            prio_val = _find_first_value(zone_block, "priority")
            if prio_val is not None:
                try:
                    zone.priority = int(prio_val)
                except (ValueError, TypeError):
                    pass

            # Clearance
            clear_val = _find_first_value(zone_block, "clearance")
            if clear_val is not None:
                try:
                    zone.clearance = float(clear_val)
                except (ValueError, TypeError):
                    pass

            # Min thickness
            min_t_val = _find_first_value(zone_block, "min_thickness")
            if min_t_val is not None:
                try:
                    zone.minThickness = float(min_t_val)  # CRITICAL-2 field name
                except (ValueError, TypeError):
                    pass

            # Polygon points (filled_polygon or polygon)
            for poly_name in ("filled_polygon", "polygon"):
                poly_block = _find_symbol(zone_block, poly_name)
                if poly_block:
                    for pts_item in poly_block[1:]:
                        if isinstance(pts_item, list) and _sym(pts_item[0]) == "pts":
                            for pt_item in pts_item[1:]:
                                if (
                                    isinstance(pt_item, list)
                                    and _sym(pt_item[0]) == "xy"
                                    and len(pt_item) >= 3
                                ):
                                    try:
                                        x = float(pt_item[1])
                                        y = float(pt_item[2])
                                        zone.polygon_points.append((x, y))
                                    except (ValueError, TypeError):
                                        pass

            zones.append(zone)

        return zones

    @classmethod
    def _extract_graphic_items(cls, root: list) -> list[NativeGraphicItem]:
        """Extract board-level graphic items: gr_line, gr_arc, gr_circle, gr_rect, gr_poly, gr_curve,
        gr_text, gr_text_box, dimension, target.

        Council HIGH-2: supports 6 geometric types.
        P-BUG-005: adds 4 annotation types.
        """
        items: list[NativeGraphicItem] = []

        type_map = {
            "gr_line": "line",
            "gr_arc": "arc",
            "gr_circle": "circle",
            "gr_rect": "rect",
            "gr_poly": "poly",
            "gr_curve": "curve",
            "gr_text": "text",
            "gr_text_box": "text_box",
            "dimension": "dimension",
            "target": "target",
        }

        for sexp_name, item_type in type_map.items():
            for block in _find_all_symbols(root, sexp_name):
                gi = cls._parse_graphic_block(block, item_type)
                if gi is not None:
                    items.append(gi)

        return items

    @classmethod
    def _parse_graphic_block(
        cls, block: list, item_type: str
    ) -> NativeGraphicItem | None:
        """Parse a graphic item block into NativeGraphicItem."""
        gi = NativeGraphicItem(item_type=item_type)

        # Start
        start_block = _find_symbol(block, "start")
        if start_block and len(start_block) >= 3:
            try:
                gi.start = _NativePosition(
                    float(start_block[1]), float(start_block[2])
                )
            except (ValueError, TypeError):
                pass

        # End
        end_block = _find_symbol(block, "end")
        if end_block and len(end_block) >= 3:
            try:
                gi.end = _NativePosition(
                    float(end_block[1]), float(end_block[2])
                )
            except (ValueError, TypeError):
                pass

        # Center (for circles)
        center_block = _find_symbol(block, "center")
        if center_block and len(center_block) >= 3:
            try:
                gi.center = _NativePosition(
                    float(center_block[1]), float(center_block[2])
                )
            except (ValueError, TypeError):
                pass

        # Mid (for arcs)
        mid_block = _find_symbol(block, "mid")
        if mid_block and len(mid_block) >= 3:
            try:
                gi.mid = _NativePosition(
                    float(mid_block[1]), float(mid_block[2])
                )
            except (ValueError, TypeError):
                pass

        # Radius (for circles)
        radius_val = _find_first_value(block, "radius")
        if radius_val is not None:
            try:
                gi.radius = float(radius_val)
            except (ValueError, TypeError):
                pass

        # Layer
        gi.layer = _find_string_child(block, "layer")

        # Width / stroke
        width_val = _find_first_value(block, "width")
        if width_val is not None:
            try:
                gi.width = float(width_val)
            except (ValueError, TypeError):
                pass

        # Also check stroke width for KiCad 10 format
        stroke_block = _find_symbol(block, "stroke")
        if stroke_block and not gi.width:
            stroke_width = _find_first_value(stroke_block, "width")
            if stroke_width is not None:
                try:
                    gi.width = float(stroke_width)
                except (ValueError, TypeError):
                    pass

        # Filled (for rects)
        filled_val = _find_first_value(block, "fill")
        if filled_val is not None:
            # (fill yes) or (fill no) -> "yes"/"no"
            gi.filled = str(filled_val)

        # UUID
        gi.uuid = _find_string_child(block, "uuid")

        # P-BUG-005: Text content (gr_text, gr_text_box)
        if item_type in ("text", "text_box"):
            # gr_text: (gr_text "text content" ...)
            # gr_text_box: (gr_text_box "text content" ...)
            if len(block) > 1 and isinstance(block[1], str):
                gi.text = block[1]
            # Also check for (effects ...) font size
            effects_block = _find_symbol(block, "effects")
            if effects_block:
                font_block = _find_symbol(effects_block, "font")
                if font_block:
                    size_block = _find_symbol(font_block, "size")
                    if size_block and len(size_block) >= 3:
                        try:
                            gi.font_size = float(size_block[1])
                        except (ValueError, TypeError):
                            pass
                # Check rotation in effects
                justify_block = _find_symbol(effects_block, "justify")
                if justify_block:
                    for j in justify_block[1:]:
                        if isinstance(j, str) and "mirror" in j.lower():
                            break

        # P-BUG-005: Dimension text
        if item_type == "dimension":
            dim_text = _find_symbol(block, "property")
            if dim_text and len(dim_text) >= 3 and isinstance(dim_text[2], str):
                gi.text = dim_text[2]

        # P-BUG-005: Target size
        if item_type == "target":
            size_val = _find_first_value(block, "size")
            if size_val is not None:
                try:
                    gi.target_size = float(size_val)
                except (ValueError, TypeError):
                    pass

        return gi

    @classmethod
    def _extract_general(cls, root: list) -> NativeGeneral:
        """Extract (general ...) section. CRITICAL-2 compatibility."""
        general = NativeGeneral()

        gen_block = _find_symbol(root, "general")
        if gen_block is None:
            return general

        # Thickness
        thickness_val = _find_first_value(gen_block, "thickness")
        if thickness_val is not None:
            try:
                general.thickness = float(thickness_val)
            except (ValueError, TypeError):
                pass

        # Layers (top-level layers, not general's children)
        layers_block = _find_symbol(root, "layers")
        if layers_block and len(layers_block) > 1:
            layer_list = []
            for item in layers_block[1:]:
                if isinstance(item, list) and len(item) >= 2:
                    layer_list.append(str(item[1]))
                elif isinstance(item, str):
                    layer_list.append(item)
            general.layers = layer_list

        return general

    @classmethod
    def _extract_setup(cls, root: list) -> NativeSetup | None:
        """Extract (setup ...) section. CRITICAL-2 compatibility."""
        setup_block = _find_symbol(root, "setup")
        if setup_block is None:
            return None

        setup = NativeSetup()

        # Stackup (placeholder -- full parsing deferred to future phase)
        stackup_block = _find_symbol(setup_block, "stackup")
        if stackup_block is not None:
            stackup = NativeStackup()
            # Extract layer names from stackup for basic compatibility
            layer_list = []
            for item in stackup_block[1:]:
                if isinstance(item, list) and len(item) >= 2 and _sym(item[0]) == "layer":
                    if isinstance(item[1], str):
                        layer_list.append(item[1])
            stackup.layers = layer_list
            setup.stackup = stackup

        return setup
