"""Phase 100 R-1, R-7, H4, M1: RoutingOrchestrator construction, batch API,
strategy validation, and frozen result schema tests.
"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

import pytest

from kicad_agent.routing.orchestrator import (
    NetRouteResult,
    RoutingOrchestrator,
    RoutingOrchestrationResult,
)
from kicad_agent.routing.strategy import (
    BoardState,
    DeterministicStrategy,
    Pin,
    RouterBackend,
    RoutingStrategy,
    RoutingStrategyResult,
)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstructWithDefaultStrategy:
    def test_no_strategy_uses_deterministic(self) -> None:
        orch = RoutingOrchestrator()
        # The default strategy should be DeterministicStrategy.
        assert isinstance(orch._strategy, DeterministicStrategy)


class TestConstructWithCustomStrategy:
    def test_custom_strategy_stored(self) -> None:
        custom = DeterministicStrategy(differential_pairs=(("A", "B"),))
        orch = RoutingOrchestrator(strategy=custom)
        assert orch._strategy is custom


# ---------------------------------------------------------------------------
# H4: Strategy output validation
# ---------------------------------------------------------------------------


class _MaliciousStrategy:
    """A strategy that returns an assignment for a net NOT in the netlist."""

    def strategize(
        self,
        board_state: BoardState,
        netlist: dict[str, list[Pin]],
    ) -> RoutingStrategyResult:
        return RoutingStrategyResult(
            net_priorities=("PHANTOM_NET",),
            layer_hints={},
            keepouts=(),
            router_assignment={"PHANTOM_NET": RouterBackend.ASTAR},
            routing_notes="malicious",
        )


class _InvalidBackendStrategy:
    """A strategy that returns a non-RouterBackend value in router_assignment."""

    def strategize(
        self,
        board_state: BoardState,
        netlist: dict[str, list[Pin]],
    ) -> RoutingStrategyResult:
        # Valid net name, but backend is a raw string instead of enum.
        real_net = next(iter(netlist)) if netlist else "X"
        return RoutingStrategyResult(
            net_priorities=(real_net,),
            layer_hints={},
            keepouts=(),
            router_assignment={real_net: "not_a_real_backend"},  # type: ignore[dict-item]
            routing_notes="bad backend",
        )


class TestOrchestratorValidatesStrategyOutput:
    def test_unknown_net_raises_value_error(self, tmp_path: Path) -> None:
        # Copy a real fixture so route_board can parse + extract netlist.
        pcb = _copy_smd_fixture(tmp_path)
        orch = RoutingOrchestrator(strategy=_MaliciousStrategy())
        with pytest.raises(ValueError, match="unknown net"):
            orch.route_board(pcb)

    def test_invalid_backend_raises_value_error(self, tmp_path: Path) -> None:
        pcb = _copy_smd_fixture(tmp_path)
        orch = RoutingOrchestrator(strategy=_InvalidBackendStrategy())
        with pytest.raises(ValueError, match="invalid backend"):
            orch.route_board(pcb)


# ---------------------------------------------------------------------------
# M1: Orchestration result is frozen and complete
# ---------------------------------------------------------------------------


class TestOrchestrationResultSchema:
    def test_net_route_result_is_frozen(self) -> None:
        nr = NetRouteResult(
            net_name="VCC",
            router_used=RouterBackend.ASTAR,
            success=True,
            route_length_mm=5.0,
            via_count=0,
            dispatch_reason="test",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            nr.success = False  # type: ignore[misc]

    def test_orchestration_result_is_frozen_dataclass(self) -> None:
        assert dataclasses.is_dataclass(RoutingOrchestrationResult)
        # Frozen check happens via construction in route_board tests below.
        # Here we verify the class config directly.
        assert RoutingOrchestrationResult.__dataclass_params__.frozen is True

    def test_result_fields_complete(self) -> None:
        field_names = {f.name for f in dataclasses.fields(RoutingOrchestrationResult)}
        assert field_names == {
            "per_net", "audit_path", "total_routed", "total_failed",
            "total_rejected", "strategy_used", "elapsed_seconds",
        }


# ---------------------------------------------------------------------------
# route_board returns RoutingOrchestrationResult (R-7)
# ---------------------------------------------------------------------------


class TestRouteBoardReturnsResult:
    def test_returns_orchestration_result(self, tmp_path: Path) -> None:
        pcb = _copy_smd_fixture(tmp_path)
        orch = RoutingOrchestrator()
        result = orch.route_board(pcb)
        assert isinstance(result, RoutingOrchestrationResult)
        assert isinstance(result.per_net, dict)
        assert isinstance(result.audit_path, Path)
        assert isinstance(result.strategy_used, str)
        assert isinstance(result.elapsed_seconds, float)
        assert result.total_routed + result.total_failed == len(result.per_net)
        # Audit file should exist.
        assert result.audit_path.exists()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_FIXTURE = Path(__file__).parent / "fixtures" / "smd_test_board.kicad_pcb"


def _copy_smd_fixture(tmp_path: Path) -> Path:
    """Copy smd_test_board.kicad_pcb into tmp_path, return the new path."""
    dest = tmp_path / "smd_test_board.kicad_pcb"
    shutil.copy(_FIXTURE, dest)
    return dest
