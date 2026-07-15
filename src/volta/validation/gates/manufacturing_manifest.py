"""Manufacturing manifest with artifact hashing and provenance.

ManufacturingArtifact records each generated file with SHA256 hash,
file size, and the exact kicad-cli command that produced it.

ManufacturingManifest aggregates all artifacts plus DRC/DFM results
and BOM metadata into a single portable record.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from volta.io.atomic_write import atomic_write


@dataclass(frozen=True)
class ManufacturingArtifact:
    """Immutable record of a single manufacturing artifact."""

    name: str
    path: str
    sha256: str
    size_bytes: int
    generated_by: str  # actual kicad-cli command string
    timestamp: str

    @staticmethod
    def from_file(name: str, path: str, generated_by: str) -> ManufacturingArtifact:
        """Create artifact record by hashing the file on disk."""
        p = Path(path)
        data = p.read_bytes()
        return ManufacturingArtifact(
            name=name,
            path=str(p),
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            generated_by=generated_by,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def to_dict(self) -> dict:
        """Serialize artifact to a plain dict (explicit field mapping).

        Do NOT use ``dataclasses.asdict`` for load -- round-trip must
        reconstruct the frozen dataclass explicitly (RESEARCH RQ1).
        """
        return {
            "name": self.name,
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "generated_by": self.generated_by,
            "timestamp": self.timestamp,
        }

    @staticmethod
    def from_dict(d: dict) -> ManufacturingArtifact:
        """Reconstruct artifact from a plain dict."""
        return ManufacturingArtifact(
            name=d["name"],
            path=d["path"],
            sha256=d["sha256"],
            size_bytes=d["size_bytes"],
            generated_by=d["generated_by"],
            timestamp=d["timestamp"],
        )


@dataclass(frozen=True)
class ManufacturingManifest:
    """Immutable manufacturing manifest aggregating all export results."""

    project_name: str
    board_name: str
    fab_profile: str
    artifacts: tuple[ManufacturingArtifact, ...] = ()
    bom_rows: int = 0
    total_components: int = 0
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    # Phase 208: DRC/ERC validation results as proof of manufacturability (HANDOFF-09)
    drc_passed: Optional[bool] = None
    erc_passed: Optional[bool] = None
    vendor_drc_passed: Optional[bool] = None
    drc_violation_count: int = 0
    erc_violation_count: int = 0

    def to_json(self) -> str:
        """Serialize manifest to JSON string (indent=2).

        Converts the ``artifacts`` tuple to a list of dicts via
        ``ManufacturingArtifact.to_dict``.
        """
        data = {
            "project_name": self.project_name,
            "board_name": self.board_name,
            "fab_profile": self.fab_profile,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "bom_rows": self.bom_rows,
            "total_components": self.total_components,
            "generated_at": self.generated_at,
            "drc_passed": self.drc_passed,
            "erc_passed": self.erc_passed,
            "vendor_drc_passed": self.vendor_drc_passed,
            "drc_violation_count": self.drc_violation_count,
            "erc_violation_count": self.erc_violation_count,
        }
        return json.dumps(data, indent=2)

    def save(self, path: Path) -> None:
        """Persist manifest to ``path`` atomically (tempfile + os.replace).

        Mirrors ``board_spec.save_board_spec``.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, self.to_json())

    @classmethod
    def load(cls, path: Path) -> ManufacturingManifest:
        """Reconstruct manifest from JSON file on disk (lossless round-trip).

        Rebuilds the ``artifacts`` tuple via ``ManufacturingArtifact.from_dict``.
        """
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        artifacts = tuple(
            ManufacturingArtifact.from_dict(a) for a in data.get("artifacts", [])
        )
        return cls(
            project_name=data["project_name"],
            board_name=data["board_name"],
            fab_profile=data["fab_profile"],
            artifacts=artifacts,
            bom_rows=data.get("bom_rows", 0),
            total_components=data.get("total_components", 0),
            generated_at=data.get("generated_at", ""),
            drc_passed=data.get("drc_passed", None),
            erc_passed=data.get("erc_passed", None),
            vendor_drc_passed=data.get("vendor_drc_passed", None),
            drc_violation_count=data.get("drc_violation_count", 0),
            erc_violation_count=data.get("erc_violation_count", 0),
        )


def generate_manifest(
    project_name: str,
    board_name: str,
    fab_profile: str,
    artifacts: list[ManufacturingArtifact],
    bom_rows: int = 0,
    total_components: int = 0,
) -> ManufacturingManifest:
    """Create a ManufacturingManifest from collected artifacts."""
    return ManufacturingManifest(
        project_name=project_name,
        board_name=board_name,
        fab_profile=fab_profile,
        artifacts=tuple(artifacts),
        bom_rows=bom_rows,
        total_components=total_components,
    )


def validate_manifest(
    manifest: ManufacturingManifest,
    fab_profile: str,
) -> list[str]:
    """Validate manifest completeness for a given fab profile.

    Returns list of blockers for missing required artifacts.
    """
    blockers: list[str] = []
    artifact_names = {a.name for a in manifest.artifacts}

    required = {"gerbers", "drill", "bom", "cpl"}
    missing = required - artifact_names
    for m in sorted(missing):
        blockers.append(f"Missing required artifact: {m}")

    return blockers
