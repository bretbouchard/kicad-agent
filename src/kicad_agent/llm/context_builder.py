"""Prompt assembly, token budgeting, and data sanitization for LLM integration.

Provides ContextBuilder with static methods for assembling LLM prompts
from KiCad file content and ERC/DRC violation data.

Security (threat model):
  T-15-04: sanitize() strips instruction-like patterns from file content
           before LLM inclusion to prevent prompt injection.
"""

from __future__ import annotations

import re
from typing import Any

# Patterns that indicate instruction injection attempts
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+previous", re.IGNORECASE),
    re.compile(r"act\s+as", re.IGNORECASE),
    re.compile(r"forget\s+rules", re.IGNORECASE),
    re.compile(r"disregard", re.IGNORECASE),
    re.compile(r"ignore\s+all", re.IGNORECASE),
    re.compile(r"you\s+are\s+now", re.IGNORECASE),
    re.compile(r"new\s+instructions", re.IGNORECASE),
]

_DESCRIPTION_MAX_LENGTH = 200


class ContextBuilder:
    """Assembles LLM prompts from KiCad file content and validation results.

    All methods are static/classmethods; no instance state is needed.
    """

    @staticmethod
    def sanitize(content: str) -> str:
        """Strip instruction-like patterns from KiCad file content.

        Wraps content in data boundary markers and replaces injection
        patterns with [REDACTED] to prevent prompt injection attacks.

        Args:
            content: Raw KiCad file content or user-provided text.

        Returns:
            Sanitized content wrapped in data boundary markers.
        """
        sanitized = content
        for pattern in _INJECTION_PATTERNS:
            sanitized = pattern.sub("[REDACTED]", sanitized)

        return f"--- DATA BOUNDARY ---\n{sanitized}\n--- DATA BOUNDARY ---"

    @staticmethod
    def truncate_violations(
        violations: list[Any],
        max_count: int = 10,
    ) -> list[dict[str, str]]:
        """Cap violation count and truncate descriptions for LLM context budgeting.

        Args:
            violations: List of violation objects with severity and description attributes.
            max_count: Maximum number of violations to include (default 10).

        Returns:
            List of plain dicts with severity and description fields,
            each description truncated to 200 characters.
        """
        capped = violations[:max_count]
        result: list[dict[str, str]] = []

        for v in capped:
            description = str(v.description)
            if len(description) > _DESCRIPTION_MAX_LENGTH:
                description = description[:_DESCRIPTION_MAX_LENGTH]

            result.append({
                "severity": str(v.severity.value),
                "description": description,
            })

        return result

    @staticmethod
    def build_error_summary(
        erc_result: Any,
        drc_result: Any | None = None,
        max_count: int = 10,
    ) -> str:
        """Build compact error text for LLM from ErcResult/DrcResult.

        Formats ERC and DRC results into a compact string suitable for
        inclusion in an LLM prompt, with violation counts and truncated
        descriptions.

        Args:
            erc_result: ErcResult with passed, error_count, and violations attributes.
            drc_result: Optional DrcResult with same attributes.
            max_count: Maximum violations per category (default 10).

        Returns:
            Compact error summary string.
        """
        parts: list[str] = []

        erc_status = "PASS" if erc_result.passed else "FAIL"
        parts.append(f"ERC: {erc_status} ({erc_result.error_count} errors)")

        erc_violations = ContextBuilder.truncate_violations(
            erc_result.violations, max_count=max_count
        )
        for v in erc_violations:
            parts.append(f"  [{v['severity']}] {v['description']}")

        if drc_result is not None:
            drc_status = "PASS" if drc_result.passed else "FAIL"
            parts.append(f"DRC: {drc_status} ({drc_result.error_count} errors)")

            drc_violations = ContextBuilder.truncate_violations(
                drc_result.violations, max_count=max_count
            )
            for v in drc_violations:
                parts.append(f"  [{v['severity']}] {v['description']}")

        return "\n".join(parts)
