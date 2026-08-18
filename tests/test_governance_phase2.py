"""Phase 2 governed-object and capability adoption tests for Volta."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from volta.governance import (
    CapabilityStatus,
    EvidenceKind,
    GovernedExecutionContext,
    GovernedObjectType,
)
from volta.manufacturing.handoff import (
    HandoffResult,
    HandoffValidation,
    _empty_manifest,
)
from volta.validation.gates.manufacturing_manifest import ManufacturingArtifact, ManufacturingManifest


def test_modeled_world_registers_stable_electronics_objects(tmp_path: Path) -> None:
    context = GovernedExecutionContext()
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    pcb_path = project_dir / "demo.kicad_pcb"
    pcb_path.write_text("(kicad_pcb)", encoding="utf-8")
    sch_path = project_dir / "demo.kicad_sch"
    sch_path.write_text("(kicad_sch)", encoding="utf-8")

    records = context.register_project_objects(
        project_dir=project_dir,
        pcb_path=pcb_path,
        schematic_path=sch_path,
        revision="rev-a",
    )

    assert records["project"].object_type is GovernedObjectType.PROJECT
    assert records["pcb"].object_type is GovernedObjectType.PCB
    assert records["schematic"].object_type is GovernedObjectType.SCHEMATIC
    assert records["pcb"].object_id == context.world.get(GovernedObjectType.PCB, pcb_path).object_id


def test_modeled_world_supports_logical_locators(tmp_path: Path) -> None:
    context = GovernedExecutionContext()
    schematic_path = tmp_path / "demo.kicad_sch"
    schematic_path.write_text("(kicad_sch)", encoding="utf-8")

    record = context.world.register(
        GovernedObjectType.COMPONENT,
        f"{schematic_path}#component:R1",
        revision="rev-a",
        metadata={"reference": "R1"},
    )

    assert context.world.get(
        GovernedObjectType.COMPONENT,
        f"{schematic_path}#component:R1",
    ) == record


def test_governed_verification_records_evidence(tmp_path: Path) -> None:
    from volta.governance import run_governed_verification

    context = GovernedExecutionContext()
    pcb_path = tmp_path / "board.kicad_pcb"
    pcb_path.write_text("(kicad_pcb)", encoding="utf-8")
    sch_path = tmp_path / "board.kicad_sch"
    sch_path.write_text(
        '(kicad_sch (version 20241229) (generator "test")\n'
        '  (sheet (at 0 0) (size 10 10))\n'
        '  (symbol (lib_id "Device:R")\n'
        '    (property "Reference" "R1" (at 0 0))\n'
        '    (property "Value" "10k" (at 0 0))\n'
        '  )\n'
        '  (label "NET_A" (at 0 0 0))\n'
        '  (bus_alias "CTRL" (members "CTRL0" "CTRL1"))\n'
        ')\n',
        encoding="utf-8",
    )

    result = run_governed_verification(
        context=context,
        pcb_path=pcb_path,
        schematic_path=sch_path,
        drc_result=SimpleNamespace(passed=True, error_count=0, warning_count=1, error_message=None),
        erc_result=SimpleNamespace(passed=False, error_count=2, warning_count=0, error_message=None),
        vendor="jlcpcb",
        vendor_result=SimpleNamespace(passed=True, errors=[], warnings=["near limit"], error_message=None),
    )

    assert result.status is CapabilityStatus.FAILED
    assert len(result.evidence) == 3
    assert {item.kind for item in result.evidence} == {
        EvidenceKind.DRC,
        EvidenceKind.ERC,
        EvidenceKind.SUPPLY_CHAIN_VALIDATION,
    }
    assert len(context.evidence.all_records()) == 3
    governed_types = {item["object_type"] for item in result.payload["governed_objects"]}
    assert "component" in governed_types
    assert "net" in governed_types
    assert "sheet" in governed_types


def test_governed_handoff_records_capability_metadata(tmp_path: Path) -> None:
    from volta.governance import run_governed_handoff

    context = GovernedExecutionContext()
    pcb_path = tmp_path / "board.kicad_pcb"
    pcb_path.write_text("(kicad_pcb)", encoding="utf-8")
    project_dir = tmp_path

    handoff = HandoffResult(
        success=True,
        zip_path="builds/handoff_20260817/handoff.zip",
        manifest=ManufacturingManifest(
            project_name="board",
            board_name="board",
            fab_profile="jlcpcb",
            artifacts=(
                ManufacturingArtifact(
                    name="bom",
                    path=str(tmp_path / "board_JLCPCB-BOM.csv"),
                    sha256="a" * 64,
                    size_bytes=10,
                    generated_by="stub-bom",
                    timestamp="2026-08-17T00:00:00+00:00",
                ),
                ManufacturingArtifact(
                    name="step",
                    path=str(tmp_path / "board.step"),
                    sha256="b" * 64,
                    size_bytes=10,
                    generated_by="stub-step",
                    timestamp="2026-08-17T00:00:00+00:00",
                ),
            ),
        ),
        build=None,
        validation=HandoffValidation(True, True, True, 0, 0, 0),
    )
    result = run_governed_handoff(
        context=context,
        pcb_path=pcb_path,
        project_dir=project_dir,
        result=handoff,
        vendor="jlcpcb",
        schematic_path=None,
    )

    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.invocation.capability_name == "manufacturing.handoff.export"
    assert result.invocation.approval_required is True
    assert len(result.evidence) == 1
    assert result.evidence[0].kind is EvidenceKind.MANUFACTURING_EXPORT
    governed_types = {item["object_type"] for item in result.payload["governed_objects"]}
    assert "bom" in governed_types
    assert "assembly" in governed_types


def test_governed_build_records_snapshot_evidence(tmp_path: Path) -> None:
    from volta.governance import run_governed_build

    context = GovernedExecutionContext()
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    pcb_path = project_dir / "board.kicad_pcb"
    pcb_path.write_text("(kicad_pcb)", encoding="utf-8")
    sch_path = project_dir / "board.kicad_sch"
    sch_path.write_text("(kicad_sch)", encoding="utf-8")

    result = run_governed_build(
        context=context,
        project_dir=project_dir,
        pcb_path=pcb_path,
        schematic_path=sch_path,
        build_result={
            "success": True,
            "build_id": "build-123",
            "board_rev": "1.0",
            "build_dir": "builds/v1",
            "source_files": ["board.kicad_pcb", "board.kicad_sch"],
            "artifacts": [{"name": "board.kicad_pcb"}],
        },
    )

    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.invocation.capability_name == "manufacturing.build.snapshot"
    assert result.evidence[0].kind is EvidenceKind.BUILD_SNAPSHOT


def test_governed_import_records_source_evidence(tmp_path: Path) -> None:
    from volta.governance import run_governed_import

    context = GovernedExecutionContext()
    source_dir = tmp_path / "imports"
    source_dir.mkdir()
    symbol_path = source_dir / "NE555.kicad_sym"
    symbol_path.write_text("(kicad_symbol_lib)", encoding="utf-8")

    components = [
        {
            "mpn": "NE555",
            "file_path": str(symbol_path),
            "supplier": "snapmagic-import",
        }
    ]
    result = run_governed_import(
        context=context,
        source_path=source_dir,
        imported_components=components,
    )

    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.invocation.capability_name == "exchange.import.cad_model"
    assert result.evidence[0].kind is EvidenceKind.IMPORT_SOURCE
    assert "governed_object_id" in components[0]
