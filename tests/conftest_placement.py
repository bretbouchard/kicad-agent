"""Shared test fixtures for placement graph tests."""

import pytest

from kicad_agent.generation.intent import ComponentSpec, PositionSpec
from kicad_agent.generation.intent import NetSpec
from kicad_agent.placement.graph import PlacementGraph, netlist_to_placement_graph


@pytest.fixture
def sample_components() -> list[ComponentSpec]:
    """Five diverse components for placement graph testing.

    Includes: U1 (IC), R1 (resistor), C1 (cap), J1 (connector), L1 (inductor).
    """
    return [
        ComponentSpec(
            library_id="MCU_ST:STM32F103",
            reference="U1",
            value="STM32F103C8T6",
            position=PositionSpec(x=50.0, y=40.0),
        ),
        ComponentSpec(
            library_id="Device:R_Small_US",
            reference="R1",
            value="10k",
        ),
        ComponentSpec(
            library_id="Device:C_Small",
            reference="C1",
            value="100nF",
        ),
        ComponentSpec(
            library_id="Connector:Conn_01x04",
            reference="J1",
            value="I2C_HDR",
        ),
        ComponentSpec(
            library_id="Device:L_Small",
            reference="L1",
            value="4.7uH",
        ),
    ]


@pytest.fixture
def sample_nets() -> list[NetSpec]:
    """Three nets for placement graph testing.

    - SDA: signal net connecting U1 + R1
    - GND: power net connecting U1 + C1 + J1
    - VCC: power net connecting U1 + L1
    """
    return [
        NetSpec(name="SDA", pins=["U1.3", "R1.1"]),
        NetSpec(name="GND", pins=["U1.5", "C1.2", "J1.4"]),
        NetSpec(name="VCC", pins=["U1.10", "L1.2"]),
    ]


@pytest.fixture
def sample_board_dims() -> tuple[float, float]:
    """Standard board dimensions for testing: (100.0, 80.0)."""
    return (100.0, 80.0)


@pytest.fixture
def sample_placement_graph(
    sample_components: list[ComponentSpec],
    sample_nets: list[NetSpec],
    sample_board_dims: tuple[float, float],
) -> PlacementGraph:
    """PlacementGraph built from sample_components + sample_nets + sample_board_dims."""
    width, height = sample_board_dims
    graph = netlist_to_placement_graph(
        sample_components, sample_nets, width, height
    )
    return PlacementGraph(graph)
