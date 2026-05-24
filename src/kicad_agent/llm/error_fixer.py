"""ERC/DRC violation to fix operations converter via Claude tool use.

Provides ErrorFixer that sends violations to Claude and receives structured
fix operations matching the existing Operation Pydantic schema. Uses prompt
caching on the system prompt to reduce API costs on the large operation schema.

Security (threat model):
  T-15-10: Operations from LLM validated via Operation.model_validate() before execution.
  T-15-12: target_file path traversal check inherited from Operation schema (T-H-01).
  T-15-13: Operation count capped at 1000 (inherited from pipeline.py _MAX_OPERATIONS).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from kicad_agent.llm.client import LLMClient
from kicad_agent.ops.schema import get_operation_schema

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FixResult:
    """Result from an LLM fix attempt.

    Attributes:
        operations: Tuple of operation dicts from Claude tool use response.
        fix_description: Human-readable summary of what was fixed.
        success: Whether the LLM returned valid fix operations.
    """

    operations: tuple[dict[str, Any], ...] = ()
    fix_description: str = ""
    success: bool = False


# System prompt for Claude -- cached via prompt caching to save on the 51KB schema
FIX_SYSTEM_PROMPT = (
    "You are a PCB design error fixer. Given ERC/DRC violations, generate a minimal "
    "set of operations to fix each error. Focus on the specific error reported -- do "
    "not make unnecessary changes. Each operation must match the operation schema "
    "exactly. Prefer add_component, add_net, add_power, and modify_property operations."
)

# Tool definition for Claude to return fix operations
FIX_TOOL: dict[str, Any] = {
    "name": "apply_fix_operations",
    "description": (
        "Apply a set of operations to fix ERC/DRC violations in a KiCad design. "
        "Each operation must match the operation schema exactly."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "fix_description": {
                "type": "string",
                "description": "Human-readable summary of what this fix does",
            },
            "operations": {
                "type": "array",
                "description": "List of operations to apply to fix the violations",
                "items": get_operation_schema(),
            },
        },
        "required": ["fix_description", "operations"],
    },
}


class ErrorFixer:
    """Converts ERC/DRC violations into fix operations via Claude tool use.

    Sends violations to Claude with the full operation schema as a tool definition.
    Claude responds with structured operations that match the existing Operation
    Pydantic model. Includes iteration history so Claude avoids repeating failed fixes.

    Args:
        model: Optional model override for the LLM client.
    """

    def __init__(self, model: str | None = None) -> None:
        self._client = LLMClient(model=model)

    def fix(
        self,
        violations: list[dict[str, str]],
        iteration_history: list[str] | None = None,
    ) -> FixResult:
        """Generate fix operations for the given violations.

        Args:
            violations: List of violation dicts with description, severity, type keys.
            iteration_history: Optional list of previous attempt descriptions so LLM
                avoids repeating failed fixes.

        Returns:
            FixResult with operations, description, and success status.
        """
        # Build error context from violations
        error_lines: list[str] = []
        for v in violations:
            desc = v.get("description", "Unknown violation")
            sev = v.get("severity", "error")
            vtype = v.get("type", "unknown")
            error_lines.append(f"[{sev}] ({vtype}) {desc}")

        error_context = "Current violations:\n" + "\n".join(error_lines) if error_lines else "No violations to fix."

        # Include iteration history if present
        user_content = error_context
        if iteration_history:
            history_text = "\n".join(iteration_history)
            user_content = f"Previous attempts:\n{history_text}\n\n{error_context}"

        # Build system with prompt caching on the system prompt
        # The FIX_TOOL contains the ~51KB operation schema, which is expensive to re-send
        system_prompt: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": FIX_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            },
        ]

        messages = [{"role": "user", "content": user_content}]

        try:
            response = self._client.create_message(
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
                tools=[FIX_TOOL],
                tool_choice={"type": "tool", "name": "apply_fix_operations"},
            )
        except Exception as exc:
            logger.warning("ErrorFixer LLM call failed: %s", exc)
            return FixResult(
                operations=(),
                fix_description=f"LLM call failed: {exc}",
                success=False,
            )

        # Extract tool_use block
        for block in response.content:
            if block.type == "tool_use" and block.name == "apply_fix_operations":
                ops = block.input.get("operations", [])
                description = block.input.get("fix_description", "LLM fix")
                return FixResult(
                    operations=tuple(ops),
                    fix_description=description,
                    success=True,
                )

        # No tool_use block returned
        return FixResult(
            operations=(),
            fix_description="LLM did not return fix operations",
            success=False,
        )
