"""Tests for DrcAutoFixer (GAP-06)."""

import pytest
from unittest.mock import MagicMock, patch

from kicad_agent.analysis.drc_auto_fixer import DrcAutoFixer
from kicad_agent.validation.drc_intel import (
    EnrichedViolation,
    ViolationClassification,
)


@pytest.fixture
def clearance_violation():
    return EnrichedViolation(
        description="Copper collision between traces",
        severity="error",
        violation_type="clearance",
        items=(),
        spatial_context="Two traces 0.15mm apart, minimum 0.25mm",
    )


@pytest.fixture
def courtyard_violation():
    return EnrichedViolation(
        description="Courtyard overlap",
        severity="warning",
        violation_type="courtyard_clearance",
        items=(),
        spatial_context="Footprint courtyards overlap by 0.1mm",
    )


@pytest.fixture
def violation_with_fix():
    return EnrichedViolation(
        description="Unrouted net",
        severity="error",
        violation_type="unrouted_net",
        items=(),
        spatial_context="Net VCC has no copper segments",
        fix_suggestions=(
            MagicMock(
                action="route_net",
                confidence=0.9,
                rationale="Add copper to connect pins",
                to_json=lambda: {"action": "route_net", "confidence": 0.9},
            ),
        ),
    )


class TestDeterministicFix:
    """Deterministic mode (no AI)."""

    def test_clearance_returns_none(self, clearance_violation):
        fixer = DrcAutoFixer(target_file="test.kicad_pcb", use_ai=False)
        ops = fixer.fix_violations((clearance_violation,))
        assert ops == []

    def test_courtyard_returns_none(self, courtyard_violation):
        fixer = DrcAutoFixer(target_file="test.kicad_pcb", use_ai=False)
        ops = fixer.fix_violations((courtyard_violation,))
        assert ops == []

    def test_unknown_type_returns_none(self):
        v = EnrichedViolation(
            description="Unknown issue",
            severity="info",
            violation_type="something_weird",
            items=(),
            spatial_context="No context",
        )
        fixer = DrcAutoFixer(target_file="test.kicad_pcb", use_ai=False)
        ops = fixer.fix_violations((v,))
        assert ops == []

    def test_empty_violations(self):
        fixer = DrcAutoFixer(target_file="test.kicad_pcb", use_ai=False)
        ops = fixer.fix_violations(())
        assert ops == []

    def test_multiple_violations(self, clearance_violation, courtyard_violation):
        fixer = DrcAutoFixer(target_file="test.kicad_pcb", use_ai=False)
        ops = fixer.fix_violations((clearance_violation, courtyard_violation))
        assert ops == []


class TestAIFix:
    """AI mode with mocked LLM."""

    def test_ai_suggests_fix(self, clearance_violation):
        mock_client = MagicMock()
        mock_client.chat.return_value = (
            '```json\n{"op_type": "move_footprint", "target_file": "auto", '
            '"reference": "R1", "x": 25.0, "y": 30.0}\n```'
        )

        with patch(
            "kicad_agent.llm.local_client.LocalLLMClient",
            return_value=mock_client,
        ):
            fixer = DrcAutoFixer(target_file="test.kicad_pcb", use_ai=True)
            ops = fixer.fix_violations((clearance_violation,))

        assert len(ops) == 1
        assert ops[0]["op_type"] == "move_footprint"
        assert ops[0]["target_file"] == "test.kicad_pcb"

    def test_ai_declines_fix(self, clearance_violation):
        mock_client = MagicMock()
        mock_client.chat.return_value = (
            '{"op_type": null, "reason": "Too risky to move automatically"}'
        )

        with patch(
            "kicad_agent.llm.local_client.LocalLLMClient",
            return_value=mock_client,
        ):
            fixer = DrcAutoFixer(target_file="test.kicad_pcb", use_ai=True)
            ops = fixer.fix_violations((clearance_violation,))

        assert ops == []

    def test_ai_falls_back_on_exception(self, clearance_violation):
        mock_client = MagicMock()
        mock_client.chat.side_effect = RuntimeError("Model error")

        with patch(
            "kicad_agent.llm.local_client.LocalLLMClient",
            return_value=mock_client,
        ):
            fixer = DrcAutoFixer(target_file="test.kicad_pcb", use_ai=True)
            ops = fixer.fix_violations((clearance_violation,))

        # Falls back to deterministic: clearance -> None
        assert ops == []

    def test_ai_falls_back_on_invalid_json(self, clearance_violation):
        mock_client = MagicMock()
        mock_client.chat.return_value = "not json"

        with patch(
            "kicad_agent.llm.local_client.LocalLLMClient",
            return_value=mock_client,
        ):
            fixer = DrcAutoFixer(target_file="test.kicad_pcb", use_ai=True)
            ops = fixer.fix_violations((clearance_violation,))

        assert ops == []

    def test_violation_with_fix_suggestions_in_prompt(self, violation_with_fix):
        mock_client = MagicMock()
        mock_client.chat.return_value = (
            '{"op_type": "rename_net", "old_name": "N_00042", "new_name": "VCC"}'
        )

        with patch(
            "kicad_agent.llm.local_client.LocalLLMClient",
            return_value=mock_client,
        ):
            fixer = DrcAutoFixer(target_file="test.kicad_pcb", use_ai=True)
            ops = fixer.fix_violations((violation_with_fix,))

        # Verify the prompt includes fix suggestions
        call_args = mock_client.chat.call_args[0][0]
        user_msg = call_args[1]["content"]
        assert "Existing fix suggestions" in user_msg
