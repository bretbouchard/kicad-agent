"""Handler modules -- schematic, PCB, project, create, query, cross-file, and gate operations.

Each sub-module defines its own handler registry dict and register decorator.
The executor imports these registries to dispatch operations by op_type.
"""

from .schematic import _SCHEMATIC_HANDLERS, register_schematic
from .schematic_query import _SCHEMATIC_QUERY_HANDLERS, register_schematic_query
from .pcb import _PCB_HANDLERS, register_pcb
from .pcb_fill_zones import _FILL_ZONES_HANDLERS, register_fill_zones
from .pcb_cleanup import _CLEANUP_HANDLERS, register_cleanup
from .project import _PROJECT_HANDLERS, register_project
from .create import _CREATE_HANDLERS, register_create
from .query import _QUERY_HANDLERS, register_query
from .crossfile import _CROSSFILE_HANDLERS, register_crossfile
from .gate_handlers import _GATE_HANDLERS, register_gate_handler

# Merge fill_zones and cleanup handlers into PCB handlers at import time
_PCB_HANDLERS.update(_FILL_ZONES_HANDLERS)
_PCB_HANDLERS.update(_CLEANUP_HANDLERS)

__all__ = [
    "_SCHEMATIC_HANDLERS",
    "register_schematic",
    "_SCHEMATIC_QUERY_HANDLERS",
    "register_schematic_query",
    "_PCB_HANDLERS",
    "register_pcb",
    "_FILL_ZONES_HANDLERS",
    "register_fill_zones",
    "_CLEANUP_HANDLERS",
    "register_cleanup",
    "_PROJECT_HANDLERS",
    "register_project",
    "_CREATE_HANDLERS",
    "register_create",
    "_QUERY_HANDLERS",
    "register_query",
    "_CROSSFILE_HANDLERS",
    "register_crossfile",
    "_GATE_HANDLERS",
    "register_gate_handler",
]
