"""Tests for the bootable Volta platform runtime wrapper."""

from __future__ import annotations

import json
from pathlib import Path

from volta.platform_runtime import VoltaPlatformRuntime
from volta.result import OperationResult


def _create_runtime_pcb(tmp_path: Path, rev: str = "A1") -> Path:
    pcb_path = tmp_path / "runtime_board.kicad_pcb"
    pcb_path.write_text(
        f'''(kicad_pcb (version 20241229) (generator "test")
  (general (thickness 1.6) (layers 2))
  (paper "A4")
  (title_block
    (title "Runtime Test")
    (date "2026-08-17")
    (rev "{rev}")
    (company "Volta")
  )
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
  )
)
''',
        encoding="utf-8",
    )
    return pcb_path


def test_runtime_boot_and_diagnostics_for_build_create(tmp_path: Path) -> None:
    runtime = VoltaPlatformRuntime.boot(tmp_path)
    pcb_path = _create_runtime_pcb(tmp_path)

    result = runtime.execute_operation(
        json.dumps(
            {
                "op_type": "build_create",
                "target_file": pcb_path.name,
            }
        )
    )

    assert isinstance(result, OperationResult)
    assert result.success is True
    assert result.details["governed_build"]["capability_name"] == "manufacturing.build.snapshot"

    diagnostics = runtime.diagnostics()
    assert diagnostics["operation_count"] == 1
    assert diagnostics["success_count"] == 1
    assert diagnostics["failure_count"] == 0
    assert diagnostics["evidence_count"] >= 1
    assert diagnostics["governed_object_count"] >= 2


def test_runtime_feed_and_export_capture_governed_paths(tmp_path: Path) -> None:
    runtime = VoltaPlatformRuntime.boot(tmp_path)
    pcb_path = _create_runtime_pcb(tmp_path, rev="B2")

    build_result = runtime.execute_operation(
        json.dumps(
            {
                "op_type": "build_create",
                "target_file": pcb_path.name,
            }
        )
    )
    metadata_result = runtime.execute_operation(
        json.dumps(
            {
                "op_type": "read_board_metadata",
                "target_file": pcb_path.name,
            }
        )
    )

    assert isinstance(build_result, OperationResult)
    assert isinstance(metadata_result, OperationResult)

    feed = runtime.diagnostics_feed()
    assert len(feed) == 2
    assert feed[0]["operation_type"] == "build_create"
    assert "manufacturing.build.snapshot" in feed[0]["governed_capabilities"]
    assert feed[1]["operation_type"] == "read_board_metadata"
    assert "design.metadata.read" in feed[1]["governed_capabilities"]

    exported = runtime.export()
    assert exported["diagnostics"]["operation_count"] == 2
    assert len(exported["events"]) == 2
    assert len(exported["evidence"]) >= 1
    assert len(exported["governed_objects"]) >= 2
