"""Phase 159: Training data factory tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from volta.training_data import (
    TrainingExample,
    generate_nl_description,
    create_training_example,
    convert_schematic_to_training_data,
    batch_convert_schematics,
)
from volta.circuit_ir.types import (
    CircuitIR,
    NetDescriptor,
    PartDescriptor,
    PinRef,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_LED_FIXTURE = _FIXTURES / "schematic_intent" / "complete_led.kicad_sch"


def _make_test_circuit_ir() -> CircuitIR:
    """Create a minimal CircuitIR with an opamp + passives."""
    return CircuitIR(
        parts=(
            PartDescriptor(
                lib_id="Amplifier_Operational:NE5532", reference="U1",
                value="NE5532", footprint="SOIC-8", unit=1, is_power=False,
                pins=(PinRef("U1", "1", "IN+"), PinRef("U1", "7", "VCC")),
            ),
            PartDescriptor(
                lib_id="Device:R", reference="R1", value="10k",
                footprint="R_0603", unit=1, is_power=False,
                pins=(PinRef("R1", "1", "~"), PinRef("R1", "2", "~")),
            ),
            PartDescriptor(
                lib_id="Device:C", reference="C1", value="100n",
                footprint="C_0603", unit=1, is_power=False,
                pins=(PinRef("C1", "1", "~"), PinRef("C1", "2", "~")),
            ),
        ),
        nets=(
            NetDescriptor("VCC", (PinRef("U1", "7", "VCC"),), is_power=True),
            NetDescriptor("Net_R1_1", (PinRef("R1", "1", "~"),)),
        ),
        diagnostics=(),
        source_file="test.kicad_sch",
    )


class TestNLDescription:
    """Natural language description generation."""

    def test_opamp_circuit(self) -> None:
        cir = _make_test_circuit_ir()
        desc = generate_nl_description(cir)
        assert "opamp" in desc.lower() or "analog" in desc.lower()
        assert "NE5532" in desc or "resistor" in desc.lower()

    def test_empty_circuit(self) -> None:
        cir = CircuitIR(parts=(), nets=(), diagnostics=(), source_file="empty")
        desc = generate_nl_description(cir)
        assert "empty" in desc.lower() or "no component" in desc.lower()

    def test_led_circuit(self) -> None:
        cir = CircuitIR(
            parts=(
                PartDescriptor("Device:LED", "D1", "Red", "LED_0805", 1, False, ()),
                PartDescriptor("Device:R", "R1", "330", "R_0805", 1, False, ()),
            ),
            nets=(), diagnostics=(), source_file="led.kicad_sch",
        )
        desc = generate_nl_description(cir)
        assert "LED" in desc or "led" in desc.lower()


class TestTrainingExample:
    """Training example creation."""

    def test_creates_chatml(self) -> None:
        cir = _make_test_circuit_ir()
        example = create_training_example(cir, "L1")
        chatml = example.to_chatml()

        assert "messages" in chatml
        assert len(chatml["messages"]) == 2
        assert chatml["messages"][0]["role"] == "user"
        assert chatml["messages"][1]["role"] == "assistant"
        assert "SKIDL" in chatml["messages"][1]["content"] or "Part(" in chatml["messages"][1]["content"]
        assert chatml["task_type"] == "nl_to_skidl"

    def test_user_message_has_description(self) -> None:
        cir = _make_test_circuit_ir()
        example = create_training_example(cir, "L1")
        assert "circuit" in example.user_message.lower()
        assert "SKIDL" in example.user_message


class TestConvertSchematic:
    """End-to-end schematic → training data."""

    def test_convert_led_fixture(self, tmp_path: Path) -> None:
        """Convert the LED fixture to training data."""
        if not _LED_FIXTURE.exists():
            pytest.skip(f"Fixture not found: {_LED_FIXTURE}")

        output = tmp_path / "training.jsonl"
        count = convert_schematic_to_training_data(_LED_FIXTURE, output)

        assert count == 1
        assert output.exists()

        # Verify the JSONL is valid.
        line = output.read_text().strip()
        data = json.loads(line)
        assert "messages" in data
        assert len(data["messages"]) == 2

    def test_batch_convert(self, tmp_path: Path) -> None:
        """Batch convert multiple schematics."""
        if not _LED_FIXTURE.exists():
            pytest.skip(f"Fixture not found: {_LED_FIXTURE}")

        output = tmp_path / "batch.jsonl"
        success, failure = batch_convert_schematics([_LED_FIXTURE], output)

        assert success + failure == 1
        if success:
            assert output.exists()
