"""Base IR class with mutation tracking for all file-type IR wrappers.

D-05: Holds reference to ParseResult (which contains kiutils obj), not a copy.
D-06: Tracks mutations, UUID map reference, dirty flag.

IMPORTANT: One IR instance per ParseResult. The registry enforces this
at construction time -- creating a second IR for the same ParseResult
raises RuntimeError. Never share kiutils objects between IR instances
-- mutations would affect all references (Pitfall 2).

Usage:
    from kicad_agent.ir.schematic_ir import SchematicIR
    from kicad_agent.parser import parse_schematic

    result = parse_schematic(Path("my_schematic.kicad_sch"))
    ir = SchematicIR(_parse_result=result)
    assert not ir.dirty
    components = ir.components
"""

import logging
import threading
import weakref
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

from kicad_agent.parser.types import ParseResult
from kicad_agent.parser.uuid_extractor import UUIDMap

logger = logging.getLogger(__name__)

# Council HIGH: Registry to enforce one-IR-per-ParseResult invariant.
# Uses id() of ParseResult for lookup since dataclass IR instances are unhashable.
# Thread-safe for concurrent access.
#
# Each registered id is paired with a weakref finalizer for the IR. When the IR
# is garbage-collected (taking its ParseResult with it) the finalizer removes
# the id from the set. This prevents spurious "ParseResult already has an IR
# wrapper" errors when Python reuses a gc'd ParseResult's id() for a new object.
_ir_registry: set[int] = set()
_ir_finalizers: "dict[int, weakref.finalize]" = {}
_ir_registry_lock = threading.Lock()


def _finalize_ir(pr_id: int) -> None:
    """Finalizer callback to remove a gc'd IR's id from the registry."""
    with _ir_registry_lock:
        _ir_registry.discard(pr_id)
        _ir_finalizers.pop(pr_id, None)


def _clear_registry() -> None:
    """Clear the IR registry. For testing only."""
    with _ir_registry_lock:
        _ir_registry.clear()
        _ir_finalizers.clear()


def _deregister_ir(ir: "BaseIR") -> None:
    """Remove a ParseResult's id from the IR registry.

    Must be called before replacing an IR with a fresh re-parse,
    otherwise Python may reuse the GC'd ParseResult's id and the
    one-IR-per-ParseResult guard raises a spurious error.
    """
    with _ir_registry_lock:
        pr_id = id(ir._parse_result)
        _ir_registry.discard(pr_id)
        fin = _ir_finalizers.pop(pr_id, None)
        if fin is not None:
            fin.detach()


@dataclass
class BaseIR:
    """Base class for all IR types. Tracks mutation state.

    D-05: Holds reference to kiutils object (not a copy).
    D-06: Tracks mutations, UUID map reference, dirty flag.

    IMPORTANT: One IR instance per ParseResult. The registry enforces this
    at construction time -- creating a second IR for the same ParseResult
    raises RuntimeError. Never share kiutils objects between IR instances
    -- mutations would affect all references (Pitfall 2).

    IMPORTANT: The kiutils_obj property provides READ-ONLY access to the
    underlying kiutils object. All mutations must go through IR methods
    that call _record_mutation(). Direct mutation of kiutils_obj fields
    bypasses audit tracking (Council LOW).
    """

    _parse_result: ParseResult
    _uuid_map: Optional[UUIDMap] = None
    _dirty: bool = False
    _mutation_log: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=1000))

    def __post_init__(self) -> None:
        """Enforce one-IR-per-ParseResult invariant (Council HIGH)."""
        pr_id = id(self._parse_result)
        with _ir_registry_lock:
            if pr_id in _ir_registry:
                raise RuntimeError(
                    "ParseResult already has an IR wrapper. "
                    "Create only one IR per ParseResult to prevent shared-reference bugs."
                )
            _ir_registry.add(pr_id)
            # Register a finalizer that removes the id when this IR is gc'd.
            # This prevents stale entries when Python reuses a gc'd id().
            _ir_finalizers[pr_id] = weakref.finalize(self, _finalize_ir, pr_id)

    @property
    def file_path(self) -> Any:
        """Source file path from the ParseResult."""
        return self._parse_result.file_path

    @property
    def file_type(self) -> str:
        """File type string from the ParseResult."""
        return self._parse_result.file_type

    @property
    def dirty(self) -> bool:
        """Whether any mutations have been recorded."""
        return self._dirty

    @property
    def kiutils_obj(self) -> Any:
        """READ-ONLY access to the underlying kiutils object.

        Mutations to this object bypass audit tracking. Use IR methods
        that call _record_mutation() for all modifications (Council LOW).
        """
        return self._parse_result.kiutils_obj

    @property
    def raw_content(self) -> str:
        """Raw file content from the ParseResult."""
        return self._parse_result.raw_content

    @property
    def uuid_map(self) -> Optional[UUIDMap]:
        """UUID map for PCB/footprint serialization."""
        return self._uuid_map

    def _record_mutation(self, description: str, details: dict[str, Any]) -> None:
        """Record a mutation for audit/diagnostic purposes.

        Note: D-08 uses file-level snapshots for actual rollback, not per-field undo.
        This log is for audit trail only.

        Council M-1: Uses deque(maxlen=1000) for O(1) append with automatic
        eviction of oldest entries when the cap is reached.
        """
        if len(self._mutation_log) == self._mutation_log.maxlen:
            logger.warning(
                "Mutation log cap reached (%d). Oldest entries auto-evicted.",
                self._mutation_log.maxlen,
            )
        self._mutation_log.append({"type": description, **details})
        self._dirty = True

    def mark_dirty(self, description: str = "external_mark") -> None:
        """Mark the IR as dirty without recording a specific mutation.

        Use this when an external process (e.g. kiutils direct manipulation)
        modifies the underlying data outside the normal mutation tracking path.

        Args:
            description: Optional description of why the IR was marked dirty.
        """
        self._record_mutation(description, {"source": "mark_dirty"})

    @property
    def mutation_log(self) -> list[dict[str, Any]]:
        """Read-only access to mutation history.

        Returns a copy to prevent external mutation of the internal log.
        """
        return list(self._mutation_log)
