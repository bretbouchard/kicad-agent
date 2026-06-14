"""Proposal model and validator for AI-suggested fixes.

Proposal represents a proposed change (operation JSON) with provenance
(source type, confidence, rationale). ProposalValidator checks schema
validity against the operation registry. accept_proposal enforces confidence
thresholds per source type.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class FixSource(str, Enum):
    """Source of a fix proposal."""
    DETERMINISTIC = "deterministic"
    LOCAL_AI = "local_ai"
    EXTERNAL_LLM = "external_llm"


class Proposal(BaseModel):
    """Immutable proposal for a fix operation.

    Attributes:
        proposed_op: Operation JSON (must contain "op_type" and "target_file").
        source: Where the proposal came from.
        confidence: 0.0-1.0 confidence score.
        rationale: Human-readable explanation.
        target_blocker: Which gate blocker this addresses.
        human_review: Required for external_llm source.
    """

    model_config = {"frozen": True}

    proposed_op: dict[str, Any]
    source: FixSource
    confidence: float
    rationale: str
    target_blocker: str
    human_review: bool = False

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class ProposalValidator:
    """Validates proposals against the operation registry."""

    def __init__(self, registry: dict[str, Any] | None = None) -> None:
        self._registry = registry or {}

    def validate(self, proposal: Proposal) -> tuple[bool, str]:
        """Check proposal against registry constraints.

        Returns (valid, error_message).
        """
        op = proposal.proposed_op
        op_type = op.get("op_type")
        target_file = op.get("target_file")

        if not op_type:
            return (False, "Proposal missing 'op_type' in proposed_op")
        if op_type not in self._registry:
            return (False, f"Unknown op_type '{op_type}' not in registry")
        if not target_file or not isinstance(target_file, str):
            return (False, "Proposal missing or invalid 'target_file'")

        return (True, "")

    @staticmethod
    def accept_proposal(proposal: Proposal) -> bool:
        """Check confidence thresholds per source type.

        deterministic: always accept if validated
        local_ai: confidence >= 0.7
        external_llm: confidence >= 0.8 AND human_review=True
        """
        if proposal.source == FixSource.DETERMINISTIC:
            return True
        if proposal.source == FixSource.LOCAL_AI:
            return proposal.confidence >= 0.7
        if proposal.source == FixSource.EXTERNAL_LLM:
            return proposal.confidence >= 0.8 and proposal.human_review
        return False
