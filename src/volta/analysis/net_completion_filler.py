"""Net completion filler (GAP-05).

Generates AutoRouteOp dicts for unrouted and incomplete nets. Uses AI to
prioritize routing order and strategy, with deterministic fallback (shortest
gap distance first, auto strategy).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from volta.analysis.gap_analyzer import BoardInfo, GapReport

logger = logging.getLogger(__name__)


class NetCompletionFiller:
    """Generates AutoRouteOp dicts for unrouted and incomplete nets.

    Args:
        target_file: Relative path to the PCB file for operation dicts.
        use_ai: Whether to use the LLM for prioritization.
    """

    def __init__(self, *, target_file: str = "board.kicad_pcb", use_ai: bool = True) -> None:
        self._target_file = target_file
        self._use_ai = use_ai

    def generate_ops(
        self,
        report: GapReport,
        board_info: BoardInfo,
    ) -> list[dict[str, Any]]:
        """Generate AutoRouteOp dicts for unrouted and incomplete nets.

        Args:
            report: GapReport from GapAnalyzer.
            board_info: Board context for layer selection.

        Returns:
            List of AutoRouteOp dicts.
        """
        # Collect net names that need routing
        unrouted_names = [n.net_name for n in report.unrouted_nets]
        incomplete_names = [n.net_name for n in report.incomplete_nets]
        all_gap_names = unrouted_names + incomplete_names

        if not all_gap_names:
            return []

        # Default layers based on board
        default_layers = "F.Cu,B.Cu" if board_info.layer_count >= 2 else "F.Cu"

        if self._use_ai:
            return self._ai_generate(report, all_gap_names, default_layers)
        return self._deterministic_generate(all_gap_names, default_layers)

    def _ai_generate(
        self,
        report: GapReport,
        net_names: list[str],
        default_layers: str,
    ) -> list[dict[str, Any]]:
        """Use LLM to prioritize and generate routing ops."""
        try:
            from volta.llm.local_client import LocalLLMClient
            from volta.llm.text_prompts import (
                NET_COMPLETION_SYSTEM,
                extract_json_from_text,
            )

            client = LocalLLMClient()

            # Build net summary for the prompt
            net_summaries = []
            for net in report.unrouted_nets:
                net_summaries.append(
                    f"- {net.net_name}: {net.pad_count} pins, "
                    f"obstacle_dist={net.nearest_obstacle_distance:.2f}mm"
                )
            for net in report.incomplete_nets:
                net_summaries.append(
                    f"- {net.net_name}: {len(net.unrouted_pins)} unrouted pins, "
                    f"gap={net.gap_distance:.2f}mm"
                )

            user_msg = (
                f"Board has {report.board_info.net_count} nets, "
                f"{report.routing_stats.route_percentage:.1f}% routed.\n\n"
                f"Nets needing routing:\n"
                + "\n".join(net_summaries)
            )

            response = client.chat([
                {"role": "system", "content": NET_COMPLETION_SYSTEM},
                {"role": "user", "content": user_msg},
            ])

            parsed = extract_json_from_text(response)
            if parsed and isinstance(parsed, dict) and "nets" in parsed:
                return self._build_ops_from_plan(parsed["nets"], default_layers)

            logger.warning("AI returned invalid plan, falling back to deterministic")
        except Exception:
            logger.warning("AI prioritization failed, falling back to deterministic")

        return self._deterministic_generate(net_names, default_layers)

    def _deterministic_generate(
        self,
        net_names: list[str],
        default_layers: str,
    ) -> list[dict[str, Any]]:
        """Deterministic fallback: one AutoRouteOp per net with auto strategy."""
        ops: list[dict[str, Any]] = []
        for name in net_names:
            ops.append({
                "op_type": "auto_route",
                "target_file": self._target_file,
                "nets": [name],
                "layers": [default_layers],
            })
        return ops

    def _build_ops_from_plan(
        self,
        plan_nets: list[Any],
        default_layers: str,
    ) -> list[dict[str, Any]]:
        """Build AutoRouteOp dicts from AI routing plan."""
        ops: list[dict[str, Any]] = []
        for entry in plan_nets:
            if not isinstance(entry, dict) or "name" not in entry:
                continue
            ops.append({
                "op_type": "auto_route",
                "target_file": self._target_file,
                "nets": [entry["name"]],
                "strategy": entry.get("strategy", "auto"),
                "layers": entry.get("layers", default_layers).split(","),
            })
        return ops
