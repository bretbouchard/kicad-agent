"""Net connectivity graph analysis using networkx.

NET-05: Net connectivity graph analysis via networkx.

Builds an undirected graph where:
- Nodes are pads, represented as (footprint_reference, pad_number) tuples
- Edges connect pads that share the same net (electrical connection)

Supports:
- Path finding between any two pads
- Connectivity component identification (electrical islands)
- Net membership queries
- Connectivity statistics

Usage:
    from kicad_agent.analysis import NetGraph
    from kicad_agent.ir.pcb_ir import PcbIR

    graph = NetGraph.from_pcb_ir(pcb_ir)
    connected = graph.get_connected_pads("GND")
    path = graph.shortest_path(("J1", "1"), ("U1", "5"))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from kicad_agent.ir.pcb_ir import PcbIR


# Type alias for pad node identifiers
PadRef = tuple[str, str]  # (footprint_reference, pad_number)


@dataclass
class NetGraph:
    """Connectivity graph for a PCB built from PcbIR data.

    Nodes are pads (footprint_ref, pad_number). Edges connect pads
    sharing the same net. Net 0 (unconnected) is excluded.
    """

    graph: nx.Graph = field(default_factory=nx.Graph)
    _net_index: dict[str, list[PadRef]] = field(default_factory=dict)

    @classmethod
    def from_pcb_ir(cls, pcb_ir: PcbIR) -> NetGraph:
        """Build a connectivity graph from a PcbIR instance.

        Iterates all footprints and their pads. Pads with a net
        (net.number != 0) are added as nodes and connected by edges
        to all other pads on the same net.

        Args:
            pcb_ir: A PcbIR instance with loaded board data.

        Returns:
            NetGraph with connectivity populated.
        """
        net_graph = cls()
        # Build net -> pads mapping
        net_pads: dict[str, list[PadRef]] = {}
        for fp in pcb_ir.footprints:
            # kiutils stores reference in properties dict, not as attribute
            fp_ref: str = fp.properties.get("Reference", "")
            for pad in fp.pads:
                if pad.net is not None and pad.net.number != 0:
                    pad_ref: PadRef = (fp_ref, pad.number)
                    net_graph.graph.add_node(
                        pad_ref,
                        footprint_libid=fp.libId,
                        net_name=pad.net.name,
                    )
                    net_pads.setdefault(pad.net.name, []).append(pad_ref)

        # Connect all pads sharing the same net with edges
        for net_name, pads in net_pads.items():
            for i in range(len(pads)):
                for j in range(i + 1, len(pads)):
                    net_graph.graph.add_edge(
                        pads[i], pads[j], net_name=net_name
                    )

        net_graph._net_index = net_pads
        return net_graph

    def get_connected_pads(self, net_name: str) -> list[PadRef]:
        """Get all pad nodes connected to the named net.

        Returns:
            List of (footprint_ref, pad_number) tuples. Empty if net not found.
        """
        return list(self._net_index.get(net_name, []))

    def shortest_path(self, source: PadRef, target: PadRef) -> list[PadRef]:
        """Find shortest path between two pads.

        Returns:
            List of pad refs forming the path. Empty list if no path exists.
        """
        try:
            return nx.shortest_path(self.graph, source, target)
        except (nx.NodeNotFound, nx.NetworkXNoPath):
            return []

    def are_connected(self, source: PadRef, target: PadRef) -> bool:
        """Check if two pads are electrically connected (same net)."""
        return self.graph.has_edge(source, target) or source == target

    def get_connectivity_components(self) -> list[set[PadRef]]:
        """Identify isolated connectivity islands.

        Returns:
            List of sets, each containing pad refs that are mutually connected.
        """
        return list(nx.connected_components(self.graph))

    def get_net_stats(self) -> dict[str, int]:
        """Get connectivity statistics.

        Returns:
            Dict with total_nets, total_pads (nodes), total_connections (edges).
        """
        return {
            "total_nets": len(self._net_index),
            "total_pads": self.graph.number_of_nodes(),
            "total_connections": self.graph.number_of_edges(),
        }
