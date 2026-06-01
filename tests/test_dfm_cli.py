"""Tests for DFM CLI subcommand.

Covers:
- Parser registration
- Error handling (missing file, invalid manufacturer)
- Integration with PcbSpatialModel (skipif-guarded)
"""
from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.dfm.cli import dfm_command, register_dfm_parser

# Check for PcbSpatialModel availability (Phase 51 dependency)
try:
    from kicad_agent.spatial.pcb_model import PcbSpatialModel
    HAS_SPATIAL_MODEL = True
except ImportError:
    HAS_SPATIAL_MODEL = False


def _make_args(**overrides) -> argparse.Namespace:
    """Create a Namespace with default DFM CLI args."""
    defaults = {
        "board": "test.kicad_pcb",
        "manufacturer": None,
        "profile": None,
        "format": "markdown",
        "output": None,
        "stage": "all",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestDfmCli:
    """Tests for DFM CLI subcommand."""

    def test_register_dfm_parser_creates_parser(self):
        """register_dfm_parser creates a parser without error."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_dfm_parser(subparsers)

        # Parse with valid arguments
        args = parser.parse_args(["dfm", "board.kicad_pcb"])
        assert args.board == "board.kicad_pcb"
        assert args.format == "markdown"
        assert args.stage == "all"
        assert args.manufacturer is None
        assert args.profile is None
        assert args.output is None

    def test_register_dfm_parser_all_options(self):
        """Parser handles all CLI options."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_dfm_parser(subparsers)

        args = parser.parse_args([
            "dfm", "board.kicad_pcb",
            "--manufacturer", "jlcpcb",
            "--format", "json",
            "--output", "report.json",
            "--stage", "post-route",
        ])
        assert args.board == "board.kicad_pcb"
        assert args.manufacturer == "jlcpcb"
        assert args.format == "json"
        assert args.output == "report.json"
        assert args.stage == "post-route"

    def test_dfm_command_missing_file_returns_2(self):
        """Pass nonexistent board path returns exit code 2."""
        args = _make_args(board="/nonexistent/path/test.kicad_pcb")
        result = dfm_command(args)
        assert result == 2

    def test_dfm_command_invalid_extension_returns_2(self):
        """Pass a file with wrong extension returns exit code 2."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"not a pcb")
            tmp_path = f.name
        try:
            args = _make_args(board=tmp_path)
            result = dfm_command(args)
            assert result == 2
        finally:
            os.unlink(tmp_path)

    def test_dfm_command_invalid_manufacturer_returns_2(self):
        """Pass an unknown manufacturer name returns exit code 2."""
        with tempfile.NamedTemporaryFile(suffix=".kicad_pcb", delete=False) as f:
            f.write(b"(kicad_pcb (version 20231014))")
            tmp_path = f.name
        try:
            # The CLI parser restricts choices, but test the command directly
            args = _make_args(board=tmp_path, manufacturer="nonexistent_fab")
            result = dfm_command(args)
            assert result == 2
        finally:
            os.unlink(tmp_path)

    @pytest.mark.skipif(not HAS_SPATIAL_MODEL, reason="PcbSpatialModel not available (Phase 51)")
    def test_dfm_command_with_board_runs_analysis(self):
        """Integration test: DFM analysis runs on a real PCB fixture."""
        fixture = Path("tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_pcb")
        if not fixture.exists():
            pytest.skip("Arduino_Mega fixture not found")

        args = _make_args(board=str(fixture), format="json")
        result = dfm_command(args)
        # Should return 0 (pass) or 1 (findings but no error), not 2 (error)
        assert result in (0, 1)

    @pytest.mark.skipif(not HAS_SPATIAL_MODEL, reason="PcbSpatialModel not available (Phase 51)")
    def test_dfm_command_markdown_output(self):
        """Integration test: markdown output is generated."""
        fixture = Path("tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_pcb")
        if not fixture.exists():
            pytest.skip("Arduino_Mega fixture not found")

        args = _make_args(board=str(fixture), format="markdown")
        result = dfm_command(args)
        assert result in (0, 1)

    @pytest.mark.skipif(not HAS_SPATIAL_MODEL, reason="PcbSpatialModel not available (Phase 51)")
    def test_dfm_command_single_stage(self):
        """Integration test: single stage analysis runs."""
        fixture = Path("tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_pcb")
        if not fixture.exists():
            pytest.skip("Arduino_Mega fixture not found")

        args = _make_args(board=str(fixture), stage="footprint")
        result = dfm_command(args)
        assert result in (0, 1)
