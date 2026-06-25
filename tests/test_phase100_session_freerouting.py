"""Phase 100 R-3: InteractiveRoutingSession Freerouting ingestion tests.

Covers ingest_freerouting_result which converts SesParseResult wires into
RoutingSuggestion objects, reusing the existing approve/reject/reroute
lifecycle unchanged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import pytest

from kicad_agent.routing.constraints import RoutingConstraints
from kicad_agent.routing.graph import RoutingGraph
from kicad_agent.routing.interactive import (
    InteractiveRoutingSession,
    RoutingSuggestion,
    SuggestionStatus,
)


# ---------------------------------------------------------------------------
# Lightweight SesWire / SesParseResult stand-ins.
#
# We avoid importing the real SesWire/SesParseResult from freerouting.py
# because that module pulls in heavy Java subprocess machinery. The real
# SesWire is a frozen dataclass with .net, .layer, .width_mm, .points —
# we mirror those fields exactly so ingest_freerouting_result's getattr
# calls work identically.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _MockSesWire:
    net: str
    layer: str = "F.Cu"
    width_mm: float = 0.25
    points: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class _MockSesParseResult:
    wires: list[_MockSesWire] = field(default_factory=list)
    vias: list[Any] = field(default_factory=list)
    resolution_factor: float = 100000.0


def _make_graph() -> RoutingGraph:
    return RoutingGraph(
        board_bounds=(0.0, 0.0, 50.0, 50.0),
        obstacles=[],
        constraints=RoutingConstraints(),
    )


def _make_session(
    netlist: dict[str, list[tuple[float, float]]] | None = None,
) -> InteractiveRoutingSession:
    nl = netlist if netlist is not None else {
        "VCC": [(5.0, 5.0), (20.0, 5.0)],
        "GND": [(5.0, 10.0), (20.0, 10.0)],
    }
    return InteractiveRoutingSession(
        graph=_make_graph(),
        netlist=nl,
        constraints=RoutingConstraints(),
    )


# ---------------------------------------------------------------------------
# Ingest tests
# ---------------------------------------------------------------------------


class TestIngestConvertsWires:
    def test_two_wires_produce_two_suggestions(self) -> None:
        session = _make_session()
        # Clear A*-generated suggestions so we only see FR ones.
        session._suggestions.clear()

        ses = _MockSesParseResult(wires=[
            _MockSesWire(net="VCC", points=[(0.0, 0.0), (10.0, 0.0), (10.0, 5.0)]),
            _MockSesWire(net="GND", points=[(0.0, 1.0), (10.0, 1.0)]),
        ])
        session.ingest_freerouting_result(ses)
        assert "VCC" in session._suggestions
        assert "GND" in session._suggestions

    def test_path_matches_wire_points(self) -> None:
        session = _make_session()
        session._suggestions.clear()
        pts = [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]
        ses = _MockSesParseResult(wires=[_MockSesWire(net="VCC", points=pts)])
        session.ingest_freerouting_result(ses)
        sugg = session._suggestions["VCC"]
        assert sugg.path == pts

    def test_length_computed_from_points(self) -> None:
        session = _make_session()
        session._suggestions.clear()
        pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0)]
        ses = _MockSesParseResult(wires=[_MockSesWire(net="VCC", points=pts)])
        session.ingest_freerouting_result(ses)
        sugg = session._suggestions["VCC"]
        expected = math.hypot(10.0, 0.0) + math.hypot(0.0, 5.0)
        assert abs(sugg.length_mm - expected) < 0.001


class TestIngestRespectsNetFilter:
    def test_only_filtered_nets_ingested(self) -> None:
        session = _make_session()
        session._suggestions.clear()
        ses = _MockSesParseResult(wires=[
            _MockSesWire(net="VCC", points=[(0.0, 0.0), (1.0, 0.0)]),
            _MockSesWire(net="GND", points=[(0.0, 1.0), (1.0, 1.0)]),
        ])
        session.ingest_freerouting_result(ses, net_filter={"VCC"})
        assert "VCC" in session._suggestions
        assert "GND" not in session._suggestions


class TestIngestSkipsUnknownNets:
    def test_wire_on_unknown_net_skipped(self) -> None:
        session = _make_session()
        session._suggestions.clear()
        ses = _MockSesParseResult(wires=[
            _MockSesWire(net="UNKNOWN", points=[(0.0, 0.0), (1.0, 0.0)]),
        ])
        # Must not raise.
        session.ingest_freerouting_result(ses)
        assert "UNKNOWN" not in session._suggestions

    def test_known_and_unknown_mixed(self) -> None:
        session = _make_session()
        session._suggestions.clear()
        ses = _MockSesParseResult(wires=[
            _MockSesWire(net="VCC", points=[(0.0, 0.0), (1.0, 0.0)]),
            _MockSesWire(net="MYSTERY", points=[(0.0, 0.0), (1.0, 0.0)]),
        ])
        session.ingest_freerouting_result(ses)
        assert "VCC" in session._suggestions
        assert "MYSTERY" not in session._suggestions


# ---------------------------------------------------------------------------
# Approve/reject on Freerouting suggestions
# ---------------------------------------------------------------------------


class TestApproveFreeroutingSuggestion:
    def test_approve_sets_status_and_locks(self) -> None:
        session = _make_session()
        session._suggestions.clear()
        ses = _MockSesParseResult(wires=[
            _MockSesWire(net="VCC", points=[(0.0, 0.0), (10.0, 0.0)]),
        ])
        session.ingest_freerouting_result(ses)
        session.approve("VCC")
        assert session._suggestions["VCC"].status == SuggestionStatus.APPROVED
        assert "VCC" in session._locked_routes


class TestRejectFreeroutingSuggestion:
    def test_reject_sets_status_and_reason(self) -> None:
        session = _make_session()
        session._suggestions.clear()
        ses = _MockSesParseResult(wires=[
            _MockSesWire(net="GND", points=[(0.0, 0.0), (10.0, 0.0)]),
        ])
        session.ingest_freerouting_result(ses)
        session.reject("GND", reason="too close to VCC")
        sugg = session._suggestions["GND"]
        assert sugg.status == SuggestionStatus.REJECTED
        assert sugg.reject_reason == "too close to VCC"
        assert "GND" not in session._locked_routes
