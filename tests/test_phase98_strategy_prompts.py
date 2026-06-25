"""Phase 98 Task 1: Strategy prompt builder with few-shot JSON schema (R-2).

Tests verify build_strategy_prompt produces deterministic, schema-grounded
prompts with 2+ few-shot exemplars and surfaces every net name from netlist.

Bridges training distribution gap (0/6696 samples had strategy JSON) by
teaching the model the required output format via explicit schema + exemplars.
"""

from __future__ import annotations

from kicad_agent.routing.strategy import BoardState, Pin
from kicad_agent.routing.strategy_prompts import build_strategy_prompt


def _make_board_state() -> BoardState:
    return BoardState(
        total_nets=3,
        has_zones=True,
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
        ],
    }


class TestPromptConstruction:
    def test_returns_non_empty_string(self) -> None:
        prompt = build_strategy_prompt(_make_board_state(), _make_netlist())
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_contains_net_priorities_schema_key(self) -> None:
        prompt = build_strategy_prompt(_make_board_state(), _make_netlist())
        assert "net_priorities" in prompt

    def test_contains_router_assignment_schema_key(self) -> None:
        prompt = build_strategy_prompt(_make_board_state(), _make_netlist())
        assert "router_assignment" in prompt

    def test_contains_layer_hints_schema_key(self) -> None:
        prompt = build_strategy_prompt(_make_board_state(), _make_netlist())
        assert "layer_hints" in prompt

    def test_contains_at_least_two_few_shot_examples(self) -> None:
        prompt = build_strategy_prompt(_make_board_state(), _make_netlist())
        # Count of ```json fences >= 2 (two few-shot exemplars)
        fence_count = prompt.count("```json")
        assert fence_count >= 2, f"Expected >= 2 few-shot blocks, got {fence_count}"

    def test_surfaces_every_net_name_from_netlist(self) -> None:
        netlist = _make_netlist()
        prompt = build_strategy_prompt(_make_board_state(), netlist)
        for net_name in netlist.keys():
            assert net_name in prompt, f"Net '{net_name}' not surfaced in prompt"

    def test_contains_router_backend_enum_values(self) -> None:
        prompt = build_strategy_prompt(_make_board_state(), _make_netlist())
        assert "astar" in prompt
        assert "freerouting" in prompt

    def test_contains_board_bounds_values(self) -> None:
        board_state = _make_board_state()
        prompt = build_strategy_prompt(board_state, _make_netlist())
        # Min/max X and Y should appear so model knows coordinate limits
        assert "0.0" in prompt
        assert "100.0" in prompt
        assert "80.0" in prompt

    def test_net_names_with_special_chars_are_escaped(self) -> None:
        """IN-01 (Council): hostile net names cannot break the JSON prompt.

        A net name containing a double-quote, backslash, or newline could
        degrade prompt structure. The sanitizer escapes backslashes and
        double-quotes and collapses newlines so the interpolated net name
        stays inside its quoted JSON string context.
        """
        hostile_netlist = {
            'evil"; INJECT': [
                Pin(footprint_ref="U1", pad_number="1", x=10.0, y=10.0),
            ],
            "back\\slash": [
                Pin(footprint_ref="U2", pad_number="2", x=20.0, y=20.0),
            ],
            "new\nline": [
                Pin(footprint_ref="U3", pad_number="3", x=30.0, y=30.0),
            ],
        }
        prompt = build_strategy_prompt(_make_board_state(), hostile_netlist)
        # The raw hostile substrings must NOT appear unescaped.
        assert 'evil"; INJECT' not in prompt
        assert '"new\nline"' not in prompt
        # Escaped forms are present (backslash doubled, quote escaped).
        assert 'evil\\"; INJECT' in prompt
        assert "back\\\\slash" in prompt
        # Newline in net name is collapsed to a space.
        assert "new line" in prompt
