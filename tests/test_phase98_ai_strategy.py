"""Phase 98 Task 3: AiRoutingStrategy class implementing RoutingStrategy Protocol.

Tests verify R-1 (Protocol compliance via structural subtyping, NO inheritance),
R-3 (translation correctness with safe defaults), and error paths (empty
output, render failure). Uses mocked pipeline — never loads the 23.8 GB Gemma
model in unit tests.

Fallback wiring (R-6) lives in Plan 98-02; this plan tests the error-raising
path directly via _AiStrategyError.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kicad_agent.routing.ai_strategy import AiRoutingStrategy, _AiStrategyError
from kicad_agent.routing.strategy import (
    BoardState,
    Pin,
    RouterBackend,
    RoutingStrategy,
    RoutingStrategyResult,
)


def _make_board_state(total_nets: int = 3) -> BoardState:
    return BoardState(
        total_nets=total_nets,
        has_zones=False,
        board_bounds=(0.0, 0.0, 100.0, 80.0),
        net_classes=("Power", "Signal"),
    )


def _make_netlist() -> dict[str, list[Pin]]:
    return {
        "GND": [
            Pin(footprint_ref="U1", pad_number="1", x=10.0, y=10.0),
            Pin(footprint_ref="U2", pad_number="2", x=20.0, y=20.0),
        ],
        "VCC": [
            Pin(footprint_ref="U1", pad_number="3", x=15.0, y=15.0),
            Pin(footprint_ref="U2", pad_number="4", x=25.0, y=25.0),
        ],
        "N1": [
            Pin(footprint_ref="U1", pad_number="5", x=30.0, y=30.0),
            Pin(footprint_ref="U2", pad_number="6", x=35.0, y=35.0),
        ],
    }


def _make_strategy(
    pipeline_output: str = '{"net_priorities": []}',
    render_fn=None,
) -> AiRoutingStrategy:
    pipeline = MagicMock()
    pipeline.generate_from_image.return_value = pipeline_output
    if render_fn is None:
        render_fn = MagicMock(return_value=MagicMock())  # fake PIL.Image
    return AiRoutingStrategy(
        pipeline=pipeline,
        pcb_path=Path("/fake/board.kicad_pcb"),
        render_fn=render_fn,
    )


class TestProtocolCompliance:
    def test_strategize_returns_routing_strategy_result(self) -> None:
        strategy = _make_strategy(
            '{"net_priorities": ["GND"], "router_assignment": {"GND": "astar"}}'
        )
        result = strategy.strategize(_make_board_state(), _make_netlist())
        assert isinstance(result, RoutingStrategyResult)

    def test_strategize_signature_matches_protocol(self) -> None:
        sig = inspect.signature(AiRoutingStrategy.strategize)
        params = list(sig.parameters.keys())
        assert params == ["self", "board_state", "netlist"]

    def test_no_inheritance_from_protocol(self) -> None:
        # Protocol uses structural subtyping — NOT inheritance
        assert AiRoutingStrategy.__bases__ == (object,)
        assert not issubclass(AiRoutingStrategy, RoutingStrategy)

    def test_has_strategize_method(self) -> None:
        assert hasattr(AiRoutingStrategy, "strategize")
        assert callable(getattr(AiRoutingStrategy, "strategize"))


class TestResultTranslation:
    def test_full_happy_path_translation(self) -> None:
        raw = (
            '{"net_priorities": ["GND", "VCC", "N1"], '
            '"router_assignment": {"GND": "astar", "VCC": "freerouting", "N1": "astar"}, '
            '"layer_hints": {"GND": "F.Cu"}, '
            '"keepouts": [], '
            '"routing_notes": "ok"}'
        )
        strategy = _make_strategy(raw)
        result = strategy.strategize(_make_board_state(), _make_netlist())

        assert result.net_priorities == ("GND", "VCC", "N1")
        assert result.router_assignment["GND"] == RouterBackend.ASTAR
        assert result.router_assignment["VCC"] == RouterBackend.FREEROUTING
        assert result.router_assignment["N1"] == RouterBackend.ASTAR
        assert result.layer_hints == {"GND": "F.Cu"}
        assert result.routing_notes == "ok"

    def test_missing_net_in_router_assignment_defaults_to_astar(self) -> None:
        # Model omits N1 from router_assignment
        raw = (
            '{"net_priorities": ["GND", "VCC"], '
            '"router_assignment": {"GND": "astar", "VCC": "freerouting"}}'
        )
        strategy = _make_strategy(raw)
        result = strategy.strategize(_make_board_state(), _make_netlist())

        # Every net in netlist must have an entry
        assert "N1" in result.router_assignment
        assert result.router_assignment["N1"] == RouterBackend.ASTAR

    def test_unknown_backend_string_defaults_to_astar(self) -> None:
        raw = (
            '{"net_priorities": ["GND"], '
            '"router_assignment": {"GND": "magic_router", "VCC": "astar", "N1": "astar"}}'
        )
        strategy = _make_strategy(raw)
        result = strategy.strategize(_make_board_state(), _make_netlist())

        assert result.router_assignment["GND"] == RouterBackend.ASTAR

    def test_extra_net_in_router_assignment_dropped(self) -> None:
        # Model emits a net not in netlist — translator should drop it (permissive)
        raw = (
            '{"net_priorities": ["GND", "VCC", "N1"], '
            '"router_assignment": {"GND": "astar", "VCC": "astar", "N1": "astar", '
            '"BOGUS": "freerouting"}}'
        )
        strategy = _make_strategy(raw)
        result = strategy.strategize(_make_board_state(), _make_netlist())

        assert "BOGUS" not in result.router_assignment


class TestErrorPaths:
    def test_empty_model_output_raises_ai_strategy_error(self) -> None:
        strategy = _make_strategy("")
        with pytest.raises(_AiStrategyError):
            strategy.strategize(_make_board_state(), _make_netlist())

    def test_render_failure_raises_ai_strategy_error(self) -> None:
        def failing_render(pcb_path):
            raise RuntimeError("kicad-cli exploded")

        strategy = _make_strategy('{"net_priorities": []}', render_fn=failing_render)
        with pytest.raises(_AiStrategyError, match="render"):
            strategy.strategize(_make_board_state(), _make_netlist())

    def test_unparseable_output_raises_ai_strategy_error(self) -> None:
        strategy = _make_strategy("totally not json at all")
        with pytest.raises(_AiStrategyError):
            strategy.strategize(_make_board_state(), _make_netlist())
