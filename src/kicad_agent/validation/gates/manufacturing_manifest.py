"""Manufacturing manifest with artifact hashing and provenance.

ManufacturingArtifact records each generated file with SHA256 hash,
file size, and the exact kicad-cli command that produced it.

ManufacturingManifest aggregates all artifacts plus DRC/DFM results
and BOM metadata into a single portable record.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


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
