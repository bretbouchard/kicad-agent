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
