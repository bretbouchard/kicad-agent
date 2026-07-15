"""Tests for NetCompletionFiller (GAP-05)."""

import pytest
from unittest.mock import MagicMock, patch

from volta.analysis.gap_analyzer import (
    BoardInfo,
    GapReport,
    IncompleteNet,
    RoutingStats,
    UnroutedNet,
)
from volta.analysis.net_completion_filler import NetCompletionFiller


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
def gap_report(board_info):
    return GapReport(
        board_info=board_info,
        routing_stats=RoutingStats(
            total_nets=20,
            routed_nets=15,
            unrouted_nets=3,
            incomplete_nets=2,
            route_percentage=75.0,
        ),
        unrouted_nets=(
            UnroutedNet(
                net_name="NET_A",
                pad_count=2,
                pin_positions=((10.0, 20.0), (30.0, 20.0)),
                nearest_obstacle_distance=5.0,
            ),
            UnroutedNet(
                net_name="NET_B",
                pad_count=3,
                pin_positions=((10.0, 30.0), (50.0, 30.0), (70.0, 30.0)),
                nearest_obstacle_distance=2.0,
            ),
            UnroutedNet(
                net_name="NET_C",
                pad_count=2,
                pin_positions=((10.0, 40.0), (90.0, 40.0)),
                nearest_obstacle_distance=1.0,
            ),
        ),
        incomplete_nets=(
            IncompleteNet(
                net_name="NET_D",
                routed_pins=((10.0, 50.0),),
                unrouted_pins=((60.0, 50.0),),
                gap_distance=50.0,
            ),
            IncompleteNet(
                net_name="NET_E",
                routed_pins=((20.0, 60.0),),
                unrouted_pins=((40.0, 60.0),),
                gap_distance=20.0,
            ),
        ),
        drc_violations=(),
        net_naming_issues=(),
    )


class TestDeterministicGeneration:
    """Deterministic mode (no AI)."""

    def test_generates_ops_for_unrouted(self, gap_report, board_info):
        filler = NetCompletionFiller(target_file="test.kicad_pcb", use_ai=False)
        ops = filler.generate_ops(gap_report, board_info)
        assert len(ops) == 5  # 3 unrouted + 2 incomplete

    def test_op_type_is_auto_route(self, gap_report, board_info):
        filler = NetCompletionFiller(target_file="test.kicad_pcb", use_ai=False)
        ops = filler.generate_ops(gap_report, board_info)
        for op in ops:
            assert op["op_type"] == "auto_route"

    def test_target_file_set(self, gap_report, board_info):
        filler = NetCompletionFiller(target_file="my_board.kicad_pcb", use_ai=False)
        ops = filler.generate_ops(gap_report, board_info)
        for op in ops:
            assert op["target_file"] == "my_board.kicad_pcb"

    def test_nets_specified(self, gap_report, board_info):
        filler = NetCompletionFiller(target_file="test.kicad_pcb", use_ai=False)
        ops = filler.generate_ops(gap_report, board_info)
        net_names = [op["nets"][0] for op in ops]
        assert "NET_A" in net_names
        assert "NET_B" in net_names
        assert "NET_C" in net_names
        assert "NET_D" in net_names
        assert "NET_E" in net_names

    def test_layers_default_both(self, gap_report, board_info):
        filler = NetCompletionFiller(target_file="test.kicad_pcb", use_ai=False)
        ops = filler.generate_ops(gap_report, board_info)
        for op in ops:
            assert "F.Cu" in op["layers"][0]
            assert "B.Cu" in op["layers"][0]

    def test_single_layer_board(self, board_info):
        single_layer_board = BoardInfo(
            file_path="test.kicad_pcb",
            component_count=5,
            net_count=10,
            layer_count=1,
            bounds=None,
        )
        report = GapReport(
            board_info=single_layer_board,
            routing_stats=RoutingStats(10, 8, 2, 0, 80.0),
            unrouted_nets=(
                UnroutedNet("NET_X", 2, ((1.0, 1.0), (2.0, 2.0)), 10.0),
            ),
            incomplete_nets=(),
            drc_violations=(),
            net_naming_issues=(),
        )
        filler = NetCompletionFiller(target_file="test.kicad_pcb", use_ai=False)
        ops = filler.generate_ops(report, single_layer_board)
        assert ops[0]["layers"] == ["F.Cu"]

    def test_empty_report(self, board_info):
        empty_report = GapReport(
            board_info=board_info,
            routing_stats=RoutingStats(10, 10, 0, 0, 100.0),
            unrouted_nets=(),
            incomplete_nets=(),
            drc_violations=(),
            net_naming_issues=(),
        )
        filler = NetCompletionFiller(target_file="test.kicad_pcb", use_ai=False)
        ops = filler.generate_ops(empty_report, board_info)
        assert ops == []


class TestAIGeneration:
    """AI mode with mocked LLM."""

    def test_ai_plan_parsed(self, gap_report, board_info):
        mock_client = MagicMock()
        mock_client.chat.return_value = (
            '```json\n{"nets": [{"name": "NET_B", "strategy": "single_pass", "layers": "F.Cu"}]}\n```'
        )

        with patch(
            "volta.llm.local_client.LocalLLMClient",
            return_value=mock_client,
        ):
            filler = NetCompletionFiller(target_file="test.kicad_pcb", use_ai=True)
            ops = filler.generate_ops(gap_report, board_info)

        assert len(ops) == 1
        assert ops[0]["nets"] == ["NET_B"]
        assert ops[0]["strategy"] == "single_pass"
        assert ops[0]["layers"] == ["F.Cu"]

    def test_ai_falls_back_on_error(self, gap_report, board_info):
        mock_client = MagicMock()
        mock_client.chat.side_effect = RuntimeError("Model error")

        with patch(
            "volta.llm.local_client.LocalLLMClient",
            return_value=mock_client,
        ):
            filler = NetCompletionFiller(target_file="test.kicad_pcb", use_ai=True)
            ops = filler.generate_ops(gap_report, board_info)

        # Falls back to deterministic: 5 ops
        assert len(ops) == 5

    def test_ai_falls_back_on_invalid_json(self, gap_report, board_info):
        mock_client = MagicMock()
        mock_client.chat.return_value = "no json here"

        with patch(
            "volta.llm.local_client.LocalLLMClient",
            return_value=mock_client,
        ):
            filler = NetCompletionFiller(target_file="test.kicad_pcb", use_ai=True)
            ops = filler.generate_ops(gap_report, board_info)

        assert len(ops) == 5
