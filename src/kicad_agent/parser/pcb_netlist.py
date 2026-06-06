"""Standalone PCB netlist extractor via sexpdata (#41).

Extracts pad-to-net mappings from raw .kicad_pcb S-expression text using
sexpdata for parsing. Works without kiutils, making it suitable for
contexts where only raw S-expression content is available.

Council F-06 compliance: Pre-processes short-form net refs before sexpdata
parsing to handle KiCad 10 variations.

Usage:
    from kicad_agent.parser.pcb_netlist import extract_pcb_netlist

    netlist = extract_pcb_netlist(content)
    # {"GND": [(50.0, 30.0), (75.0, 40.0)], "VCC": [(10.0, 20.0)]}
"""

import logging
import re
from typing import Any

import sexpdata

logger = logging.getLogger(__name__)


def extract_pcb_netlist(
    content: str,
) -> dict[str, list[tuple[float, float]]]:
    """Extract pad positions grouped by net name from raw PCB content.

    Args:
        content: Raw .kicad_pcb S-expression text.

    Returns:
        Dict mapping net name to list of (x, y) pad positions.
        Unconnected pads have net_name="".
    """
    preprocessed = _preprocess_nets(content)
    try:
        tree = sexpdata.loads(preprocessed)
    except Exception:
        logger.exception("Failed to parse PCB content with sexpdata")
        return {}

    return _extract_from_tree(tree)


def _preprocess_nets(content: str) -> str:
    """Normalize short-form net refs for sexpdata parsing.

    KiCad 10 uses both forms:
      (pad 1 smd rect (at 10 20) (net 1 "GND"))
      (pad 1 thru_hole circle (at 10 20) (net "GND"))

    sexpdata requires consistent format. This normalizes (net N "name")
    to (net "name") by removing the numeric index.

    Args:
        content: Raw PCB S-expression text.

    Returns:
        Preprocessed content with normalized net references.
    """
    # Match (net N "NAME") and normalize to (net "NAME")
    content = re.sub(
        r'\(net\s+(\d+)\s+"([^"]*?)"\)',
        r'(net "\2")',
        content,
    )
    return content


def _sym(item: Any) -> str:
    """Convert sexpdata Symbol or plain value to string for comparison."""
    if isinstance(item, sexpdata.Symbol):
        return str(item)
    return item


def _extract_from_tree(tree: Any) -> dict[str, list[tuple[float, float]]]:
    """Walk the S-expression tree and extract pad positions by net.

    Args:
        tree: Parsed S-expression tree (list of lists and atoms).

    Returns:
        Dict mapping net name to list of (x, y) positions.
    """
    netlist: dict[str, list[tuple[float, float]]] = {}

    # Find the kicad_pcb root
    root = _find_symbol(tree, "kicad_pcb")
    if root is None:
        return {}

    # Find all footprint blocks
    for fp_block in _find_all_symbols(root, "footprint"):
        fp_ref = _find_property(fp_block, "Reference", default="")
        if not fp_ref:
            continue

        # Find all pads within this footprint
        for pad_block in _find_all_symbols(fp_block, "pad"):
            at_vals = _find_at(pad_block)
            if at_vals is None or len(at_vals) < 2:
                continue

            x, y = float(at_vals[0]), float(at_vals[1])
            net_name = _find_pad_net(pad_block, default="")

            if net_name not in netlist:
                netlist[net_name] = []
            netlist[net_name].append((round(x, 4), round(y, 4)))

    return netlist


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


def _find_at(block: list) -> list | None:
    """Find (at X Y ...) values in a block."""
    for item in block:
        if isinstance(item, list) and len(item) > 0 and _sym(item[0]) == "at":
            try:
                return [float(v) for v in item[1:]]
            except (ValueError, TypeError):
                return None
    return None


def _find_pad_net(pad_block: list, default: str = "") -> str:
    """Find the net name for a pad.

    Handles both normalized and short-form net references.
    """
    for item in pad_block:
        if isinstance(item, list) and len(item) >= 2 and _sym(item[0]) == "net":
            # (net "NAME") — normalized form
            if isinstance(item[1], str):
                return item[1]
            # (net N "NAME") — still present if not preprocessed
            if len(item) >= 3 and isinstance(item[2], str):
                return item[2]
    return default


def _find_property(fp_block: list, prop_name: str, default: str = "") -> str:
    """Find a property value by name in a footprint block."""
    for item in fp_block:
        if isinstance(item, list) and len(item) >= 3 and _sym(item[0]) == "property":
            if isinstance(item[1], str) and item[1] == prop_name:
                return item[2] if isinstance(item[2], str) else default
    return default
