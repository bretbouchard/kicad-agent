"""Phase 64 tests -- CLI/UX polish: H-15, H-16, H-17."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _run(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Invoke the CLI via ``python -m volta.cli``."""
    cmd = [sys.executable, "-m", "volta.cli", *args]
    # Inherit PYTHONPATH so the uninstalled source tree (src/) is importable.
    import os
    env = dict(os.environ)
    src_dir = str(Path(__file__).resolve().parent.parent / "src")
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=env)


# ---------------------------------------------------------------------------
# H-15: route subcommand must not crash on paths outside CWD
# ---------------------------------------------------------------------------


class TestRoutePathOutsideCwd:
    """H-15: ``route`` subcommand computes a relative path via
    ``resolve().relative_to(Path.cwd())`` which raises ``ValueError``
    when the PCB file lives outside CWD.  After the fix it should fall
    back to an absolute path instead of crashing.
    """

    def test_route_outside_cwd_does_not_raise_value_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A PCB in /tmp (outside CWD) should not crash with ValueError."""
        # Create a dummy PCB in tmp_path (which is outside most CWDs)
        pcb_file = tmp_path / "outside.kicad_pcb"
        pcb_file.write_text("(kicad_pcb (version 20221018))")

        # Mock handle_operation so we don't need a real auto-router
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.details = {"routed_nets": 3, "segments": 12, "failed_nets": []}

        with patch("volta.handler.handle_operation", return_value=mock_result):
            from volta.cli import main

            # This used to raise ValueError -- now it should succeed
            with pytest.raises(SystemExit) as exc_info:
                main(["route", str(pcb_file)])
            assert exc_info.value.code == 0

        captured = capsys.readouterr()
        assert "Routing complete" in captured.out

    def test_route_outside_cwd_passes_absolute_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When the PCB is outside CWD, the target_file should be an absolute path."""
        pcb_file = tmp_path / "outside.kicad_pcb"
        pcb_file.write_text("(kicad_pcb (version 20221018))")

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.details = {"routed_nets": 1, "segments": 5, "failed_nets": []}

        with patch("volta.handler.handle_operation", return_value=mock_result) as mock_handle:
            from volta.cli import main

            with pytest.raises(SystemExit) as exc_info:
                main(["route", str(pcb_file)])
            assert exc_info.value.code == 0

            # Verify the operation JSON was passed with an absolute path
            call_args = mock_handle.call_args
            op = json.loads(call_args[0][0])
            assert Path(op["target_file"]).is_absolute()

    def test_route_inside_cwd_still_works(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When the PCB is inside CWD, routing should still work (regression check)."""
        pcb_file = tmp_path / "inside.kicad_pcb"
        pcb_file.write_text("(kicad_pcb (version 20221018))")

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.details = {"routed_nets": 2, "segments": 8, "failed_nets": []}

        with patch("volta.handler.handle_operation", return_value=mock_result):
            from volta.cli import main

            with pytest.raises(SystemExit) as exc_info:
                main(["route", str(pcb_file)])
            assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# H-16: top-level --help lists all subcommands
# ---------------------------------------------------------------------------


class TestTopLevelHelp:
    """H-16: ``kicad-agent --help`` (or ``-h`` or no args) should print a
    help message listing all available subcommands with descriptions.
    """

    def test_help_flag_lists_subcommands(self) -> None:
        """``kicad-agent --help`` exits 0 and lists subcommands."""
        result = _run("--help")
        assert result.returncode == 0
        # Check that key subcommands appear in output
        for subcmd in ["route", "analyze", "erc", "drc", "collect", "context", "export", "component-search"]:
            assert subcmd in result.stdout, f"Expected subcommand '{subcmd}' in --help output"

    def test_help_flag_shows_descriptions(self) -> None:
        """``kicad-agent --help`` includes descriptions for subcommands."""
        result = _run("--help")
        assert result.returncode == 0
        assert "Auto-route" in result.stdout or "auto-route" in result.stdout.lower()
        assert "ERC" in result.stdout or "Electrical Rules Check" in result.stdout

    def test_short_help_flag(self) -> None:
        """``kicad-agent -h`` exits 0 and lists subcommands."""
        result = _run("-h")
        assert result.returncode == 0
        assert "route" in result.stdout
        assert "analyze" in result.stdout

    def test_no_args_shows_help(self) -> None:
        """Running ``kicad-agent`` with no args shows help (exits 0)."""
        result = _run()
        assert result.returncode == 0
        assert "Subcommands" in result.stdout

    def test_help_shows_usage_line(self) -> None:
        """Help output includes a usage line."""
        result = _run("--help")
        assert result.returncode == 0
        assert "usage:" in result.stdout.lower()


# ---------------------------------------------------------------------------
# H-17: component-search --help shows help instead of starting MCP server
# ---------------------------------------------------------------------------


class TestComponentSearchHelp:
    """H-17: ``kicad-agent component-search --help`` should print usage
    information and exit, not start the MCP server.
    """

    def test_component_search_help_exits_zero(self) -> None:
        """``kicad-agent component-search --help`` exits 0."""
        result = _run("component-search", "--help")
        assert result.returncode == 0

    def test_component_search_help_prints_usage(self) -> None:
        """``kicad-agent component-search --help`` prints usage info."""
        result = _run("component-search", "--help")
        assert "component-search" in result.stdout
        assert "usage" in result.stdout.lower()

    def test_component_search_help_does_not_import_mcp(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--help`` should be handled by argparse before the MCP import."""
        # Use in-process call to verify MCP server is never imported
        with patch("volta.mcp.server.main") as mock_mcp_main:
            from volta.cli import main

            with pytest.raises(SystemExit) as exc_info:
                main(["component-search", "--help"])
            assert exc_info.value.code == 0
            # MCP main should NOT have been called
            mock_mcp_main.assert_not_called()
