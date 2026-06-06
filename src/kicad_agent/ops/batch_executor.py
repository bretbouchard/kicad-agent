"""Batch execution -- single parse/write per file for multiple operations.

Extracted from executor.py to keep the OperationExecutor class under 800 lines.
The execute_batch function groups operations by target file, parses each once,
applies all mutations, and serializes once per file.

Security (threat model):
- T-24-01: Path confinement validated for all batch operation targets

Usage:
    from kicad_agent.ops.executor import OperationExecutor

    executor = OperationExecutor(base_dir=Path("/project"))
    result = executor.execute_batch([op1, op2, op3])
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from kicad_agent.ir.base import _clear_registry
from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ir.transaction import Transaction
from kicad_agent.ops.ir_cache import CacheEntry
from kicad_agent.ops.schema import Operation
from kicad_agent.parser import parse_pcb, parse_schematic
from kicad_agent.parser.uuid_extractor import extract_uuids
from kicad_agent.serializer import normalize_kicad_output, serialize_pcb, serialize_schematic

if TYPE_CHECKING:
    from kicad_agent.ops.executor import OperationExecutor

logger = logging.getLogger(__name__)


def _get_pre_analysis_gate():
    """Lazy-load the pre-analysis gate to avoid import overhead."""
    from kicad_agent.ops.pre_analysis import PreAnalysisGate

    return PreAnalysisGate()


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
    from kicad_agent.ops.handlers import (
        _PCB_HANDLERS,
        _PROJECT_HANDLERS,
        _SCHEMATIC_HANDLERS,
        _SCHEMATIC_QUERY_HANDLERS,
    )

    # Op-type classification sets (mirrored from executor.py to avoid circular import)
    _CROSS_FILE_OP_TYPES = {"propagate_symbol_change", "update_pcb_from_schematic"}
    _CREATE_OP_TYPES = {"create_schematic", "create_pcb", "create_project", "create_symbol", "create_footprint"}

    base_dir = executor._base_dir
    cache = executor._cache
    undo_stack = executor._undo_stack

    # Early return for empty batch
    if not ops:
        return {"success": True, "results": []}

    # Validate operation dependency ordering before execution
    from kicad_agent.ops.registry import validate_dependencies
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
    from kicad_agent.ops.registry import OPERATION_REGISTRY
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
    from kicad_agent.ops.registry import OPERATION_REGISTRY as _REG
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
            elif executor._is_project_file(file_path):
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

        # Pre-analysis gate: check all ops against this file's IR
        if file_path.suffix == ".kicad_sch":
            gate = _get_pre_analysis_gate()
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
    all_results: list[dict[str, Any]] = []

    for file_path in file_order:
        ops_for_file = file_ops[file_path]
        ir = ir_map[file_path]
        parse_result = parse_result_map[file_path]

        with Transaction(file_path) as txn:
            for op in ops_for_file:
                root = op.root
                if file_path.suffix == ".kicad_pcb":
                    details = executor._dispatch_pcb(root.op_type, root, ir, file_path)
                elif executor._is_project_file(file_path):
                    details = executor._dispatch_project(
                        root.op_type, root, file_path
                    )
                else:
                    handler = _SCHEMATIC_HANDLERS.get(root.op_type)
                    if handler is not None:
                        details = handler(root, ir, file_path)
                    else:
                        sq_handler = _SCHEMATIC_QUERY_HANDLERS.get(root.op_type)
                        if sq_handler is not None:
                            details = sq_handler(root, ir, file_path)
                        else:
                            raise ValueError(f"Unknown op_type: {root.op_type!r}")

                all_results.append({
                    "success": True,
                    "operation": root.op_type,
                    "target_file": root.target_file,
                    "details": details,
                })

            # Serialize once per file
            if file_path.suffix == ".kicad_pcb":
                uuid_map = uuid_map_store.get(file_path)
                if ir.needs_serialization():
                    serialize_pcb(parse_result, file_path, uuid_map=uuid_map)
            elif not executor._is_project_file(file_path):
                serialize_schematic(parse_result, file_path)
                content = file_path.read_text(encoding="utf-8")
                normalized = normalize_kicad_output(content)
                file_path.write_text(normalized, encoding="utf-8")

            txn.commit()

            # Push undo entry for this file (M-05: synthetic batch op_type)
            if undo_stack is not None and file_path in pre_contents:
                post_content = file_path.read_text(encoding="utf-8")
                post_mtime = file_path.stat().st_mtime_ns
                op_type = f"batch[{len(ops_for_file)}]"
                undo_stack.push(file_path, pre_contents[file_path], post_content, op_type, post_mtime)

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
            elif not executor._is_project_file(file_path):
                cache.put(
                    file_path, CacheEntry(parse_result=parse_result)
                )

    return {"success": True, "results": all_results}
