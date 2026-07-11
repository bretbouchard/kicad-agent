"""Versioned build system handlers (Phase 207).

Three query-category handlers: ``build_create``, ``build_list``,
``build_show``. These are merged into ``_QUERY_HANDLERS`` in
``handlers/__init__.py`` (mirroring the ``_FILL_ZONES_HANDLERS`` pattern).

Although ``build_create`` writes side-effect artifacts to a ``builds/``
directory, it is registered as a read-only query op because it never modifies
the target ``.kicad_pcb`` source file (CONTEXT.md IP-4 deviation). The
``execute_query`` path skips source serialization, which is correct here.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from kicad_agent.ir.pcb_ir import PcbIR

logger = logging.getLogger(__name__)

_BUILD_HANDLERS: dict[str, Callable] = {}


def register_build(op_type: str) -> Callable:
    """Decorator to register a build operation handler."""
    def decorator(fn: Callable) -> Callable:
        _BUILD_HANDLERS[op_type] = fn
        return fn
    return decorator


@register_build("build_create")
def _handle_build_create(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    """Create a versioned build snapshot (BUILD-01, BUILD-06).

    Snapshots source files, captures git SHA + board revision, and writes a
    manifest with SHA256-hashed artifacts to ``builds/v{rev}_{timestamp}/``.
    The target ``.kicad_pcb`` is never modified (registered read-only).

    On any failure (parse error, traversal attempt), returns an error dict and
    ensures NO partial build directory remains (BUILD-04: no partial state).

    Simplified validation for v1 (CONTEXT.md): the PCB parse in step 2 is the
    validation check; builds default to ``DRAFT``. The full
    ``ManufacturingReadinessGate`` requires context that Phase 208 provides.
    """
    import re
    import shutil
    import uuid
    from datetime import datetime, timezone

    from kicad_agent.manufacturing.build import (
        Build,
        BuildStatus,
        _get_git_sha,
    )
    from kicad_agent.parser.pcb_native_parser import NativeParser
    from kicad_agent.validation.gates.manufacturing_manifest import (
        ManufacturingArtifact,
        ManufacturingManifest,
    )

    # 1. Resolve project_dir + reject path traversal (threat model #1).
    if op.project_dir and ".." in Path(op.project_dir).parts:
        return {
            "success": False,
            "error": "Invalid project_dir: path traversal forbidden",
        }
    project_dir = Path(op.project_dir) if op.project_dir else Path(file_path).parent

    build_dir: Path | None = None
    try:
        # 2. Read board_rev via re-parse (dual-path: query ir has _native_board=None).
        board = NativeParser.parse_pcb(file_path)
        board_rev = (
            board.title_block.rev
            if board.title_block and board.title_block.rev
            else "unknown"
        )

        # 3. Sanitize board_rev for directory name (user-controlled via PCB).
        safe_rev = re.sub(r"[^A-Za-z0-9._-]", "_", board_rev)[:64]

        # 4. Capture git SHA.
        git_sha = _get_git_sha(project_dir)

        # 5. Generate build_id + timestamps.
        build_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        dir_timestamp = now.strftime("%Y%m%d_%H%M%S")

        # 6. Create build dir (handle sub-second timestamp collision).
        build_dir_name = f"v{safe_rev}_{dir_timestamp}"
        builds_root = project_dir / "builds"
        builds_root.mkdir(parents=True, exist_ok=True)
        try:
            build_dir = builds_root / build_dir_name
            build_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            build_dir = builds_root / f"{build_dir_name}_{build_id[:8]}"
            build_dir.mkdir(parents=True, exist_ok=False)

        # 7. Snapshot source files (stem-based discovery, bounded to project_dir).
        stem = Path(file_path).stem
        source_files: list[str] = []
        artifacts: list[ManufacturingArtifact] = []
        resolved_project = project_dir.resolve()
        for ext in (".kicad_pcb", ".kicad_sch", ".kicad_pro"):
            candidate = project_dir / f"{stem}{ext}"
            if candidate.exists() and candidate.resolve().is_relative_to(resolved_project):
                rel = str(candidate.relative_to(project_dir))
                dest = build_dir / candidate.name
                shutil.copy2(candidate, dest)  # copy2 preserves metadata (RQ7)
                source_files.append(rel)
                artifacts.append(
                    ManufacturingArtifact.from_file(
                        name=candidate.name, path=str(dest), generated_by="snapshot"
                    )
                )

        # 8. Create + serialize manifest (manufacturing subset).
        manifest = ManufacturingManifest(
            project_name=stem,
            board_name=stem,
            fab_profile="unknown",
            artifacts=tuple(artifacts),
            bom_rows=0,
            total_components=0,
            generated_at=created_at,
        )
        manifest.save(build_dir / "manifest.json")

        # 9. Create Build record + serialize full envelope (build.json).
        build = Build(
            build_id=build_id,
            board_rev=board_rev,
            source_files=tuple(source_files),
            git_sha=git_sha,
            created_at=created_at,
            status=BuildStatus.DRAFT,
            artifacts=tuple(artifacts),
            manifest_path=str((build_dir / "manifest.json").relative_to(project_dir)),
            build_dir=str(build_dir.relative_to(project_dir)),
        )
        build.save(build_dir / "build.json")

        # 10. Return success.
        return {
            "success": True,
            "build_id": build_id,
            "board_rev": board_rev,
            "git_sha": git_sha,
            "status": BuildStatus.DRAFT.value,
            "build_dir": build.build_dir,
            "manifest_path": build.manifest_path,
            "source_files": source_files,
            "artifacts": [a.to_dict() for a in artifacts],
        }
    except Exception as exc:
        # BUILD-04: no partial state -- rmtree the build dir on any failure.
        if build_dir is not None and build_dir.exists():
            shutil.rmtree(build_dir, ignore_errors=True)
        logger.warning("build_create failed: %s", exc)
        return {
            "success": False,
            "error": f"build_create failed: {exc}",
        }


def _resolve_project_dir(op: Any, file_path: Path) -> Path | dict[str, Any]:
    """Resolve project_dir from op, rejecting path traversal.

    Returns the resolved ``Path`` on success, or an error dict (with
    ``success=False``) if the project_dir contains ``..`` segments. Used by
    build_list/build_show to share the traversal check with build_create.
    """
    if op.project_dir and ".." in Path(op.project_dir).parts:
        return {
            "success": False,
            "error": "Invalid project_dir: path traversal forbidden",
        }
    return Path(op.project_dir) if op.project_dir else Path(file_path).parent


def _find_build_dir_by_id(project_dir: Path, build_id: str) -> Path | None:
    """Scan builds/v*_* for the build whose build.json matches ``build_id``.

    Returns the build subdirectory Path, or None if not found.
    """
    builds_root = project_dir / "builds"
    if not builds_root.is_dir():
        return None
    from kicad_agent.manufacturing.build import Build

    for subdir in sorted(builds_root.glob("v*_*")):
        build_json = subdir / "build.json"
        if not build_json.is_file():
            continue
        try:
            build = Build.load(build_json)
        except Exception:
            continue  # corrupt build.json -- skip
        if build.build_id == build_id:
            return subdir
    return None


@register_build("build_list")
def _handle_build_list(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    """List all builds for a project (BUILD-07).

    Scans ``builds/v*_*`` for subdirectories with a valid ``build.json``.
    Corrupt directories are skipped (never crash the whole list on one bad
    dir). Builds are sorted by ``created_at`` descending (most recent first).
    """
    from kicad_agent.manufacturing.build import Build

    resolved = _resolve_project_dir(op, file_path)
    if isinstance(resolved, dict):
        return resolved  # traversal error
    project_dir = resolved

    builds_root = project_dir / "builds"
    if not builds_root.is_dir():
        return {"builds": [], "count": 0}

    summaries: list[dict[str, Any]] = []
    for subdir in sorted(builds_root.glob("v*_*")):
        build_json = subdir / "build.json"
        if not build_json.is_file():
            continue
        try:
            build = Build.load(build_json)
        except Exception as exc:
            # Skip corrupt dirs -- never crash the whole list on one bad dir.
            logger.warning("build_list: skipping corrupt build dir %s: %s", subdir, exc)
            continue
        summaries.append({
            "build_id": build.build_id,
            "board_rev": build.board_rev,
            "git_sha": build.git_sha,
            "created_at": build.created_at,
            "status": build.status.value,
            "build_dir": str(subdir.relative_to(project_dir)),
        })

    # Sort by created_at descending (most recent first).
    summaries.sort(key=lambda s: s["created_at"], reverse=True)
    return {"builds": summaries, "count": len(summaries)}


@register_build("build_show")
def _handle_build_show(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    """Show build details by build_id (BUILD-08, BUILD-10).

    Optionally accepts ``diff_build_id`` (BUILD-10) -- when set, loads the
    second build and includes a ``diff`` in the response via
    ``diff_builds``. If the diff target is not found, the primary build
    details are still returned with a ``diff_error`` note.
    """
    from dataclasses import asdict

    from kicad_agent.manufacturing.build import Build, diff_builds
    from kicad_agent.validation.gates.manufacturing_manifest import (
        ManufacturingManifest,
    )

    resolved = _resolve_project_dir(op, file_path)
    if isinstance(resolved, dict):
        return resolved  # traversal error
    project_dir = resolved

    # 1. Find the primary build.
    build_dir = _find_build_dir_by_id(project_dir, op.build_id)
    if build_dir is None:
        return {"success": False, "error": f"build not found: {op.build_id}"}

    build = Build.load(build_dir / "build.json")

    # 2. Load the manifest (tolerate missing/corrupt manifest).
    manifest: ManufacturingManifest | None = None
    try:
        manifest = ManufacturingManifest.load(build_dir / "manifest.json")
    except Exception as exc:
        logger.warning("build_show: could not load manifest for %s: %s", build_dir, exc)

    response: dict[str, Any] = {
        "success": True,
        "build_id": build.build_id,
        "board_rev": build.board_rev,
        "git_sha": build.git_sha,
        "created_at": build.created_at,
        "status": build.status.value,
        "source_files": list(build.source_files),
        "build_dir": str(build_dir.relative_to(project_dir)),
        "manifest": manifest.to_json() if manifest else None,
        "artifacts": [a.to_dict() for a in build.artifacts],
    }

    # 3. Diff integration (BUILD-10).
    if op.diff_build_id:
        diff_dir = _find_build_dir_by_id(project_dir, op.diff_build_id)
        if diff_dir is None:
            response["diff_error"] = f"build not found: {op.diff_build_id}"
        else:
            try:
                build_b = Build.load(diff_dir / "build.json")
                diff = diff_builds(build, build_b)
                response["diff"] = asdict(diff)
            except Exception as exc:
                response["diff_error"] = f"diff failed: {exc}"

    return response


@register_build("build_handoff_export")
def _handle_build_handoff_export(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    """Export a complete manufacturer handoff package (HANDOFF-01, HANDOFF-08).

    Delegates to ``export_handoff()`` from ``manufacturing/handoff.py``.
    The target ``.kicad_pcb`` is never modified (registered read-only).
    """
    from dataclasses import asdict

    from kicad_agent.manufacturing.handoff import export_handoff

    # 1. Resolve project_dir + reject path traversal (threat model #1).
    if op.project_dir and ".." in Path(op.project_dir).parts:
        return {
            "success": False,
            "error": "Invalid project_dir: path traversal forbidden",
        }
    project_dir = Path(op.project_dir) if op.project_dir else Path(file_path).parent

    # 2. Call the orchestrator (schematic discovered inside via stem).
    result = export_handoff(
        pcb_path=Path(file_path),
        sch_path=None,
        project_dir=project_dir,
        vendor=op.vendor,
        include_step=op.include_step,
        include_render=op.include_render,
        skip_validation=op.skip_validation,
    )

    # 3. Serialize HandoffResult to dict.
    out: dict[str, Any] = {
        "success": result.success,
        "zip_path": result.zip_path,
        "validation": asdict(result.validation),
        "error_message": result.error_message,
        "manifest": result.manifest.to_json(),
        "artifact_count": len(result.manifest.artifacts),
    }
    if result.build is not None:
        out["build_id"] = result.build.build_id
        out["build_status"] = result.build.status.value
    if result.error_message:
        out["error"] = result.error_message
    return out
