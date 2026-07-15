"""Parse KiCad netlist (.net) files into net→pin and pin→net indexes.

KiCad netlist format is S-expression. Key sections:
  (nets
    (net (code N) (name "NET_NAME")
      (node (ref "U1") (pin "5") (pinfunction "SDA") (pintype "bidirectional"))
      ...
    )
    ...
  )

Usage:
    from volta.schematic_routing.netlist_parser import parse_netlist

    net_index, pin_index = parse_netlist("analog-board.net")
    # net_index: {"SDA": [("U1", "5"), ("U2", "3")], ...}
    # pin_index: {("U1", "5"): "SDA", ...}
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


def parse_netlist(filepath: str | Path) -> tuple[dict[str, list[tuple[str, str]]], dict[tuple[str, str], str]]:
    """Parse a KiCad netlist file into forward and reverse net indexes.

    Args:
        filepath: Path to the .net file.

    Returns:
        Tuple of (net_index, pin_index):
        - net_index: {net_name: [(ref, pin_number), ...]}
        - pin_index: {(ref, pin_number): net_name}
    """
    content = Path(filepath).read_text()
    net_index: dict[str, list[tuple[str, str]]] = {}
    pin_index: dict[tuple[str, str], str] = {}

    # Find the (nets ...) section
    nets_start = content.find("(nets")
    if nets_start < 0:
        return net_index, pin_index

    # CAVEAT (R-BUG-003): This regex-based parser assumes the net block starts
    # with "(net (code ...) (name ...))". The regex matches the opening pattern
    # and then counts parens to find the block end. This is fragile -- any
    # net block that doesn't match this exact format (e.g., unquoted values)
    # will be silently skipped. A full S-expression parser would be more robust
    # but would add significant complexity for a read-only parse operation.
    for net_match in re.finditer(r'\(net\s+\(code\s+"?\d+"?\)\s+\(name\s+"([^"]+)"\)', content[nets_start:]):
        net_name = net_match.group(1)
        # R-BUG-003: Verify regex matched at a "(net" boundary, not mid-string
        assert net_match.start() == 0 or content[nets_start + net_match.start() - 1] in ('\n', '\r', '\t', ' '), \
            f"Net regex matched mid-string at offset {net_match.start()}"
        net_block_start = net_match.start() + nets_start

        # Find the end of this net block
        depth = 0
        net_block_end = net_block_start
        for i in range(net_block_start, len(content)):
            if content[i] == '(':
                depth += 1
            elif content[i] == ')':
                depth -= 1
                if depth == 0:
                    net_block_end = i + 1
                    break

        net_block = content[net_block_start:net_block_end]
        nodes = []

        # Parse node entries: (node (ref "U1") (pin "5") ...)
        for node_match in re.finditer(
            r'\(node\s+\(ref\s+"([^"]+)"\)\s+\(pin\s+"([^"]+)"\)', net_block
        ):
            ref = node_match.group(1)
            pin = node_match.group(2)
            nodes.append((ref, pin))
            pin_index[(ref, pin)] = net_name

        net_index[net_name] = nodes

    return net_index, pin_index


def get_nets_for_sheet(
    net_index: dict[str, list[tuple[str, str]]],
    sheet_refs: set[str],
) -> dict[str, list[tuple[str, str]]]:
    """Filter net index to only include pins from components in a given sheet.

    Args:
        net_index: Full net index from parse_netlist.
        sheet_refs: Set of component references present in the sheet.

    Returns:
        Filtered net index with only pins from sheet_refs components.
    """
    filtered: dict[str, list[tuple[str, str]]] = {}
    for net_name, pins in net_index.items():
        sheet_pins = [(ref, pin) for ref, pin in pins if ref in sheet_refs]
        if sheet_pins:
            filtered[net_name] = sheet_pins
    return filtered
