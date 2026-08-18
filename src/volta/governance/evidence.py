"""Evidence helpers for governed verification and manufacturing flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EvidenceKind(str, Enum):
    """Evidence categories used by Volta Phase 2."""

    BUILD_SNAPSHOT = "build_snapshot"
    IMPORT_SOURCE = "import_source"
    ERC = "erc"
    DRC = "drc"
    BOM_VALIDATION = "bom_validation"
    SUPPLY_CHAIN_VALIDATION = "supply_chain_validation"
    ASSEMBLY_CHECK = "assembly_check"
    FUNCTIONAL_TEST = "functional_test"
    MANUFACTURING_EXPORT = "manufacturing_export"


@dataclass(frozen=True)
class EvidenceRecord:
    """Single evidence item attached to a governed action."""

    kind: EvidenceKind
    subject_id: str
    passed: bool | None
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    recorded_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class EvidenceLedger:
    """Append-only in-memory evidence ledger for governed flows."""

    def __init__(self) -> None:
        self._records: list[EvidenceRecord] = []

    def record(self, evidence: EvidenceRecord) -> EvidenceRecord:
        self._records.append(evidence)
        return evidence

    def extend(self, evidence: list[EvidenceRecord]) -> None:
        self._records.extend(evidence)

    def all_records(self) -> list[EvidenceRecord]:
        return list(self._records)
