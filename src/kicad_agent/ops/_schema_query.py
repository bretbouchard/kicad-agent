"""Query operation schemas -- connectivity and analysis queries.

Read-only operations that inspect PCB/schematic state without mutation.
Query handlers use a separate dispatch path (_QUERY_HANDLERS) that
bypasses Transaction wrapping and file serialization.

Security (threat model):
- T-26-01: Read-only queries cannot mutate IR or write files.
- T-26-02: Source/target PadRef fields validated with min/max length.

Usage:
    from kicad_agent.ops._schema_query import QueryConnectivityOp

    op = QueryConnectivityOp(
        target_file="board.kicad_pcb",
        query_type="net_stats",
    )
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from kicad_agent.ops.schema import TargetFile


class QueryConnectivityOp(BaseModel):
    """Query PCB connectivity via NetGraph.

    Read-only operation -- no IR mutation, no Transaction, no file write.

    Attributes:
        op_type: Discriminator literal ``"query_connectivity"``.
        target_file: Relative path to the target KiCad PCB file (H-01 validated).
        query_type: Type of connectivity query to execute.
        net_name: Net name for ``connected_pads`` queries (required for that type).
        source: Source pad reference [footprint_ref, pad_number] for path queries.
        target: Target pad reference [footprint_ref, pad_number] for path queries.
    """

    op_type: Literal["query_connectivity"] = "query_connectivity"
    target_file: TargetFile
    query_type: Literal[
        "connected_pads",
        "net_stats",
        "are_connected",
        "shortest_path",
        "connected_components",
    ]
    net_name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Net name for connected_pads queries",
    )
    source: Optional[list[str]] = Field(
        default=None,
        min_length=2,
        max_length=2,
        description="Source pad [footprint_ref, pad_number]",
    )
    target: Optional[list[str]] = Field(
        default=None,
        min_length=2,
        max_length=2,
        description="Target pad [footprint_ref, pad_number]",
    )

    @model_validator(mode="after")
    def _validate_query_fields(self) -> "QueryConnectivityOp":
        """Enforce field requirements based on query_type."""
        if self.query_type == "connected_pads" and not self.net_name:
            raise ValueError(
                "net_name is required when query_type is 'connected_pads'"
            )
        if self.query_type in ("are_connected", "shortest_path"):
            if not self.source:
                raise ValueError(
                    f"source is required when query_type is '{self.query_type}'"
                )
            if not self.target:
                raise ValueError(
                    f"target is required when query_type is '{self.query_type}'"
                )
        return self
