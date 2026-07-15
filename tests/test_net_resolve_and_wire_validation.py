"""Tests for Phase 129: net-aware wire generation.

Covers:
  Wave 1 -- ``SchematicIR._resolve_net_at_position()`` resolves net names
            from labels, power-symbol pins, and wire-graph BFS.
  Wave 2 -- ``SchematicIR.add_wire()`` rejects endpoints on different nets
            and supports a ``force=True`` escape hatch.

Uses the Arduino_Mega fixture (which contains real power symbols and local
labels) plus an in-memory schematic for wire-graph BFS coverage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from volta.ir import SchematicIR
from volta.ir.base import _clear_registry
from volta.parser import parse_schematic


@pytest.fixture(autouse=True)
def _reset_ir_registry():
    """Clear the IR registry before and after each test."""
    _clear_registry()
    yield
    _clear_registry()


@pytest.fixture
def arduino_ir(arduino_mega_sch: Path) -> SchematicIR:
    """SchematicIR over the Arduino_Mega fixture (has power + labels)."""
    result = parse_schematic(arduino_mega_sch)
    return SchematicIR(_parse_result=result)


# ---------------------------------------------------------------------------
# Wave 1: _resolve_net_at_position
# ---------------------------------------------------------------------------


class TestResolveNetAtPosition:
    """Net resolution from labels, power pins, and wire graph."""

    def test_resolves_local_label(self, arduino_ir: SchematicIR) -> None:
        """A position with a local label resolves to that label's name."""
        # A10 label sits at (21.59, 90.17) in the fixture.
        net = arduino_ir._resolve_net_at_position(21.59, 90.17)
        assert net == "A10"

    def test_resolves_power_symbol_pin(self, arduino_ir: SchematicIR) -> None:
        """A position on a power-symbol pin resolves to the rail name."""
        # #PWR06 is power:+5V at (74.93, 111.76).
        net = arduino_ir._resolve_net_at_position(74.93, 111.76)
        assert net == "+5V"

    def test_resolves_ground_symbol_pin(self, arduino_ir: SchematicIR) -> None:
        """A GND power-symbol pin resolves to 'GND'."""
        # #PWR04 is power:GND at (31.75, 52.07).
        net = arduino_ir._resolve_net_at_position(31.75, 52.07)
        assert net == "GND"

    def test_empty_position_returns_none(self, arduino_ir: SchematicIR) -> None:
        """A position with no label, pin, or wire returns None."""
        # (0, 0) is far from any element in the Arduino fixture.
        net = arduino_ir._resolve_net_at_position(0.0, 0.0)
        assert net is None

    def test_tolerance_parameter(self, arduino_ir: SchematicIR) -> None:
        """A near-miss coordinate resolves when within tolerance."""
        # 0.25mm off the A10 label -- inside the default 0.5mm tolerance.
        net = arduino_ir._resolve_net_at_position(21.59 + 0.25, 90.17)
        assert net == "A10"

    def test_explicit_tolerance_too_tight(self, arduino_ir: SchematicIR) -> None:
        """A custom tolerance below the offset returns None."""
        # 0.25mm off, but tolerance tightened to 0.1mm.
        net = arduino_ir._resolve_net_at_position(21.59 + 0.25, 90.17, _tol=0.1)
        assert net is None


# ---------------------------------------------------------------------------
# Wave 1: _is_power_symbol helper
# ---------------------------------------------------------------------------


class TestIsPowerSymbol:
    """Power-symbol detection via Reference prefix and lib_id prefix."""

    def test_detects_power_ref_prefix(self, arduino_ir: SchematicIR) -> None:
        """A #PWR-prefixed reference is a power symbol."""
        comp = arduino_ir.get_component_by_ref("#PWR06")
        assert comp is not None
        assert arduino_ir._is_power_symbol(comp) is True

    def test_rejects_regular_component(self, arduino_ir: SchematicIR) -> None:
        """A normal component (e.g. U1) is not a power symbol."""
        # Pick any non-power reference from the fixture. Arduino_Mega has
        # several ICs; if the lookup fails we skip rather than fail -- the
        # key assertion is that *no* regular component looks like power.
        for ref in ("U1", "U2", "U3", "J1", "R1"):
            comp = arduino_ir.get_component_by_ref(ref)
            if comp is None:
                continue
            assert arduino_ir._is_power_symbol(comp) is False
            return
        pytest.skip("No non-power components in fixture to test against")


# ---------------------------------------------------------------------------
# Wave 1: wire-graph BFS tracing
# ---------------------------------------------------------------------------


class TestTraceWireToNet:
    """Net resolution through wire-graph traversal."""

    def test_traces_wire_to_distant_label(
        self, tmp_path: Path, arduino_mega_sch: Path
    ) -> None:
        """A position on a wire resolves to the label at the other end."""
        # Build a tiny schematic in memory by adding a wire to a copy of the
        # Arduino fixture, then verifying the BFS finds the A10 label from
        # the wire's far endpoint. We use add_wire with force=True because
        # the Arduino fixture already has a label at the near endpoint.
        import shutil

        sch_copy = tmp_path / "test.kicad_sch"
        shutil.copy2(arduino_mega_sch, sch_copy)

        _clear_registry()
        result = parse_schematic(sch_copy)
        ir = SchematicIR(_parse_result=result)

        # Add a wire chain from the A10 label out to an empty coordinate.
        # A10 sits at (21.59, 90.17). Route horizontally then vertically to
        # (30.0, 95.0). Use force=True because the intermediate positions
        # are not labelled.
        ir.add_wire(21.59, 90.17, 25.0, 90.17, force=True)
        ir.add_wire(25.0, 90.17, 25.0, 95.0, force=True)
        ir.add_wire(25.0, 95.0, 30.0, 95.0, force=True)

        # Resolving at the wire's far endpoint should find the A10 net.
        net = ir._resolve_net_at_position(30.0, 95.0)
        assert net == "A10"


# ---------------------------------------------------------------------------
# Wave 2: add_wire net validation
# ---------------------------------------------------------------------------


class TestAddWireNetValidation:
    """add_wire rejects cross-net wires and supports force override."""

    def test_rejects_cross_net_wire(self, arduino_ir: SchematicIR) -> None:
        """A wire between +5V and GND pins raises ValueError."""
        # #PWR06 (+5V) at (74.93, 111.76) and #PWR04 (GND) at (31.75, 52.07).
        with pytest.raises(ValueError) as exc:
            arduino_ir.add_wire(74.93, 111.76, 31.75, 52.07)
        msg = str(exc.value)
        assert "+5V" in msg
        assert "GND" in msg
        assert "force=True" in msg

    def test_allows_same_net_wire(self, arduino_ir: SchematicIR) -> None:
        """A wire between two GND pins succeeds."""
        # #PWR04 (GND) at (31.75, 52.07) and #PWR05 (GND) at (64.77, 52.07).
        result = arduino_ir.add_wire(31.75, 52.07, 64.77, 52.07)
        assert "start" in result
        assert "end" in result
        assert "net_conflict_overridden" not in result

    def test_allows_labelled_to_empty_wire(self, arduino_ir: SchematicIR) -> None:
        """A wire from a labelled position to empty space succeeds."""
        # A10 at (21.59, 90.17) -> empty (50.0, 90.17).
        result = arduino_ir.add_wire(21.59, 90.17, 50.0, 90.17)
        assert result["start"] == [21.59, 90.17]
        assert result["end"] == [50.0, 90.17]

    def test_force_overrides_conflict(self, arduino_ir: SchematicIR) -> None:
        """force=True bypasses validation and records the override."""
        # +5V (74.93, 111.76) -> GND (31.75, 52.07) with force=True.
        result = arduino_ir.add_wire(74.93, 111.76, 31.75, 52.07, force=True)
        assert "net_conflict_overridden" in result
        conflict = result["net_conflict_overridden"]
        assert conflict["start_net"] == "+5V"
        assert conflict["end_net"] == "GND"

    def test_force_logs_mutation(self, arduino_ir: SchematicIR) -> None:
        """Forced override is recorded in the mutation log."""
        before = len(arduino_ir.mutation_log)
        arduino_ir.add_wire(74.93, 111.76, 31.75, 52.07, force=True)
        after = len(arduino_ir.mutation_log)
        assert after == before + 1
        last = arduino_ir.mutation_log[-1]
        assert last["type"] == "add_wire"
        assert "net_conflict_overridden" in last

    def test_rejection_does_not_mutate(self, arduino_ir: SchematicIR) -> None:
        """A rejected wire must not modify the schematic."""
        before_wires = len(arduino_ir.get_wire_endpoints())
        before_log = len(arduino_ir.mutation_log)
        with pytest.raises(ValueError):
            arduino_ir.add_wire(74.93, 111.76, 31.75, 52.07)
        assert len(arduino_ir.get_wire_endpoints()) == before_wires
        assert len(arduino_ir.mutation_log) == before_log

    def test_duplicate_short_circuits_validation(
        self, arduino_ir: SchematicIR
    ) -> None:
        """An identical pre-existing wire is reported as duplicate, not short."""
        # First, install a wire between the two GND pins (same net -> OK).
        first = arduino_ir.add_wire(31.75, 52.07, 64.77, 52.07)
        assert "duplicate" not in first
        # Second call with identical coords returns duplicate=True.
        second = arduino_ir.add_wire(31.75, 52.07, 64.77, 52.07)
        assert second.get("duplicate") is True


# ---------------------------------------------------------------------------
# Wave 2: handler-level smoke test
# ---------------------------------------------------------------------------


class TestAddWireHandlerForceParam:
    """The op handler forwards force and surfaces the override."""

    def test_handler_passes_force(
        self, tmp_path: Path, arduino_mega_sch: Path
    ) -> None:
        """The add_wire op honours force=True at the handler boundary."""
        import json
        import shutil

        from volta.handler import handle_operation
        from volta.result import OperationResult

        sch_dst = tmp_path / "Arduino_Mega.kicad_sch"
        shutil.copy2(arduino_mega_sch, sch_dst)

        op_json = json.dumps({
            "op_type": "add_wire",
            "target_file": "Arduino_Mega.kicad_sch",
            "start_x": 74.93,
            "start_y": 111.76,
            "end_x": 31.75,
            "end_y": 52.07,
            "force": True,
        })
        result = handle_operation(op_json, project_dir=tmp_path)
        assert isinstance(result, OperationResult)
        assert result.success, getattr(result, "error", "")
        # The returned details should include the override marker.
        details = result.details or {}
        assert (
            "net_conflict_overridden" in details
            or "net_conflict_overridden" in (details.get("result") or {})
        ), f"Expected override marker in {details}"

    def test_handler_rejects_without_force(
        self, tmp_path: Path, arduino_mega_sch: Path
    ) -> None:
        """The add_wire op fails on cross-net wires without force."""
        import json
        import shutil

        from volta.handler import handle_operation
        from volta.result import OperationError

        sch_dst = tmp_path / "Arduino_Mega.kicad_sch"
        shutil.copy2(arduino_mega_sch, sch_dst)

        op_json = json.dumps({
            "op_type": "add_wire",
            "target_file": "Arduino_Mega.kicad_sch",
            "start_x": 74.93,
            "start_y": 111.76,
            "end_x": 31.75,
            "end_y": 52.07,
        })
        result = handle_operation(op_json, project_dir=tmp_path)
        # Failures come back as OperationError, not OperationResult.
        assert isinstance(result, OperationError)
        assert not result.success
        # The error should mention the conflict and the escape hatch.
        err = result.error or ""
        assert "+5V" in err or "GND" in err or "force" in err


# ---------------------------------------------------------------------------
# Wave 4: Backplane regression test
# ---------------------------------------------------------------------------

# The backplane power-supply sheet suffered the original Phase 26 shorts.
# Coordinates below come from detect_net_shorts output on the live file:
#   +3V3 at (142.24, 91.44) shorted to GND at (73.66, 76.2)
# This test pins the regression: if add_wire ever accepts this wire again,
# the same corruption that forced the Phase 26 rebuild will return.
_BACKPLANE_PS = (
    "/Users/bretbouchard/apps/analog-ecosystem/hardware/backplane/"
    "power-supply.kicad_sch"
)


@pytest.mark.skipif(
    not Path(_BACKPLANE_PS).exists(),
    reason="Backplane fixture not available on this machine",
)
class TestBackplaneRegression:
    """The exact wire that shorted +3V3 to GND in Phase 26 must be rejected."""

    def test_power_supply_short_rejected(self) -> None:
        """The +3V3 to GND wire that Phase 26 generated must now raise."""
        _clear_registry()
        result = parse_schematic(Path(_BACKPLANE_PS))
        ir = SchematicIR(_parse_result=result)
        with pytest.raises(ValueError) as exc:
            ir.add_wire(142.24, 91.44, 73.66, 76.2)
        msg = str(exc.value)
        assert "+3V3" in msg
        assert "GND" in msg

    def test_power_supply_short_force_override_records(self) -> None:
        """The escape hatch records the override for audit trails."""
        _clear_registry()
        result = parse_schematic(Path(_BACKPLANE_PS))
        ir = SchematicIR(_parse_result=result)
        result_dict = ir.add_wire(142.24, 91.44, 73.66, 76.2, force=True)
        override = result_dict.get("net_conflict_overridden")
        assert override is not None
        assert override["start_net"] == "+3V3"
        assert override["end_net"] == "GND"
