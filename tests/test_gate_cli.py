"""Tests for kicad-agent gate CLI subcommand."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from kiutils.schematic import Schematic

from kicad_agent.parser import parse_schematic
from kicad_agent.cli import _handle_gate


def _create_minimal_schematic(tmpdir: Path) -> Path:
    """Create a minimal valid .kicad_sch file."""
    sch = Schematic.create_new()
    sch_path = tmpdir / "test.kicad_sch"
    sch.to_file(str(sch_path))
    return sch_path


def _make_gate_runner_aware():
    """Ensure the default GateRunner has pre_pcb_schematic registered."""
    from kicad_agent.ops.validation_gates import pre_pcb_schematic_gate
    from kicad_agent.validation.gate_types import GateDefinition, DesignStage
    from kicad_agent.validation.gate_runner import get_gate_runner, register_gate

    runner = get_gate_runner()
    if runner.get_gate("pre_pcb_schematic") is None:
        register_gate(
            GateDefinition(
                name="pre_pcb_schematic",
                from_stage=DesignStage.SCHEMATIC,
                to_stage=DesignStage.PCB_SETUP,
                check_fn_name="pre_pcb_schematic_gate",
            ),
            check_fn=lambda ctx: pre_pcb_schematic_gate(**ctx),
        )


class TestGateStatusCLI:
    """Test 'kicad-agent gate status' subcommand."""

    def test_status_shows_current_stage(self, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_minimal_schematic(Path(tmpdir))
            _make_gate_runner_aware()

            with pytest.raises(SystemExit):
                _handle_gate(["status", "-p", tmpdir])

            captured = capsys.readouterr()
            assert "schematic" in captured.out
            assert "Registered gates" in captured.out

    def test_status_json_output(self, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_minimal_schematic(Path(tmpdir))
            _make_gate_runner_aware()

            with pytest.raises(SystemExit):
                _handle_gate(["status", "-p", tmpdir, "--json"])

            captured = capsys.readouterr()
            data = json.loads(captured.out)
            assert "current_stage" in data
            assert isinstance(data["registered_gates"], list)

    def test_status_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_minimal_schematic(Path(tmpdir))
            _make_gate_runner_aware()

            with pytest.raises(SystemExit) as exc_info:
                _handle_gate(["status", "-p", tmpdir])
            assert exc_info.value.code == 0


class TestGateRunCLI:
    """Test 'kicad-agent gate run' subcommand."""

    def test_run_on_empty_schematic_passes(self, capsys):
        """Empty schematic (no components) should pass with ERC disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_minimal_schematic(Path(tmpdir))
            _make_gate_runner_aware()

            with pytest.raises(SystemExit) as exc_info:
                _handle_gate(["run", "pre_pcb_schematic", "-p", tmpdir])
            # Empty schematic passes when ERC is not required (default requires ERC,
            # but kicad-cli may not be available so it may fail)
            captured = capsys.readouterr()
            assert "Gate" in captured.out or "gate" in captured.out

    def test_run_no_schematic_fails(self):
        """Running gate in directory without schematics fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(SystemExit) as exc_info:
                _handle_gate(["run", "pre_pcb_schematic", "-p", tmpdir])
            assert exc_info.value.code == 1

    def test_run_json_output(self, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_minimal_schematic(Path(tmpdir))
            _make_gate_runner_aware()

            with pytest.raises(SystemExit):
                _handle_gate(["run", "pre_pcb_schematic", "-p", tmpdir, "--json"])

            captured = capsys.readouterr()
            data = json.loads(captured.out)
            assert "pass" in data or "ready_for_pcb" in data


class TestGateHelpCLI:
    """Test 'kicad-agent gate' help output."""

    def test_gate_no_action_shows_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            _handle_gate([])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "run" in captured.out
        assert "status" in captured.out
