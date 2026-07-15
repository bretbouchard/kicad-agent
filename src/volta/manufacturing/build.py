"""Versioned build data model (BUILD-02, BUILD-03, BUILD-10).

Phase 207: frozen ``Build`` record, ``BuildStatus`` lifecycle enum,
``BuildDiff`` + ``diff_builds`` utility, and the ``_get_git_sha`` helper.

The ``Build`` record is the source of truth for a versioned build snapshot.
It is serialized to ``build.json`` on disk (via ``save``/``load``) alongside a
``manifest.json`` carrying the ``ManufacturingManifest`` subset. ``build_show``
reconstructs the ``Build`` from ``build.json`` -- the round-trip is lossless.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from volta.io.atomic_write import atomic_write
from volta.validation.gates.manufacturing_manifest import ManufacturingArtifact


class BuildStatus(str, Enum):
    """Build lifecycle states (BUILD-03).

    Transitions are forward-only::

        DRAFT --> VALIDATED --> EXPORTED --> HANDED_OFF

    Phase 207 produces ``DRAFT`` (simplified validation). The full
    ``ManufacturingReadinessGate`` (VALIDATED) and export/handoff steps are
    Phase 208.
    """

    DRAFT = "draft"
    VALIDATED = "validated"
    EXPORTED = "exported"
    HANDED_OFF = "handed_off"


# Allowed forward transitions (BUILD-03). A status maps to the set of statuses
# it may transition INTO.
_ALLOWED_TRANSITIONS: dict[BuildStatus, frozenset[BuildStatus]] = {
    BuildStatus.DRAFT: frozenset({BuildStatus.VALIDATED}),
    BuildStatus.VALIDATED: frozenset({BuildStatus.EXPORTED}),
    BuildStatus.EXPORTED: frozenset({BuildStatus.HANDED_OFF}),
    BuildStatus.HANDED_OFF: frozenset(),  # terminal
}


@dataclass(frozen=True)
class Build:
    """Immutable versioned build record (BUILD-02).

    Attributes:
        build_id: UUID4 string identifying this build.
        board_rev: Revision string from the PCB title block (Phase 205), or
            ``"unknown"`` if absent.
        source_files: Relative paths (to project_dir) of snapshot source files.
        git_sha: HEAD commit SHA at build time, or ``"unknown"`` if not a git
            repo / git unavailable.
        created_at: ISO 8601 timestamp of build creation.
        status: Current lifecycle status (``BuildStatus``).
        artifacts: Snapshot artifacts with SHA256 hashes.
        manifest_path: Relative path (to project_dir) of ``manifest.json``.
        build_dir: Relative path (to project_dir) of the build directory.
    """

    build_id: str
    board_rev: str
    source_files: tuple[str, ...]
    git_sha: str
    created_at: str
    status: BuildStatus
    artifacts: tuple[ManufacturingArtifact, ...]
    manifest_path: str
    build_dir: str

    def transition_to(self, new_status: BuildStatus) -> Build:
        """Return a new ``Build`` with ``status`` set to ``new_status``.

        Validates that the transition is an allowed forward move per
        ``_ALLOWED_TRANSITIONS``. Raises ``ValueError`` on disallowed
        transitions (e.g. backwards, skipping, or from a terminal state).
        Uses ``dataclasses.replace`` (CR-01 frozen pattern).
        """
        allowed = _ALLOWED_TRANSITIONS.get(self.status, frozenset())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid build status transition: {self.status.value} -> "
                f"{new_status.value} (allowed: {sorted(s.value for s in allowed) or 'none'})"
            )
        return replace(self, status=new_status)

    def to_dict(self) -> dict:
        """Serialize the Build to a plain dict (for JSON persistence)."""
        return {
            "build_id": self.build_id,
            "board_rev": self.board_rev,
            "source_files": list(self.source_files),
            "git_sha": self.git_sha,
            "created_at": self.created_at,
            "status": self.status.value,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "manifest_path": self.manifest_path,
            "build_dir": self.build_dir,
        }

    def save(self, path: Path) -> None:
        """Persist the Build envelope to ``path`` atomically (build.json)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path) -> Build:
        """Reconstruct a Build from ``build.json`` on disk (lossless round-trip).

        Converts the JSON ``status`` string back to ``BuildStatus`` and the
        artifacts list back to a tuple via ``ManufacturingArtifact.from_dict``.
        """
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            build_id=data["build_id"],
            board_rev=data["board_rev"],
            source_files=tuple(data.get("source_files", [])),
            git_sha=data["git_sha"],
            created_at=data["created_at"],
            status=BuildStatus(data["status"]),
            artifacts=tuple(
                ManufacturingArtifact.from_dict(a) for a in data.get("artifacts", [])
            ),
            manifest_path=data["manifest_path"],
            build_dir=data["build_dir"],
        )


def _get_git_sha(project_dir: Path) -> str:
    """Capture the HEAD git SHA for ``project_dir`` (BUILD-01, RQ5).

    Returns the stripped SHA on success, or the sentinel ``"unknown"`` if:
    - ``git`` is not installed (``FileNotFoundError``),
    - ``project_dir`` is not inside a git repo (non-zero exit),
    - the command times out or otherwise fails.

    Never raises -- degrades gracefully. Uses an argument list (no
    ``shell=True``) so command injection is not possible; ``project_dir`` is
    passed as ``cwd`` only.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    return "unknown"


@dataclass(frozen=True)
class BuildDiff:
    """Result of comparing two ``Build`` records (BUILD-10).

    The ``*_added`` / ``*_removed`` tuples are from the perspective of
    ``diff_builds(a, b)``: "added" means present in ``b`` but not ``a``;
    "removed" means present in ``a`` but not ``b``.
    """

    source_files_added: tuple[str, ...]
    source_files_removed: tuple[str, ...]
    artifacts_added: tuple[str, ...]
    artifacts_removed: tuple[str, ...]
    status_changed: bool
    git_sha_changed: bool
    board_rev_changed: bool


def diff_builds(a: Build, b: Build) -> BuildDiff:
    """Compare two ``Build`` records (BUILD-10).

    Uses set arithmetic on ``source_files`` and artifact ``name`` sets
    (semantic identity -- paths may differ between snapshots). Returned tuples
    are sorted for determinism (RQ8).
    """
    a_src = set(a.source_files)
    b_src = set(b.source_files)
    a_art = {art.name for art in a.artifacts}
    b_art = {art.name for art in b.artifacts}
    return BuildDiff(
        source_files_added=tuple(sorted(b_src - a_src)),
        source_files_removed=tuple(sorted(a_src - b_src)),
        artifacts_added=tuple(sorted(b_art - a_art)),
        artifacts_removed=tuple(sorted(a_art - b_art)),
        status_changed=a.status != b.status,
        git_sha_changed=a.git_sha != b.git_sha,
        board_rev_changed=a.board_rev != b.board_rev,
    )
