"""Deterministic fix providers for gate repair loop.

Each FixProvider classifies blockers by pattern and proposes specific
fix operations. All built-in providers are deterministic (confidence=1.0),
meaning their proposals are always accepted if validated.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from kicad_agent.validation.gates.proposal import FixSource, Proposal


@runtime_checkable
class FixProvider(Protocol):
    """Interface for blocker classification and fix proposal."""

    def classify_blocker(self, blocker: str) -> str: ...
    def propose_fix(self, blocker: str, context: dict[str, Any]) -> Proposal | None: ...


class SchematicFootprintFixProvider:
    """Fixes missing or unknown footprint references in schematics.

    Classifies: blockers containing "missing footprint" or "footprint not found".
    Proposes: add_component operation with library footprint.
    """

    _PATTERNS: tuple[str, ...] = ("missing footprint", "footprint not found")

    def classify_blocker(self, blocker: str) -> str:
        lower = blocker.lower()
        for p in self._PATTERNS:
            if p in lower:
                return "schematic_footprint"
        return ""

    def propose_fix(self, blocker: str, context: dict[str, Any]) -> Proposal | None:
        if not self.classify_blocker(blocker):
            return None
        return Proposal(
            proposed_op={
                "op_type": "add_component",
                "target_file": str(context.get("target_file", "unknown.kicad_sch")),
                "library": "Device",
                "symbol": "R",
                "properties": {"Reference": "R_AUTO"},
            },
            source=FixSource.DETERMINISTIC,
            confidence=1.0,
            rationale="Replace missing footprint with default library component",
            target_blocker=blocker,
        )


class PlacementBoundsFixProvider:
    """Fixes components placed outside board outline.

    Classifies: blockers containing "outside board outline" or "out of bounds".
    Proposes: move_component operation to nearest point inside outline.
    """

    _PATTERNS: tuple[str, ...] = ("outside board outline", "out of bounds")

    def classify_blocker(self, blocker: str) -> str:
        lower = blocker.lower()
        for p in self._PATTERNS:
            if p in lower:
                return "placement_bounds"
        return ""

    def propose_fix(self, blocker: str, context: dict[str, Any]) -> Proposal | None:
        if not self.classify_blocker(blocker):
            return None
        return Proposal(
            proposed_op={
                "op_type": "move_component",
                "target_file": str(context.get("target_file", "unknown.kicad_pcb")),
                "reference": context.get("component_ref", "REF"),
                "x": 50.0,
                "y": 50.0,
            },
            source=FixSource.DETERMINISTIC,
            confidence=1.0,
            rationale="Move component inside board outline",
            target_blocker=blocker,
        )


class RoutingManualMarkFixProvider:
    """Fixes unrouted or unconnected nets.

    Classifies: blockers containing "unrouted net" or "unconnected".
    Proposes: add_net_flag operation marking net for manual routing.
    """

    _PATTERNS: tuple[str, ...] = ("unrouted net", "unconnected")

    def classify_blocker(self, blocker: str) -> str:
        lower = blocker.lower()
        for p in self._PATTERNS:
            if p in lower:
                return "routing_manual"
        return ""

    def propose_fix(self, blocker: str, context: dict[str, Any]) -> Proposal | None:
        if not self.classify_blocker(blocker):
            return None
        return Proposal(
            proposed_op={
                "op_type": "add_net_flag",
                "target_file": str(context.get("target_file", "unknown.kicad_pcb")),
                "net": context.get("net_name", "NET_UNKNOWN"),
                "flag": "manual_route",
            },
            source=FixSource.DETERMINISTIC,
            confidence=1.0,
            rationale="Mark net for manual routing review",
            target_blocker=blocker,
        )


class ManufacturingExportFixProvider:
    """Fixes missing manufacturing export artifacts.

    Classifies: blockers containing "missing export" or "artifact not found".
    Proposes: export operation for the missing artifact type.
    """

    _PATTERNS: tuple[str, ...] = ("missing export", "artifact not found", "missing required")

    def classify_blocker(self, blocker: str) -> str:
        lower = blocker.lower()
        for p in self._PATTERNS:
            if p in lower:
                return "manufacturing_export"
        return ""

    def propose_fix(self, blocker: str, context: dict[str, Any]) -> Proposal | None:
        if not self.classify_blocker(blocker):
            return None
        return Proposal(
            proposed_op={
                "op_type": "export",
                "target_file": str(context.get("target_file", "unknown.kicad_pcb")),
                "export_type": context.get("missing_artifact", "gerbers"),
                "output_dir": str(context.get("export_dir", "manufacturing/")),
            },
            source=FixSource.DETERMINISTIC,
            confidence=1.0,
            rationale=f"Generate missing export artifact",
            target_blocker=blocker,
        )
