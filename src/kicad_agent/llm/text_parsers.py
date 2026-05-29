"""Text-based parsers that replace Anthropic tool_use with local model inference.

Provides drop-in replacements for IntentParser, ErrorFixer, and the critique
parsing portion of DesignCritic. Each class calls the LLM without the ``tools``
kwarg and extracts structured JSON from the plain-text response.

These parsers work with any backend that exposes ``create_message()`` -- both
the remote ``LLMClient`` (Anthropic) and the local ``LocalLLMClient`` (mlx-lm).

Classes:
    TextIntentParser:   NL description -> GenerationIntent
    TextErrorFixer:     Violations -> FixResult
    TextCritiqueParser: Text response -> CritiqueReport
"""
from __future__ import annotations

import logging
from typing import Any

from kicad_agent.generation.intent import GenerationIntent
from kicad_agent.llm.design_critic import (
    CritiqueFinding,
    CritiqueReport,
    CritiqueSeverity,
)
from kicad_agent.llm.error_fixer import FixResult
from kicad_agent.llm.text_prompts import build_text_prompt, extract_json_from_text

logger = logging.getLogger(__name__)


class TextIntentParser:
    """Intent parsing using text prompts instead of Anthropic tool_use.

    Calls the LLM without the ``tools`` kwarg, then extracts and validates
    JSON from the plain-text response. Works with both ``LLMClient`` and
    ``LocalLLMClient`` backends.

    Args:
        client: Any object with a ``create_message(**kwargs)`` method.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def parse(self, description: str) -> GenerationIntent:
        """Parse a natural language description into a GenerationIntent.

        Builds a text prompt, calls the LLM without tool_use, extracts JSON
        from the response, and validates against the GenerationIntent schema.

        Args:
            description: Natural language circuit description.

        Returns:
            Validated GenerationIntent object.

        Raises:
            ValueError: If JSON extraction fails or model validation fails.
        """
        user_content = build_text_prompt("intent_parse", description)

        response = self._client.create_message(
            max_tokens=4096,
            system="",
            messages=[{"role": "user", "content": user_content}],
        )

        text = response.content[0].text
        data = extract_json_from_text(text)

        if data is None:
            raise ValueError(
                "TextIntentParser: could not extract JSON from model response"
            )

        return GenerationIntent.model_validate(data)


class TextErrorFixer:
    """Error fixing using text prompts instead of Anthropic tool_use.

    Generates fix operations from ERC/DRC violations by sending a text prompt
    to the LLM and extracting structured JSON from the response.

    Args:
        client: Any object with a ``create_message(**kwargs)`` method.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def fix(
        self,
        violations: list[dict[str, str]],
        iteration_history: list[str] | None = None,
    ) -> FixResult:
        """Generate fix operations from violations using text prompts.

        Args:
            violations: List of violation dicts with description, severity,
                and type keys.
            iteration_history: Optional list of previous attempt descriptions
                so the LLM avoids repeating failed fixes.

        Returns:
            FixResult with operations, description, and success status.
            Returns ``FixResult(success=False)`` if JSON extraction fails.
        """
        # Build error context from violations
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

        # Include iteration history if present
        user_content = error_context
        if iteration_history:
            history_text = "\n".join(iteration_history)
            user_content = f"Previous attempts:\n{history_text}\n\n{error_context}"

        full_prompt = build_text_prompt("error_fix", user_content)

        try:
            response = self._client.create_message(
                max_tokens=4096,
                system="",
                messages=[{"role": "user", "content": full_prompt}],
            )
        except Exception as exc:
            logger.warning("TextErrorFixer LLM call failed: %s", exc)
            return FixResult(
                operations=(),
                fix_description=f"LLM call failed: {exc}",
                success=False,
            )

        text = response.content[0].text
        data = extract_json_from_text(text)

        if data is None:
            return FixResult(
                operations=(),
                fix_description="Could not extract JSON from model response",
                success=False,
            )

        ops = data.get("operations", [])
        description = data.get("fix_description", "LLM fix")

        return FixResult(
            operations=tuple(ops),
            fix_description=description,
            success=True,
        )


class TextCritiqueParser:
    """Design critique parsing from text responses.

    Extracts a CritiqueReport from a plain-text LLM response containing
    JSON with findings, summary, and quality score.
    """

    def parse(self, text: str) -> CritiqueReport:
        """Extract CritiqueReport from text response.

        Parses the raw text to find JSON with findings, summary, and
        quality_score fields, then converts them into a CritiqueReport.

        Args:
            text: Raw LLM response text expected to contain JSON.

        Returns:
            CritiqueReport with findings, summary, and quality score.
            Returns an empty report with quality_score=1.0 if parsing fails.
        """
        data = extract_json_from_text(text)

        if data is None:
            return CritiqueReport(
                findings=(),
                summary="No critique available -- JSON extraction failed",
                overall_quality_score=1.0,
            )

        raw_findings = data.get("findings", [])
        findings: list[CritiqueFinding] = []

        for raw in raw_findings:
            severity_str = raw.get("severity", "info")
            try:
                severity = CritiqueSeverity(severity_str)
            except ValueError:
                logger.warning(
                    "TextCritiqueParser: unknown severity %r, defaulting to info",
                    severity_str,
                )
                severity = CritiqueSeverity.INFO

            coords = tuple(
                (float(c[0]), float(c[1]))
                for c in raw.get("coordinates", [])
            )

            findings.append(
                CritiqueFinding(
                    severity=severity,
                    category=raw.get("category", "unknown"),
                    description=raw.get("description", ""),
                    coordinates=coords,
                )
            )

        # Compute quality score from severity penalties (mirrors design_critic.py)
        severity_penalty = {
            CritiqueSeverity.CRITICAL: 0.3,
            CritiqueSeverity.WARNING: 0.1,
            CritiqueSeverity.INFO: 0.02,
        }
        score = 1.0
        for finding in findings:
            score -= severity_penalty[finding.severity]

        # Also allow the LLM's own score if provided and reasonable
        llm_score = data.get("overall_quality_score")
        if isinstance(llm_score, (int, float)):
            score = float(llm_score)

        score = max(0.0, min(1.0, score))

        return CritiqueReport(
            findings=tuple(findings),
            summary=data.get("summary", ""),
            overall_quality_score=score,
        )
