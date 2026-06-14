"""Tests for Proposal model and validator (Phase 92)."""

from __future__ import annotations

import pytest

from kicad_agent.validation.gates.proposal import (
    FixSource,
    Proposal,
    ProposalValidator,
)


def _make_proposal(
    source: FixSource = FixSource.DETERMINISTIC,
    confidence: float = 1.0,
    human_review: bool = False,
    op_type: str = "add_component",
    target_file: str = "test.kicad_sch",
) -> Proposal:
    return Proposal(
        proposed_op={"op_type": op_type, "target_file": target_file},
        source=source,
        confidence=confidence,
        rationale="test rationale",
        target_blocker="some blocker",
        human_review=human_review,
    )


_REGISTRY = {"add_component": {}, "move_component": {}, "export": {}}


class TestProposalValidation:
    def test_valid_deterministic_accepted(self) -> None:
        validator = ProposalValidator(_REGISTRY)
        valid, _ = validator.validate(_make_proposal())
        assert valid is True

    def test_unknown_op_type_rejected(self) -> None:
        validator = ProposalValidator(_REGISTRY)
        valid, err = validator.validate(_make_proposal(op_type="unknown_op"))
        assert valid is False
        assert "Unknown op_type" in err

    def test_missing_target_file_rejected(self) -> None:
        validator = ProposalValidator(_REGISTRY)
        p = Proposal(
            proposed_op={"op_type": "add_component"},
            source=FixSource.DETERMINISTIC,
            confidence=1.0,
            rationale="test",
            target_blocker="b",
        )
        valid, err = validator.validate(p)
        assert valid is False
        assert "target_file" in err

    def test_missing_op_type_rejected(self) -> None:
        validator = ProposalValidator(_REGISTRY)
        p = Proposal(
            proposed_op={"target_file": "test.sch"},
            source=FixSource.DETERMINISTIC,
            confidence=1.0,
            rationale="test",
            target_blocker="b",
        )
        valid, err = validator.validate(p)
        assert valid is False
        assert "op_type" in err

    def test_confidence_clamped_high(self) -> None:
        p = _make_proposal(confidence=1.5)
        assert p.confidence == 1.0

    def test_confidence_clamped_low(self) -> None:
        p = _make_proposal(confidence=-0.5)
        assert p.confidence == 0.0

    def test_proposal_frozen(self) -> None:
        p = _make_proposal()
        with pytest.raises(Exception):
            p.confidence = 0.5


class TestAcceptProposal:
    def test_deterministic_always_accepted(self) -> None:
        assert ProposalValidator.accept_proposal(_make_proposal(FixSource.DETERMINISTIC)) is True

    def test_local_ai_high_confidence(self) -> None:
        assert ProposalValidator.accept_proposal(_make_proposal(FixSource.LOCAL_AI, 0.8)) is True

    def test_local_ai_low_confidence(self) -> None:
        assert ProposalValidator.accept_proposal(_make_proposal(FixSource.LOCAL_AI, 0.5)) is False

    def test_local_ai_threshold_boundary(self) -> None:
        assert ProposalValidator.accept_proposal(_make_proposal(FixSource.LOCAL_AI, 0.7)) is True
        assert ProposalValidator.accept_proposal(_make_proposal(FixSource.LOCAL_AI, 0.699)) is False

    def test_external_llm_accepted(self) -> None:
        assert ProposalValidator.accept_proposal(
            _make_proposal(FixSource.EXTERNAL_LLM, 0.9, human_review=True)
        ) is True

    def test_external_llm_no_human_review(self) -> None:
        assert ProposalValidator.accept_proposal(
            _make_proposal(FixSource.EXTERNAL_LLM, 0.9, human_review=False)
        ) is False

    def test_external_llm_low_confidence(self) -> None:
        assert ProposalValidator.accept_proposal(
            _make_proposal(FixSource.EXTERNAL_LLM, 0.6, human_review=True)
        ) is False
