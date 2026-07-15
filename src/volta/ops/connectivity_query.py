"""Connectivity query handler -- wraps NetGraph for read-only PCB queries.

Exposes the NetGraph (analysis/connectivity.py) through the operation executor
as five query types returning structured JSON results.

Read-only: no Transaction, no IR mutation, no file serialization.

Security (threat model):
- T-26-02: Read-only path has NO Transaction, NO serialization, NO file write.
- T-26-03: NetGraph reads from IR without mutation.

Usage:
    from volta.ops.connectivity_query import handle_connectivity_query

    result = handle_connectivity_query(op, pcb_ir, file_path)
"""

from pathlib import Path
from typing import Any

from volta.analysis.connectivity import NetGraph, PadRef
from volta.ir.pcb_ir import PcbIR
from volta.ops._schema_query import QueryConnectivityOp


def handle_connectivity_query(
    op: QueryConnectivityOp, ir: PcbIR, file_path: Path
) -> dict[str, Any]:
    """Execute a connectivity query against the PCB IR.

    Builds a NetGraph from the PcbIR and returns query results as
    JSON-serializable dicts. PadRef tuples are converted to [ref, pad] lists.

    Args:
        op: Validated QueryConnectivityOp.
        ir: PcbIR for the target PCB file.
        file_path: Resolved path to the target PCB file.

    Returns:
        Dict with query results. Structure varies by query_type.
    """
    graph = NetGraph.from_pcb_ir(ir)

    if op.query_type == "net_stats":
        return graph.get_net_stats()

    if op.query_type == "connected_pads":
        pads = graph.get_connected_pads(op.net_name)  # type: ignore[arg-type]
        pads_as_lists: list[list[str]] = [[ref, pad] for ref, pad in pads]
        return {
            "net_name": op.net_name,
            "pads": pads_as_lists,
            "count": len(pads_as_lists),
        }

    if op.query_type == "are_connected":
        source_ref: PadRef = (op.source[0], op.source[1])  # type: ignore[index]
        target_ref: PadRef = (op.target[0], op.target[1])  # type: ignore[index]
        connected = graph.are_connected(source_ref, target_ref)
        return {
            "source": op.source,
            "target": op.target,
            "connected": connected,
        }

    if op.query_type == "shortest_path":
        source_ref = (op.source[0], op.source[1])  # type: ignore[index]
        target_ref = (op.target[0], op.target[1])  # type: ignore[index]
        path = graph.shortest_path(source_ref, target_ref)
        path_as_lists: list[list[str]] = [[ref, pad] for ref, pad in path]
        return {
            "source": op.source,
            "target": op.target,
            "path": path_as_lists,
            "length": len(path_as_lists),
        }

    if op.query_type == "connected_components":
        components = graph.get_connectivity_components()
        components_as_lists: list[list[list[str]]] = [
            sorted([[ref, pad] for ref, pad in comp])
            for comp in components
        ]
        return {
            "components": components_as_lists,
            "count": len(components_as_lists),
        }

    raise ValueError(f"Unknown query_type: {op.query_type!r}")
