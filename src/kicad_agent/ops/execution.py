"""File-type execution paths -- parse, dispatch, serialize, transaction.

These functions implement the per-file-type execution logic that the
OperationExecutor routes to based on file extension and op_type.

Each function is a standalone extraction from OperationExecutor methods,
taking explicit parameters instead of self to keep executor.py small.

Concurrency safety (O-BUG-008):
    kicad-agent is NOT safe for concurrent access to the same file. Two
    processes (or threads) editing the same .kicad_sch or .kicad_pcb file
    simultaneously will corrupt it. A ``.kicad_agent.lock`` file mechanism
    warns (does not block) when concurrent editors are detected.

Security (threat model):
- T-04-06: Dispatch uses exact op_type matching; unknown raises ValueError
- T-24-01: Path confinement checks for cross-file and create operations
- H-04: Symlink protection in undo stack push
- D-10: LockError raised on lock file write failure
- L-05: External modification detection via mtime
"""

import logging
import os
from pathlib import Path
from typing import Any, Optional

from kicad_agent.crossfile.atomic import AtomicOperation
from kicad_agent.ir.base import _clear_registry
from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ir.transaction import Transaction
from kicad_agent.ops.schema import Operation
from kicad_agent.parser import parse_pcb, parse_schematic
from kicad_agent.parser.uuid_extractor import extract_uuids
from kicad_agent.ops.ir_cache import CacheEntry, IRCache
from kicad_agent.ops.undo_stack import UndoStack
import time

from kicad_agent.serializer import normalize_kicad_output, serialize_pcb, serialize_schematic

# Import handler registries from sub-modules
from kicad_agent.ops.handlers import (
    _SCHEMATIC_HANDLERS,
    _SCHEMATIC_QUERY_HANDLERS,
    _PCB_HANDLERS,
    _PROJECT_HANDLERS,
    _CREATE_HANDLERS,
    _QUERY_HANDLERS,
    _CROSSFILE_HANDLERS,
)

# O-BUG-008: Lock file for concurrent access warning
_LOCK_FILE_NAME = ".kicad_agent.lock"
_LOCK_WARN_INTERVAL_S = 30.0  # Don't warn more often than this
_last_lock_warn: float = 0.0


class LockError(RuntimeError):
    """Raised when lock file creation fails (D-10).

    Concurrent writes to KiCad files cause corruption -- this is a
    blocker, not a warning. Only raised on WRITE failure; lock READ
    failure at site (1) remains soft warning per M-02.
    """
    pass


def _check_concurrent_access(file_path: Path) -> None:
    """Check for and warn about concurrent access to the same file.

    Creates a ``.kicad_agent.lock`` file in the parent directory of the
    target file. If the lock already exists (another process is editing),
    emits a warning. Does NOT block execution -- this is advisory only.

    The lock file contains the target filename and PID for debugging.
    """
    global _last_lock_warn
    lock_path = file_path.parent / _LOCK_FILE_NAME

    now = time.monotonic()
    if lock_path.exists():
        # Only warn once per interval to avoid log spam
        if now - _last_lock_warn > _LOCK_WARN_INTERVAL_S:
            try:
                lock_content = lock_path.read_text(encoding="utf-8").strip()
            except OSError:
                lock_content = "<unreadable>"
            logger.warning(
                "Concurrent access detected: %s is being edited by another process. "
                "Lock file: %s (content: %s). File corruption may occur. (O-BUG-008)",
                file_path.name, lock_path, lock_content,
            )
            _last_lock_warn = now

    # Create/update lock file for this process
    try:
        lock_content = f"{file_path.name}:pid={os.getpid()}"
        lock_path.write_text(lock_content, encoding="utf-8")
    except OSError as e:
        # D-10: Lock file creation failure MUST raise LockError.
        # Concurrent writes to KiCad files cause corruption -- this is a blocker.
        # M-02 note: Site (1) above (lock read failure) remains soft warning.
        raise LockError(
            f"Failed to create lock file {lock_path}: {e}. "
            "Concurrent writes may corrupt KiCad files."
        ) from e

logger = logging.getLogger(__name__)

# Op-type classification sets
CROSS_FILE_OP_TYPES = {"propagate_symbol_change", "update_pcb_from_schematic", "safe_sync_pcb_from_schematic", "repopulate_pcb_from_schematic", "rebuild_pcb_nets"}
CREATE_OP_TYPES = {"create_schematic", "create_pcb", "create_project", "create_symbol", "create_footprint"}
# Ops that manage their own file I/O via raw S-expr edits (must bypass
# serialize_schematic() to avoid kiutils re-serialization on KiCad 10 files).
# safe_annotate (Phase 102): MUST bypass serialize_schematic() to avoid
#   kiutils re-serialization (P0-006). Edits via SchematicRawWriter.
#   Note: safe_sync_pcb_from_schematic uses CROSS_FILE_OP_TYPES above instead
#   (different dispatch path — it's multi-file, safe_annotate is single_file).
SELF_SERIALIZING_OPS = frozenset({"erc_auto_fix_hierarchical", "convert_kicad6_to_10", "safe_annotate"})

# Pre-analysis gate: shared instance (stateless, safe to reuse)
_PRE_ANALYSIS_GATE = None

# M-03: Single source of truth for valid KiCad extensions (imported from pre_analysis.py)
from kicad_agent.ops.pre_analysis import _VALID_KICAD_EXTENSIONS


def get_pre_analysis_gate():
    """Lazy-load the pre-analysis gate to avoid import overhead."""
    global _PRE_ANALYSIS_GATE
    if _PRE_ANALYSIS_GATE is None:
        from kicad_agent.ops.pre_analysis import PreAnalysisGate
        _PRE_ANALYSIS_GATE = PreAnalysisGate()
    return _PRE_ANALYSIS_GATE


def is_project_file(file_path: Path) -> bool:
    """Check if the file is a project-level file (not schematic/PCB)."""
    name = file_path.name
    suffix = file_path.suffix
    return (
        name in ("sym-lib-table", "fp-lib-table")
        or suffix in (".kicad_dru", ".kicad_pro")
    )


def try_native_parse(file_path: Path) -> "NativeBoard | None":
    """Try native parser. Returns NativeBoard on success, None on failure.

    CRITICAL-1: Catches Exception (not just RecursionError) since
    the depth pre-scan prevents RecursionError from occurring.
    """
    from kicad_agent.parser.pcb_native_parser import NativeParser

    try:
        native_board = NativeParser.parse_pcb(file_path)
        # Validate parse succeeded (has nets or footprints)
        if native_board.nets or native_board.footprints:
            return native_board
        logger.warning(
            "NativeParser returned empty board for %s, falling back to kiutils",
            file_path,
        )
    except Exception:
        logger.warning(
            "NativeParser failed for %s, falling back to kiutils",
            file_path,
            exc_info=True,
        )
    return None


# ---------------------------------------------------------------------------
# Query execution (read-only, no Transaction, no serialization)
# ---------------------------------------------------------------------------


def execute_query(
    op: Operation,
    file_path: Path,
    cache: Optional[IRCache],
) -> dict[str, Any]:
    """Execute a read-only query operation (no Transaction, no serialization).

    Query operations parse the file and build IR, but skip Transaction
    wrapping, serialization, and file writes. The file mtime is unchanged.

    Args:
        op: Validated Operation from the schema.
        file_path: Resolved path to the target file.
        cache: Optional IR cache for parse results.

    Returns:
        Dict with: success, operation, target_file, details.
    """
    root = op.root

    cached_entry = cache.get(file_path) if cache else None
    if cached_entry is not None:
        parse_result = cached_entry.parse_result
        uuid_map = cached_entry.uuid_map
    else:
        parse_result = parse_pcb(file_path)
        uuid_map = extract_uuids(parse_result.raw_content, "pcb")
        if cache:
            cache.put(file_path, CacheEntry(parse_result=parse_result, uuid_map=uuid_map))

    ir = PcbIR(_parse_result=parse_result, _uuid_map=uuid_map)
    details = dispatch_query(root.op_type, root, ir, file_path)
    return {
        "success": True,
        "operation": root.op_type,
        "target_file": root.target_file,
        "details": details,
    }


def dispatch_query(
    op_type: str,
    op: Any,
    ir: PcbIR,
    file_path: Path,
) -> dict[str, Any]:
    """Dispatch query operations via registry.

    Args:
        op_type: The operation type string.
        op: The operation's root model.
        ir: PcbIR for the target PCB file.
        file_path: Resolved path to the target file.

    Returns:
        Handler result dict.

    Raises:
        ValueError: For unknown op_type.
    """
    handler = _QUERY_HANDLERS.get(op_type)
    if handler is not None:
        return handler(op, ir, file_path)
    raise ValueError(f"Unknown query op_type: {op_type!r}")


def execute_schematic_query(
    op: Operation,
    file_path: Path,
    cache: Optional[IRCache],
) -> dict[str, Any]:
    """Execute a read-only schematic query (no Transaction, no serialization).

    Schematic query operations parse the file and build SchematicIR, but skip
    Transaction wrapping, serialization, and file writes. The file mtime is
    unchanged.

    Args:
        op: Validated Operation from the schema.
        file_path: Resolved path to the target schematic file.
        cache: Optional IR cache for parse results.

    Returns:
        Dict with: success, operation, target_file, details.
    """
    root = op.root

    # Clear IR registry to avoid stale registrations across operations
    _clear_registry()

    cached_entry = cache.get(file_path) if cache else None
    if cached_entry is not None:
        parse_result = cached_entry.parse_result
    else:
        parse_result = parse_schematic(file_path)
        if cache:
            cache.put(file_path, CacheEntry(parse_result=parse_result))

    ir = SchematicIR(_parse_result=parse_result)
    handler = _SCHEMATIC_QUERY_HANDLERS.get(root.op_type)
    if handler is None:
        raise ValueError(f"Unknown schematic query op_type: {root.op_type!r}")
    details = handler(root, ir, file_path)
    # Clear registry after query so ParseResult id is released for
    # subsequent operations in the same process (e.g. tests).
    _clear_registry()
    return {
        "success": True,
        "operation": root.op_type,
        "target_file": root.target_file,
        "details": details,
    }


# ---------------------------------------------------------------------------
# Create execution (no Transaction, no IR)
# ---------------------------------------------------------------------------


def execute_create(
    op: Operation,
    file_path: Path,
    base_dir: Path,
) -> dict[str, Any]:
    """Execute a file-creation operation (no Transaction, no IR).

    Create operations generate new files from scratch. They do not need
    Transaction wrapping since there is nothing to roll back to.

    Args:
        op: Validated Operation from the schema.
        file_path: Resolved path for the new file.
        base_dir: Base directory for security checks.

    Returns:
        Dict with: success, operation, target_file, details.
    """
    # Security (T-24-01): path confinement for create operations too
    resolved = file_path.resolve()
    base_resolved = base_dir.resolve()
    if not resolved.is_relative_to(base_resolved):
        raise ValueError(
            f"Security: path escapes project directory: {op.root.target_file}"
        )

    root = op.root
    handler = _CREATE_HANDLERS.get(root.op_type)
    if handler is None:
        raise ValueError(f"Unknown create op_type: {root.op_type!r}")

    details = handler(root, file_path)
    return {
        "success": True,
        "operation": root.op_type,
        "target_file": root.target_file,
        "details": details,
    }


# ---------------------------------------------------------------------------
# Schematic execution (parse, dispatch, serialize, transaction)
# ---------------------------------------------------------------------------


def execute_schematic(
    op: Operation,
    file_path: Path,
    cache: Optional[IRCache],
    undo_stack: Optional[UndoStack],
) -> dict[str, Any]:
    """Execute an operation targeting a schematic file."""
    # O-BUG-008: Check for concurrent access
    _check_concurrent_access(file_path)
    root = op.root

    # Capture pre-mutation content for undo stack
    pre_content: Optional[str] = None
    if undo_stack is not None:
        pre_content = file_path.read_text(encoding="utf-8")

    cached_entry = cache.get(file_path) if cache else None
    if cached_entry is not None:
        parse_result = cached_entry.parse_result
    else:
        parse_result = parse_schematic(file_path)
        if cache:
            cache.put(file_path, CacheEntry(parse_result=parse_result))

    ir = SchematicIR(_parse_result=parse_result)

    # Pre-analysis gate: check before mutating
    gate = get_pre_analysis_gate()
    pre_result = gate.analyze(root, ir, file_path)
    if pre_result.blocked:
        blocker_msgs = [f.message for f in pre_result.blockers]
        return {
            "success": False,
            "operation": root.op_type,
            "target_file": root.target_file,
            "pre_analysis": pre_result.to_dict(),
            "error": f"Pre-analysis blocked: {'; '.join(blocker_msgs)}",
        }
    if pre_result.warnings:
        for w in pre_result.warnings:
            logger.warning("Pre-analysis warning [%s]: %s", w.category, w.message)

    with Transaction(file_path) as txn:
        details = dispatch_schematic(root.op_type, root, ir, file_path)

        # Skip serialization for operations that manage their own file I/O
        # (e.g. erc_auto_fix_hierarchical writes sub-sheets directly).
        if root.op_type not in SELF_SERIALIZING_OPS:
            serialize_schematic(parse_result, file_path)
            content = file_path.read_text(encoding="utf-8")
            normalized = normalize_kicad_output(content)
            file_path.write_text(normalized, encoding="utf-8")

        txn.commit()

        # Capture post-mutation content for undo stack
        if undo_stack is not None and pre_content is not None:
            post_content = file_path.read_text(encoding="utf-8")
            post_mtime = file_path.stat().st_mtime_ns
            undo_stack.push(file_path, pre_content, post_content, root.op_type, post_mtime)

    # Invalidate old cache entry and re-parse from disk to get fresh content
    # (O-BUG-001: avoid caching stale parse_result with old raw_content)
    if cache:
        cache.invalidate(file_path)
        fresh_parse_result = parse_schematic(file_path)
        cache.put(file_path, CacheEntry(parse_result=fresh_parse_result))

    # Clear registry so ParseResult id is released for subsequent operations
    _clear_registry()

    return {
        "success": True,
        "operation": root.op_type,
        "target_file": root.target_file,
        "details": details,
        "pre_analysis": pre_result.to_dict(),
    }


def dispatch_schematic(
    op_type: str,
    op: Any,
    ir: SchematicIR,
    file_path: Path,
) -> dict[str, Any]:
    """Dispatch to the appropriate schematic handler via registry.

    T-04-06: Exact string matching. Unknown op_type raises ValueError.

    Args:
        op_type: The operation type string.
        op: The operation's root model (e.g. AddComponentOp).
        ir: SchematicIR for the target file.
        file_path: Resolved path to the target file.

    Returns:
        Handler result dict.

    Raises:
        ValueError: For unknown op_type.
    """
    handler = _SCHEMATIC_HANDLERS.get(op_type)
    if handler is not None:
        return handler(op, ir, file_path)
    raise ValueError(f"Unknown op_type: {op_type!r}")


# ---------------------------------------------------------------------------
# PCB execution (parse, dispatch, serialize, transaction)
# ---------------------------------------------------------------------------


def execute_pcb(
    op: Operation,
    file_path: Path,
    cache: Optional[IRCache],
    undo_stack: Optional[UndoStack],
) -> dict[str, Any]:
    """Execute an operation targeting a PCB file."""
    # O-BUG-008: Check for concurrent access
    _check_concurrent_access(file_path)
    root = op.root

    # Capture pre-mutation content for undo stack
    pre_content: Optional[str] = None
    if undo_stack is not None:
        pre_content = file_path.read_text(encoding="utf-8")

    cached_entry = cache.get(file_path) if cache else None
    if cached_entry is not None:
        parse_result = cached_entry.parse_result
        uuid_map = cached_entry.uuid_map
        if cached_entry.native_board is not None:
            ir = PcbIR.from_native(cached_entry.native_board)
        else:
            ir = PcbIR(_parse_result=parse_result, _uuid_map=uuid_map)
    else:
        # Try native parser first (kiutils corrupts some PCB files)
        native_board = try_native_parse(file_path)
        parse_result = None
        uuid_map = None

        if native_board is not None:
            ir = PcbIR.from_native(native_board)
        else:
            # Fall back to kiutils for serialization support
            parse_result = parse_pcb(file_path)
            uuid_map = extract_uuids(parse_result.raw_content, "pcb")
            ir = PcbIR(_parse_result=parse_result, _uuid_map=uuid_map)

        if cache:
            cache.put(file_path, CacheEntry(parse_result=parse_result, uuid_map=uuid_map, native_board=native_board))

    # Pre-flight gate: check before mutating (D-01)
    gate = get_pre_analysis_gate()
    pre_result = gate.analyze(root, ir, file_path)
    if pre_result.blocked:
        blocker_msgs = [f.message for f in pre_result.blockers]
        return {
            "success": False,
            "operation": root.op_type,
            "target_file": root.target_file,
            "pre_analysis": pre_result.to_dict(),
            "error": f"Pre-flight blocked: {'; '.join(blocker_msgs)}",
        }
    if pre_result.warnings:
        for w in pre_result.warnings:
            logger.warning("Pre-flight warning [%s]: %s", w.category, w.message)

    with Transaction(file_path) as txn:
        details = dispatch_pcb(root.op_type, root, ir, file_path)

        # Skip kiutils serialization if the IR method already wrote directly
        # via raw S-expression manipulation, or if native parser was used
        # (no kiutils parse_result available).
        if not ir.raw_written and parse_result is not None:
            serialize_pcb(parse_result, file_path, uuid_map=uuid_map)

        txn.commit()

        # Capture post-mutation content for undo stack
        if undo_stack is not None and pre_content is not None:
            post_content = file_path.read_text(encoding="utf-8")
            post_mtime = file_path.stat().st_mtime_ns
            undo_stack.push(file_path, pre_content, post_content, root.op_type, post_mtime)

    # Invalidate old cache entry; for raw-written PCBs, do NOT re-cache
    # stale data -- the next operation will trigger a fresh parse.
    # (O-BUG-002: raw writes may change UUIDs, so uuid_map is also stale)
    if cache:
        cache.invalidate(file_path)
        if not ir.raw_written:
            fresh_parse_result = parse_pcb(file_path)
            fresh_uuid_map = extract_uuids(fresh_parse_result.raw_content, "pcb")
            cache.put(file_path, CacheEntry(parse_result=fresh_parse_result, uuid_map=fresh_uuid_map))

    return {
        "success": True,
        "operation": root.op_type,
        "target_file": root.target_file,
        "details": details,
    }


def dispatch_pcb(
    op_type: str,
    op: Any,
    ir: PcbIR,
    file_path: Path,
) -> dict[str, Any]:
    """Dispatch PCB-specific operations via registry.

    Args:
        op_type: The operation type string.
        op: The operation's root model.
        ir: PcbIR for the target PCB file.
        file_path: Resolved path to the target PCB file.

    Returns:
        Handler result dict.

    Raises:
        ValueError: For unknown op_type.
    """
    handler = _PCB_HANDLERS.get(op_type)
    if handler is not None:
        return handler(op, ir, file_path)
    raise ValueError(f"Unknown PCB op_type: {op_type!r}")


# ---------------------------------------------------------------------------
# Project execution
# ---------------------------------------------------------------------------


def execute_project(
    op: Operation,
    file_path: Path,
    undo_stack: Optional[UndoStack],
) -> dict[str, Any]:
    """Execute an operation targeting a project-level file.

    Handles sym-lib-table, fp-lib-table, .kicad_dru, and .kicad_pro files
    using the project module parsers and editors.

    Args:
        op: Validated Operation from the schema.
        file_path: Resolved path to the target file.
        undo_stack: Optional undo stack for tracking mutations.

    Returns:
        Dict with: success, operation, target_file, details.
    """
    root = op.root
    pre_content: Optional[str] = None
    if undo_stack is not None and file_path.exists():
        pre_content = file_path.read_text(encoding="utf-8")

    with Transaction(file_path) as txn:
        details = dispatch_project(root.op_type, root, file_path)
        txn.commit()

        if undo_stack is not None and pre_content is not None:
            post_content = file_path.read_text(encoding="utf-8")
            post_mtime = file_path.stat().st_mtime_ns
            undo_stack.push(file_path, pre_content, post_content, root.op_type, post_mtime)

    return {
        "success": True,
        "operation": root.op_type,
        "target_file": root.target_file,
        "details": details,
    }


def dispatch_project(
    op_type: str,
    op: Any,
    file_path: Path,
) -> dict[str, Any]:
    """Dispatch project-file operations via registry.

    Args:
        op_type: The operation type string.
        op: The operation's root model.
        file_path: Resolved path to the target file.

    Returns:
        Handler result dict.

    Raises:
        ValueError: For unknown op_type.
    """
    handler = _PROJECT_HANDLERS.get(op_type)
    if handler is not None:
        return handler(op, file_path)
    raise ValueError(f"Unknown project op_type: {op_type!r}")


# ---------------------------------------------------------------------------
# Cross-file execution
# ---------------------------------------------------------------------------


def resolve_cross_file_paths(op: Any, base_dir: Path) -> list[Path]:
    """Resolve file paths from a cross-file operation schema."""
    if hasattr(op, "target_files"):
        return [base_dir / tf for tf in op.target_files]
    return []


def execute_cross_file(
    op: Operation,
    file_path: Path,
    base_dir: Path,
    cache: Optional[IRCache],
    undo_stack: Optional[UndoStack],
) -> dict[str, Any]:
    """Execute a cross-file operation targeting multiple files atomically."""
    root = op.root

    # Resolve all target file paths relative to base_dir
    file_paths = resolve_cross_file_paths(root, base_dir)
    if not file_paths:
        raise ValueError(f"Cross-file operation {root.op_type!r} requires at least one target file")

    # Security (T-24-01): path confinement for ALL files in cross-file operation
    base_resolved = base_dir.resolve()
    for fp in file_paths:
        if not fp.resolve().is_relative_to(base_resolved):
            raise ValueError(
                f"Security: path escapes project directory in cross-file op: {fp}"
            )
        if not fp.exists():
            raise FileNotFoundError(f"Cross-file target not found: {fp}")
        # D-15: Validate KiCad file extension
        if fp.suffix not in _VALID_KICAD_EXTENSIONS:
            raise ValueError(
                f"Cross-file operation target has invalid KiCad file extension: {fp.suffix}. "
                f"Valid extensions: {sorted(_VALID_KICAD_EXTENSIONS)}"
            )

    # Clear IR registry to avoid stale registrations
    _clear_registry()

    # Phase 1: Parse all files and build IR map (XFILE-07: validate before Transaction)
    ir_map: dict[Path, Any] = {}
    for fp in file_paths:
        if fp.suffix == ".kicad_pcb":
            parse_result = parse_pcb(fp)
            uuid_map = extract_uuids(parse_result.raw_content, "pcb")
            ir_map[fp] = PcbIR(_parse_result=parse_result, _uuid_map=uuid_map)
        elif fp.suffix == ".kicad_sch":
            parse_result = parse_schematic(fp)
            ir_map[fp] = SchematicIR(_parse_result=parse_result)
        else:
            raise ValueError(f"Cross-file operation unsupported file type: {fp.suffix}")

    # Phase 2: Capture pre-mutation content for undo stack
    pre_contents: dict[Path, str] = {}
    if undo_stack is not None:
        for fp in file_paths:
            if fp.exists():
                pre_contents[fp] = fp.read_text(encoding="utf-8")

    # Pre-flight gate: check before mutating (D-01)
    # H-02 fix: Pass full ir_map so cross-file checks can access all files' IRs
    gate = get_pre_analysis_gate()
    first_file = file_paths[0]
    pre_result = gate.analyze(root, ir_map, first_file)
    if pre_result.blocked:
        blocker_msgs = [f.message for f in pre_result.blockers]
        return {
            "success": False,
            "operation": root.op_type,
            "target_file": root.target_file,
            "pre_analysis": pre_result.to_dict(),
            "error": f"Pre-flight blocked: {'; '.join(blocker_msgs)}",
        }
    if pre_result.warnings:
        for w in pre_result.warnings:
            logger.warning("Pre-flight warning [%s]: %s", w.category, w.message)

    # Phase 3: Open AtomicOperation and execute handler
    with AtomicOperation(file_paths) as atomic:
        handler = _CROSSFILE_HANDLERS.get(root.op_type)
        if handler is None:
            raise ValueError(f"Unknown cross-file op_type: {root.op_type!r}")

        details = handler(root, ir_map, base_dir)

        # Phase 4: Serialize all dirty IRs
        for fp, ir in ir_map.items():
            if ir.dirty:
                if isinstance(ir, PcbIR):
                    parse_result = ir._parse_result
                    uuid_map = ir.uuid_map
                    if not ir.raw_written:
                        serialize_pcb(parse_result, fp, uuid_map=uuid_map)
                elif isinstance(ir, SchematicIR):
                    serialize_schematic(ir._parse_result, fp)
                    content = fp.read_text(encoding="utf-8")
                    normalized = normalize_kicad_output(content)
                    fp.write_text(normalized, encoding="utf-8")

        # Phase 5: Commit atomic operation
        atomic_result = atomic.commit()
        if not atomic_result.success:
            return {
                "success": False,
                "operation": root.op_type,
                "details": details,
                "error": atomic_result.error,
            }

    # Push undo entries for all dirty files after successful commit
    if undo_stack is not None:
        for fp, ir in ir_map.items():
            if ir.dirty and fp in pre_contents:
                post_content = fp.read_text(encoding="utf-8")
                post_mtime = fp.stat().st_mtime_ns
                undo_stack.push(fp, pre_contents[fp], post_content, root.op_type, post_mtime)

    return {
        "success": True,
        "operation": root.op_type,
        "details": details,
    }
