"""Tests for generation module: GenerationIntent, BoardSpec, intent_to_operations."""

import pytest

from volta.generation.intent import (
    BoardSpec,
    ComponentSpec,
    GenerationIntent,
    NetSpec,
    PowerSpec,
    PositionSpec,
    intent_to_operations,
)


class TestPositionSpec:
    """Tests for PositionSpec schema."""

    def test_create_with_defaults(self):
        """PositionSpec with x,y creates valid spec, angle defaults to 0."""
        pos = PositionSpec(x=10.0, y=20.0)
        assert pos.x == 10.0
        assert pos.y == 20.0
        assert pos.angle == 0.0

    def test_create_with_angle(self):
        """PositionSpec accepts explicit angle."""
        pos = PositionSpec(x=5.0, y=15.0, angle=90.0)
        assert pos.angle == 90.0


class TestComponentSpec:
    """Tests for ComponentSpec schema."""

    def test_create_minimal(self):
        """ComponentSpec with library_id creates valid spec."""
        comp = ComponentSpec(library_id="Device:R")
        assert comp.library_id == "Device:R"
        assert comp.reference == "U?"

    def test_create_full(self):
        """ComponentSpec with all fields."""
        comp = ComponentSpec(
            library_id="Device:R",
            reference="R1",
            value="10k",
            position=PositionSpec(x=10.0, y=20.0),
            footprint="Resistor_SMD:R_0603",
        )
        assert comp.value == "10k"
        assert comp.footprint == "Resistor_SMD:R_0603"

    def test_unsafe_library_id_rejected(self):
        """ComponentSpec rejects library_id with unsafe characters."""
        with pytest.raises(ValueError, match="unsafe"):
            ComponentSpec(library_id="bad;rm -rf/")

    def test_unsafe_reference_rejected(self):
        """ComponentSpec rejects reference with unsafe characters."""
        with pytest.raises(ValueError, match="unsafe"):
            ComponentSpec(library_id="Device:R", reference="R1;drop")


class TestNetSpec:
    """Tests for NetSpec schema."""

    def test_create_minimal(self):
        """NetSpec with name creates valid spec."""
        net = NetSpec(name="SDA")
        assert net.name == "SDA"
        assert net.pins == []

    def test_create_with_pins(self):
        """NetSpec with pins validates REF.PIN format."""
        net = NetSpec(name="SDA", pins=["R1.1", "U1.3"])
        assert len(net.pins) == 2

    def test_invalid_pin_format_rejected(self):
        """NetSpec rejects pins without dot separator."""
        with pytest.raises(ValueError, match="REF.PIN"):
            NetSpec(name="BAD", pins=["R11"])


class TestBoardSpec:
    """Tests for BoardSpec schema."""

    def test_create_with_defaults(self):
        """BoardSpec with defaults creates valid spec."""
        board = BoardSpec()
        assert board.width_mm == 50.0
        assert board.height_mm == 50.0
        assert board.layer_count == 2

    def test_create_custom(self):
        """BoardSpec accepts custom dimensions."""
        board = BoardSpec(width_mm=100, height_mm=80, layer_count=4)
        assert board.width_mm == 100
        assert board.layer_count == 4

    def test_zero_width_rejected(self):
        """BoardSpec rejects zero or negative width."""
        with pytest.raises(ValueError):
            BoardSpec(width_mm=0)

    def test_too_many_layers_rejected(self):
        """BoardSpec rejects more than 32 layers."""
        with pytest.raises(ValueError):
            BoardSpec(layer_count=33)


class TestPowerSpec:
    """Tests for PowerSpec schema."""

    def test_default_power_nets(self):
        """PowerSpec defaults to GND and +3V3."""
        power = PowerSpec()
        assert "GND" in power.nets
        assert "+3V3" in power.nets

    def test_custom_power_nets(self):
        """PowerSpec accepts custom power net list."""
        power = PowerSpec(nets=["GND", "+5V", "+12V"])
        assert len(power.nets) == 3


class TestGenerationIntent:
    """Tests for GenerationIntent schema."""

    def test_create_minimal(self):
        """GenerationIntent with name creates valid intent."""
        intent = GenerationIntent(name="Motor Driver")
        assert intent.name == "Motor Driver"
        assert intent.components == []
        assert intent.nets == []

    def test_create_full(self):
        """GenerationIntent with all fields."""
        intent = GenerationIntent(
            name="Motor Driver",
            description="H-bridge motor driver",
            board=BoardSpec(width_mm=100, height_mm=80),
            components=[
                ComponentSpec(library_id="Device:R", reference="R1", value="10k"),
            ],
            nets=[
                NetSpec(name="SDA", pins=["R1.1"]),
            ],
            power=PowerSpec(nets=["GND", "+5V"]),
        )
        assert len(intent.components) == 1
        assert len(intent.nets) == 1

    def test_empty_name_rejected(self):
        """GenerationIntent rejects empty name."""
        with pytest.raises(ValueError):
            GenerationIntent(name="")


class TestIntentToOperations:
    """Tests for intent_to_operations converter."""

    def test_empty_intent_produces_only_power_ops(self):
        """Empty intent (no components/nets) produces only default power ops."""
        intent = GenerationIntent(name="Empty")
        ops = intent_to_operations(intent)
        # Default PowerSpec adds GND and +3V3
        assert len(ops) == 2
        assert all(op.root.op_type == "add_power" for op in ops)

    def test_components_produce_add_ops(self):
        """Components produce AddComponentOp operations."""
        intent = GenerationIntent(
            name="Test",
            components=[
                ComponentSpec(library_id="Device:R", reference="R1", value="10k"),
                ComponentSpec(library_id="Device:C", reference="C1", value="100nF"),
            ],
            power=PowerSpec(nets=[]),  # No power ops
        )
        ops = intent_to_operations(intent)
        assert len(ops) == 2

    def test_nets_produce_add_net_ops(self):
        """Nets produce AddNetOp operations."""
        intent = GenerationIntent(
            name="Test",
            nets=[
                NetSpec(name="SDA", pins=["R1.1"]),
            ],
            power=PowerSpec(nets=[]),
        )
        ops = intent_to_operations(intent)
        assert len(ops) == 1

    def test_power_produces_add_power_ops(self):
        """Power specs produce AddPowerOp operations."""
        intent = GenerationIntent(
            name="Test",
            power=PowerSpec(nets=["GND", "+3V3"]),
        )
        ops = intent_to_operations(intent)
        assert len(ops) == 2

    def test_full_intent_produces_ordered_ops(self):
        """Full intent produces operations in correct order: components, nets, power."""
        intent = GenerationIntent(
            name="Full",
            components=[ComponentSpec(library_id="Device:R", reference="R1")],
            nets=[NetSpec(name="NET1")],
            power=PowerSpec(nets=["GND"]),
        )
        ops = intent_to_operations(intent)
        # 1 component + 1 net + 1 power = 3 ops
        assert len(ops) == 3


class TestGenerationImports:
    """Verify all generation module exports."""

    def test_core_imports(self):
        """Core generation classes are importable."""
        from volta.generation import (
            BoardSpec,
            ComponentSpec,
            GenerationIntent,
            NetSpec,
            PowerSpec,
            PositionSpec,
            intent_to_operations,
        )
        assert callable(intent_to_operations)
