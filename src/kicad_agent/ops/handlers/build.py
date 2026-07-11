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

    Implemented in Task 3. Stub returns an error so the op is reachable but
    clearly unimplemented until the handler lands.
    """
    raise NotImplementedError("build_create handler not yet implemented")


@register_build("build_list")
def _handle_build_list(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    """List all builds for a project (BUILD-07).

    Implemented in Task 4.
    """
    raise NotImplementedError("build_list handler not yet implemented")


@register_build("build_show")
def _handle_build_show(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    """Show build details by build_id (BUILD-08).

    Implemented in Task 4.
    """
    raise NotImplementedError("build_show handler not yet implemented")
