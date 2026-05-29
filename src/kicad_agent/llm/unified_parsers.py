"""Unified parsers that adapt to backend capabilities.

Wraps existing IntentParser, ErrorFixer, and DesignCritic so they work
with both cloud (tool_use) and local (text) responses from HybridLLMClient.

When the backend returns a cloud response with tool_use blocks, the unified
parser extracts structured data the normal way.  When the response is from
a local model (plain text), the unified parser falls back to text-based JSON
extraction and Pydantic validation.

Classes:
    UnifiedIntentParser:  NL -> GenerationIntent (cloud or local)
    UnifiedErrorFixer:    Violations -> FixResult (cloud or local)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from kicad_agent.generation.intent import GenerationIntent
from kicad_agent.llm.error_fixer import FixResult
from kicad_agent.llm.text_prompts import build_text_prompt, extract_json_from_text
from kicad_agent.llm.tools import INTENT_TOOL

if TYPE_CHECKING:
    from kicad_agent.llm.backend import LLMBackend

logger = logging.getLogger(__name__)


def _has_tool_use(response: Any, tool_name: str) -> bool:
    """Check if a response contains a specific tool_use block."""
    for block in response.content:
        if getattr(block, "type", "") == "tool_use" and getattr(block, "name", "") == tool_name:
            return True
    return False


def _get_tool_input(response: Any, tool_name: str) -> dict[str, Any] | None:
    """Extract tool_use input dict from a response."""
    for block in response.content:
        if getattr(block, "type", "") == "tool_use" and getattr(block, "name", "") == tool_name:
            return block.input  # type: ignore[no-any-return]
    return None


def _get_text(response: Any) -> str:
    """Extract text from a response (works for both cloud and local)."""
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    return ""


class UnifiedIntentParser:
    """Intent parser that works with both cloud (tool_use) and local (text).

    Uses Anthropic tool_use when the backend returns structured blocks.
    Falls back to text-based JSON extraction for local model responses.

    Args:
        client: LLMBackend instance (typically HybridLLMClient).
    """

    def __init__(self, client: LLMBackend) -> None:
        self._client = client

    def parse(self, description: str) -> GenerationIntent:
        """Parse NL into GenerationIntent via cloud tool_use or text extraction.

        Args:
            description: Natural language circuit description.

        Returns:
            Validated GenerationIntent.

        Raises:
            ValueError: If neither tool_use nor text extraction succeeds.
        """
        response = self._client.create_message(
            max_tokens=4096,
            tools=[INTENT_TOOL],
            tool_choice={"type": "tool", "name": "create_design_intent"},
            messages=[{"role": "user", "content": description}],
        )

        # Cloud path: extract from tool_use block
        tool_input = _get_tool_input(response, "create_design_intent")
        if tool_input is not None:
            return GenerationIntent.model_validate(tool_input)

        # Local path: extract JSON from text
        text = _get_text(response)
        if text:
            full_prompt = build_text_prompt("intent_parse", description)
            # The local model already received the prompt, just extract from its text
            data = extract_json_from_text(text)
            if data is not None:
                try:
                    return GenerationIntent.model_validate(data)
                except Exception as exc:
                    logger.warning("UnifiedIntentParser: JSON validation failed: %s", exc)
                    raise ValueError(
                        f"Extracted JSON failed GenerationIntent validation: {exc}"
                    ) from exc

        raise ValueError(
            "UnifiedIntentParser: no tool_use block and no extractable JSON in response"
        )


class UnifiedErrorFixer:
    """Error fixer that works with both cloud (tool_use) and local (text).

    Uses Anthropic tool_use when the backend returns structured blocks.
    Falls back to text-based JSON extraction for local model responses.

    Args:
        client: LLMBackend instance (typically HybridLLMClient).
    """

    def __init__(self, client: LLMBackend) -> None:
        self._client = client

    def fix(
        self,
        violations: list[dict[str, str]],
        iteration_history: list[str] | None = None,
    ) -> FixResult:
        """Generate fix operations via cloud tool_use or text extraction.

        Args:
            violations: List of violation dicts.
            iteration_history: Optional list of previous attempt descriptions.

        Returns:
            FixResult with operations and success status.
        """
        from kicad_agent.llm.error_fixer import FIX_SYSTEM_PROMPT, FIX_TOOL
        from kicad_agent.ops.schema import get_operation_schema

        # Build error context
        error_lines: list[str] = []
        for v in violations:
            desc = v.get("description", "Unknown violation")
            sev = v.get("severity", "error")
            vtype = v.get("type", "unknown")
            error_lines.append(f"[{sev}] ({vtype}) {desc}")

        error_context = (
            "Current violations:\n" + "\n".join(error_lines)
            if error_lines
            else "No violations to fix."
        )

        user_content = error_context
        if iteration_history:
            history_text = "\n".join(iteration_history)
            user_content = f"Previous attempts:\n{history_text}\n\n{error_context}"

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
            logger.warning("UnifiedErrorFixer LLM call failed: %s", exc)
            return FixResult(
                operations=(),
                fix_description=f"LLM call failed: {exc}",
                success=False,
            )

        # Cloud path: extract from tool_use block
        tool_input = _get_tool_input(response, "apply_fix_operations")
        if tool_input is not None:
            ops = tool_input.get("operations", [])
            description = tool_input.get("fix_description", "LLM fix")
            return FixResult(
                operations=tuple(ops),
                fix_description=description,
                success=True,
            )

        # Local path: extract JSON from text
        text = _get_text(response)
        if text:
            full_prompt = build_text_prompt("error_fix", user_content)
            data = extract_json_from_text(text)
            if data is not None:
                ops = data.get("operations", [])
                description = data.get("fix_description", "LLM fix")
                return FixResult(
                    operations=tuple(ops),
                    fix_description=description,
                    success=True,
                )

        return FixResult(
            operations=(),
            fix_description="No tool_use block and no extractable JSON in response",
            success=False,
        )
