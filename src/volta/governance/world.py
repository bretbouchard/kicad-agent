"""Modeled-world helpers for governed Volta electronics objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
import hashlib


class GovernedObjectType(str, Enum):
    """Minimum governed object set for Volta Phase 2."""

    PROJECT = "project"
    SCHEMATIC = "schematic"
    SHEET = "sheet"
    SYMBOL = "symbol"
    COMPONENT = "component"
    NET = "net"
    BUS = "bus"
    PCB = "pcb"
    FOOTPRINT = "footprint"
    BOM = "bom"
    ASSEMBLY = "assembly"


@dataclass(frozen=True)
class GovernedObjectRecord:
    """Stable governed-object identity plus light metadata."""

    object_type: GovernedObjectType
    object_id: str
    path: str
    revision: str
    metadata: dict[str, Any] = field(default_factory=dict)


class VoltaModeledWorld:
    """Small in-repo modeled world for Phase 2 adoption work.

    This deliberately stays minimal: stable IDs, revision tracking, and a
    registry keyed by object type + source path. It is enough to let Volta
    attach governed identity and traceability to existing KiCad workflows
    without inventing product-specific persistence rules.
    """

    def __init__(self) -> None:
        self._records: dict[tuple[GovernedObjectType, str], GovernedObjectRecord] = {}

    @staticmethod
    def _normalize_path(path: Path) -> str:
        return str(path.resolve())

    @classmethod
    def _normalize_locator(cls, locator: Path | str) -> str:
        if isinstance(locator, Path):
            return cls._normalize_path(locator)
        if "#" in locator:
            base, fragment = locator.split("#", 1)
            return f"{cls._normalize_path(Path(base))}#{fragment}"
        return locator

    @staticmethod
    def _derive_id(object_type: GovernedObjectType, normalized_path: str) -> str:
        digest = hashlib.sha256(
            f"{object_type.value}:{normalized_path}".encode("utf-8")
        ).hexdigest()[:16]
        return f"volta:{object_type.value}:{digest}"

    def register(
        self,
        object_type: GovernedObjectType,
        path: Path | str,
        *,
        revision: str = "working",
        metadata: dict[str, Any] | None = None,
    ) -> GovernedObjectRecord:
        """Register or refresh a governed object."""

        normalized_path = self._normalize_locator(path)
        key = (object_type, normalized_path)
        record = GovernedObjectRecord(
            object_type=object_type,
            object_id=self._derive_id(object_type, normalized_path),
            path=normalized_path,
            revision=revision,
            metadata=metadata or {},
        )
        self._records[key] = record
        return record

    def get(
        self, object_type: GovernedObjectType, path: Path | str
    ) -> GovernedObjectRecord | None:
        """Return the governed object for ``path`` if registered."""

        return self._records.get((object_type, self._normalize_locator(path)))

    def all_records(self) -> list[GovernedObjectRecord]:
        """Return every registered governed object."""

        return list(self._records.values())
