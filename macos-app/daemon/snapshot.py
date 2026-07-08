"""
snapshot.py — File snapshot helper for verification rollback.

Phase 170 — Verification Loop Integration (GOV-05).

Provides atomic file snapshots for the auto-rollback pipeline:
    1. Pre-op:  capture_snapshot(files) → Snapshot(path_map)
    2. Op executes (may mutate files)
    3. Post-op verification runs
    4. On failure: Snapshot.restore() writes original bytes back

Design constraints:
    - Atomic per-file: temp-write + os.replace so a crash mid-restore
      leaves either the new or original file, never a torn write.
    - Snapshots live in a session-scoped directory under the system
      temp prefix; each snapshot gets a unique subdir to avoid collisions.
    - File boundaries enforced: refuse to snapshot path traversal outside
      the project root (T-170-06 mitigation). The daemon handler always
      passes absolute paths; we additionally reject any path containing
      '..' segments as a defense-in-depth measure.
    - Missing files are tracked as "deletions to restore" — if the op
      created a new file that didn't exist pre-op, restore removes it.

Storage layout:
    <tmp>/kicadagent-snapshots/<uuid>/
        manifest.json   # {original_path: sha256, ...}
        blobs/<sha256>  # content-addressed blob store

Content addressing deduplicates identical file contents within one
snapshot (rare, but it keeps the restore loop simple).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# =============================================================================
# Exceptions
# =============================================================================

class SnapshotError(Exception):
    """Raised for any snapshot creation or restoration failure."""


# =============================================================================
# Snapshot
# =============================================================================

@dataclass
class Snapshot:
    """An immutable file snapshot. Restorable exactly once.

    The snapshot directory stays alive until `close()` is called. The
    daemon holds a bounded LRU of recent snapshots (Phase 170 Scope:
    one snapshot per in-flight op; old snapshots GC'd after restore).
    """

    snapshot_dir: Path
    manifest: dict[str, dict[str, Any]] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        files: list[str | Path],
        base_dir: str | Path | None = None,
    ) -> "Snapshot":
        """Capture a snapshot of the given files.

        Args:
            files: List of absolute paths to snapshot. Missing files are
                recorded as "to-be-deleted-on-restore" — if the op creates
                one of these paths, restore removes it.
            base_dir: Optional project root for path-traversal defense.
                If provided, every file must live under base_dir.

        Returns:
            A new Snapshot pointing at a populated snapshot directory.

        Raises:
            SnapshotError: on traversal attempt, permission error, or
                underlying I/O failure.
        """
        # Defense-in-depth: reject any '..' segments regardless of base_dir.
        normalized: list[Path] = []
        for raw in files:
            p = Path(raw)
            if ".." in p.parts:
                raise SnapshotError(
                    f"refused path with '..' segment: {raw} (T-170-06)"
                )
            if base_dir is not None:
                base = Path(base_dir).resolve(strict=False)
                try:
                    resolved = p.resolve(strict=False)
                    resolved.relative_to(base)
                except ValueError:
                    raise SnapshotError(
                        f"path '{raw}' outside base_dir '{base_dir}' (T-170-06)"
                    ) from None
            normalized.append(p)

        # tempfile.mkdtemp treats '/' in prefix as part of the filename, not
        # a subdirectory path — use a flat prefix and rely on the OS temp
        # root. The snapshot_dir itself contains the manifest + blobs/.
        snapshot_dir = Path(tempfile.mkdtemp(prefix="kicadagent-snapshot-"))
        blobs_dir = snapshot_dir / "blobs"
        blobs_dir.mkdir(parents=True, exist_ok=True)

        manifest: dict[str, dict[str, Any]] = {}
        for path in normalized:
            key = str(path)
            if not path.exists():
                # File doesn't exist yet — record that it should be removed
                # on restore (if the op creates it).
                manifest[key] = {"exists": False, "sha256": None}
                continue
            if not path.is_file():
                # Skip directories and special files — snapshots are for
                # regular files only (KiCad artifacts are all regular files).
                raise SnapshotError(
                    f"cannot snapshot non-regular file: {path}"
                )
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            blob_path = blobs_dir / digest
            if not blob_path.exists():
                # Dedupe: identical content already snapshotted.
                blob_path.write_bytes(data)
            manifest[key] = {"exists": True, "sha256": digest}

        manifest_path = snapshot_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return cls(snapshot_dir=snapshot_dir, manifest=manifest)

    # ------------------------------------------------------------------
    # Restoration
    # ------------------------------------------------------------------

    def restore(self) -> dict[str, Any]:
        """Restore all files in the manifest to their pre-op state.

        Returns a summary dict:
            {"restored": int, "removed": int, "skipped": int}

        Raises SnapshotError on any I/O failure. Restoration is
        best-effort atomic per file — a mid-restore crash leaves some
        files restored and others not. The journal logs the intent so
        a future session can complete the restore.
        """
        restored = 0
        removed = 0
        skipped = 0
        for path_str, meta in self.manifest.items():
            path = Path(path_str)
            if not meta.get("exists", False):
                # Pre-op the file didn't exist. If op created it, remove.
                if path.exists():
                    try:
                        path.unlink()
                        removed += 1
                    except OSError as exc:
                        raise SnapshotError(
                            f"failed to remove post-op-created file {path}: {exc}"
                        ) from exc
                else:
                    skipped += 1
                continue

            # Pre-op file existed with this sha256.
            sha = meta.get("sha256")
            if sha is None:
                skipped += 1
                continue
            blob_path = self.snapshot_dir / "blobs" / sha
            if not blob_path.exists():
                raise SnapshotError(
                    f"snapshot blob missing for {path}: {blob_path}"
                )
            data = blob_path.read_bytes()
            # Atomic per-file restore: write to temp then os.replace.
            parent = path.parent
            parent.mkdir(parents=True, exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(
                prefix=".restore-",
                dir=str(parent),
            )
            try:
                with os.fdopen(tmp_fd, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, path)
                restored += 1
            except OSError as exc:
                # Cleanup the temp file if replace failed.
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise SnapshotError(
                    f"failed to restore {path}: {exc}"
                ) from exc

        return {"restored": restored, "removed": removed, "skipped": skipped}

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Delete the snapshot directory. Idempotent."""
        if self.snapshot_dir.exists():
            shutil.rmtree(self.snapshot_dir, ignore_errors=True)


# =============================================================================
# Convenience entry point used by the daemon handler
# =============================================================================

def capture_snapshot(
    files: list[str],
    base_dir: str | None = None,
) -> Snapshot:
    """Module-level convenience wrapper around Snapshot.create."""
    return Snapshot.create(files=files, base_dir=base_dir)
