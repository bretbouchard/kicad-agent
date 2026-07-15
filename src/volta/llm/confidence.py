"""Confidence scoring for local LLM responses.

Provides ConfidenceScorer that evaluates local model output across three
dimensions: format (JSON extractability), schema (Pydantic validation),
and reward (neural reward model). The composite score determines whether
the hybrid client should fall back to the cloud API.

Also exports extract_json_from_text() for standalone JSON extraction from
LLM output that may contain markdown fences or other formatting.

Usage::

    from volta.llm.confidence import ConfidenceScorer, extract_json_from_text

    scorer = ConfidenceScorer()
    result = scorer.score('```json\\n{"name": "amp"}\\n```', expected_schema=MyModel)
    print(result.overall)  # 0.0-1.0
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# JSON extraction utility
# ---------------------------------------------------------------------------

# Pattern for ```json ... ``` and ``` ... ``` fenced blocks
_FENCED_JSON_RE = re.compile(
    r"```(?:json)?\s*\n?(.*?)```", re.DOTALL
)


def extract_json_from_text(text: str) -> dict | list | None:
    """Extract JSON from markdown code blocks or raw text.

    Tries extraction strategies in priority order:
    1. ```json ... ``` fenced code blocks
    2. ``` ... ``` generic fenced code blocks
    3. Raw brace-delimited {...} or bracket-delimited [...] spans via
       balanced counting

    Args:
        text: Raw LLM output that may contain JSON in various formats.

    Returns:
        Parsed dict or list on success, None if no JSON found or parse failed.
    """
    # Strategy 1 & 2: fenced code blocks (json-labeled or generic)
    matches = _FENCED_JSON_RE.findall(text)
    for match in matches:
        candidate = match.strip()
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    # Strategy 3: balanced brace/bracket counting for raw JSON in text
    return _extract_balanced_json(text)


def _extract_balanced_json(text: str) -> dict | list | None:
    """Find the first valid JSON object or array using balanced delimiters.

    Scans the text for the first ``{`` or ``[``, then counts nested
    delimiters to find the matching close. Parses the extracted span
    and returns it on success.

    Args:
        text: Text potentially containing raw JSON.

    Returns:
        Parsed dict/list, or None if no valid JSON found.
    """
    for open_char, close_char in [("{", "}"), ("[", "]")]:
        start = text.find(open_char)
        if start == -1:
            continue

        depth = 0
        in_string = False
        escape_next = False

        for i in range(start, len(text)):
            ch = text[i]

            if escape_next:
                escape_next = False
                continue

            if ch == "\\":
                escape_next = True
                continue

            if ch == '"':
                in_string = not in_string
                continue

            if in_string:
                continue

            if ch == open_char:
                depth += 1
            elif ch == close_char:
                depth -= 1

            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, (dict, list)):
                        return parsed
                except json.JSONDecodeError:
                    pass
                break  # matched but invalid; don't keep scanning same opener

    return None


# ---------------------------------------------------------------------------
# Confidence score
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfidenceScore:
    """Composite confidence score for a local LLM response.

    Attributes:
        overall: Weighted composite 0.0-1.0 across all dimensions.
        format_score: 0 or 1 -- could valid JSON be extracted from the text?
        schema_score: 0 or 1 -- does extracted JSON validate against a Pydantic model?
        reward_score: 0.0-1.0 from the neural RewardModel (0.5 neutral if unavailable).
        latency_s: Wall-clock time spent on scoring (seconds).
    """

    overall: float
    format_score: float
    schema_score: float
    reward_score: float
    latency_s: float


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

# Weight constants for the composite score
_WEIGHT_FORMAT = 0.4
_WEIGHT_SCHEMA = 0.3
_WEIGHT_REWARD = 0.3


class ConfidenceScorer:
    """Scores local LLM output to decide cloud fallback.

    Evaluates text across three dimensions:
    - **Format**: Can valid JSON be extracted? (binary 0/1)
    - **Schema**: Does the JSON validate against an expected Pydantic model? (binary 0/1)
    - **Reward**: Optional neural reward model score (0-1, defaults to 0.5 neutral)

    The composite ``overall`` is a weighted average:
    ``format * 0.4 + schema * 0.3 + reward * 0.3``

    Args:
        reward_model: Optional RewardModel instance from training. If None,
            reward_score defaults to 0.5 (neutral).
    """

    def __init__(self, reward_model: Any = None) -> None:
        self._reward_model = reward_model

    def score(
        self,
        text: str,
        expected_schema: type | None = None,
        stage: str = "unknown",
    ) -> ConfidenceScore:
        """Score a local LLM response for confidence.

        Args:
            text: Raw text output from the local model.
            expected_schema: Optional Pydantic model class to validate extracted
                JSON against. If None, schema_score defaults to 1.0.
            stage: Pipeline stage identifier (for reward model context).

        Returns:
            ConfidenceScore with per-dimension scores and weighted composite.
        """
        t0 = time.monotonic()

        # 1. Format score -- can we extract JSON?
        extracted = extract_json_from_text(text)
        format_score = 1.0 if extracted is not None else 0.0

        # 2. Schema score -- does extracted JSON validate?
        schema_score = self._compute_schema_score(extracted, expected_schema)

        # 3. Reward score -- neural model or neutral default
        reward_score = self._compute_reward_score(text, stage)

        # 4. Composite
        overall = (
            format_score * _WEIGHT_FORMAT
            + schema_score * _WEIGHT_SCHEMA
            + reward_score * _WEIGHT_REWARD
        )
        # Clamp to [0.0, 1.0]
        overall = max(0.0, min(1.0, overall))

        latency_s = time.monotonic() - t0

        return ConfidenceScore(
            overall=overall,
            format_score=format_score,
            schema_score=schema_score,
            reward_score=reward_score,
            latency_s=latency_s,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_schema_score(
        extracted: dict | list | None,
        expected_schema: type | None,
    ) -> float:
        """Compute schema validation score.

        Returns 1.0 if no schema expected or validation succeeds, 0.0 otherwise.
        """
        if expected_schema is None:
            # No schema to validate against -- assume valid
            return 1.0

        if extracted is None:
            # No JSON to validate
            return 0.0

        if not isinstance(extracted, dict):
            # Pydantic models expect dict input
            return 0.0

        try:
            expected_schema.model_validate(extracted)
            return 1.0
        except Exception:
            return 0.0

    def _compute_reward_score(self, text: str, stage: str) -> float:
        """Compute reward score via neural model or neutral default.

        Returns 0.5 (neutral) when no reward model is configured.
        """
        if self._reward_model is None:
            return 0.5

        try:
            from volta.training.reward_model import predict_reward

            prediction = predict_reward(self._reward_model, text)
            # Average the three sub-scores
            return (
                prediction.format_score
                + prediction.quality_score
                + prediction.accuracy_score
            ) / 3.0
        except Exception:
            return 0.5
