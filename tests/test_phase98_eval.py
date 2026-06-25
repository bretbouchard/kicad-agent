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
from kicad_agent.routing.strategy import RouterBackend


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
                model_output_chars=0,
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
            model_output_chars=0,
            parse_success=True,
            validation_passed=True,
        )
        for field in (
            "fixture_name", "strategy_name", "total_nets", "routed_nets",
            "completion_pct", "via_count", "total_trace_length_mm",
            "drc_pass", "drc_unconnected", "elapsed_seconds",
            "model_output_chars", "parse_success", "validation_passed",
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

        # Mock subprocess to produce a report with 3 unconnected items
        def fake_report(*args: Any, **kwargs: Any) -> Any:
            # Write a fake DRC JSON report
            report_path = fake_pcb.with_suffix(".drc.json")
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
