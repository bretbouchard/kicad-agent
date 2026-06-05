"""Operation executor -- dispatches validated Operation intents to handlers.

Establishes the pattern (executor dispatch, handler function, Transaction
wrapping, IR mutation, serialization) that all subsequent operations follow.

Handler functions are organized in the handlers/ sub-package by category:
  - handlers/schematic.py       -- schematic mutation operations
  - handlers/schematic_query.py -- read-only schematic queries
  - handlers/pcb.py             -- PCB mutation operations
  - handlers/project.py         -- project file operations
  - handlers/create.py          -- file creation operations
  - handlers/query.py           -- PCB query operations
  - handlers/crossfile.py       -- cross-file operations

Security (threat model):
- T-04-06: Dispatch uses exact op_type matching; unknown raises ValueError
- T-04-01: UUID generated server-side in handlers

Usage:
    from kicad_agent.ops.executor import OperationExecutor
    from kicad_agent.ops.schema import Operation

    executor = OperationExecutor(base_dir=Path("/project"))
    result = executor.execute(op)
"""

import logging
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

logger = logging.getLogger(__name__)

# Set of op_types that use cross-file dispatch path
_CROSS_FILE_OP_TYPES = {"propagate_symbol_change", "update_pcb_from_schematic"}

# Pre-analysis gate: shared instance (stateless, safe to reuse)
_PRE_ANALYSIS_GATE = None


def _get_pre_analysis_gate():
    """Lazy-load the pre-analysis gate to avoid import overhead."""
    global _PRE_ANALYSIS_GATE
    if _PRE_ANALYSIS_GATE is None:
        from kicad_agent.ops.pre_analysis import PreAnalysisGate
        _PRE_ANALYSIS_GATE = PreAnalysisGate()
    return _PRE_ANALYSIS_GATE

# Set of op_types that create new files (bypass file-existence check)
_CREATE_OP_TYPES = {"create_schematic", "create_pcb", "create_project", "create_symbol", "create_footprint"}

# Set of op_types that manage their own file I/O (skip executor serialization).
# These handlers write modified files directly and the executor must not
# overwrite them with the original parse_result.
_SELF_SERIALIZING_OPS = frozenset({"erc_auto_fix_hierarchical"})


# ---------------------------------------------------------------------------
# Executor class
# ---------------------------------------------------------------------------


class OperationExecutor:
    """Dispatches validated Operation intents to mutation handlers.

    Each handler call is wrapped in a Transaction for rollback on failure.
    The executor parses the file, creates SchematicIR, calls the handler,
    serializes, normalizes, and commits.

    Args:
        base_dir: Base directory for resolving relative target_file paths.
    """

    def __init__(self, base_dir: Path, *, cache: Optional[IRCache] = None, undo_stack: Optional[UndoStack] = None) -> None:
        self._base_dir = base_dir
        self._cache = cache
        self._undo_stack = undo_stack

    def execute(self, op: Operation) -> dict[str, Any]:
        """Execute a validated operation with Transaction wrapping.

        Routes to schematic or PCB execution path based on file extension.

        Args:
            op: Validated Operation from the schema.

        Returns:
            Dict with: success, operation, target_file, details.

        Raises:
            ValueError: For unknown op_type (T-04-06).
            FileNotFoundError: If target_file does not exist.
        """
        root = op.root
        file_path = self._base_dir / root.target_file

        # Security (T-24-01): path confinement -- reject paths that escape project dir
        resolved = file_path.resolve()
        base_resolved = self._base_dir.resolve()
        if not resolved.is_relative_to(base_resolved):
            raise ValueError(
                f"Security: path escapes project directory: {root.target_file}"
            )

        # Cross-file operations: coordinate multiple files atomically
        if root.op_type in _CROSS_FILE_OP_TYPES:
            return self._execute_cross_file(op, file_path)

        # Create operations: file does not exist yet (bypass existence check)
        if root.op_type in _CREATE_OP_TYPES:
            return self._execute_create(op, file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Target file not found: {file_path}")

        # Query operations: read-only, no Transaction, no serialization
        if root.op_type in _QUERY_HANDLERS:
            return self._execute_query(op, file_path)

        # Schematic query operations: read-only, parse-only path for .kicad_sch
        if root.op_type in _SCHEMATIC_QUERY_HANDLERS:
            return self._execute_schematic_query(op, file_path)

        # Clear IR registry to avoid stale registrations across operations
        _clear_registry()

        # Branch on file type
        if file_path.suffix == ".kicad_pcb":
            return self._execute_pcb(op, file_path)
        elif self._is_project_file(file_path):
            return self._execute_project(op, file_path)
        else:
            return self._execute_schematic(op, file_path)

    @staticmethod
    def _is_project_file(file_path: Path) -> bool:
        """Check if the file is a project-level file (not schematic/PCB)."""
        name = file_path.name
        suffix = file_path.suffix
        return (
            name in ("sym-lib-table", "fp-lib-table")
            or suffix in (".kicad_dru", ".kicad_pro")
        )

    def _execute_query(self, op: Operation, file_path: Path) -> dict[str, Any]:
        """Execute a read-only query operation (no Transaction, no serialization).

        Query operations parse the file and build IR, but skip Transaction
        wrapping, serialization, and file writes. The file mtime is unchanged.

        Args:
            op: Validated Operation from the schema.
            file_path: Resolved path to the target file.

        Returns:
            Dict with: success, operation, target_file, details.
        """
        root = op.root

        cached_entry = self._cache.get(file_path) if self._cache else None
        if cached_entry is not None:
            parse_result = cached_entry.parse_result
            uuid_map = cached_entry.uuid_map
        else:
            parse_result = parse_pcb(file_path)
            uuid_map = extract_uuids(parse_result.raw_content, "pcb")
            if self._cache:
                self._cache.put(file_path, CacheEntry(parse_result=parse_result, uuid_map=uuid_map))

        ir = PcbIR(_parse_result=parse_result, _uuid_map=uuid_map)
        details = self._dispatch_query(root.op_type, root, ir, file_path)
        return {
            "success": True,
            "operation": root.op_type,
            "target_file": root.target_file,
            "details": details,
        }

    def _dispatch_query(
        self,
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

    def _execute_schematic_query(self, op: Operation, file_path: Path) -> dict[str, Any]:
        """Execute a read-only schematic query (no Transaction, no serialization).

        Schematic query operations parse the file and build SchematicIR, but skip
        Transaction wrapping, serialization, and file writes. The file mtime is
        unchanged.

        Args:
            op: Validated Operation from the schema.
            file_path: Resolved path to the target schematic file.

        Returns:
            Dict with: success, operation, target_file, details.
        """
        root = op.root

        # Clear IR registry to avoid stale registrations across operations
        _clear_registry()

        cached_entry = self._cache.get(file_path) if self._cache else None
        if cached_entry is not None:
            parse_result = cached_entry.parse_result
        else:
            parse_result = parse_schematic(file_path)
            if self._cache:
                self._cache.put(file_path, CacheEntry(parse_result=parse_result))

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

    def _execute_create(self, op: Operation, file_path: Path) -> dict[str, Any]:
        """Execute a file-creation operation (no Transaction, no IR).

        Create operations generate new files from scratch. They do not need
        Transaction wrapping since there is nothing to roll back to.

        Args:
            op: Validated Operation from the schema.
            file_path: Resolved path for the new file.

        Returns:
            Dict with: success, operation, target_file, details.
        """
        # Security (T-24-01): path confinement for create operations too
        resolved = file_path.resolve()
        base_resolved = self._base_dir.resolve()
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

    def _execute_schematic(self, op: Operation, file_path: Path) -> dict[str, Any]:
        """Execute an operation targeting a schematic file."""
        root = op.root

        # Capture pre-mutation content for undo stack
        pre_content: Optional[str] = None
        if self._undo_stack is not None:
            pre_content = file_path.read_text(encoding="utf-8")

        cached_entry = self._cache.get(file_path) if self._cache else None
        if cached_entry is not None:
            parse_result = cached_entry.parse_result
        else:
            parse_result = parse_schematic(file_path)
            if self._cache:
                self._cache.put(file_path, CacheEntry(parse_result=parse_result))

        ir = SchematicIR(_parse_result=parse_result)

        # Pre-analysis gate: check before mutating
        gate = _get_pre_analysis_gate()
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
            details = self._dispatch(root.op_type, root, ir, file_path)

            # Skip serialization for operations that manage their own file I/O
            # (e.g. erc_auto_fix_hierarchical writes sub-sheets directly).
            if root.op_type not in _SELF_SERIALIZING_OPS:
                serialize_schematic(parse_result, file_path)
                content = file_path.read_text(encoding="utf-8")
                normalized = normalize_kicad_output(content)
                file_path.write_text(normalized, encoding="utf-8")

            txn.commit()

            # Capture post-mutation content for undo stack
            if self._undo_stack is not None and pre_content is not None:
                post_content = file_path.read_text(encoding="utf-8")
                post_mtime = file_path.stat().st_mtime_ns
                self._undo_stack.push(file_path, pre_content, post_content, root.op_type, post_mtime)

        # Invalidate old cache entry and store fresh one after write
        if self._cache:
            self._cache.invalidate(file_path)
            self._cache.put(file_path, CacheEntry(parse_result=parse_result))

        # Clear registry so ParseResult id is released for subsequent operations
        _clear_registry()

        return {
            "success": True,
            "operation": root.op_type,
            "target_file": root.target_file,
            "details": details,
            "pre_analysis": pre_result.to_dict(),
        }

    @staticmethod
    def _raw_write_atomic(file_path: Path, content: str) -> None:
        """Write content to file atomically via temp + rename (Council C-01).

        Args:
            file_path: Target file path.
            content: Content to write.
        """
        import os
        tmp = file_path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(str(tmp), str(file_path))

    def _execute_pcb(self, op: Operation, file_path: Path) -> dict[str, Any]:
        """Execute an operation targeting a PCB file."""
        root = op.root

        # Capture pre-mutation content for undo stack
        pre_content: Optional[str] = None
        if self._undo_stack is not None:
            pre_content = file_path.read_text(encoding="utf-8")

        cached_entry = self._cache.get(file_path) if self._cache else None
        if cached_entry is not None:
            parse_result = cached_entry.parse_result
            uuid_map = cached_entry.uuid_map
            if cached_entry.native_board is not None:
                ir = PcbIR.from_native(cached_entry.native_board)
            else:
                ir = PcbIR(_parse_result=parse_result, _uuid_map=uuid_map)
        else:
            # Always parse with kiutils for serialization support
            parse_result = parse_pcb(file_path)
            uuid_map = extract_uuids(parse_result.raw_content, "pcb")

            # Try native parser for read path (Plan 01)
            native_board = self._try_native_parse(file_path)
            if native_board is not None:
                ir = PcbIR.from_native(native_board)
            else:
                ir = PcbIR(_parse_result=parse_result, _uuid_map=uuid_map)

            if self._cache:
                self._cache.put(file_path, CacheEntry(parse_result=parse_result, uuid_map=uuid_map, native_board=native_board))

        with Transaction(file_path) as txn:
            details = self._dispatch_pcb(root.op_type, root, ir, file_path)

            # Skip kiutils serialization if the IR method already wrote directly
            # via raw S-expression manipulation (avoids data loss from kiutils)
            if not ir.raw_written:
                serialize_pcb(parse_result, file_path, uuid_map=uuid_map)

            txn.commit()

            # Capture post-mutation content for undo stack
            if self._undo_stack is not None and pre_content is not None:
                post_content = file_path.read_text(encoding="utf-8")
                post_mtime = file_path.stat().st_mtime_ns
                self._undo_stack.push(file_path, pre_content, post_content, root.op_type, post_mtime)

        # Invalidate old cache entry and store fresh one after write
        if self._cache:
            self._cache.invalidate(file_path)
            self._cache.put(file_path, CacheEntry(parse_result=parse_result, uuid_map=uuid_map))

        return {
            "success": True,
            "operation": root.op_type,
            "target_file": root.target_file,
            "details": details,
        }

    @staticmethod
    def _try_native_parse(file_path: Path) -> "NativeBoard | None":
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

    def _dispatch(
        self,
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

    def _dispatch_pcb(
        self,
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

    def _execute_project(self, op: Operation, file_path: Path) -> dict[str, Any]:
        """Execute an operation targeting a project-level file.

        Handles sym-lib-table, fp-lib-table, .kicad_dru, and .kicad_pro files
        using the project module parsers and editors.

        Args:
            op: Validated Operation from the schema.
            file_path: Resolved path to the target file.

        Returns:
            Dict with: success, operation, target_file, details.
        """
        root = op.root
        pre_content: Optional[str] = None
        if self._undo_stack is not None and file_path.exists():
            pre_content = file_path.read_text(encoding="utf-8")
        details = self._dispatch_project(root.op_type, root, file_path)
        if self._undo_stack is not None and pre_content is not None:
            post_content = file_path.read_text(encoding="utf-8")
            post_mtime = file_path.stat().st_mtime_ns
            self._undo_stack.push(file_path, pre_content, post_content, root.op_type, post_mtime)
        return {
            "success": True,
            "operation": root.op_type,
            "target_file": root.target_file,
            "details": details,
        }

    def _dispatch_project(
        self,
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

    def _execute_cross_file(self, op: Operation, file_path: Path) -> dict[str, Any]:
        """Execute a cross-file operation targeting multiple files atomically."""
        root = op.root

        # Resolve all target file paths relative to base_dir
        file_paths = self._resolve_cross_file_paths(root)
        if not file_paths:
            raise ValueError(f"Cross-file operation {root.op_type!r} requires at least one target file")

        # Security (T-24-01): path confinement for ALL files in cross-file operation
        base_resolved = self._base_dir.resolve()
        for fp in file_paths:
            if not fp.resolve().is_relative_to(base_resolved):
                raise ValueError(
                    f"Security: path escapes project directory in cross-file op: {fp}"
                )
            if not fp.exists():
                raise FileNotFoundError(f"Cross-file target not found: {fp}")

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
        if self._undo_stack is not None:
            for fp in file_paths:
                if fp.exists():
                    pre_contents[fp] = fp.read_text(encoding="utf-8")

        # Phase 3: Open AtomicOperation and execute handler
        with AtomicOperation(file_paths) as atomic:
            handler = _CROSSFILE_HANDLERS.get(root.op_type)
            if handler is None:
                raise ValueError(f"Unknown cross-file op_type: {root.op_type!r}")

            details = handler(root, ir_map, self._base_dir)

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
        if self._undo_stack is not None:
            for fp, ir in ir_map.items():
                if ir.dirty and fp in pre_contents:
                    post_content = fp.read_text(encoding="utf-8")
                    post_mtime = fp.stat().st_mtime_ns
                    self._undo_stack.push(fp, pre_contents[fp], post_content, root.op_type, post_mtime)

        return {
            "success": True,
            "operation": root.op_type,
            "details": details,
        }

    def _resolve_cross_file_paths(self, op: Any) -> list[Path]:
        """Resolve file paths from a cross-file operation schema."""
        if hasattr(op, "target_files"):
            return [self._base_dir / tf for tf in op.target_files]
        return []

    # ------------------------------------------------------------------
    # Batch execution: single parse/write per file
    # ------------------------------------------------------------------

    def execute_batch(self, ops: list[Operation]) -> dict[str, Any]:
        """Execute multiple operations with single parse/write per file.

        Groups ops by target file, parses each once, applies all mutations,
        serializes once per file. Validates ALL operations before executing ANY.

        Not supported: cross-file ops and create ops -- use execute() for those.

        Args:
            ops: List of validated Operation instances to execute.

        Returns:
            Dict with: success, results (list of per-op result dicts).
            On validation failure: success=False, validation_errors list.
        """
        # Early return for empty batch
        if not ops:
            return {"success": True, "results": []}

        # Reject unsupported op types
        unsupported: list[str] = []
        for op in ops:
            root = op.root
            if root.op_type in _CROSS_FILE_OP_TYPES:
                unsupported.append(root.op_type)
            elif root.op_type in _CREATE_OP_TYPES:
                unsupported.append(root.op_type)
        if unsupported:
            return {
                "success": False,
                "results": [],
                "error": f"Batch rejected: unsupported op types: {sorted(set(unsupported))}",
            }

        # Security (T-24-01): path confinement -- validate all paths first
        base_resolved = self._base_dir.resolve()
        for op in ops:
            file_path = self._base_dir / op.root.target_file
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
            fp = (self._base_dir / op.root.target_file).resolve()
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
                cached_entry = self._cache.get(file_path) if self._cache else None
                if cached_entry is not None:
                    parse_result = cached_entry.parse_result
                    uuid_map = cached_entry.uuid_map
                else:
                    parse_result = parse_pcb(file_path)
                    uuid_map = extract_uuids(parse_result.raw_content, "pcb")
                    if self._cache:
                        self._cache.put(
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
                cached_entry = self._cache.get(file_path) if self._cache else None
                if cached_entry is not None:
                    parse_result = cached_entry.parse_result
                else:
                    parse_result = parse_schematic(file_path)
                    if self._cache:
                        self._cache.put(
                            file_path, CacheEntry(parse_result=parse_result)
                        )
                parse_result_map[file_path] = parse_result
                ir_map[file_path] = SchematicIR(_parse_result=parse_result)

            # Validate handlers exist for all ops targeting this file
            for op in ops_for_file:
                root = op.root
                if file_path.suffix == ".kicad_pcb":
                    handler = _PCB_HANDLERS.get(root.op_type)
                elif self._is_project_file(file_path):
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
        if self._undo_stack is not None:
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
                        details = self._dispatch_pcb(root.op_type, root, ir, file_path)
                    elif self._is_project_file(file_path):
                        details = self._dispatch_project(
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
                    if not ir.raw_written:
                        serialize_pcb(parse_result, file_path, uuid_map=uuid_map)
                elif not self._is_project_file(file_path):
                    serialize_schematic(parse_result, file_path)
                    content = file_path.read_text(encoding="utf-8")
                    normalized = normalize_kicad_output(content)
                    file_path.write_text(normalized, encoding="utf-8")

                txn.commit()

                # Push undo entry for this file (M-05: synthetic batch op_type)
                if self._undo_stack is not None and file_path in pre_contents:
                    post_content = file_path.read_text(encoding="utf-8")
                    post_mtime = file_path.stat().st_mtime_ns
                    op_type = f"batch[{len(ops_for_file)}]"
                    self._undo_stack.push(file_path, pre_contents[file_path], post_content, op_type, post_mtime)

            # Invalidate old cache entry and store fresh one after write
            if self._cache:
                self._cache.invalidate(file_path)
                if file_path.suffix == ".kicad_pcb":
                    self._cache.put(
                        file_path,
                        CacheEntry(
                            parse_result=parse_result,
                            uuid_map=uuid_map_store.get(file_path),
                        ),
                    )
                elif not self._is_project_file(file_path):
                    self._cache.put(
                        file_path, CacheEntry(parse_result=parse_result)
                    )

        return {"success": True, "results": all_results}

    # ------------------------------------------------------------------
    # Undo/redo methods
    # ------------------------------------------------------------------

    def undo(self, target_file: Optional[str] = None) -> dict[str, Any]:
        """Undo the most recent mutation for a file.

        Args:
            target_file: Relative path to the file. If None, undoes the latest
                mutation across all files.

        Returns:
            Dict with success, undone_op, target_file on success.
            Dict with success=False, error on failure.
        """
        if self._undo_stack is None:
            return {"success": False, "error": "Undo stack not enabled"}

        if target_file is not None:
            file_path = (self._base_dir / target_file).resolve()
            entry = self._undo_stack.pop_undo(file_path)
        else:
            entry = self._undo_stack.pop_latest_undo()

        if entry is None:
            return {"success": False, "error": "No operations to undo"}

        # H-04: Symlink protection (mirrors Transaction H-02 control)
        if entry.file_path.is_symlink():
            return {"success": False, "error": "Security: target file is a symlink"}

        # M-08: Check parent directory exists before writing
        if not entry.file_path.parent.exists():
            return {"success": False, "error": "Cannot undo: parent directory no longer exists"}

        # L-05: Warn if file was modified externally since snapshot
        if entry.post_mtime and entry.file_path.exists():
            current_mtime = entry.file_path.stat().st_mtime_ns
            if current_mtime != entry.post_mtime:
                logger.warning(
                    "Undo: file modified externally since snapshot: %s",
                    entry.file_path,
                )

        # L-04: Use newline="" to preserve exact byte content (LF line endings)
        try:
            entry.file_path.write_text(entry.pre_content, encoding="utf-8", newline="")
        except OSError as e:
            # Reverse: pop_redo moves entry back to undo so user can retry
            self._undo_stack.pop_redo(entry.file_path)
            return {"success": False, "error": f"Write error during undo: {e}"}

        # Invalidate cache for this file
        if self._cache:
            self._cache.invalidate(entry.file_path)

        return {
            "success": True,
            "undone_op": entry.op_type,
            "target_file": str(entry.file_path.relative_to(self._base_dir)),
        }

    def redo(self, target_file: Optional[str] = None) -> dict[str, Any]:
        """Redo the most recently undone mutation for a file.

        Args:
            target_file: Relative path to the file. If None, redoes the latest
                undone mutation across all files.

        Returns:
            Dict with success, redone_op, target_file on success.
            Dict with success=False, error on failure.
        """
        if self._undo_stack is None:
            return {"success": False, "error": "Undo stack not enabled"}

        if target_file is not None:
            file_path = (self._base_dir / target_file).resolve()
            entry = self._undo_stack.pop_redo(file_path)
        else:
            entry = self._undo_stack.pop_latest_redo()

        if entry is None:
            return {"success": False, "error": "No operations to redo"}

        # H-04: Symlink protection
        if entry.file_path.is_symlink():
            return {"success": False, "error": "Security: target file is a symlink"}

        # M-08: Check parent directory exists before writing
        if not entry.file_path.parent.exists():
            return {"success": False, "error": "Cannot redo: parent directory no longer exists"}

        # L-05: Warn if file was modified externally since snapshot
        if entry.post_mtime and entry.file_path.exists():
            current_mtime = entry.file_path.stat().st_mtime_ns
            if current_mtime != entry.post_mtime:
                logger.warning(
                    "Redo: file modified externally since snapshot: %s",
                    entry.file_path,
                )

        # L-04: Use newline="" to preserve exact byte content
        try:
            entry.file_path.write_text(entry.post_content, encoding="utf-8", newline="")
        except OSError as e:
            # Reverse: pop_undo moves entry back to redo so user can retry
            self._undo_stack.pop_undo(entry.file_path)
            return {"success": False, "error": f"Write error during redo: {e}"}

        # Invalidate cache for this file
        if self._cache:
            self._cache.invalidate(entry.file_path)

        return {
            "success": True,
            "redone_op": entry.op_type,
            "target_file": str(entry.file_path.relative_to(self._base_dir)),
        }
