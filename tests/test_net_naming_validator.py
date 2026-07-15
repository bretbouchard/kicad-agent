"""Tests for NetNamingValidator (GAP-07)."""

import pytest
from unittest.mock import MagicMock, patch

from volta.analysis.gap_analyzer import BoardInfo, NetNamingIssue
from volta.analysis.net_naming_validator import NetNamingValidator


@pytest.fixture
def board_info():
    return BoardInfo(
        file_path="test.kicad_pcb",
        component_count=10,
        net_count=20,
        layer_count=2,
        bounds=(0.0, 0.0, 100.0, 80.0),
    )


@pytest.fixture
def good_issue():
    return NetNamingIssue(
        current_name="N_00142",
        suggested_name="SDA",
        connected_components=("U1", "R3"),
        reason="Connected to I2C data pin",
    )


@pytest.fixture
def reserved_issue():
    return NetNamingIssue(
        current_name="N_00005",
        suggested_name="GND",
        connected_components=("R1",),
        reason="Connected to ground pin",
    )


@pytest.fixture
def bad_format_issue():
    return NetNamingIssue(
        current_name="N_00007",
        suggested_name="invalid-name",
        connected_components=("C1",),
        reason="Some reason",
    )


@pytest.fixture
def same_name_issue():
    return NetNamingIssue(
        current_name="VCC",
        suggested_name="VCC",
        connected_components=("U1",),
        reason="Already correct",
    )


class TestDeterministicValidation:
    """Deterministic fallback validation (no AI)."""

    def test_accepts_valid_name(self, board_info, good_issue):
        validator = NetNamingValidator(target_file="test.kicad_pcb", use_ai=False)
        ops = validator.validate((good_issue,), board_info)
        assert len(ops) == 1
        assert ops[0]["op_type"] == "rename_net"
        assert ops[0]["old_name"] == "N_00142"
        assert ops[0]["new_name"] == "SDA"

    def test_rejects_reserved_name(self, board_info, reserved_issue):
        validator = NetNamingValidator(target_file="test.kicad_pcb", use_ai=False)
        ops = validator.validate((reserved_issue,), board_info)
        assert len(ops) == 0

    def test_rejects_bad_format(self, board_info, bad_format_issue):
        validator = NetNamingValidator(target_file="test.kicad_pcb", use_ai=False)
        ops = validator.validate((bad_format_issue,), board_info)
        assert len(ops) == 0

    def test_rejects_same_name(self, board_info, same_name_issue):
        validator = NetNamingValidator(target_file="test.kicad_pcb", use_ai=False)
        ops = validator.validate((same_name_issue,), board_info)
        assert len(ops) == 0

    def test_empty_issues(self, board_info):
        validator = NetNamingValidator(target_file="test.kicad_pcb", use_ai=False)
        ops = validator.validate((), board_info)
        assert ops == []

    def test_multiple_issues(self, board_info, good_issue, reserved_issue):
        validator = NetNamingValidator(target_file="test.kicad_pcb", use_ai=False)
        ops = validator.validate((good_issue, reserved_issue), board_info)
        assert len(ops) == 1
        assert ops[0]["new_name"] == "SDA"

    def test_uppercase_with_numbers(self, board_info):
        issue = NetNamingIssue(
            current_name="N_00001",
            suggested_name="I2C_SDA",
            connected_components=("U1",),
            reason="I2C data line",
        )
        validator = NetNamingValidator(target_file="test.kicad_pcb", use_ai=False)
        ops = validator.validate((issue,), board_info)
        assert len(ops) == 1


class TestAIValidation:
    """AI validation with mocked LLM."""

    def test_accepts_when_ai_says_yes(self, board_info, good_issue):
        mock_client = MagicMock()
        mock_client.chat.return_value = '{"accept": true, "reason": "Good name"}'

        with patch(
            "volta.llm.local_client.LocalLLMClient",
            return_value=mock_client,
        ):
            validator = NetNamingValidator(target_file="test.kicad_pcb", use_ai=True)
            ops = validator.validate((good_issue,), board_info)

        assert len(ops) == 1
        assert ops[0]["new_name"] == "SDA"

    def test_rejects_when_ai_says_no(self, board_info, good_issue):
        mock_client = MagicMock()
        mock_client.chat.return_value = '{"accept": false, "reason": "Bad suggestion"}'

        with patch(
            "volta.llm.local_client.LocalLLMClient",
            return_value=mock_client,
        ):
            validator = NetNamingValidator(target_file="test.kicad_pcb", use_ai=True)
            ops = validator.validate((good_issue,), board_info)

        assert len(ops) == 0

    def test_falls_back_on_exception(self, board_info, good_issue):
        mock_client = MagicMock()
        mock_client.chat.side_effect = RuntimeError("Model not loaded")

        with patch(
            "volta.llm.local_client.LocalLLMClient",
            return_value=mock_client,
        ):
            validator = NetNamingValidator(target_file="test.kicad_pcb", use_ai=True)
            ops = validator.validate((good_issue,), board_info)

        # Should fall back to deterministic — SDA is valid
        assert len(ops) == 1

    def test_falls_back_on_invalid_json(self, board_info, good_issue):
        mock_client = MagicMock()
        mock_client.chat.return_value = "not json at all"

        with patch(
            "volta.llm.local_client.LocalLLMClient",
            return_value=mock_client,
        ):
            validator = NetNamingValidator(target_file="test.kicad_pcb", use_ai=True)
            ops = validator.validate((good_issue,), board_info)

        # Falls back to deterministic
        assert len(ops) == 1
