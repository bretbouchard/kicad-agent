"""Phase 98 R-1, R-3: AiRoutingStrategy implementing RoutingStrategy Protocol.

Thin adapter around KiCadVisionPipeline that:
1. Renders the PCB to a PNG (via render_pcb_layer_png)
2. Builds a few-shot JSON prompt (via build_strategy_prompt)
3. Runs vision inference (KiCadVisionPipeline.generate_from_image)
4. Extracts structured JSON (via parse_strategy_json)
5. Translates to RoutingStrategyResult with safe defaults

Implements the Phase 100 RoutingStrategy Protocol via STRUCTURAL SUBTYPING
(duck typing) - NO inheritance. This is deliberate: Protocol enables pluggable
strategies without coupling to a base class.

Per RESEARCH.md Pattern 1: wraps KiCadVisionPipeline without modifying it.
Per Council M-1: RouterBackend(value.lower()) wrapped in try/except.
Per RESEARCH.md T-98-01-02: unknown backends default to ASTAR (lowest privilege).

R-6 fallback (DeterministicStrategy) is NOT wired here - it lives in Plan 98-02
where StrategyValidator wraps this class. This plan raises _AiStrategyError so
Plan 02's wrapper can catch it and trigger fallback.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from kicad_agent.routing.strategy import (
    BoardState,
    Keepout,
    Pin,
    RouterBackend,
    RoutingStrategyResult,
)
from kicad_agent.routing.strategy_parser import parse_strategy_json
from kicad_agent.routing.strategy_prompts import build_strategy_prompt

logger = logging.getLogger(__name__)


class _AiStrategyError(Exception):
    """Internal failure signal for AiRoutingStrategy.

    Raised on render failure, empty model output, or JSON extraction failure.
    Plan 98-02's StrategyValidator wrapper catches this and triggers the R-6
    DeterministicStrategy fallback.
    """


def _default_render(pcb_path: Path) -> Any:
    """Lazy import wrapper for render_pcb_layer_png.

    Imported inside the function so this module loads without PIL/cairosvg.
    """
    from kicad_agent.export.pcb_image_renderer import render_pcb_layer_png

    return render_pcb_layer_png(pcb_path)


class AiRoutingStrategy:
    """AI routing strategy backed by the Gemma 4 12B V2 vision adapter.

    Implements the RoutingStrategy Protocol via structural subtyping. NO
    inheritance - duck-typed by method signature.

    Args:
        pipeline: KiCadVisionPipeline instance (typed Any to avoid hard
            mlx-vlm import at module load time - the pipeline is 23.8 GB).
        pcb_path: Path to the .kicad_pcb file to render for vision input.
        render_fn: Injectable render function for testing. Defaults to
            render_pcb_layer_png via lazy import.
    """

    def __init__(
        self,
        pipeline: Any,
        pcb_path: Path,
        render_fn: Any = None,
    ) -> None:
        self._pipeline = pipeline
        self._pcb_path = pcb_path
        self._render_fn = render_fn if render_fn is not None else _default_render

    def strategize(
        self,
        board_state: BoardState,
        netlist: dict[str, list[Pin]],
    ) -> RoutingStrategyResult:
        """Produce a routing strategy from PCB render + vision inference.

        Flow:
        1. Render PCB to PNG (raises _AiStrategyError on failure)
        2. Build few-shot JSON prompt
        3. Run vision inference (raises _AiStrategyError on empty output)
        4. Extract JSON (raises _AiStrategyError on parse failure)
        5. Translate to RoutingStrategyResult with safe defaults

        Does NOT implement R-6 fallback - that's Plan 98-02's responsibility.
        """
        # 1. Render
        try:
            image = self._render_fn(self._pcb_path)
        except Exception as exc:
            raise _AiStrategyError(f"render failed: {exc}") from exc

        # 2. Prompt
        prompt = build_strategy_prompt(board_state, netlist)

        # 3. Inference
        raw = self._pipeline.generate_from_image(image, prompt)
        if not raw or len(raw.strip()) < 10:
            raise _AiStrategyError("empty or too-short model output")

        # 4. Parse
        parsed = parse_strategy_json(raw)
        if not parsed:
            raise _AiStrategyError("json extraction failed")

        # 5. Translate
        return _translate_to_result(parsed, board_state, netlist)


def _translate_to_result(
    parsed: dict,
    board_state: BoardState,
    netlist: dict[str, list[Pin]],
) -> RoutingStrategyResult:
    """Translate parsed JSON dict into a fully-populated RoutingStrategyResult.

    Applies safe defaults for every field per RESEARCH.md threat T-98-01-02:
    - Unknown backend strings -> RouterBackend.ASTAR (lowest privilege)
    - Missing nets in router_assignment -> RouterBackend.ASTAR
    - Unknown nets (not in netlist) dropped from all fields
    - Malformed keepout entries dropped with a warning
    """
    known_nets = set(netlist.keys())

    # net_priorities: filter to nets present in netlist
    raw_priorities = parsed.get("net_priorities", []) or []
    if not isinstance(raw_priorities, list):
        raw_priorities = []
    net_priorities = tuple(p for p in raw_priorities if p in known_nets)

    # layer_hints: filter to known nets
    raw_layer_hints = parsed.get("layer_hints", {}) or {}
    if not isinstance(raw_layer_hints, dict):
        raw_layer_hints = {}
    layer_hints = {
        net: layer for net, layer in raw_layer_hints.items() if net in known_nets
    }

    # keepouts: parse list of dicts into Keepout dataclasses
    raw_keepouts = parsed.get("keepouts", []) or []
    if not isinstance(raw_keepouts, list):
        raw_keepouts = []
    keepouts = _parse_keepouts(raw_keepouts)

    # router_assignment: build dict with safe defaults
    raw_assignment = parsed.get("router_assignment", {}) or {}
    if not isinstance(raw_assignment, dict):
        raw_assignment = {}
    router_assignment = _build_router_assignment(raw_assignment, known_nets)

    routing_notes = parsed.get("routing_notes", "") or ""
    if not isinstance(routing_notes, str):
        routing_notes = str(routing_notes)

    return RoutingStrategyResult(
        net_priorities=net_priorities,
        layer_hints=layer_hints,
        keepouts=tuple(keepouts),
        router_assignment=router_assignment,
        routing_notes=routing_notes,
    )


def _parse_keepouts(raw_keepouts: list) -> list[Keepout]:
    """Parse list of keepout dicts into Keepout dataclasses.

    Drops entries missing required numeric fields (logs warning).
    """
    keepouts: list[Keepout] = []
    for entry in raw_keepouts:
        if not isinstance(entry, dict):
            continue
        try:
            x1 = float(entry.get("x1"))
            y1 = float(entry.get("y1"))
            x2 = float(entry.get("x2"))
            y2 = float(entry.get("y2"))
        except (TypeError, ValueError):
            logger.warning("dropping malformed keepout (missing coords): %s", entry)
            continue
        layer = str(entry.get("layer", ""))
        reason = str(entry.get("reason", ""))
        keepouts.append(
            Keepout(x1=x1, y1=y1, x2=x2, y2=y2, layer=layer, reason=reason)
        )
    return keepouts


def _build_router_assignment(
    raw_assignment: dict,
    known_nets: set[str],
) -> dict[str, RouterBackend]:
    """Build router_assignment dict with safe defaults.

    - Drops nets not in known_nets (permissive - R-4 validator in Plan 02
      enforces strictness)
    - Unknown backend strings -> RouterBackend.ASTAR (M-1: try/except around
      RouterBackend(value.lower()))
    - Every known net gets an entry (missing -> ASTAR)
    """
    assignment: dict[str, RouterBackend] = {}
    for net in known_nets:
        raw_value = raw_assignment.get(net)
        backend = _coerce_backend(raw_value)
        assignment[net] = backend
    return assignment


def _coerce_backend(raw_value: Any) -> RouterBackend:
    """Coerce a raw backend value into RouterBackend.

    Council M-1 fix: RouterBackend(value.lower()) wrapped in try/except.
    Unknown values -> ASTAR (lowest privilege, no Freerouting dispatch without
    explicit model consent).
    """
    if not isinstance(raw_value, str):
        logger.warning(
            "router_assignment value not a string (%r); defaulting to ASTAR",
            raw_value,
        )
        return RouterBackend.ASTAR
    try:
        return RouterBackend(raw_value.strip().lower())
    except ValueError:
        logger.warning(
            "unknown router backend %r; defaulting to ASTAR", raw_value
        )
        return RouterBackend.ASTAR
