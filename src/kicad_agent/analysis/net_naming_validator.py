"""Net naming validator (GAP-07).

Validates GapAnalyzer naming suggestions via AI classification and produces
RenameNetOp dicts for approved renames.

Deterministic fallback: accepts all suggestions that follow naming conventions
(UPPER_CASE_WITH_UNDERSCORES, non-reserved, non-empty).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kicad_agent.analysis.gap_analyzer import BoardInfo, NetNamingIssue

logger = logging.getLogger(__name__)

_RESERVED_NET_NAMES = frozenset({
    "GND", "VCC", "VDD", "VSS", "+3V3", "+5V", "+12V", "+1V8", "+3V",
    "AGND", "DGND", "PGND", "Earth",
})

_VALID_NET_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


class NetNamingValidator:
    """Validates net naming suggestions and produces RenameNetOp dicts.

    Args:
        target_file: Relative path to the PCB file for operation dicts.
        use_ai: Whether to use the LLM for validation.
    """

    def __init__(self, *, target_file: str = "board.kicad_pcb", use_ai: bool = True) -> None:
        self._target_file = target_file
        self._use_ai = use_ai

    def validate(
        self,
        issues: tuple[NetNamingIssue, ...],
        board_info: BoardInfo,
    ) -> list[dict[str, Any]]:
        """Validate naming suggestions and produce RenameNetOp dicts.

        Args:
            issues: Net naming issues from GapReport.
            board_info: Board context for AI validation.

        Returns:
            List of RenameNetOp dicts for approved renames.
        """
        if not issues:
            return []

        ops: list[dict[str, Any]] = []
        for issue in issues:
            if self._use_ai:
                accepted = self._ai_validate(issue, board_info)
            else:
                accepted = self._deterministic_validate(issue)

            if accepted:
                ops.append(self._make_rename_op(issue))
                logger.info(
                    "Accepted rename: %s -> %s (%s)",
                    issue.current_name, issue.suggested_name,
                    issue.reason,
                )

        return ops

    def _ai_validate(self, issue: NetNamingIssue, board_info: BoardInfo) -> bool:
        """Use LLM to validate a single naming suggestion."""
        try:
            from kicad_agent.llm.local_client import LocalLLMClient
            from kicad_agent.llm.text_prompts import (
                NET_NAMING_SYSTEM,
                extract_json_from_text,
            )

            client = LocalLLMClient()
            user_msg = (
                f"Current name: {issue.current_name}\n"
                f"Suggested name: {issue.suggested_name}\n"
                f"Connected components: {', '.join(issue.connected_components)}\n"
                f"Reason: {issue.reason}\n"
                f"Board context: {board_info.component_count} components, "
                f"{board_info.net_count} nets"
            )

            response = client.chat([
                {"role": "system", "content": NET_NAMING_SYSTEM},
                {"role": "user", "content": user_msg},
            ])

            parsed = extract_json_from_text(response)
            if parsed and isinstance(parsed, dict):
                return bool(parsed.get("accept", False))
        except Exception:
            logger.warning(
                "AI validation failed for %s, falling back to deterministic",
                issue.current_name,
            )

        return self._deterministic_validate(issue)

    def _deterministic_validate(self, issue: NetNamingIssue) -> bool:
        """Deterministic fallback: accept if name follows conventions."""
        name = issue.suggested_name

        if name in _RESERVED_NET_NAMES:
            return False

        if not _VALID_NET_NAME.match(name):
            return False

        if name == issue.current_name:
            return False

        return True

    def _make_rename_op(self, issue: NetNamingIssue) -> dict[str, Any]:
        """Build a RenameNetOp dict for an approved rename."""
        return {
            "op_type": "rename_net",
            "target_file": self._target_file,
            "old_name": issue.current_name,
            "new_name": issue.suggested_name,
        }
