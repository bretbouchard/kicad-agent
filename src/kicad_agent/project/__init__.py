"""Project-level KiCad file parsers and editors.

Provides parsers for sym-lib-table, fp-lib-table, .kicad_dru, and .kicad_pro
files, with structured data models for programmatic editing.
"""

from kicad_agent.project.lib_table import (
    LibEntry,
    LibTable,
    parse_lib_table,
    serialize_lib_table,
)
from kicad_agent.project.design_rules import (
    DesignRule,
    DesignRulesFile,
    NetClassDef,
    parse_design_rules,
    serialize_design_rules,
)
from kicad_agent.project.project_file import (
    ProjectFile,
    get_project_settings,
    parse_project_file,
)

__all__ = [
    "LibEntry",
    "LibTable",
    "parse_lib_table",
    "serialize_lib_table",
    "DesignRule",
    "DesignRulesFile",
    "NetClassDef",
    "parse_design_rules",
    "serialize_design_rules",
    "ProjectFile",
    "get_project_settings",
    "parse_project_file",
]
