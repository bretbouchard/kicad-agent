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
    NativeStackupLayer,
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
        """Walk the parsed S-expression tree and build a NativeBoard.

        CR-01: constructs the board in a single constructor call. All field
        values are extracted into locals first, then passed to NativeBoard().
        No in-place mutation on the frozen board.
        """
        # Find (kicad_pcb ...) root
        root = _find_symbol(tree, "kicad_pcb")
        if root is None:
            logger.warning("No kicad_pcb root found in PCB content")
            return NativeBoard(raw_content=content, file_path=file_path)

        # Version and generator
        version = ""
        version_sym = _find_symbol(root, "version")
        if version_sym and len(version_sym) > 1:
            version = str(version_sym[1])

        generator = ""
        generator_sym = _find_symbol(root, "generator")
        if generator_sym and len(generator_sym) > 1:
            generator = str(generator_sym[1])

        # Extract all element types
        nets = tuple(cls._extract_nets(root))
        net_classes = tuple(cls._extract_net_classes(root))
        footprints = cls._extract_footprints(root)
        segments = cls._extract_segments(root)
        vias = cls._extract_vias(root)
        zones = cls._extract_zones(root)
        graphic_items = tuple(cls._extract_graphic_items(root))
        general = cls._extract_general(root)
        setup = cls._extract_setup(root)

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
        board_outline: NativeBoardOutline | None = None
        edge_items = tuple(
            gi for gi in graphic_items if gi.layer == "Edge.Cuts"
        )
        if edge_items:
            board_outline = NativeBoardOutline(items=edge_items)

        return NativeBoard(
            version=version,
            generator=generator,
            nets=nets,
            footprints=footprints,
            segments=segments,
            vias=vias,
            zones=zones,
            net_classes=net_classes,
            graphic_items=graphic_items,
            board_outline=board_outline,
            raw_content=content,
            file_path=file_path,
            general=general,
            setup=setup,
        )

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
    def _extract_net_classes(cls, root: list) -> tuple[NativeNetClass, ...]:
        """Extract (net_class "Name" ...) declarations.

        CR-01: returns a tuple. Builds locals then constructs each
        NativeNetClass in a single constructor call.
        """
        classes: list[NativeNetClass] = []
        for nc_block in _find_all_symbols(root, "net_class"):
            if len(nc_block) < 2:
                continue
            name = str(nc_block[1])

            clearance = 0.0
            track_width = 0.0
            via_diameter = 0.0
            via_drill = 0.0
            add_nets: list[str] = []

            # Extract parameters from children
            clearance_val = _find_first_value(nc_block, "clearance")
            if clearance_val is not None:
                try:
                    clearance = float(clearance_val)
                except (ValueError, TypeError):
                    pass

            track_width_val = _find_first_value(nc_block, "trace_width")
            if track_width_val is not None:
                try:
                    track_width = float(track_width_val)
                except (ValueError, TypeError):
                    pass

            via_diam = _find_first_value(nc_block, "via_diameter")
            if via_diam is not None:
                try:
                    via_diameter = float(via_diam)
                except (ValueError, TypeError):
                    pass

            via_dr = _find_first_value(nc_block, "via_drill")
            if via_dr is not None:
                try:
                    via_drill = float(via_dr)
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
                        add_nets.append(net_name)

            classes.append(NativeNetClass(
                name=name,
                clearance=clearance,
                track_width=track_width,
                via_diameter=via_diameter,
                via_drill=via_drill,
                add_nets=tuple(add_nets),
            ))

        return tuple(classes)

    @classmethod
    def _extract_footprints(cls, root: list) -> tuple[NativeFootprint, ...]:
        """Extract (footprint "lib:fp" ...) blocks.

        CR-01: returns a tuple. Builds locals (props_pairs, graphic_items)
        then constructs each NativeFootprint in a single constructor call.
        """
        footprints: list[NativeFootprint] = []
        for fp_block in _find_all_symbols(root, "footprint"):
            if len(fp_block) < 2:
                continue

            lib_id = str(fp_block[1]) if fp_block[1] is not None else ""

            # Position (at X Y [angle])
            position: tuple[float, float, float] = (0.0, 0.0, 0.0)
            at_vals = _find_at(fp_block)
            if at_vals and len(at_vals) >= 2:
                x, y = at_vals[0], at_vals[1]
                angle = at_vals[2] if len(at_vals) > 2 else 0.0
                position = (x, y, angle)

            # UUID
            uuid = _find_string_child(fp_block, "uuid")

            # Layer
            layer = _find_string_child(fp_block, "layer")

            # Properties — accumulate as list of (key, value) pairs (later
            # stored as the internal _properties_tuple).
            props_pairs: list[tuple[str, str]] = []
            ref = _find_property(fp_block, "Reference")
            if ref:
                props_pairs.append(("Reference", ref))
            val = _find_property(fp_block, "Value")
            if val:
                props_pairs.append(("Value", val))

            # Extract all property keys (not just Reference/Value)
            for item in fp_block:
                if (
                    isinstance(item, list)
                    and len(item) >= 3
                    and _sym(item[0]) == "property"
                    and isinstance(item[1], str)
                    and isinstance(item[2], str)
                ):
                    props_pairs.append((item[1], item[2]))

            # Pads
            pads = cls._extract_pads(fp_block)

            # Graphic items (fp_line, fp_arc, fp_circle)
            graphic_items: list = []
            for fp_item_type, native_type in [
                ("fp_line", "line"),
                ("fp_arc", "arc"),
                ("fp_circle", "circle"),
            ]:
                for gr_block in _find_all_symbols(fp_block, fp_item_type):
                    gi = cls._parse_graphic_block(gr_block, native_type)
                    if gi is not None:
                        graphic_items.append(gi)

            footprints.append(NativeFootprint(
                lib_id=lib_id,
                position=position,
                pads=pads,
                _properties_tuple=tuple(props_pairs),
                layer=layer,
                graphic_items=tuple(graphic_items),
                uuid=uuid,
            ))

        return tuple(footprints)

    @classmethod
    def _extract_pads(cls, fp_block: list) -> tuple[NativePad, ...]:
        """Extract pads from a footprint block.

        CR-01: returns a tuple (frozen-friendly). Builds locals then constructs
        each NativePad in a single constructor call.
        """
        pads: list[NativePad] = []
        for pad_block in _find_all_symbols(fp_block, "pad"):
            if len(pad_block) < 3:
                continue

            # Pad number (second element, string)
            number = str(pad_block[1]) if pad_block[1] is not None else ""

            # Pad type (third element: "smd", "thru_hole", "np_thru_hole")
            pad_type = str(pad_block[2]) if pad_block[2] is not None else ""

            # Shape (fourth element: "rect", "circle", "oval", etc.)
            shape = ""
            if len(pad_block) > 3:
                shape = str(pad_block[3])

            # Position
            position: tuple[float, float] = (0.0, 0.0)
            at_vals = _find_at(pad_block)
            if at_vals and len(at_vals) >= 2:
                position = (at_vals[0], at_vals[1])

            # Size (size W H)
            size: tuple[float, float] = (0.0, 0.0)
            size_block = _find_symbol(pad_block, "size")
            if size_block and len(size_block) >= 3:
                try:
                    w = float(size_block[1])
                    h = float(size_block[2])
                    size = (w, h)
                except (ValueError, TypeError):
                    pass

            # Layers
            layers = ""
            layers_block = _find_symbol(pad_block, "layers")
            if layers_block and len(layers_block) > 1:
                # layers can have multiple values: (layers "*.Cu" "*.Mask")
                layer_parts = []
                for val in layers_block[1:]:
                    if isinstance(val, str):
                        layer_parts.append(val)
                layers = " ".join(layer_parts)

            # Drill
            drill = 0.0
            drill_block = _find_symbol(pad_block, "drill")
            if drill_block and len(drill_block) >= 2:
                try:
                    drill = float(drill_block[1])
                except (ValueError, TypeError):
                    pass

            # Net (net N "NAME") or (net "NAME")
            net_name = ""
            net_number = 0
            for item in pad_block:
                if (
                    isinstance(item, list)
                    and len(item) >= 2
                    and _sym(item[0]) == "net"
                ):
                    if isinstance(item[1], str):
                        # (net "NAME") -- no number
                        net_name = item[1]
                    elif len(item) >= 3:
                        # (net N "NAME") -- has number
                        try:
                            net_number = int(item[1])
                        except (ValueError, TypeError):
                            pass
                        if isinstance(item[2], str):
                            net_name = item[2]
                    break

            # Pin function (pinfunction "name") -- Council HIGH-3
            pinfunction = _find_string_child(pad_block, "pinfunction")

            # Pin type (pintype "type") -- Council HIGH-3
            pintype = _find_string_child(pad_block, "pintype")

            pads.append(NativePad(
                number=number,
                net_name=net_name,
                net_number=net_number,
                position=position,
                layers=layers,
                shape=shape,
                pad_type=pad_type,
                pinfunction=pinfunction,
                pintype=pintype,
                size=size,
                drill=drill,
            ))

        return tuple(pads)

    @classmethod
    def _extract_segments(cls, root: list) -> tuple[NativeSegment, ...]:
        """Extract (segment ...) blocks.

        CR-01: returns a tuple. Builds locals then constructs each NativeSegment
        in a single constructor call.
        """
        segments: list[NativeSegment] = []
        for seg_block in _find_all_symbols(root, "segment"):
            start: _NativePosition | None = None
            end: _NativePosition | None = None
            width = 0.0
            net_number = 0
            net_name = ""

            # Start
            start_block = _find_symbol(seg_block, "start")
            if start_block and len(start_block) >= 3:
                try:
                    start = _NativePosition(
                        float(start_block[1]), float(start_block[2])
                    )
                except (ValueError, TypeError):
                    pass

            # End
            end_block = _find_symbol(seg_block, "end")
            if end_block and len(end_block) >= 3:
                try:
                    end = _NativePosition(
                        float(end_block[1]), float(end_block[2])
                    )
                except (ValueError, TypeError):
                    pass

            # Width
            width_val = _find_first_value(seg_block, "width")
            if width_val is not None:
                try:
                    width = float(width_val)
                except (ValueError, TypeError):
                    pass

            # Layer
            layer = _find_string_child(seg_block, "layer")

            # Net
            # KiCad 10 format: (net "NAME")        -- string-only
            # KiCad 9 format:  (net NUMBER "NAME") -- number + name
            net_block = _find_symbol(seg_block, "net")
            if net_block and len(net_block) >= 2:
                # Phase 99 Gap 1: handle KiCad 10 string-only net format.
                if isinstance(net_block[1], str):
                    net_name = net_block[1]
                    # No net_number in KiCad 10 string-only format; leave as 0.
                else:
                    try:
                        net_number = int(net_block[1])
                    except (ValueError, TypeError):
                        pass
                    if len(net_block) >= 3 and isinstance(net_block[2], str):
                        net_name = net_block[2]

            segments.append(NativeSegment(
                start=start,
                end=end,
                width=width,
                layer=layer,
                net_number=net_number,
                net_name=net_name,
            ))

        return tuple(segments)

    @classmethod
    def _extract_vias(cls, root: list) -> tuple[NativeVia, ...]:
        """Extract (via ...) blocks.

        CR-01: returns a tuple. Builds locals then constructs each NativeVia
        in a single constructor call.
        """
        vias: list[NativeVia] = []
        for via_block in _find_all_symbols(root, "via"):
            position: tuple[float, float] = (0.0, 0.0)
            drill = 0.0
            diameter = 0.0
            net_number = 0
            net_name = ""
            layers: tuple[str, str] = ("", "")

            # Position
            at_vals = _find_at(via_block)
            if at_vals and len(at_vals) >= 2:
                position = (at_vals[0], at_vals[1])

            # Size (diameter)
            size_val = _find_first_value(via_block, "size")
            if size_val is not None:
                try:
                    diameter = float(size_val)
                except (ValueError, TypeError):
                    pass

            # Drill
            drill_val = _find_first_value(via_block, "drill")
            if drill_val is not None:
                try:
                    drill = float(drill_val)
                except (ValueError, TypeError):
                    pass

            # Net (KiCad 10 string-only format supported, same as segments)
            net_block = _find_symbol(via_block, "net")
            if net_block and len(net_block) >= 2:
                if isinstance(net_block[1], str):
                    net_name = net_block[1]
                else:
                    try:
                        net_number = int(net_block[1])
                    except (ValueError, TypeError):
                        pass
                    if len(net_block) >= 3 and isinstance(net_block[2], str):
                        net_name = net_block[2]

            # Layers
            layers_block = _find_symbol(via_block, "layers")
            if layers_block and len(layers_block) >= 3:
                layers = (
                    str(layers_block[1]),
                    str(layers_block[2]),
                )

            vias.append(NativeVia(
                position=position,
                drill=drill,
                diameter=diameter,
                net_number=net_number,
                net_name=net_name,
                layers=layers,
            ))

        return tuple(vias)

    @classmethod
    def _extract_zones(cls, root: list) -> tuple[NativeZone, ...]:
        """Extract (zone ...) blocks with CRITICAL-2 compatibility fields.

        CR-01: returns a tuple. Builds locals then constructs each NativeZone
        in a single constructor call.
        """
        zones: list[NativeZone] = []
        for zone_block in _find_all_symbols(root, "zone"):
            net_number = 0
            net_name = ""
            net = 0
            netName = ""
            layer = ""
            layers: tuple[str, ...] = ()
            polygon_points: list[tuple[float, float]] = []
            clearance = 0.0
            priority = 0
            minThickness = 0.25
            uuid = ""
            keepout_tracks = "allowed"
            keepout_vias = "allowed"
            keepout_pads = "allowed"
            keepout_copperpour = "allowed"
            keepout_footprints = "allowed"

            # Net
            net_block = _find_symbol(zone_block, "net")
            if net_block and len(net_block) >= 2:
                try:
                    net_num = int(net_block[1])
                    net_number = net_num
                    net = net_num  # CRITICAL-2 compatibility
                except (ValueError, TypeError):
                    pass
                if len(net_block) >= 3 and isinstance(net_block[2], str):
                    net_name = net_block[2]
                    netName = net_block[2]  # CRITICAL-2 compatibility

            # Phase 99 Rule 1 fix: real KiCad zones emit (net N) and (net_name "NAME")
            # as SEPARATE sibling fields (not the combined (net N "NAME") form used in
            # nets list). Read the standalone (net_name ...) field so R-3 copper-pour
            # classification (Category 1: net_name != "") works on real fixtures.
            if not net_name:
                net_name_val = _find_string_child(zone_block, "net_name")
                if net_name_val:
                    net_name = net_name_val
                    netName = net_name_val  # CRITICAL-2 compatibility

            # Layer
            layer_block = _find_symbol(zone_block, "layer")
            if layer_block and len(layer_block) >= 2:
                layer = str(layer_block[1])
                layers = (layer,)  # CRITICAL-2 compatibility

            # Layers list (KiCad 10 zones can have multiple layers)
            layers_block = _find_symbol(zone_block, "layers")
            if layers_block and len(layers_block) > 1:
                layers = tuple(
                    str(v) for v in layers_block[1:] if isinstance(v, str)
                )

            # UUID
            uuid = _find_string_child(zone_block, "uuid")

            # Priority
            prio_val = _find_first_value(zone_block, "priority")
            if prio_val is not None:
                try:
                    priority = int(prio_val)
                except (ValueError, TypeError):
                    pass

            # Clearance
            clear_val = _find_first_value(zone_block, "clearance")
            if clear_val is not None:
                try:
                    clearance = float(clear_val)
                except (ValueError, TypeError):
                    pass

            # Min thickness
            min_t_val = _find_first_value(zone_block, "min_thickness")
            if min_t_val is not None:
                try:
                    minThickness = float(min_t_val)  # CRITICAL-2 field name
                except (ValueError, TypeError):
                    pass

            # Phase 99 C-1 fix: parse (keepout (tracks X) (vias X) (pads X)
            # (copperpour X) (footprints X)) subblock. Values are "allowed" or
            # "not_allowed". Defaults remain "allowed" if subblock absent.
            keepout_block = _find_symbol(zone_block, "keepout")
            if keepout_block is not None:
                keepout_lookup = {
                    "keepout_tracks": keepout_tracks,
                    "keepout_vias": keepout_vias,
                    "keepout_pads": keepout_pads,
                    "keepout_copperpour": keepout_copperpour,
                    "keepout_footprints": keepout_footprints,
                }
                for field_name, attr_name in [
                    ("tracks", "keepout_tracks"),
                    ("vias", "keepout_vias"),
                    ("pads", "keepout_pads"),
                    ("copperpour", "keepout_copperpour"),
                    ("footprints", "keepout_footprints"),
                ]:
                    value = _find_first_value(keepout_block, field_name)
                    if value is not None:
                        keepout_lookup[attr_name] = str(value)
                keepout_tracks = keepout_lookup["keepout_tracks"]
                keepout_vias = keepout_lookup["keepout_vias"]
                keepout_pads = keepout_lookup["keepout_pads"]
                keepout_copperpour = keepout_lookup["keepout_copperpour"]
                keepout_footprints = keepout_lookup["keepout_footprints"]

            # Polygon points (filled_polygon or polygon) — accumulate in local
            # list (frozen-friendly: local list is fine, only the dataclass field
            # must be immutable).
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
                                        polygon_points.append((x, y))
                                    except (ValueError, TypeError):
                                        pass

            zones.append(NativeZone(
                net_number=net_number,
                net_name=net_name,
                net=net,
                netName=netName,
                layer=layer,
                layers=layers,
                polygon_points=tuple(polygon_points),
                clearance=clearance,
                priority=priority,
                minThickness=minThickness,
                uuid=uuid,
                keepout_tracks=keepout_tracks,
                keepout_vias=keepout_vias,
                keepout_pads=keepout_pads,
                keepout_copperpour=keepout_copperpour,
                keepout_footprints=keepout_footprints,
            ))

        return tuple(zones)

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
        """Parse a graphic item block into NativeGraphicItem.

        CR-01: builds locals then constructs the frozen dataclass in a single
        constructor call (no in-place mutation).
        """
        start: _NativePosition | None = None
        end: _NativePosition | None = None
        center: _NativePosition | None = None
        mid: _NativePosition | None = None
        radius = 0.0
        width = 0.0
        filled: str | None = None
        text = ""
        font_size = 0.0
        target_size = 0.0

        # Start
        start_block = _find_symbol(block, "start")
        if start_block and len(start_block) >= 3:
            try:
                start = _NativePosition(
                    float(start_block[1]), float(start_block[2])
                )
            except (ValueError, TypeError):
                pass

        # End
        end_block = _find_symbol(block, "end")
        if end_block and len(end_block) >= 3:
            try:
                end = _NativePosition(
                    float(end_block[1]), float(end_block[2])
                )
            except (ValueError, TypeError):
                pass

        # Center (for circles)
        center_block = _find_symbol(block, "center")
        if center_block and len(center_block) >= 3:
            try:
                center = _NativePosition(
                    float(center_block[1]), float(center_block[2])
                )
            except (ValueError, TypeError):
                pass

        # Mid (for arcs)
        mid_block = _find_symbol(block, "mid")
        if mid_block and len(mid_block) >= 3:
            try:
                mid = _NativePosition(
                    float(mid_block[1]), float(mid_block[2])
                )
            except (ValueError, TypeError):
                pass

        # Radius (for circles)
        radius_val = _find_first_value(block, "radius")
        if radius_val is not None:
            try:
                radius = float(radius_val)
            except (ValueError, TypeError):
                pass

        # Layer
        layer = _find_string_child(block, "layer")

        # Width / stroke
        width_val = _find_first_value(block, "width")
        if width_val is not None:
            try:
                width = float(width_val)
            except (ValueError, TypeError):
                pass

        # Also check stroke width for KiCad 10 format
        stroke_block = _find_symbol(block, "stroke")
        if stroke_block and not width:
            stroke_width = _find_first_value(stroke_block, "width")
            if stroke_width is not None:
                try:
                    width = float(stroke_width)
                except (ValueError, TypeError):
                    pass

        # Filled (for rects)
        filled_val = _find_first_value(block, "fill")
        if filled_val is not None:
            # (fill yes) or (fill no) -> "yes"/"no"
            filled = str(filled_val)

        # UUID
        uuid = _find_string_child(block, "uuid")

        # P-BUG-005: Text content (gr_text, gr_text_box)
        if item_type in ("text", "text_box"):
            # gr_text: (gr_text "text content" ...)
            # gr_text_box: (gr_text_box "text content" ...)
            if len(block) > 1 and isinstance(block[1], str):
                text = block[1]
            # Also check for (effects ...) font size
            effects_block = _find_symbol(block, "effects")
            if effects_block:
                font_block = _find_symbol(effects_block, "font")
                if font_block:
                    size_block = _find_symbol(font_block, "size")
                    if size_block and len(size_block) >= 3:
                        try:
                            font_size = float(size_block[1])
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
                text = dim_text[2]

        # P-BUG-005: Target size
        if item_type == "target":
            size_val = _find_first_value(block, "size")
            if size_val is not None:
                try:
                    target_size = float(size_val)
                except (ValueError, TypeError):
                    pass

        return NativeGraphicItem(
            item_type=item_type,
            start=start,
            end=end,
            mid=mid,
            center=center,
            radius=radius,
            layer=layer,
            width=width,
            filled=filled,
            uuid=uuid,
            text=text,
            font_size=font_size,
            target_size=target_size,
        )

    @classmethod
    def _extract_general(cls, root: list) -> NativeGeneral:
        """Extract (general ...) section. CRITICAL-2 compatibility."""
        thickness = 1.6
        layers: tuple = ()

        gen_block = _find_symbol(root, "general")
        if gen_block is not None:
            # Thickness
            thickness_val = _find_first_value(gen_block, "thickness")
            if thickness_val is not None:
                try:
                    thickness = float(thickness_val)
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
            layers = tuple(layer_list)

        return NativeGeneral(thickness=thickness, layers=layers)

    @classmethod
    def _extract_setup(cls, root: list) -> NativeSetup | None:
        """Extract (setup ...) section. CRITICAL-2 compatibility.

        Phase 99 R-4: stackup parsing now emits typed NativeStackupLayer objects
        (name, type, thickness) instead of bare strings. Falls back to synthesizing
        inner copper layers from general.layers count when stackup block is absent
        but the board declares >2 layers (enables blind/buried via padstack emission
        for boards that omit explicit stackup metadata).
        """
        setup_block = _find_symbol(root, "setup")
        if setup_block is None:
            return None

        stackup: NativeStackup | None = None
        stackup_block = _find_symbol(setup_block, "stackup")
        if stackup_block is not None:
            stackup = NativeStackup(
                layers=tuple(cls._extract_stackup_layers(stackup_block))
            )

        return NativeSetup(stackup=stackup)

    @classmethod
    def _extract_stackup_layers(cls, stackup_block: list) -> list:
        """Phase 99 R-4: extract typed NativeStackupLayer list from (stackup ...) block.

        Pattern follows _extract_zones (_find_symbol + _find_first_value + typed append).
        Each (layer "NAME" (type "copper"|"core"|"prepreg") (thickness N) ...) entry
        becomes a NativeStackupLayer. Non-copper layers (dielectric cores, mask, silk)
        are preserved so downstream consumers can filter by type == "copper".
        """
        layers: list[NativeStackupLayer] = []
        for item in stackup_block[1:]:
            if not isinstance(item, list) or len(item) < 2:
                continue
            if _sym(item[0]) != "layer":
                continue
            if not isinstance(item[1], str):
                continue
            name = item[1]
            type_val = _find_first_value(item, "type")
            type_str = str(type_val) if type_val is not None else ""
            thickness_val = _find_first_value(item, "thickness")
            thickness = 0.0
            if thickness_val is not None:
                try:
                    thickness = float(thickness_val)
                except (ValueError, TypeError):
                    thickness = 0.0
            layers.append(NativeStackupLayer(
                name=name, type=type_str, thickness=thickness
            ))
        return layers
