"""Phase 98 Plan 03: Eval harness tests (R-5, SC-1 through SC-5).

Unit tests (mocked orchestrator + mocked model) + opt-in integration tests.

Integration tests are marked @pytest.mark.integration and skip when:
  - mlx_vlm is not importable (model unavailable)
  - kicad-cli is not on PATH (DRC cannot run)
  - Freerouting JAR/Java not available (routing backend unavailable)
"""

from __future__ import annotations

import json
import shutil
from dataclasses import FrozenInstanceError, is_dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.routing.orchestrator import (
    NetRouteResult,
    RoutingOrchestrationResult,
)
from kicad_agent.routing.strategy import DeterministicStrategy, RouterBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_orch_result(
    *,
    per_net: dict[str, NetRouteResult] | None = None,
    total_routed: int | None = None,
    strategy_name: str = "DeterministicStrategy",
    elapsed: float = 0.5,
) -> RoutingOrchestrationResult:
    """Build a fake RoutingOrchestrationResult for unit tests."""
    if per_net is None:
        per_net = {
            "VCC": NetRouteResult(
                net_name="VCC",
                router_used=RouterBackend.ASTAR,
                success=True,
                route_length_mm=10.0,
                via_count=1,
                dispatch_reason="test",
                notes="",
            ),
            "GND": NetRouteResult(
                net_name="GND",
                router_used=RouterBackend.FREEROUTING,
                success=True,
                route_length_mm=20.0,
                via_count=2,
                dispatch_reason="test",
                notes="",
            ),
        }
    if total_routed is None:
        total_routed = sum(1 for nr in per_net.values() if nr.success)
    total_failed = len(per_net) - total_routed
    return RoutingOrchestrationResult(
        per_net=per_net,
        audit_path=Path("/tmp/fake_audit.jsonl"),
        total_routed=total_routed,
        total_failed=total_failed,
        total_rejected=0,
        strategy_used=strategy_name,
        elapsed_seconds=elapsed,
    )


# ===========================================================================
# Task 1: Data types + strategy runner + DRC runner
# ===========================================================================

class TestDataTypes:
    """StrategyEvalResult dataclass contract."""

    def test_is_frozen_dataclass(self) -> None:
        from scripts.phase98_eval import StrategyEvalResult

        assert is_dataclass(StrategyEvalResult)
        with pytest.raises(FrozenInstanceError):
            StrategyEvalResult(
                fixture_name="x",
                strategy_name="y",
                total_nets=1,
                routed_nets=1,
                completion_pct=1.0,
                via_count=0,
                total_trace_length_mm=0.0,
                drc_pass=True,
                drc_unconnected=0,
                elapsed_seconds=0.0,
                parse_success=True,
                validation_passed=True,
            ).via_count = 5  # type: ignore[misc]

    def test_has_all_required_fields(self) -> None:
        from scripts.phase98_eval import StrategyEvalResult

        r = StrategyEvalResult(
            fixture_name="smd_test_board",
            strategy_name="DeterministicStrategy",
            total_nets=5,
            routed_nets=3,
            completion_pct=0.6,
            via_count=2,
            total_trace_length_mm=30.0,
            drc_pass=True,
            drc_unconnected=0,
            elapsed_seconds=1.2,
            parse_success=True,
            validation_passed=True,
        )
        for field in (
            "fixture_name", "strategy_name", "total_nets", "routed_nets",
            "completion_pct", "via_count", "total_trace_length_mm",
            "drc_pass", "drc_unconnected", "elapsed_seconds",
            "parse_success", "validation_passed",
        ):
            assert hasattr(r, field), f"missing field: {field}"


class TestCategoryStrategyRunner:
    """run_strategy_with_orchestrator with mocked orchestrator."""

    def test_deterministic_strategy_name(self, tmp_path: Path) -> None:
        from scripts.phase98_eval import run_strategy_with_orchestrator

        strategy = MagicMock()
        strategy.__class__.__name__ = "DeterministicStrategy"
        fake_result = _make_orch_result(strategy_name="DeterministicStrategy")

        with patch("scripts.phase98_eval.RoutingOrchestrator") as mock_orch_cls, \
             patch("scripts.phase98_eval.run_drc", return_value=(True, 0)):
            mock_orch_cls.return_value.route_board.return_value = fake_result
            r = run_strategy_with_orchestrator(
                strategy, pcb_path=tmp_path / "fake.kicad_pcb",
                project_dir=tmp_path, strategy_name="DeterministicStrategy",
            )
        assert r.strategy_name == "DeterministicStrategy"

    def test_ai_strategy_name(self, tmp_path: Path) -> None:
        from scripts.phase98_eval import run_strategy_with_orchestrator

        strategy = MagicMock()
        strategy.__class__.__name__ = "AiRoutingStrategy"
        fake_result = _make_orch_result(strategy_name="AiRoutingStrategy")

        with patch("scripts.phase98_eval.RoutingOrchestrator") as mock_orch_cls, \
             patch("scripts.phase98_eval.run_drc", return_value=(True, 0)):
            mock_orch_cls.return_value.route_board.return_value = fake_result
            r = run_strategy_with_orchestrator(
                strategy, pcb_path=tmp_path / "fake.kicad_pcb",
                project_dir=tmp_path, strategy_name="AiRoutingStrategy",
            )
        assert r.strategy_name == "AiRoutingStrategy"

    def test_completion_pct_formula(self, tmp_path: Path) -> None:
        """3 routed / 5 total nets = 0.6 completion."""
        from scripts.phase98_eval import run_strategy_with_orchestrator

        per_net = {
            f"net_{i}": NetRouteResult(
                net_name=f"net_{i}",
                router_used=RouterBackend.ASTAR,
                success=(i < 3),
                route_length_mm=5.0,
                via_count=0,
                dispatch_reason="test",
                notes="",
            )
            for i in range(5)
        }
        fake_result = _make_orch_result(
            per_net=per_net, total_routed=3, strategy_name="DeterministicStrategy",
        )

        with patch("scripts.phase98_eval.RoutingOrchestrator") as mock_orch_cls, \
             patch("scripts.phase98_eval.run_drc", return_value=(True, 0)):
            mock_orch_cls.return_value.route_board.return_value = fake_result
            r = run_strategy_with_orchestrator(
                MagicMock(), pcb_path=tmp_path / "fake.kicad_pcb",
                project_dir=tmp_path, strategy_name="DeterministicStrategy",
            )
        assert r.routed_nets == 3
        assert r.total_nets == 5
        assert r.completion_pct == pytest.approx(0.6)

    def test_via_count_summed_from_per_net(self, tmp_path: Path) -> None:
        from scripts.phase98_eval import run_strategy_with_orchestrator

        per_net = {
            "a": NetRouteResult("a", RouterBackend.ASTAR, True, 10.0, 1, "t", ""),
            "b": NetRouteResult("b", RouterBackend.ASTAR, True, 10.0, 2, "t", ""),
            "c": NetRouteResult("c", RouterBackend.ASTAR, True, 10.0, 3, "t", ""),
        }
        fake_result = _make_orch_result(
            per_net=per_net, total_routed=3, strategy_name="DeterministicStrategy",
        )
        with patch("scripts.phase98_eval.RoutingOrchestrator") as mock_orch_cls, \
             patch("scripts.phase98_eval.run_drc", return_value=(True, 0)):
            mock_orch_cls.return_value.route_board.return_value = fake_result
            r = run_strategy_with_orchestrator(
                MagicMock(), pcb_path=tmp_path / "fake.kicad_pcb",
                project_dir=tmp_path, strategy_name="DeterministicStrategy",
            )
        assert r.via_count == 6

    def test_total_trace_length_summed(self, tmp_path: Path) -> None:
        from scripts.phase98_eval import run_strategy_with_orchestrator

        per_net = {
            "a": NetRouteResult("a", RouterBackend.ASTAR, True, 10.5, 0, "t", ""),
            "b": NetRouteResult("b", RouterBackend.ASTAR, True, 20.3, 0, "t", ""),
        }
        fake_result = _make_orch_result(
            per_net=per_net, total_routed=2, strategy_name="DeterministicStrategy",
        )
        with patch("scripts.phase98_eval.RoutingOrchestrator") as mock_orch_cls, \
             patch("scripts.phase98_eval.run_drc", return_value=(True, 0)):
            mock_orch_cls.return_value.route_board.return_value = fake_result
            r = run_strategy_with_orchestrator(
                MagicMock(), pcb_path=tmp_path / "fake.kicad_pcb",
                project_dir=tmp_path, strategy_name="DeterministicStrategy",
            )
        assert r.total_trace_length_mm == pytest.approx(30.8)

    def test_ai_fallback_detected(self, tmp_path: Path) -> None:
        """When AI falls back, notes contain 'ai_fallback:' -> parse_success=False."""
        from scripts.phase98_eval import run_strategy_with_orchestrator

        per_net = {
            "a": NetRouteResult(
                "a", RouterBackend.ASTAR, True, 10.0, 0, "t",
                "ai_fallback: _AiStrategyError: empty output",
            ),
        }
        fake_result = _make_orch_result(
            per_net=per_net, total_routed=1, strategy_name="AiRoutingStrategy",
        )
        with patch("scripts.phase98_eval.RoutingOrchestrator") as mock_orch_cls, \
             patch("scripts.phase98_eval.run_drc", return_value=(True, 0)):
            mock_orch_cls.return_value.route_board.return_value = fake_result
            r = run_strategy_with_orchestrator(
                MagicMock(), pcb_path=tmp_path / "fake.kicad_pcb",
                project_dir=tmp_path, strategy_name="AiRoutingStrategy",
            )
        assert r.parse_success is False
        assert r.validation_passed is False


class TestCategoryDrc:
    """run_drc behavior."""

    def test_drc_clean_board_passes(self, tmp_path: Path) -> None:
        """A clean board should report drc_pass=True, unconnected=0.

        Uses the smd_test_board fixture (Phase 99 verified it passes DRC).
        This is a real subprocess call — marked integration because it
        requires kicad-cli and is slow (~5s).
        """
        if not shutil.which("kicad-cli"):
            pytest.skip("kicad-cli unavailable")
        from scripts.phase98_eval import run_drc

        fixture = _REPO_ROOT / "tests" / "fixtures" / "smd_test_board.kicad_pcb"
        pcb_copy = tmp_path / "smd_test_board.kicad_pcb"
        shutil.copy2(fixture, pcb_copy)

        drc_pass, unconnected = run_drc(pcb_copy)
        assert drc_pass is True
        assert unconnected == 0

    def test_drc_handles_missing_kicad_cli(self, tmp_path: Path) -> None:
        """When kicad-cli is unavailable, run_drc returns (False, -1)."""
        from scripts.phase98_eval import run_drc

        fake_pcb = tmp_path / "fake.kicad_pcb"
        fake_pcb.write_text("(kicad_pcb)")
        with patch("scripts.phase98_eval.subprocess.run", side_effect=FileNotFoundError):
            drc_pass, unconnected = run_drc(fake_pcb)
        assert drc_pass is False
        assert unconnected == -1

    def test_drc_handles_unconnected_nets(self, tmp_path: Path) -> None:
        """Synthetic DRC output with unconnected_items -> drc_pass=False."""
        from scripts.phase98_eval import run_drc

        fake_pcb = tmp_path / "fake.kicad_pcb"
        fake_pcb.write_text("(kicad_pcb)")

        # Mock subprocess to produce a report with 3 unconnected items.
        # run_drc writes to <stem>.<tag>.drc.json (ME-03); default tag is "default".
        def fake_report(*args: Any, **kwargs: Any) -> Any:
            report_path = fake_pcb.with_suffix(".default.drc.json")
            report_path.write_text(json.dumps({
                "violations": [
                    {"type": "unconnected_items", "description": "x"},
                    {"type": "unconnected_items", "description": "y"},
                    {"type": "unconnected_items", "description": "z"},
                ]
            }))
            return MagicMock(returncode=0)

        with patch("scripts.phase98_eval.subprocess.run", side_effect=fake_report):
            drc_pass, unconnected = run_drc(fake_pcb)
        assert drc_pass is False
        assert unconnected == 3

    def test_run_drc_tag_prevents_collision(self, tmp_path: Path) -> None:
        """ME-03: two run_drc calls with distinct tags produce distinct report files.

        Previously both calls wrote <stem>.drc.json, clobbering each other.
        Now the tag is embedded: <stem>.<tag>.drc.json.
        """
        from scripts.phase98_eval import run_drc

        fake_pcb = tmp_path / "board.kicad_pcb"
        fake_pcb.write_text("(kicad_pcb)")

        # Track the --output paths kicad-cli is invoked with.
        invoked_outputs: list[str] = []

        def fake_run(cmd: list[str], **kwargs: Any) -> Any:
            # Extract --output path from the command vector.
            out_idx = cmd.index("--output")
            invoked_outputs.append(cmd[out_idx + 1])
            # Write an empty-violations report at that path so run_drc can parse it.
            Path(cmd[out_idx + 1]).write_text(json.dumps({"violations": []}))
            return MagicMock(returncode=0)

        with patch("scripts.phase98_eval.subprocess.run", side_effect=fake_run):
            run_drc(fake_pcb, tag="det")
            run_drc(fake_pcb, tag="ai")

        assert len(invoked_outputs) == 2
        assert invoked_outputs[0] != invoked_outputs[1]
        assert invoked_outputs[0].endswith(".det.drc.json")
        assert invoked_outputs[1].endswith(".ai.drc.json")


# ===========================================================================
# Task 2: CLI + comparison table + SC evaluators + integration tests
# ===========================================================================

def _eval_result(
    *,
    fixture: str = "smd_test_board",
    strategy: str = "DeterministicStrategy",
    completion: float = 0.5,
    vias: int = 5,
    trace: float = 100.0,
    drc_pass: bool = True,
    drc_unconnected: int = 0,
    parse_success: bool = True,
    validation_passed: bool = True,
) -> Any:
    from scripts.phase98_eval import StrategyEvalResult

    return StrategyEvalResult(
        fixture_name=fixture,
        strategy_name=strategy,
        total_nets=10,
        routed_nets=int(completion * 10),
        completion_pct=completion,
        via_count=vias,
        total_trace_length_mm=trace,
        drc_pass=drc_pass,
        drc_unconnected=drc_unconnected,
        elapsed_seconds=1.0,
        parse_success=parse_success,
        validation_passed=validation_passed,
    )


class TestCategoryCli:
    """CLI argument parsing and main() behavior."""

    def test_help_mentions_flags(self, capsys: pytest.CaptureFixture[str]) -> None:
        from scripts.phase98_eval import main

        # IN-05 (Council): argparse exit code semantics.
        # --help -> SystemExit(code=0)  (success, help printed to stdout)
        # parse error -> SystemExit(code=2)  (error printed to stderr)
        # We assert code==0 specifically so the test fails if --help ever
        # triggers a parse error instead of the help path.
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "fixtures" in captured.out
        assert "json" in captured.out

    def test_deterministic_only_runs(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        """--no-ai runs deterministic baseline on smd_test_board, prints table.

        Mocked orchestrator so this is fast and doesn't need Freerouting.
        """
        from scripts.phase98_eval import main

        fake_result = _make_orch_result(strategy_name="DeterministicStrategy")
        with patch("scripts.phase98_eval.RoutingOrchestrator") as mock_orch_cls, \
             patch("scripts.phase98_eval.run_drc", return_value=(True, 0)), \
             patch("scripts.phase98_eval._copy_fixture_to_tmp") as mock_copy:
            mock_orch_cls.return_value.route_board.return_value = fake_result
            mock_copy.return_value = tmp_path / "smd_test_board.kicad_pcb"
            rc = main(["--fixtures", "smd_test_board", "--no-ai"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "DeterministicStrategy" in captured.out

    def test_json_output_valid(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        """--json emits valid JSON with 'results' key and fallback_rate diagnostic."""
        from scripts.phase98_eval import main

        fake_result = _make_orch_result(strategy_name="DeterministicStrategy")
        with patch("scripts.phase98_eval.RoutingOrchestrator") as mock_orch_cls, \
             patch("scripts.phase98_eval.run_drc", return_value=(True, 0)), \
             patch("scripts.phase98_eval._copy_fixture_to_tmp") as mock_copy:
            mock_orch_cls.return_value.route_board.return_value = fake_result
            mock_copy.return_value = tmp_path / "smd_test_board.kicad_pcb"
            rc = main(["--json", "--no-ai", "--fixtures", "smd_test_board"])
        assert rc == 0
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert "results" in payload
        assert isinstance(payload["results"], list)
        # M-4: fallback_rate diagnostic must be present in --json output
        assert "fallback_rate" in payload

    def test_unknown_fixture_exits_nonzero(self, capsys: pytest.CaptureFixture[str]) -> None:
        from scripts.phase98_eval import main

        rc = main(["--fixtures", "nonexistent_fixture"])
        assert rc != 0


class TestCategoryComparisonTable:
    """format_comparison_table renders both strategies side by side."""

    def test_table_contains_both_strategies(self) -> None:
        from scripts.phase98_eval import format_comparison_table

        det = _eval_result(strategy="DeterministicStrategy")
        ai = _eval_result(strategy="AiRoutingStrategy")
        table = format_comparison_table([det, ai])
        assert "DeterministicStrategy" in table
        assert "AiRoutingStrategy" in table

    def test_table_has_completion_column(self) -> None:
        from scripts.phase98_eval import format_comparison_table

        table = format_comparison_table([_eval_result()])
        assert "completion" in table.lower()

    def test_table_has_via_column(self) -> None:
        from scripts.phase98_eval import format_comparison_table

        table = format_comparison_table([_eval_result()])
        assert "via" in table.lower()

    def test_table_has_drc_column(self) -> None:
        from scripts.phase98_eval import format_comparison_table

        table = format_comparison_table([_eval_result()])
        assert "drc" in table.lower()

    def test_table_has_parse_success_column(self) -> None:
        from scripts.phase98_eval import format_comparison_table

        table = format_comparison_table([_eval_result()])
        assert "parse" in table.lower()

    def test_empty_results_handled(self) -> None:
        from scripts.phase98_eval import format_comparison_table

        table = format_comparison_table([])
        assert len(table) > 0  # non-empty graceful message


class TestCategorySuccessCriteria:
    """SC-1 through SC-5 evaluators (unit-level)."""

    def test_sc1_parse_success_rate(self) -> None:
        """SC-1: parse_success rate across AI results. Threshold >= 0.95."""
        from scripts.phase98_eval import evaluate_sc1

        results = [
            _eval_result(strategy="AiRoutingStrategy", parse_success=True),
            _eval_result(strategy="AiRoutingStrategy", parse_success=True),
            _eval_result(strategy="AiRoutingStrategy", parse_success=True),
            _eval_result(strategy="DeterministicStrategy", parse_success=True),
        ]
        rate = evaluate_sc1(results)
        assert rate == pytest.approx(1.0)

    def test_sc1_with_fallback(self) -> None:
        from scripts.phase98_eval import evaluate_sc1

        results = [
            _eval_result(strategy="AiRoutingStrategy", parse_success=True),
            _eval_result(strategy="AiRoutingStrategy", parse_success=False),
        ]
        rate = evaluate_sc1(results)
        assert rate == pytest.approx(0.5)

    def test_sc2_ai_beats_deterministic(self) -> None:
        """SC-2: AI matches or beats det on >=2 of 3 metrics.

        M-3: ties count as 'matches or beats' (<= for vias/trace, >= for completion).
        """
        from scripts.phase98_eval import evaluate_sc2

        det = _eval_result(strategy="DeterministicStrategy", completion=0.5, vias=10, trace=100.0)
        ai = _eval_result(strategy="AiRoutingStrategy", completion=0.6, vias=8, trace=90.0)
        winners = evaluate_sc2(det, ai)
        # AI wins all 3 here
        assert len(winners) == 3

    def test_sc2_tie_counts_as_match(self) -> None:
        """M-3: when ai.via_count == det.via_count, it counts as 'matches or beats'.

        ME-02: ties only count when AI genuinely parsed (parse_success=True).
        """
        from scripts.phase98_eval import evaluate_sc2

        det = _eval_result(strategy="DeterministicStrategy", completion=0.5, vias=5, trace=100.0)
        ai = _eval_result(
            strategy="AiRoutingStrategy",
            completion=0.5,
            vias=5,
            trace=100.0,
            parse_success=True,
        )
        winners = evaluate_sc2(det, ai)
        # All 3 are ties -> all 3 count as 'matches or beats'
        assert len(winners) == 3

    def test_sc2_does_not_count_fallback_ties_as_wins(self) -> None:
        """ME-02: fallback (parse_success=False) short-circuits to empty winners.

        When AI falls back to DeterministicStrategy, all metrics are identical
        ties. Counting them as wins would mask 'model contributed nothing'.
        """
        from scripts.phase98_eval import evaluate_sc2

        det = _eval_result(strategy="DeterministicStrategy", completion=0.5, vias=5, trace=100.0)
        ai_fallback = _eval_result(
            strategy="AiRoutingStrategy",
            completion=0.5,
            vias=5,
            trace=100.0,
            parse_success=False,
        )
        winners = evaluate_sc2(det, ai_fallback)
        assert winners == []

    def test_sc2_ai_loses(self) -> None:
        from scripts.phase98_eval import evaluate_sc2

        det = _eval_result(strategy="DeterministicStrategy", completion=0.8, vias=2, trace=50.0)
        ai = _eval_result(strategy="AiRoutingStrategy", completion=0.3, vias=10, trace=200.0)
        winners = evaluate_sc2(det, ai)
        assert len(winners) == 0

    def test_sc3_no_drc_regression(self) -> None:
        """SC-3: AI drc_pass >= deterministic drc_pass."""
        from scripts.phase98_eval import evaluate_sc3

        # Both pass -> no regression
        det = _eval_result(strategy="DeterministicStrategy", drc_pass=True)
        ai = _eval_result(strategy="AiRoutingStrategy", drc_pass=True)
        assert evaluate_sc3(det, ai) is True

    def test_sc3_regression_detected(self) -> None:
        from scripts.phase98_eval import evaluate_sc3

        det = _eval_result(strategy="DeterministicStrategy", drc_pass=True)
        ai = _eval_result(strategy="AiRoutingStrategy", drc_pass=False)
        assert evaluate_sc3(det, ai) is False

    def test_sc3_ai_passes_det_fails(self) -> None:
        from scripts.phase98_eval import evaluate_sc3

        det = _eval_result(strategy="DeterministicStrategy", drc_pass=False)
        ai = _eval_result(strategy="AiRoutingStrategy", drc_pass=True)
        assert evaluate_sc3(det, ai) is True

    def test_sc5_distinct_fixture_count(self) -> None:
        """SC-5: count distinct fixtures with AI results. Threshold >= 3."""
        from scripts.phase98_eval import evaluate_sc5

        results = [
            _eval_result(fixture="smd_test_board", strategy="AiRoutingStrategy"),
            _eval_result(fixture="raspberrypi_uhat", strategy="AiRoutingStrategy"),
            _eval_result(fixture="synthetic_4layer", strategy="AiRoutingStrategy"),
            _eval_result(fixture="smd_test_board", strategy="DeterministicStrategy"),
        ]
        assert evaluate_sc5(results) == 3

    def test_sc5_below_threshold(self) -> None:
        from scripts.phase98_eval import evaluate_sc5

        results = [
            _eval_result(fixture="smd_test_board", strategy="AiRoutingStrategy"),
            _eval_result(fixture="raspberrypi_uhat", strategy="AiRoutingStrategy"),
        ]
        assert evaluate_sc5(results) == 2


# ---------------------------------------------------------------------------
# Integration tests (opt-in via @pytest.mark.integration)
# ---------------------------------------------------------------------------

def _kicad_cli_available() -> bool:
    return shutil.which("kicad-cli") is not None


def _freerouting_available() -> bool:
    from kicad_agent.routing.freerouting import is_freerouting_available
    return is_freerouting_available()


@pytest.mark.integration
@pytest.mark.skipif(not _kicad_cli_available(), reason="kicad-cli unavailable")
@pytest.mark.skipif(not _freerouting_available(), reason="Freerouting unavailable")
class TestCategoryIntegration:
    """End-to-end integration tests.

    These tests are SLOW (Freerouting routing, real DRC, and for AI tests:
    23.8 GB model load at 5.6 tok/s). Expected runtime:
      - Deterministic: ~10-30s per fixture
      - AI: ~60-120s per fixture (model load + inference)

    Skip conditions:
      - mlx_vlm not installed -> AI tests skip via importorskip
      - kicad-cli not on PATH -> all integration tests skip
      - Freerouting JAR/Java missing -> all integration tests skip
      - Adapter path missing -> AI tests skip
    """

    def test_i1_deterministic_smd_test_board(self, tmp_path: Path) -> None:
        """I1: deterministic strategy on smd_test_board completes end-to-end."""
        from scripts.phase98_eval import run_strategy_with_orchestrator

        fixture = _REPO_ROOT / "tests" / "fixtures" / "smd_test_board.kicad_pcb"
        pcb_copy = tmp_path / "smd_test_board.kicad_pcb"
        shutil.copy2(fixture, pcb_copy)

        result = run_strategy_with_orchestrator(
            DeterministicStrategy(),
            pcb_path=pcb_copy,
            project_dir=tmp_path,
            strategy_name="DeterministicStrategy",
        )
        assert result.strategy_name == "DeterministicStrategy"
        assert result.total_nets > 0

    def test_i2_deterministic_synthetic_4layer(self, tmp_path: Path) -> None:
        """I2: deterministic strategy on synthetic 4-layer completes."""
        from scripts.phase98_eval import run_strategy_with_orchestrator

        fixture = _REPO_ROOT / "tests" / "fixtures" / "phase99_synthetic_4layer_mixedsignal.kicad_pcb"
        pcb_copy = tmp_path / "board.kicad_pcb"
        shutil.copy2(fixture, pcb_copy)

        result = run_strategy_with_orchestrator(
            DeterministicStrategy(),
            pcb_path=pcb_copy,
            project_dir=tmp_path,
            strategy_name="DeterministicStrategy",
        )
        assert result.strategy_name == "DeterministicStrategy"

    def test_i3_deterministic_raspberrypi_uhat(self, tmp_path: Path) -> None:
        """I3: deterministic strategy on RaspberryPi-uHAT completes."""
        from scripts.phase98_eval import run_strategy_with_orchestrator

        fixture = _REPO_ROOT / "tests" / "fixtures" / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_pcb"
        pcb_copy = tmp_path / "uhat.kicad_pcb"
        shutil.copy2(fixture, pcb_copy)

        result = run_strategy_with_orchestrator(
            DeterministicStrategy(),
            pcb_path=pcb_copy,
            project_dir=tmp_path,
            strategy_name="DeterministicStrategy",
        )
        assert result.strategy_name == "DeterministicStrategy"

    def test_i4_ai_strategy_smd_test_board(self, tmp_path: Path) -> None:
        """I4: AI strategy on smd_test_board — loads model, infers, routes.

        May fall back to deterministic — that's acceptable. The test verifies
        the full pipeline runs without crashing and produces a valid result.
        """
        pytest.importorskip("mlx_vlm", reason="mlx_vlm not installed")

        adapter_path = Path("/Volumes/Storage/models/kicad-agent/adapters/kicad-vision-v2-mlx/")
        if not adapter_path.exists():
            pytest.skip(f"Vision adapter not found at {adapter_path}")

        from scripts.phase98_eval import load_ai_strategy, run_strategy_with_orchestrator

        fixture = _REPO_ROOT / "tests" / "fixtures" / "smd_test_board.kicad_pcb"
        pcb_copy = tmp_path / "smd_test_board.kicad_pcb"
        shutil.copy2(fixture, pcb_copy)

        ai_strategy = load_ai_strategy(pcb_copy)
        result = run_strategy_with_orchestrator(
            ai_strategy,
            pcb_path=pcb_copy,
            project_dir=tmp_path,
            strategy_name="AiRoutingStrategy",
        )
        assert result.strategy_name == "AiRoutingStrategy"
        assert result.total_nets > 0
