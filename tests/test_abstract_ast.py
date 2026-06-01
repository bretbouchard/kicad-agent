"""Tests for Abstract AST: format-agnostic circuit models and validation.

Covers:
- PinType enum
- AbstractPin, AbstractComponent, AbstractNet, AbstractSheet, AbstractCircuit
- Position, RelativePosition, WireSegment helper models
- CircuitValidator with cross-model invariant checks
- JSON round-trip losslessness
- Fixture circuits for testing
"""

import json

import pytest


# ---------------------------------------------------------------------------
# Plan 55-01 Task 1: Abstract AST Models
# ---------------------------------------------------------------------------


class TestPinType:
    """Test PinType enum."""

    def test_has_eight_members(self):
        """PinType enum has 8 members."""
        from kicad_agent.abstract_ast.models import PinType

        assert len(PinType) == 8

    def test_contains_expected_types(self):
        """PinType has INPUT, OUTPUT, BIDI, PASSIVE, POWER_IN, POWER_OUT, UNSPECIFIED, NO_CONNECT."""
        from kicad_agent.abstract_ast.models import PinType

        expected = {"INPUT", "OUTPUT", "BIDI", "PASSIVE", "POWER_IN", "POWER_OUT", "UNSPECIFIED", "NO_CONNECT"}
        actual = {pt.name for pt in PinType}
        assert actual == expected


class TestPosition:
    """Test Position helper model."""

    def test_position_has_x_y(self):
        from kicad_agent.abstract_ast.models import Position

        p = Position(x=10.0, y=20.0)
        assert p.x == 10.0
        assert p.y == 20.0

    def test_wire_segment_has_start_end(self):
        from kicad_agent.abstract_ast.models import WireSegment, Position

        ws = WireSegment(
            start=Position(x=0.0, y=0.0),
            end=Position(x=10.0, y=10.0),
        )
        assert ws.start.x == 0.0
        assert ws.end.x == 10.0


class TestAbstractPin:
    """Test AbstractPin model."""

    def test_validates_with_required_fields(self):
        from kicad_agent.abstract_ast.models import AbstractPin, PinType

        pin = AbstractPin(number="1", name="OUT", pin_type=PinType.OUTPUT)
        assert pin.number == "1"
        assert pin.pin_type == PinType.OUTPUT

    def test_rejects_missing_fields(self):
        from kicad_agent.abstract_ast.models import AbstractPin

        with pytest.raises(Exception):
            AbstractPin(number="", name="OUT", pin_type="output")


class TestAbstractComponent:
    """Test AbstractComponent model."""

    def test_validates_with_required_fields(self):
        from kicad_agent.abstract_ast.models import AbstractComponent

        comp = AbstractComponent(ref="R1", lib_id="Device:R", value="10k")
        assert comp.ref == "R1"
        assert comp.value == "10k"

    def test_rejects_empty_ref(self):
        from kicad_agent.abstract_ast.models import AbstractComponent

        with pytest.raises(Exception):
            AbstractComponent(ref="", lib_id="Device:R")

    def test_rejects_empty_lib_id(self):
        from kicad_agent.abstract_ast.models import AbstractComponent

        with pytest.raises(Exception):
            AbstractComponent(ref="R1", lib_id="")

    def test_rejects_duplicate_pin_numbers(self):
        from kicad_agent.abstract_ast.models import AbstractComponent, AbstractPin, PinType

        with pytest.raises(Exception):
            AbstractComponent(
                ref="U1",
                lib_id="Amplifier:LM358",
                pins=[
                    AbstractPin(number="1", name="OUT", pin_type=PinType.OUTPUT),
                    AbstractPin(number="1", name="DUP", pin_type=PinType.INPUT),
                ],
            )

    def test_optional_fields_default_correctly(self):
        from kicad_agent.abstract_ast.models import AbstractComponent

        comp = AbstractComponent(ref="R1", lib_id="Device:R")
        assert comp.value == ""
        assert comp.footprint is None
        assert comp.position is None
        assert comp.rotation == 0.0
        assert comp.pins == []
        assert comp.properties == {}


class TestAbstractNet:
    """Test AbstractNet model."""

    def test_validates_with_name_and_pin_refs(self):
        from kicad_agent.abstract_ast.models import AbstractNet

        net = AbstractNet(name="VCC", pin_refs=[("U1", "8"), ("R1", "1")])
        assert net.name == "VCC"
        assert len(net.pin_refs) == 2

    def test_rejects_empty_name(self):
        from kicad_agent.abstract_ast.models import AbstractNet

        with pytest.raises(Exception):
            AbstractNet(name="", pin_refs=[("R1", "1")])

    def test_rejects_empty_pin_refs(self):
        from kicad_agent.abstract_ast.models import AbstractNet

        with pytest.raises(Exception):
            AbstractNet(name="VCC", pin_refs=[])


class TestAbstractSheet:
    """Test AbstractSheet model."""

    def test_validates_with_components_and_nets(self):
        from kicad_agent.abstract_ast.models import AbstractSheet, AbstractComponent, AbstractNet

        sheet = AbstractSheet(
            name="main",
            components=[AbstractComponent(ref="R1", lib_id="Device:R")],
            nets=[AbstractNet(name="VCC", pin_refs=[("R1", "1")])],
        )
        assert sheet.name == "main"
        assert len(sheet.components) == 1
        assert len(sheet.nets) == 1


class TestAbstractCircuit:
    """Test AbstractCircuit model."""

    def test_validates_with_all_fields(self):
        from kicad_agent.abstract_ast.models import AbstractCircuit, AbstractComponent, AbstractNet

        circuit = AbstractCircuit(
            name="test_circuit",
            components=[AbstractComponent(ref="R1", lib_id="Device:R")],
            nets=[AbstractNet(name="VCC", pin_refs=[("R1", "1")])],
        )
        assert circuit.name == "test_circuit"
        assert len(circuit.components) == 1

    def test_json_round_trip_is_lossless(self):
        from kicad_agent.abstract_ast.models import AbstractCircuit, AbstractComponent, AbstractNet, PinType, AbstractPin

        circuit = AbstractCircuit(
            name="round_trip_test",
            components=[
                AbstractComponent(
                    ref="U1",
                    lib_id="Amplifier:LM358",
                    value="NE5532",
                    pins=[
                        AbstractPin(number="1", name="OUT", pin_type=PinType.OUTPUT),
                        AbstractPin(number="2", name="IN-", pin_type=PinType.INPUT),
                    ],
                ),
            ],
            nets=[
                AbstractNet(name="feedback", pin_refs=[("U1", "1"), ("U1", "2")]),
            ],
            metadata={"source": "test"},
        )

        # Serialize to JSON and back
        json_str = circuit.model_dump_json()
        restored = AbstractCircuit.model_validate_json(json_str)

        # Verify lossless
        assert restored.name == circuit.name
        assert len(restored.components) == len(circuit.components)
        assert restored.components[0].ref == "U1"
        assert len(restored.components[0].pins) == 2
        assert restored.nets[0].name == "feedback"
        assert restored.metadata["source"] == "test"

        # Full round-trip
        assert restored.model_dump_json() == json_str


class TestFixtureCircuits:
    """Test fixture circuits for use in other tests."""

    def test_minimal_opamp_circuit(self):
        """Create a minimal circuit with R1, C1, opamp U1 and feedback net."""
        from tests.test_abstract_ast import FixtureCircuits

        circuit = FixtureCircuits.minimal_opamp_circuit()
        assert len(circuit.components) == 3  # R1, C1, U1
        assert len(circuit.nets) == 1  # feedback
        assert circuit.nets[0].name == "feedback"
        assert len(circuit.nets[0].pin_refs) == 2  # R1.1 -> U1.out

    def test_multi_sheet_circuit(self):
        """Create a multi-sheet circuit with hierarchical labels."""
        from tests.test_abstract_ast import FixtureCircuits

        circuit = FixtureCircuits.multi_sheet_circuit()
        assert len(circuit.sheets) >= 2
        assert any(s.name == "power" for s in circuit.sheets)
        assert any(s.name == "analog" for s in circuit.sheets)


class FixtureCircuits:
    """Factory for test fixture circuits."""

    @staticmethod
    def minimal_opamp_circuit():
        from kicad_agent.abstract_ast.models import (
            AbstractCircuit,
            AbstractComponent,
            AbstractNet,
            AbstractPin,
            PinType,
        )

        return AbstractCircuit(
            name="minimal_opamp",
            components=[
                AbstractComponent(ref="R1", lib_id="Device:R", value="10k"),
                AbstractComponent(ref="C1", lib_id="Device:C", value="100nF"),
                AbstractComponent(
                    ref="U1",
                    lib_id="Amplifier_Operational:LM358",
                    value="NE5532",
                    pins=[
                        AbstractPin(number="1", name="OUT", pin_type=PinType.OUTPUT),
                        AbstractPin(number="2", name="IN-", pin_type=PinType.INPUT),
                        AbstractPin(number="3", name="IN+", pin_type=PinType.INPUT),
                        AbstractPin(number="4", name="VEE", pin_type=PinType.POWER_IN),
                        AbstractPin(number="8", name="VCC", pin_type=PinType.POWER_IN),
                    ],
                ),
            ],
            nets=[
                AbstractNet(name="feedback", pin_refs=[("R1", "1"), ("U1", "1")]),
            ],
        )

    @staticmethod
    def multi_sheet_circuit():
        from kicad_agent.abstract_ast.models import (
            AbstractCircuit,
            AbstractComponent,
            AbstractNet,
            AbstractSheet,
        )

        return AbstractCircuit(
            name="multi_sheet",
            sheets=[
                AbstractSheet(
                    name="power",
                    components=[
                        AbstractComponent(ref="U2", lib_id="Regulator:LM7805", value="LM7805"),
                    ],
                    nets=[
                        AbstractNet(name="VCC", pin_refs=[("U2", "3")]),
                    ],
                    hierarchical_labels=["VCC", "GND"],
                ),
                AbstractSheet(
                    name="analog",
                    components=[
                        AbstractComponent(ref="R2", lib_id="Device:R", value="4.7k"),
                    ],
                    nets=[
                        AbstractNet(name="VCC", pin_refs=[("R2", "1")]),
                    ],
                    hierarchical_labels=["VCC", "GND"],
                ),
            ],
        )


# ---------------------------------------------------------------------------
# Plan 55-01 Task 2: Circuit Validation
# ---------------------------------------------------------------------------


class TestCircuitValidator:
    """Test CircuitValidator cross-model invariant checks."""

    def test_valid_circuit_passes(self):
        """Valid fixture circuit passes with no errors."""
        circuit = FixtureCircuits.minimal_opamp_circuit()
        from kicad_agent.abstract_ast.validation import CircuitValidator

        issues = CircuitValidator.validate(circuit)
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0

    def test_rejects_duplicate_refs_in_circuit(self):
        """CircuitValidator rejects duplicate component refs within a circuit."""
        from kicad_agent.abstract_ast.validation import CircuitValidator

        circuit = FixtureCircuits.minimal_opamp_circuit()
        circuit.components.append(circuit.components[0].model_copy())
        issues = CircuitValidator.validate(circuit)
        assert any(
            i.severity == "error" and "duplicate" in i.description.lower()
            for i in issues
        )

    def test_rejects_duplicate_refs_in_sheet(self):
        """CircuitValidator rejects duplicate refs within a sheet."""
        from kicad_agent.abstract_ast.validation import CircuitValidator

        circuit = FixtureCircuits.multi_sheet_circuit()
        sheet = circuit.sheets[0]
        sheet.components.append(sheet.components[0].model_copy())
        issues = CircuitValidator.validate(circuit)
        assert any(
            i.severity == "error" and "duplicate" in i.description.lower()
            for i in issues
        )

    def test_rejects_nonexistent_component_ref(self):
        """CircuitValidator rejects net pin_refs referencing non-existent components."""
        from kicad_agent.abstract_ast.models import AbstractCircuit, AbstractNet
        from kicad_agent.abstract_ast.validation import CircuitValidator

        circuit = AbstractCircuit(
            nets=[AbstractNet(name="ghost_net", pin_refs=[("X99", "1")])],
        )
        issues = CircuitValidator.validate(circuit)
        assert any(
            i.severity == "error" and "non-existent" in i.description.lower()
            for i in issues
        )

    def test_rejects_nonexistent_pin_on_component(self):
        """CircuitValidator rejects pin_refs referencing non-existent pin numbers."""
        from kicad_agent.abstract_ast.validation import CircuitValidator

        circuit = FixtureCircuits.minimal_opamp_circuit()
        # Add a net referencing pin "99" on U1 which doesn't exist
        circuit.nets.append(
            __import__("kicad_agent.abstract_ast.models", fromlist=["AbstractNet"]).AbstractNet(
                name="bad_net", pin_refs=[("U1", "99")]
            )
        )
        issues = CircuitValidator.validate(circuit)
        assert any(
            i.severity == "error" and ("pin" in i.description.lower() or "99" in i.description)
            for i in issues
        )

    def test_returns_validation_issues(self):
        """CircuitValidator returns list of ValidationIssue with severity and description."""
        from kicad_agent.abstract_ast.validation import CircuitValidator, ValidationIssue

        circuit = FixtureCircuits.minimal_opamp_circuit()
        issues = CircuitValidator.validate(circuit)
        assert isinstance(issues, list)
        # All issues should be ValidationIssue instances
        for issue in issues:
            assert isinstance(issue, ValidationIssue)
            assert issue.severity in ("error", "warning")
            assert len(issue.description) > 0

    def test_warns_on_single_pin_net(self):
        """CircuitValidator warns (not errors) on nets with only 1 pin connection."""
        from kicad_agent.abstract_ast.models import AbstractCircuit, AbstractNet, AbstractComponent
        from kicad_agent.abstract_ast.validation import CircuitValidator

        circuit = AbstractCircuit(
            components=[AbstractComponent(ref="R1", lib_id="Device:R")],
            nets=[AbstractNet(name="lonely", pin_refs=[("R1", "1")])],
        )
        issues = CircuitValidator.validate(circuit)
        single_pin_warnings = [
            i for i in issues
            if i.severity == "warning" and i.category == "single_pin_net"
        ]
        assert len(single_pin_warnings) > 0

    def test_warns_on_empty_circuit(self):
        """CircuitValidator warns on empty circuits (no components)."""
        from kicad_agent.abstract_ast.models import AbstractCircuit
        from kicad_agent.abstract_ast.validation import CircuitValidator

        circuit = AbstractCircuit()
        issues = CircuitValidator.validate(circuit)
        assert any(
            i.severity == "warning" and i.category == "empty_circuit"
            for i in issues
        )
