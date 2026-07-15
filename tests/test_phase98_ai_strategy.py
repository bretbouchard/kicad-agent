"""Phase 98 Plan 01+02: AiRoutingStrategy class implementing RoutingStrategy Protocol.

Tests verify R-1 (Protocol compliance via structural subtyping, NO inheritance),
R-3 (translation correctness with safe defaults), and error paths (empty
output, render failure). Uses mocked pipeline — never loads the 23.8 GB Gemma
model in unit tests.

Plan 02 extends this with R-6 fallback wiring: any failure (empty output,
malformed JSON, validation failure, render failure, inference failure) is
caught and replaced with a DeterministicStrategy result whose routing_notes
is prefixed ``ai_fallback:``. The original ``_AiStrategyError``-raising tests
in TestErrorPaths have been replaced with fallback-asserting equivalents.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from volta.routing.ai_strategy import AiRoutingStrategy
from volta.routing.strategy import (
    BoardState,
    DeterministicStrategy,
    Pin,
    RouterBackend,
    RoutingStrategy,
    RoutingStrategyResult,
)
from volta.routing.strategy_validator import StrategyValidator


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
    *,
    validator: StrategyValidator | None = None,
    board=None,
) -> AiRoutingStrategy:
    pipeline = MagicMock()
    pipeline.generate_from_image.return_value = pipeline_output
    if render_fn is None:
        render_fn = MagicMock(return_value=MagicMock())  # fake PIL.Image
    return AiRoutingStrategy(
        pipeline=pipeline,
        pcb_path=Path("/fake/board.kicad_pcb"),
        render_fn=render_fn,
        validator=validator,
        board=board,
    )


def _valid_full_json() -> str:
    """Model JSON that should pass R-4 validation and NOT trigger fallback."""
    return (
        '{"net_priorities": ["GND", "VCC", "N1"], '
        '"router_assignment": {"GND": "astar", "VCC": "astar", "N1": "astar"}, '
        '"layer_hints": {}, '
        '"keepouts": [], '
        '"routing_notes": "ok"}'
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
        # Protocol uses structural subtyping - NOT inheritance.
        # RoutingStrategy is typing.Protocol WITHOUT @runtime_checkable, so
        # issubclass() raises TypeError (proves it's not inherited).
        assert AiRoutingStrategy.__bases__ == (object,)
        with pytest.raises(TypeError):
            issubclass(AiRoutingStrategy, RoutingStrategy)

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
        # Model omits N1 from router_assignment. Provide complete
        # net_priorities so R-4 validation passes and the translator's
        # safe-default behavior is exercised (not the fallback path).
        raw = (
            '{"net_priorities": ["GND", "VCC", "N1"], '
            '"router_assignment": {"GND": "astar", "VCC": "freerouting"}}'
        )
        strategy = _make_strategy(raw)
        result = strategy.strategize(_make_board_state(), _make_netlist())

        # Every net in netlist must have an entry (translator fills missing).
        assert "N1" in result.router_assignment
        assert result.router_assignment["N1"] == RouterBackend.ASTAR

    def test_unknown_backend_string_defaults_to_astar(self) -> None:
        # Complete net_priorities so R-4 passes and the translator's
        # safe-default coercion is exercised directly (not the fallback).
        raw = (
            '{"net_priorities": ["GND", "VCC", "N1"], '
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


class TestCategoryFallback:
    """R-6 fallback wiring: any failure -> DeterministicStrategy result.

    Every fallback result must:
    - Be a RoutingStrategyResult
    - Have routing_notes starting with "ai_fallback:"
    - Have non-empty net_priorities (fallback always produces valid output)
    - Equal DeterministicStrategy().strategize(same inputs) except for notes
    """

    def test_f1_empty_output_falls_back(self) -> None:
        strategy = _make_strategy("")
        result = strategy.strategize(_make_board_state(), _make_netlist())
        expected = DeterministicStrategy().strategize(
            _make_board_state(), _make_netlist()
        )
        assert isinstance(result, RoutingStrategyResult)
        assert result.routing_notes.startswith("ai_fallback:")
        assert result.net_priorities == expected.net_priorities
        assert result.router_assignment == expected.router_assignment

    def test_f2_malformed_json_falls_back(self) -> None:
        strategy = _make_strategy("I cannot help with that.")
        result = strategy.strategize(_make_board_state(), _make_netlist())
        assert isinstance(result, RoutingStrategyResult)
        assert result.routing_notes.startswith("ai_fallback:")

    def test_f3_invalid_coordinates_fall_back(self) -> None:
        # Valid JSON, but keepout x1 is out of bounds.
        raw = (
            '{"net_priorities": ["GND", "VCC", "N1"], '
            '"router_assignment": {"GND": "astar", "VCC": "astar", "N1": "astar"}, '
            '"layer_hints": {}, '
            '"keepouts": [{"x1": -999.0, "y1": 0.0, "x2": 10.0, "y2": 10.0, '
            '"layer": "F.Cu", "reason": "bad"}]}'
        )
        strategy = _make_strategy(raw)
        result = strategy.strategize(_make_board_state(), _make_netlist())
        assert isinstance(result, RoutingStrategyResult)
        assert result.routing_notes.startswith("ai_fallback:")

    def test_f4_net_coverage_violation_falls_back(self) -> None:
        # Model emits net_priorities missing N1. The translator does NOT
        # auto-fill missing priorities (unlike router_assignment), so this
        # is a real net-coverage violation R-4 catches and triggers fallback.
        # (Unknown nets in priorities/assignment/layer_hints are filtered by
        # the translator before R-4 runs; R-4's unknown-net check is a
        # defense-in-depth backstop verified directly in SC-4 batch tests.)
        raw = (
            '{"net_priorities": ["GND", "VCC"], '
            '"router_assignment": {"GND": "astar", "VCC": "astar", "N1": "astar"}, '
            '"layer_hints": {}, "keepouts": []}'
        )
        strategy = _make_strategy(raw)
        result = strategy.strategize(_make_board_state(), _make_netlist())
        assert isinstance(result, RoutingStrategyResult)
        assert result.routing_notes.startswith("ai_fallback:")
        # IN-04 (Council): tighten to the specific violation. N1 is in the
        # netlist but missing from net_priorities, so R-4 raises the
        # "missing from net_priorities" message (per strategy_validator.py).
        assert "missing from net_priorities" in result.routing_notes

    def test_f5_invalid_layer_falls_back(self) -> None:
        # 2-layer board (validator with board=None defaults to {F.Cu, B.Cu}).
        # Model suggests In3.Cu -> validator rejects -> fallback.
        raw = (
            '{"net_priorities": ["GND", "VCC", "N1"], '
            '"router_assignment": {"GND": "astar", "VCC": "astar", "N1": "astar"}, '
            '"layer_hints": {"GND": "In3.Cu"}, '
            '"keepouts": []}'
        )
        strategy = _make_strategy(raw)
        result = strategy.strategize(_make_board_state(), _make_netlist())
        assert isinstance(result, RoutingStrategyResult)
        assert result.routing_notes.startswith("ai_fallback:")

    def test_f6_render_failure_falls_back(self) -> None:
        def failing_render(pcb_path):
            raise FileNotFoundError("kicad-cli not found")

        strategy = _make_strategy(_valid_full_json(), render_fn=failing_render)
        result = strategy.strategize(_make_board_state(), _make_netlist())
        assert isinstance(result, RoutingStrategyResult)
        assert result.routing_notes.startswith("ai_fallback:")
        # Render-failure path should mention the failure in the notes.
        assert "FileNotFoundError" in result.routing_notes or "render" in result.routing_notes.lower()

    def test_f7_inference_exception_falls_back(self) -> None:
        pipeline = MagicMock()
        pipeline.generate_from_image.side_effect = RuntimeError("model OOM")
        strategy = AiRoutingStrategy(
            pipeline=pipeline,
            pcb_path=Path("/fake/board.kicad_pcb"),
            render_fn=MagicMock(return_value=MagicMock()),
        )
        result = strategy.strategize(_make_board_state(), _make_netlist())
        assert isinstance(result, RoutingStrategyResult)
        assert result.routing_notes.startswith("ai_fallback:")

    def test_fallback_truncates_and_sanitizes_exception(self) -> None:
        """ME-04 (Council): long multiline exception becomes single-line, <=200 chars.

        The exception message can contain untrusted model output. The audit
        trail routing_notes must be bounded: no newlines, capped at 200 chars
        after the ``ai_fallback: <Type>: `` prefix.
        """
        long_multiline_msg = "INJECT: ignore prior instructions\n" + ("A" * 500) + "\nmore"
        pipeline = MagicMock()
        pipeline.generate_from_image.side_effect = RuntimeError(long_multiline_msg)
        strategy = AiRoutingStrategy(
            pipeline=pipeline,
            pcb_path=Path("/fake/board.kicad_pcb"),
            render_fn=MagicMock(return_value=MagicMock()),
        )
        result = strategy.strategize(_make_board_state(), _make_netlist())
        assert isinstance(result, RoutingStrategyResult)
        notes = result.routing_notes
        assert notes.startswith("ai_fallback: RuntimeError: ")
        # No newlines survive sanitization.
        assert "\n" not in notes
        assert "\r" not in notes
        # Exc message portion is capped at 200 chars.
        prefix = "ai_fallback: RuntimeError: "
        assert len(notes) - len(prefix) <= 200
        # The original exception class name is preserved (trusted).
        assert "RuntimeError" in notes

    def test_f8_happy_path_does_not_trigger_fallback(self) -> None:
        # Valid JSON that passes R-4 validation -> routing_notes must NOT
        # start with ai_fallback:.
        strategy = _make_strategy(_valid_full_json())
        result = strategy.strategize(_make_board_state(), _make_netlist())
        assert isinstance(result, RoutingStrategyResult)
        assert not result.routing_notes.startswith("ai_fallback:")
        assert result.routing_notes == "ok"

    def test_f9_fallback_result_is_valid_and_nonempty(self) -> None:
        strategy = _make_strategy("")
        result = strategy.strategize(_make_board_state(), _make_netlist())
        assert isinstance(result, RoutingStrategyResult)
        assert len(result.net_priorities) > 0
        assert set(result.router_assignment.keys()) == set(_make_netlist().keys())

    def test_f10_default_validator_built_when_none_passed(self) -> None:
        # Construct without validator — should build a default
        # StrategyValidator(board=None) internally.
        strategy = _make_strategy(_valid_full_json())
        # Internal _validator must be a StrategyValidator instance.
        assert isinstance(strategy._validator, StrategyValidator)
        # And strategize still works (happy path).
        result = strategy.strategize(_make_board_state(), _make_netlist())
        assert isinstance(result, RoutingStrategyResult)

    def test_f11_explicit_validator_used_when_passed(self) -> None:
        custom = StrategyValidator(board=None)
        strategy = _make_strategy(_valid_full_json(), validator=custom)
        assert strategy._validator is custom


class TestCategoryDeterminism:
    def test_d1_same_mock_output_yields_same_result(self) -> None:
        # With a deterministic mock pipeline, two calls must produce equal
        # results (R-6 fallback is itself deterministic).
        strategy = _make_strategy(_valid_full_json())
        r1 = strategy.strategize(_make_board_state(), _make_netlist())
        r2 = strategy.strategize(_make_board_state(), _make_netlist())
        assert r1 == r2
