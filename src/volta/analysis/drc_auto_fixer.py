"""DRC auto-fixer (GAP-06).

Generates fix operation dicts from EnrichedViolation tuples. Uses AI to
suggest fixes based on violation context, with deterministic fallback from
violation type mapping.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from volta.validation.drc_intel import EnrichedViolation

logger = logging.getLogger(__name__)

# Map of violation types to deterministic fix operations.
_DETERMINISTIC_FIX_MAP: dict[str, dict[str, Any] | None] = {
    "clearence": None,  # Requires spatial reasoning — skip
    "clearance": None,
    "missing_copper_zone": None,  # Complex — skip
    "courtyard_clearance": None,
}


class DrcAutoFixer:
    """Generates fix operation dicts for DRC violations.

    Args:
        target_file: Relative path to the PCB file for operation dicts.
        use_ai: Whether to use the LLM for fix suggestions.
    """

    def __init__(self, *, target_file: str = "board.kicad_pcb", use_ai: bool = True) -> None:
        self._target_file = target_file
        self._use_ai = use_ai

    def fix_violations(
        self,
        violations: tuple[EnrichedViolation, ...],
    ) -> list[dict[str, Any]]:
        """Generate fix operations for DRC violations.

        Each violation is handled independently. Only violations with a viable
        fix (deterministic or AI-suggested) produce operations.

        Args:
            violations: EnrichedViolation tuples from GapReport.

        Returns:
            List of operation dicts for accepted fixes.
        """
        if not violations:
            return []

        ops: list[dict[str, Any]] = []
        for violation in violations:
            if self._use_ai:
                op = self._ai_suggest_fix(violation)
            else:
                op = self._deterministic_fix(violation)

            if op is not None:
                ops.append(op)
                logger.info(
                    "DRC fix for [%s] %s: %s",
                    violation.severity, violation.violation_type,
                    op.get("op_type", "unknown"),
                )

        return ops

    def _ai_suggest_fix(self, violation: EnrichedViolation) -> dict[str, Any] | None:
        """Use LLM to suggest a fix operation for a single violation."""
        try:
            from volta.llm.local_client import LocalLLMClient
            from volta.llm.text_prompts import (
                DRC_FIX_SYSTEM,
                extract_json_from_text,
            )

            client = LocalLLMClient()

            # Build violation context
            fix_hints = ""
            if violation.fix_suggestions:
                hints = []
                for s in violation.fix_suggestions:
                    hints.append(f"  - {s.action} ({s.confidence:.0%}): {s.rationale}")
                fix_hints = "Existing fix suggestions:\n" + "\n".join(hints)

            user_msg = (
                f"Violation type: {violation.violation_type}\n"
                f"Severity: {violation.severity}\n"
                f"Description: {violation.description}\n"
                f"Spatial context: {violation.spatial_context}\n"
                f"Target file: {self._target_file}\n"
                f"{fix_hints}"
            )

            response = client.chat([
                {"role": "system", "content": DRC_FIX_SYSTEM},
                {"role": "user", "content": user_msg},
            ])

            parsed = extract_json_from_text(response)
            if parsed and isinstance(parsed, dict):
                op_type = parsed.get("op_type")
                if op_type is None:
                    # LLM said no safe fix
                    logger.info(
                        "AI declined to fix [%s] %s: %s",
                        violation.severity, violation.violation_type,
                        parsed.get("reason", "no reason"),
                    )
                    return None
                # Build the operation dict with target_file
                parsed["target_file"] = self._target_file
                return parsed

        except Exception:
            logger.warning(
                "AI fix failed for [%s] %s, falling back to deterministic",
                violation.severity, violation.violation_type,
            )

        return self._deterministic_fix(violation)

    def _deterministic_fix(self, violation: EnrichedViolation) -> dict[str, Any] | None:
        """Deterministic fallback: map violation type to known fix pattern."""
        vtype = violation.violation_type.lower()

        # Check explicit map
        if vtype in _DETERMINISTIC_FIX_MAP:
            return _DETERMINISTIC_FIX_MAP[vtype]

        # No safe deterministic fix for unknown violation types
        return None
