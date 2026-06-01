"""Shared topology utility functions for analysis modules.

Extracted from design_review.py (Phase 47) and reused by
builtin_rules.py (Phase 48) to avoid duplication.

Usage:
    from kicad_agent.analysis.topology_utils import (
        build_net_to_nodes,
        build_node_to_nets,
    )
"""
from __future__ import annotations

from kicad_agent.analysis.topology_graph import CircuitTopology, TopologyNode


def build_net_to_nodes(topology: CircuitTopology) -> dict[str, list[TopologyNode]]:
    """Build a mapping from net name to connected nodes.

    Uses topology edges to determine which nodes share nets.
    """
    net_map: dict[str, list[TopologyNode]] = {}
    node_map = {n.ref: n for n in topology.nodes}

    for edge in topology.edges:
        src_node = node_map.get(edge.source_ref)
        if src_node:
            net_map.setdefault(edge.net_name, [])
            if src_node not in net_map[edge.net_name]:
                net_map[edge.net_name].append(src_node)
        tgt_node = node_map.get(edge.target_ref)
        if tgt_node:
            net_map.setdefault(edge.net_name, [])
            if tgt_node not in net_map[edge.net_name]:
                net_map[edge.net_name].append(tgt_node)

    return net_map


def build_node_to_nets(topology: CircuitTopology) -> dict[str, list[str]]:
    """Build a mapping from node ref to connected net names."""
    node_nets: dict[str, list[str]] = {}
    for edge in topology.edges:
        for ref in (edge.source_ref, edge.target_ref):
            node_nets.setdefault(ref, [])
            if edge.net_name not in node_nets[ref]:
                node_nets[ref].append(edge.net_name)
    return node_nets
