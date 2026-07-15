"""Batch execution -- single parse/write per file for multiple operations.

Extracted from executor.py to keep the OperationExecutor class under 800 lines.
The execute_batch function groups operations by target file, parses each once,
applies all mutations, and serializes once per file.

Security (threat model):
- T-24-01: Path confinement validated for all batch operation targets

Usage:
    from volta.ops.executor import OperationExecutor

    executor = OperationExecutor(base_dir=Path("/project"))
    result = executor.execute_batch([op1, op2, op3])
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from volta.ir.base import _clear_registry, _deregister_ir
from volta.ir.pcb_ir import PcbIR
from volta.ir.schematic_ir import SchematicIR
from volta.ir.transaction import Transaction
from volta.ops.execution import (
    dispatch_pcb,
    dispatch_project,
    is_project_file,
    CROSS_FILE_OP_TYPES,
    CREATE_OP_TYPES,
)
from volta.ops.ir_cache import CacheEntry
from volta.ops.schema import Operation
from volta.parser import parse_pcb, parse_schematic
from volta.parser.uuid_extractor import extract_uuids
from volta.serializer import normalize_kicad_output, serialize_pcb, serialize_schematic

if TYPE_CHECKING:
    from volta.ops.executor import OperationExecutor

logger = logging.getLogger(__name__)


class BatchOpFailedError(Exception):
    """Raised when a batch operation fails, triggering rollback (D-08).

    L-02 fix: Chains the original exception via __cause__ for better tracebacks.
    """

    def __init__(self, op_type: str, target_file: str, reason: str):
        self.op_type = op_type
        self.target_file = target_file
        super().__init__(
            f"Batch op '{op_type}' failed on '{target_file}': {reason}"
        )


def _get_pre_analysis_gate():
    """Return the shared PreAnalysisGate singleton from execution.py.

    O-BUG-011: Uses the module-level singleton instead of creating a new
    instance, ensuring consistent pre-analysis behavior across all execution
    paths (execute, execute_batch, execute_query, etc.).
    """
    from volta.ops.execution import get_pre_analysis_gate

    return get_pre_analysis_gate()


def execute_batch(executor: OperationExecutor, ops: list[Operation]) -> dict[str, Any]:
    """Execute multiple operations with single parse/write per file.

    Groups ops by target file, parses each once, applies all mutations,
    serializes once per file. Validates ALL operations before executing ANY.

    Not supported: cross-file ops and create ops -- use execute() for those.

    Args:
        executor: The OperationExecutor instance (provides base_dir, cache,
            undo_stack, and dispatch methods).
        ops: List of validated Operation instances to execute.

    Returns:
        Dict with: success, results (list of per-op result dicts).
        On validation failure: success=False, validation_errors list.
    """
    from volta.ops.handlers import (
        _PCB_HANDLERS,
        _PROJECT_HANDLERS,
        _SCHEMATIC_HANDLERS,
        _SCHEMATIC_QUERY_HANDLERS,
    )

    # Op-type classification sets (from execution.py)
    _CROSS_FILE_OP_TYPES = CROSS_FILE_OP_TYPES
    _CREATE_OP_TYPES = CREATE_OP_TYPES

    base_dir = executor._base_dir
    cache = executor._cache
    undo_stack = executor._undo_stack

    # Early return for empty batch
    if not ops:
        return {"success": True, "results": []}

    # Validate operation dependency ordering before execution
    from volta.ops.registry import validate_dependencies
    op_types_in_order = [op.root.op_type for op in ops]
    missing_prereqs = validate_dependencies(op_types_in_order)
    if missing_prereqs:
        missing_set = sorted(set(missing_prereqs))
        return {
            "success": False,
            "results": [],
            "error": (
                f"Batch rejected: missing prerequisite operation(s): "
                f"{missing_set}. "
                f"Run these prerequisite operations before retrying."
            ),
            "missing_prerequisites": missing_set,
        }

    # Validate conflict pairs: detect op_types that conflict with each other
    from volta.ops.registry import OPERATION_REGISTRY
    op_type_set: set[str] = set()
    conflict_errors: list[str] = []
    for op in ops:
        root = op.root
        meta = OPERATION_REGISTRY.get(root.op_type)
        if meta is not None:
            for conflict in meta.conflicts:
                if conflict in op_type_set:
                    conflict_errors.append(
                        f"Conflict: {root.op_type!r} conflicts with {conflict!r}"
                    )
        op_type_set.add(root.op_type)
    if conflict_errors:
        return {
            "success": False,
            "results": [],
            "error": (
                f"Batch rejected: {len(conflict_errors)} conflict(s) detected"
            ),
            "validation_errors": conflict_errors,
        }

    # Reject unsupported op types
    unsupported: list[str] = []
    from volta.ops.registry import OPERATION_REGISTRY as _REG
    for op in ops:
        root = op.root
        if root.op_type in _CROSS_FILE_OP_TYPES:
            unsupported.append(root.op_type)
        elif root.op_type in _CREATE_OP_TYPES:
            unsupported.append(root.op_type)
        elif root.op_type in _REG and _REG[root.op_type].scope == "multi_file":
            unsupported.append(root.op_type)
    if unsupported:
        return {
            "success": False,
            "results": [],
            "error": f"Batch rejected: unsupported op types: {sorted(set(unsupported))}",
        }

    # Security (T-24-01): path confinement -- validate all paths first
    base_resolved = base_dir.resolve()
    for op in ops:
        file_path = base_dir / op.root.target_file
        resolved = file_path.resolve()
        if not resolved.is_relative_to(base_resolved):
            return {
                "success": False,
                "results": [],
                "error": f"Security: path escapes project directory: {op.root.target_file}",
            }

    # Group by target file
    file_ops: dict[Path, list[Operation]] = {}
    file_order: list[Path] = []
    for op in ops:
        fp = (base_dir / op.root.target_file).resolve()
        if fp not in file_ops:
            file_ops[fp] = []
            file_order.append(fp)
        file_ops[fp].append(op)

    # Clear IR registry once for the entire batch
    _clear_registry()

    # Phase 1 -- Parse and validate ALL operations
    ir_map: dict[Path, Any] = {}
    parse_result_map: dict[Path, Any] = {}  # file_path -> parse_result
    uuid_map_store: dict[Path, Any] = {}  # file_path -> uuid_map (PCB only)
    validation_errors: list[str] = []

    for file_path in file_order:
        ops_for_file = file_ops[file_path]

        if not file_path.exists():
            for op in ops_for_file:
                validation_errors.append(
                    f"Target file not found: {op.root.target_file}"
                )
            continue

        # Parse the file (with cache if available)
        if file_path.suffix == ".kicad_pcb":
            cached_entry = cache.get(file_path) if cache else None
            if cached_entry is not None:
                parse_result = cached_entry.parse_result
                uuid_map = cached_entry.uuid_map
            else:
                parse_result = parse_pcb(file_path)
                uuid_map = extract_uuids(parse_result.raw_content, "pcb")
                if cache:
                    cache.put(
                        file_path,
                        CacheEntry(parse_result=parse_result, uuid_map=uuid_map),
                    )
            parse_result_map[file_path] = parse_result
            uuid_map_store[file_path] = uuid_map
            ir_map[file_path] = PcbIR(
                _parse_result=parse_result, _uuid_map=uuid_map
            )
        else:
            # Schematic (default)
            cached_entry = cache.get(file_path) if cache else None
            if cached_entry is not None:
                parse_result = cached_entry.parse_result
            else:
                parse_result = parse_schematic(file_path)
                if cache:
                    cache.put(
                        file_path, CacheEntry(parse_result=parse_result)
                    )
            parse_result_map[file_path] = parse_result
            ir_map[file_path] = SchematicIR(_parse_result=parse_result)

        # Validate handlers exist for all ops targeting this file
        for op in ops_for_file:
            root = op.root
            if file_path.suffix == ".kicad_pcb":
                handler = _PCB_HANDLERS.get(root.op_type)
            elif is_project_file(file_path):
                handler = _PROJECT_HANDLERS.get(root.op_type)
            else:
                handler = (
                    _SCHEMATIC_HANDLERS.get(root.op_type)
                    or _SCHEMATIC_QUERY_HANDLERS.get(root.op_type)
                )

            if handler is None:
                validation_errors.append(
                    f"No handler for op_type '{root.op_type}' on "
                    f"{file_path.suffix or file_path.name}"
                )

        # H-04 fix: Run pre-analysis gate for ALL file types, not just .kicad_sch
        # The universal gate (Plan 96-01) now handles .kicad_pcb and cross-file
        # via file-type dispatch internally.
        gate = _get_pre_analysis_gate()
        if file_path in ir_map:
            ir = ir_map[file_path]
            for op in ops_for_file:
                root = op.root
                pre = gate.analyze(root, ir, file_path)
                if pre.blocked:
                    msgs = [f.message for f in pre.blockers]
                    validation_errors.append(
                        f"Pre-analysis blocked '{root.op_type}': "
                        + "; ".join(msgs)
                    )
                if pre.warnings:
                    for w in pre.warnings:
                        logger.warning(
                            "Pre-analysis warning [%s] for '%s': %s",
                            w.category, root.op_type, w.message,
                        )

    if validation_errors:
        return {
            "success": False,
            "results": [],
            "validation_errors": validation_errors,
            "error": f"Batch rejected: {len(validation_errors)} validation "
            f"failure{'s' if len(validation_errors) != 1 else ''}",
        }

    # Phase 2 -- Capture pre-mutation content for undo stack
    pre_contents: dict[Path, str] = {}
    if undo_stack is not None:
        for file_path in file_order:
            if file_path.exists():
                pre_contents[file_path] = file_path.read_text(encoding="utf-8")

    # Phase 3 -- Apply mutations and serialize (once per file)
    # D-08: Stop-and-rollback on first op failure (no more partial mutation).
    # D-03: Cumulative IR state -- re-parse after each mutation for gate checks.
    from volta.ops.execution import try_native_parse as _try_native_parse

    all_results: list[dict[str, Any]] = []

    def _dispatch_op(root, ir, file_path):
        """Dispatch a single op based on file type."""
        if file_path.suffix == ".kicad_pcb":
            return dispatch_pcb(root.op_type, root, ir, file_path)
        elif is_project_file(file_path):
            return dispatch_project(root.op_type, root, file_path)
        else:
            handler = _SCHEMATIC_HANDLERS.get(root.op_type)
            if handler is not None:
                return handler(root, ir, file_path)
            else:
                sq_handler = _SCHEMATIC_QUERY_HANDLERS.get(root.op_type)
                if sq_handler is not None:
                    return sq_handler(root, ir, file_path)
                else:
                    raise ValueError(f"Unknown op_type: {root.op_type!r}")

    def _reparse_ir(file_path):
        """Re-parse file after mutation using dual path (H-03 fix).

        Mirrors execute_pcb() logic: try native first, fall back to kiutils.
        """
        if file_path.suffix == ".kicad_pcb":
            native_board = _try_native_parse(file_path)
            if native_board is not None:
                return PcbIR.from_native(native_board)
            else:
                fresh_parse = parse_pcb(file_path)
                fresh_uuid = extract_uuids(fresh_parse.raw_content, "pcb")
                return PcbIR(_parse_result=fresh_parse, _uuid_map=fresh_uuid)
        elif file_path.suffix == ".kicad_sch":
            fresh_parse = parse_schematic(file_path)
            return SchematicIR(_parse_result=fresh_parse)
        return None

    def _run_phase3():
        """Execute Phase 3 mutations inside the current transaction context."""
        nonlocal all_results

        for file_path in file_order:
            ops_for_file = file_ops[file_path]
            ir = ir_map[file_path]
            parse_result = parse_result_map[file_path]

            with Transaction(file_path) as txn:
                for op in ops_for_file:
                    root = op.root
                    try:
                        # D-03: Pre-flight check against current (possibly
                        # mutated) IR before each op
                        gate = _get_pre_analysis_gate()
                        pre_result = gate.analyze(root, ir, file_path)
                        if pre_result.blocked:
                            raise BatchOpFailedError(
                                root.op_type,
                                root.target_file,
                                f"Pre-flight blocked: {'; '.join(f.message for f in pre_result.blockers)}",
                            )

                        details = _dispatch_op(root, ir, file_path)

                        all_results.append({
                            "success": True,
                            "operation": root.op_type,
                            "target_file": root.target_file,
                            "details": details,
                        })

                        # D-03 + H-03: Re-parse after mutation for
                        # cumulative state. Deregister old IR first
                        # to prevent spurious registry guard errors
                        # when Python reuses GC'd ParseResult ids.
                        _deregister_ir(ir)
                        fresh_ir = _reparse_ir(file_path)
                        if fresh_ir is not None:
                            ir = fresh_ir
                            ir_map[file_path] = fresh_ir

                    except Exception as e:
                        logger.error(
                            "Batch op failed: %s on %s: %s "
                            "-- stopping batch and rolling back (D-08)",
                            root.op_type, root.target_file, e,
                        )
                        # L-02 fix: chain original exception
                        raise BatchOpFailedError(
                            root.op_type, root.target_file, str(e)
                        ) from e

                # Serialize once per file
                if file_path.suffix == ".kicad_pcb":
                    uuid_map = uuid_map_store.get(file_path)
                    if not ir.raw_written:
                        serialize_pcb(
                            parse_result, file_path, uuid_map=uuid_map
                        )
                elif not is_project_file(file_path):
                    serialize_schematic(parse_result, file_path)
                    content = file_path.read_text(encoding="utf-8")
                    normalized = normalize_kicad_output(content)
                    file_path.write_text(normalized, encoding="utf-8")

                txn.commit()

                # Push undo entry for this file (M-05: synthetic batch op_type)
                if undo_stack is not None and file_path in pre_contents:
                    post_content = file_path.read_text(encoding="utf-8")
                    post_mtime = file_path.stat().st_mtime_ns
                    op_type_name = f"batch[{len(ops_for_file)}]"
                    undo_stack.push(
                        file_path,
                        pre_contents[file_path],
                        post_content,
                        op_type_name,
                        post_mtime,
                    )

            # Invalidate old cache entry and store fresh one after write
            if cache:
                cache.invalidate(file_path)
                if file_path.suffix == ".kicad_pcb":
                    cache.put(
                        file_path,
                        CacheEntry(
                            parse_result=parse_result,
                            uuid_map=uuid_map_store.get(file_path),
                        ),
                    )
                elif not is_project_file(file_path):
                    cache.put(
                        file_path, CacheEntry(parse_result=parse_result)
                    )

    # D-08: Run Phase 3; any failure triggers rollback via BatchOpFailedError
    # propagating to Transaction.__exit__. For multi-file batches, earlier
    # committed files need manual rollback from pre_contents snapshots.
    try:
        _run_phase3()
    except BatchOpFailedError:
        # Roll back any files that were already committed in this batch
        # before the failing op (multi-file batches).
        if len(file_order) > 1 and undo_stack is not None:
            for fp in file_order:
                if fp in pre_contents and fp.exists():
                    original = pre_contents[fp]
                    try:
                        fp.write_text(original, encoding="utf-8")
                    except OSError as e:
                        logger.error(
                            "Failed to rollback %s after batch failure: %s",
                            fp, e,
                        )
        return {
            "success": False,
            "results": all_results,
            "error": (
                "Batch stopped and rolled back: operation failure (D-08)"
            ),
        }

    return {
        "success": bool(all_results) and all(r["success"] for r in all_results),
        "results": all_results,
        "partial": any(not r["success"] for r in all_results) if all_results else False,
    }
