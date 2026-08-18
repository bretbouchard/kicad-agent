"""Capability-boundary wrappers for governed Volta workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
import re

from volta.governance.evidence import EvidenceKind, EvidenceLedger, EvidenceRecord
from volta.governance.world import (
    GovernedObjectRecord,
    GovernedObjectType,
    VoltaModeledWorld,
)
from volta.ir import SchematicIR
from volta.parser import parse_schematic


class CapabilityStatus(str, Enum):
    """Status of a governed capability invocation."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class CapabilityInvocation:
    """Capability invocation metadata."""

    capability_name: str
    subject_id: str
    approval_required: bool
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CapabilityResult:
    """Outcome of a governed capability invocation."""

    invocation: CapabilityInvocation
    status: CapabilityStatus
    evidence: tuple[EvidenceRecord, ...]
    payload: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""


@dataclass
class GovernedExecutionContext:
    """Shared governed state for a Volta execution slice."""

    world: VoltaModeledWorld = field(default_factory=VoltaModeledWorld)
    evidence: EvidenceLedger = field(default_factory=EvidenceLedger)

    def register_project_objects(
        self,
        *,
        project_dir: Path,
        pcb_path: Path,
        schematic_path: Path | None,
        revision: str = "working",
    ) -> dict[str, GovernedObjectRecord]:
        records = {
            "project": self.world.register(
                GovernedObjectType.PROJECT,
                project_dir,
                revision=revision,
                metadata={"kind": "kicad-project-root"},
            ),
            "pcb": self.world.register(
                GovernedObjectType.PCB,
                pcb_path,
                revision=revision,
            ),
        }
        if schematic_path is not None:
            records["schematic"] = self.world.register(
                GovernedObjectType.SCHEMATIC,
                schematic_path,
                revision=revision,
            )
        return records


def _register_schematic_subobjects(
    context: GovernedExecutionContext,
    schematic_path: Path | None,
    *,
    revision: str,
) -> list[dict[str, str]]:
    """Register logical locators for schematic subobjects."""

    if schematic_path is None or not schematic_path.exists():
        return []

    parse_result = parse_schematic(schematic_path)
    ir = SchematicIR(_parse_result=parse_result)
    governed_objects: list[dict[str, str]] = []

    for component in ir.components:
        ref = ir.get_component_property(component, "Reference")
        if not ref:
            continue
        record = context.world.register(
            GovernedObjectType.COMPONENT,
            f"{schematic_path}#component:{ref}",
            revision=revision,
            metadata={"reference": ref},
        )
        governed_objects.append(
            {"object_id": record.object_id, "object_type": record.object_type.value}
        )

    net_names: set[str] = set()
    schematic = ir.schematic
    for attr in ("labels", "globalLabels", "hierarchicalLabels"):
        for label in getattr(schematic, attr, []) or []:
            text = getattr(label, "text", None)
            if text:
                net_names.add(text)
    for net_name in sorted(net_names):
        record = context.world.register(
            GovernedObjectType.NET,
            f"{schematic_path}#net:{net_name}",
            revision=revision,
            metadata={"name": net_name},
        )
        governed_objects.append(
            {"object_id": record.object_id, "object_type": record.object_type.value}
        )

    for alias in ir.bus_aliases or []:
        name = getattr(alias, "name", None) or getattr(alias, "alias", None)
        if not name:
            continue
        record = context.world.register(
            GovernedObjectType.BUS,
            f"{schematic_path}#bus:{name}",
            revision=revision,
            metadata={"name": name},
        )
        governed_objects.append(
            {"object_id": record.object_id, "object_type": record.object_type.value}
        )

    sheet_count = len(re.findall(r"^\s*\(sheet\b", parse_result.raw_content, re.MULTILINE))
    for index in range(sheet_count):
        record = context.world.register(
            GovernedObjectType.SHEET,
            f"{schematic_path}#sheet:{index}",
            revision=revision,
            metadata={"index": index},
        )
        governed_objects.append(
            {"object_id": record.object_id, "object_type": record.object_type.value}
        )

    return governed_objects


def run_governed_build(
    *,
    context: GovernedExecutionContext,
    project_dir: Path,
    pcb_path: Path,
    schematic_path: Path | None,
    build_result: dict[str, Any],
) -> CapabilityResult:
    """Attach governed traceability to build snapshot creation."""

    revision = build_result.get("board_rev", "working")
    records = context.register_project_objects(
        project_dir=project_dir,
        pcb_path=pcb_path,
        schematic_path=schematic_path,
        revision=revision,
    )
    subject_id = records["pcb"].object_id
    invocation = CapabilityInvocation(
        capability_name="manufacturing.build.snapshot",
        subject_id=subject_id,
        approval_required=False,
        metadata={"build_id": build_result.get("build_id", "")},
    )
    evidence = [
        EvidenceRecord(
            kind=EvidenceKind.BUILD_SNAPSHOT,
            subject_id=subject_id,
            passed=build_result.get("success"),
            summary="Versioned manufacturing build snapshot",
            payload={
                "build_id": build_result.get("build_id", ""),
                "build_dir": build_result.get("build_dir", ""),
                "source_files": list(build_result.get("source_files", [])),
                "artifact_count": len(build_result.get("artifacts", [])),
            },
        )
    ]
    context.evidence.extend(evidence)
    governed_objects = [
        {"object_id": record.object_id, "object_type": record.object_type.value}
        for record in records.values()
    ]
    governed_objects.extend(
        _register_schematic_subobjects(
            context,
            schematic_path,
            revision=revision,
        )
    )
    return CapabilityResult(
        invocation=invocation,
        status=CapabilityStatus.SUCCEEDED
        if build_result.get("success")
        else CapabilityStatus.FAILED,
        evidence=tuple(evidence),
        payload={"governed_objects": governed_objects},
        error_message=build_result.get("error", ""),
    )


def run_governed_import(
    *,
    context: GovernedExecutionContext,
    source_path: Path,
    imported_components: list[dict[str, Any]],
) -> CapabilityResult:
    """Attach governed traceability to import flows."""

    governed_objects: list[dict[str, str]] = []
    for component in imported_components:
        file_path = Path(component["file_path"])
        object_type = (
            GovernedObjectType.FOOTPRINT
            if file_path.suffix.lower() == ".kicad_mod"
            else GovernedObjectType.SYMBOL
        )
        record = context.world.register(
            object_type,
            file_path,
            revision="imported",
            metadata={
                "mpn": component.get("mpn", ""),
                "supplier": component.get("supplier", ""),
                "source_path": str(source_path),
            },
        )
        component["governed_object_id"] = record.object_id
        governed_objects.append(
            {"object_id": record.object_id, "object_type": record.object_type.value}
        )

    invocation = CapabilityInvocation(
        capability_name="exchange.import.cad_model",
        subject_id=str(source_path.resolve()),
        approval_required=False,
        metadata={"source_name": source_path.name},
    )
    evidence = [
        EvidenceRecord(
            kind=EvidenceKind.IMPORT_SOURCE,
            subject_id=str(source_path.resolve()),
            passed=True,
            summary="Governed CAD model import source",
            payload={
                "source_path": str(source_path),
                "imported_count": len(imported_components),
            },
        )
    ]
    context.evidence.extend(evidence)
    return CapabilityResult(
        invocation=invocation,
        status=CapabilityStatus.SUCCEEDED,
        evidence=tuple(evidence),
        payload={"governed_objects": governed_objects},
    )


def run_governed_metadata_read(
    *,
    context: GovernedExecutionContext,
    pcb_path: Path,
    board_spec: Any | None = None,
) -> CapabilityResult:
    """Attach governed identity metadata to board metadata reads."""

    records = context.register_project_objects(
        project_dir=pcb_path.parent,
        pcb_path=pcb_path,
        schematic_path=None,
    )
    subject_id = records["pcb"].object_id
    invocation = CapabilityInvocation(
        capability_name="design.metadata.read",
        subject_id=subject_id,
        approval_required=False,
        metadata={"has_board_spec": board_spec is not None},
    )
    governed_objects = [
        {"object_id": record.object_id, "object_type": record.object_type.value}
        for record in records.values()
    ]
    return CapabilityResult(
        invocation=invocation,
        status=CapabilityStatus.SUCCEEDED,
        evidence=(),
        payload={"governed_objects": governed_objects},
    )


def run_governed_verification(
    *,
    context: GovernedExecutionContext,
    pcb_path: Path,
    schematic_path: Path | None,
    drc_result: Any,
    erc_result: Any | None,
    vendor: str | None = None,
    vendor_result: Any | None = None,
) -> CapabilityResult:
    """Convert Volta verification results into governed evidence."""

    records = context.register_project_objects(
        project_dir=pcb_path.parent,
        pcb_path=pcb_path,
        schematic_path=schematic_path,
    )
    subject_id = records["pcb"].object_id
    invocation = CapabilityInvocation(
        capability_name="verification.batch",
        subject_id=subject_id,
        approval_required=False,
        metadata={"vendor": vendor or "generic"},
    )

    evidence: list[EvidenceRecord] = [
        EvidenceRecord(
            kind=EvidenceKind.DRC,
            subject_id=subject_id,
            passed=getattr(drc_result, "passed", None),
            summary="PCB design-rule verification",
            payload={
                "error_count": getattr(drc_result, "error_count", 0),
                "warning_count": getattr(drc_result, "warning_count", 0),
                "error_message": getattr(drc_result, "error_message", None),
            },
        )
    ]
    if erc_result is not None and "schematic" in records:
        evidence.append(
            EvidenceRecord(
                kind=EvidenceKind.ERC,
                subject_id=records["schematic"].object_id,
                passed=getattr(erc_result, "passed", None),
                summary="Schematic electrical-rule verification",
                payload={
                    "error_count": getattr(erc_result, "error_count", 0),
                    "warning_count": getattr(erc_result, "warning_count", 0),
                    "error_message": getattr(erc_result, "error_message", None),
                },
            )
        )
    if vendor_result is not None:
        evidence.append(
            EvidenceRecord(
                kind=EvidenceKind.SUPPLY_CHAIN_VALIDATION,
                subject_id=subject_id,
                passed=getattr(vendor_result, "passed", None),
                summary="Vendor manufacturing-profile verification",
                payload={
                    "vendor": vendor,
                    "errors": list(getattr(vendor_result, "errors", [])),
                    "warnings": list(getattr(vendor_result, "warnings", [])),
                    "error_message": getattr(vendor_result, "error_message", None),
                },
            )
        )

    context.evidence.extend(evidence)
    governed_objects = [
        {"object_id": record.object_id, "object_type": record.object_type.value}
        for record in records.values()
    ]
    governed_objects.extend(
        _register_schematic_subobjects(
            context,
            schematic_path,
            revision="verified",
        )
    )
    failed = any(item.passed is False for item in evidence)
    return CapabilityResult(
        invocation=invocation,
        status=CapabilityStatus.FAILED if failed else CapabilityStatus.SUCCEEDED,
        evidence=tuple(evidence),
        payload={"governed_objects": governed_objects},
    )


def run_governed_handoff(
    *,
    context: GovernedExecutionContext,
    pcb_path: Path,
    project_dir: Path,
    result: Any,
    vendor: str | None = None,
    schematic_path: Path | None = None,
) -> CapabilityResult:
    """Attach governed capability metadata and artifact evidence to handoff."""

    records = context.register_project_objects(
        project_dir=project_dir,
        pcb_path=pcb_path,
        schematic_path=schematic_path,
    )
    subject_id = records["pcb"].object_id
    governed_objects: list[dict[str, str]] = [
        {"object_id": record.object_id, "object_type": record.object_type.value}
        for record in records.values()
    ]
    governed_objects.extend(
        _register_schematic_subobjects(
            context,
            schematic_path,
            revision="generated",
        )
    )

    manifest = getattr(result, "manifest", None)
    for artifact in getattr(manifest, "artifacts", ()):
        artifact_path = Path(artifact.path)
        if artifact.name == "bom":
            bom_record = context.world.register(
                GovernedObjectType.BOM,
                artifact_path,
                revision="generated",
                metadata={"artifact_name": artifact.name, "generated_by": artifact.generated_by},
            )
            governed_objects.append(
                {"object_id": bom_record.object_id, "object_type": bom_record.object_type.value}
            )
        elif artifact.name in {"cpl", "step"}:
            assembly_record = context.world.register(
                GovernedObjectType.ASSEMBLY,
                artifact_path,
                revision="generated",
                metadata={"artifact_name": artifact.name, "generated_by": artifact.generated_by},
            )
            governed_objects.append(
                {"object_id": assembly_record.object_id, "object_type": assembly_record.object_type.value}
            )

    invocation = CapabilityInvocation(
        capability_name="manufacturing.handoff.export",
        subject_id=subject_id,
        approval_required=vendor is not None,
        metadata={"vendor": vendor or "generic"},
    )
    evidence = [
        EvidenceRecord(
            kind=EvidenceKind.MANUFACTURING_EXPORT,
            subject_id=subject_id,
            passed=getattr(result, "success", None),
            summary="Manufacturing handoff artifact export",
            payload={
                "zip_path": getattr(result, "zip_path", ""),
                "artifact_count": len(getattr(getattr(result, "manifest", None), "artifacts", [])),
                "error_message": getattr(result, "error_message", ""),
            },
        )
    ]
    context.evidence.extend(evidence)
    return CapabilityResult(
        invocation=invocation,
        status=CapabilityStatus.SUCCEEDED if result.success else CapabilityStatus.FAILED,
        evidence=tuple(evidence),
        payload={"governed_objects": governed_objects},
        error_message=getattr(result, "error_message", ""),
    )
