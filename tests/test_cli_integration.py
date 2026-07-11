"""Integration tests for the Phase 209 CLI subcommands (INTEG-02).

Covers the 4 new subcommands (build, handoff, drc-vendor, board-metadata).
Uses the in-process ``main([...])`` + monkeypatch + capsys pattern from
``test_cli.py``. ``handle_operation`` is the seam mocked so no real KiCad
operation or kicad-cli invocation executes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_agent.cli import _SUBCOMMANDS, main
from kicad_agent.handler import OperationResult


def _ok_result(op_type: str, target_file: str) -> OperationResult:
    """Build a success OperationResult for the mocked handle_operation."""
    return OperationResult(
        success=True,
        operation_type=op_type,
        target_file=target_file,
        message=f"{op_type} ok",
        details={},
    )


def _patch_handle_operation(monkeypatch, capture: list):
    """Patch handle_operation in kicad_agent.handler to record calls.

    The _dispatch_op_and_print helper does a local
    ``from kicad_agent.handler import handle_operation`` at call time, so
    patching the source module attribute is the correct seam.
    """

    def _fake(json_str: str, project_dir: Path | None = None):
        capture.append(json.loads(json_str))
        op_type = json.loads(json_str)["op_type"]
        target_file = json.loads(json_str)["target_file"]
        return _ok_result(op_type, target_file)

    monkeypatch.setattr("kicad_agent.handler.handle_operation", _fake)
    # The _dispatch_op_and_print helper resolves handle_operation via a
    # local ``from kicad_agent.handler import handle_operation`` at call
    # time, so patching the source module attribute is the complete seam.


class TestSubcommandRegistration:
    """The 4 new subcommand names are registered."""

    def test_subcommands_set_contains_new_names(self) -> None:
        assert {"build", "handoff", "drc-vendor", "board-metadata"} <= _SUBCOMMANDS


class TestRouting:
    """Each subcommand routes without 'Unknown command' (smoke)."""

    @pytest.mark.parametrize("subcmd", ["build", "handoff", "drc-vendor", "board-metadata"])
    def test_subcommand_routes_not_unknown(
        self, subcmd: str, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        """Invoking <subcmd> --help prints help, not 'Unknown command'."""
        with pytest.raises(SystemExit):
            main([subcmd, "--help"])
        out = capsys.readouterr()
        combined = out.out + out.err
        assert "Unknown command" not in combined
        assert "usage:" in combined.lower()


class TestNestedMissingArg:
    """Nested subcommands with missing required args exit non-zero with help."""

    def test_build_no_action_prints_help(self, capsys) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["build"])
        assert exc.value.code != 0
        combined = capsys.readouterr().out + capsys.readouterr().err

    def test_drc_vendor_no_action_prints_help(self, capsys) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["drc-vendor"])
        assert exc.value.code != 0

    def test_board_metadata_no_action_prints_help(self, capsys) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["board-metadata"])
        assert exc.value.code != 0


class TestHandoffDispatch:
    """handoff <pcb> builds the right op and dispatches via handle_operation."""

    def test_handoff_constructs_op_and_dispatches(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        pcb = tmp_path / "board.kicad_pcb"
        pcb.write_text("(kicad_pcb)")
        captured: list[dict] = []
        _patch_handle_operation(monkeypatch, captured)

        with pytest.raises(SystemExit) as exc:
            main(["handoff", str(pcb), "--vendor", "jlcpcb"])

        assert exc.value.code == 0
        assert len(captured) == 1
        op = captured[0]
        assert op["op_type"] == "build_handoff_export"
        assert op["target_file"] == str(pcb)
        assert op["vendor"] == "jlcpcb"
        assert op["include_step"] is True  # default

    def test_handoff_no_step_flag(self, tmp_path: Path, monkeypatch) -> None:
        pcb = tmp_path / "board.kicad_pcb"
        pcb.write_text("(kicad_pcb)")
        captured: list[dict] = []
        _patch_handle_operation(monkeypatch, captured)

        with pytest.raises(SystemExit) as exc:
            main(["handoff", str(pcb), "--no-step"])
        assert exc.value.code == 0
        assert captured[0]["include_step"] is False
        assert captured[0]["vendor"] is None


class TestBuildDispatch:
    """build create|list|show dispatch the right ops."""

    def test_build_create_dispatches(self, tmp_path: Path, monkeypatch) -> None:
        pcb = tmp_path / "board.kicad_pcb"
        pcb.write_text("(kicad_pcb)")
        captured: list[dict] = []
        _patch_handle_operation(monkeypatch, captured)

        with pytest.raises(SystemExit) as exc:
            main(["build", "create", str(pcb)])
        assert exc.value.code == 0
        assert captured[0]["op_type"] == "build_create"
        assert captured[0]["target_file"] == str(pcb)

    def test_build_list_dispatches(self, tmp_path: Path, monkeypatch) -> None:
        pcb = tmp_path / "board.kicad_pcb"
        pcb.write_text("(kicad_pcb)")
        captured: list[dict] = []
        _patch_handle_operation(monkeypatch, captured)

        with pytest.raises(SystemExit) as exc:
            main(["build", "list", str(pcb)])
        assert exc.value.code == 0
        assert captured[0]["op_type"] == "build_list"

    def test_build_show_dispatches(self, tmp_path: Path, monkeypatch) -> None:
        pcb = tmp_path / "board.kicad_pcb"
        pcb.write_text("(kicad_pcb)")
        captured: list[dict] = []
        _patch_handle_operation(monkeypatch, captured)

        with pytest.raises(SystemExit) as exc:
            main(["build", "show", str(pcb), "--id", "abc-123"])
        assert exc.value.code == 0
        assert captured[0]["op_type"] == "build_show"
        assert captured[0]["build_id"] == "abc-123"


class TestDrcVendorDispatch:
    """drc-vendor run|list dispatch the right ops."""

    def test_drc_vendor_run_dispatches(self, tmp_path: Path, monkeypatch) -> None:
        pcb = tmp_path / "board.kicad_pcb"
        pcb.write_text("(kicad_pcb)")
        captured: list[dict] = []
        _patch_handle_operation(monkeypatch, captured)

        with pytest.raises(SystemExit) as exc:
            main(["drc-vendor", "run", str(pcb), "--vendor", "jlcpcb"])
        assert exc.value.code == 0
        assert captured[0]["op_type"] == "drc_vendor"
        assert captured[0]["vendor"] == "jlcpcb"

    def test_drc_vendor_list_dispatches(self, tmp_path: Path, monkeypatch) -> None:
        pcb = tmp_path / "board.kicad_pcb"
        pcb.write_text("(kicad_pcb)")
        captured: list[dict] = []
        _patch_handle_operation(monkeypatch, captured)

        with pytest.raises(SystemExit) as exc:
            main(["drc-vendor", "list", str(pcb)])
        assert exc.value.code == 0
        assert captured[0]["op_type"] == "list_vendor_drc_profiles"


class TestBoardMetadataDispatch:
    """board-metadata read|set-rev|set dispatch the right ops."""

    def test_read_dispatches(self, tmp_path: Path, monkeypatch) -> None:
        pcb = tmp_path / "board.kicad_pcb"
        pcb.write_text("(kicad_pcb)")
        captured: list[dict] = []
        _patch_handle_operation(monkeypatch, captured)

        with pytest.raises(SystemExit) as exc:
            main(["board-metadata", "read", str(pcb)])
        assert exc.value.code == 0
        assert captured[0]["op_type"] == "read_board_metadata"

    def test_set_rev_dispatches(self, tmp_path: Path, monkeypatch) -> None:
        pcb = tmp_path / "board.kicad_pcb"
        pcb.write_text("(kicad_pcb)")
        captured: list[dict] = []
        _patch_handle_operation(monkeypatch, captured)

        with pytest.raises(SystemExit) as exc:
            main(["board-metadata", "set-rev", str(pcb), "2.1"])
        assert exc.value.code == 0
        assert captured[0]["op_type"] == "set_board_revision"
        assert captured[0]["rev"] == "2.1"

    def test_set_dispatches(self, tmp_path: Path, monkeypatch) -> None:
        pcb = tmp_path / "board.kicad_pcb"
        pcb.write_text("(kicad_pcb)")
        captured: list[dict] = []
        _patch_handle_operation(monkeypatch, captured)

        with pytest.raises(SystemExit) as exc:
            main(["board-metadata", "set", str(pcb), "--title", "My Board"])
        assert exc.value.code == 0
        assert captured[0]["op_type"] == "set_board_metadata"
        assert captured[0]["title"] == "My Board"


class TestMissingFileGuard:
    """TM-1: a missing <pcb> exits non-zero with a stderr message."""

    def test_handoff_missing_pcb_exits_nonzero(self, tmp_path: Path, capsys) -> None:
        missing = tmp_path / "nope.kicad_pcb"
        with pytest.raises(SystemExit) as exc:
            main(["handoff", str(missing)])
        assert exc.value.code != 0
        err = capsys.readouterr().err
        assert "not found" in err.lower()

    def test_build_create_missing_pcb_exits_nonzero(self, tmp_path: Path, capsys) -> None:
        missing = tmp_path / "nope.kicad_pcb"
        with pytest.raises(SystemExit) as exc:
            main(["build", "create", str(missing)])
        assert exc.value.code != 0
        assert "not found" in capsys.readouterr().err.lower()
