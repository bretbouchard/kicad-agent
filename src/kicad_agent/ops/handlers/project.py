"""Project handler implementations -- library tables, design rules, project settings.

Handlers receive (op, file_path) and return a result dict.
"""

import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_PROJECT_HANDLERS: dict[str, Callable] = {}


def register_project(op_type: str) -> Callable:
    """Decorator to register a project-file operation handler."""
    def decorator(fn: Callable) -> Callable:
        _PROJECT_HANDLERS[op_type] = fn
        return fn
    return decorator


@register_project("add_lib_entry")
def _handle_add_lib_entry(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.project.lib_table import (
        LibEntry,
        parse_lib_table,
        serialize_lib_table,
    )
    table = parse_lib_table(file_path)
    entry = LibEntry(
        name=op.lib_name,
        type=op.lib_type,
        uri=op.uri,
        options=op.options,
        descr=op.description,
    )
    table.add(entry)
    serialize_lib_table(table, file_path)
    return {"lib_name": op.lib_name, "action": "added"}


@register_project("remove_lib_entry")
def _handle_remove_lib_entry(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.project.lib_table import (
        parse_lib_table,
        serialize_lib_table,
    )
    table = parse_lib_table(file_path)
    removed = table.remove(op.lib_name)
    serialize_lib_table(table, file_path)
    return {"lib_name": removed.name, "action": "removed"}


@register_project("add_net_class")
def _handle_add_net_class(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.project.design_rules import (
        NetClassDef,
        parse_design_rules,
        serialize_design_rules,
    )
    dru = parse_design_rules(file_path)
    nc = NetClassDef(
        name=op.name,
        clearance=op.clearance,
        track_width=op.track_width,
        via_diameter=op.via_diameter,
        via_drill=op.via_drill,
    )
    dru.add_net_class(nc)
    serialize_design_rules(dru, file_path)
    return {"net_class": op.name, "action": "added"}


@register_project("add_design_rule")
def _handle_add_design_rule(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.project.design_rules import (
        DesignRule,
        parse_design_rules,
        serialize_design_rules,
    )
    dru = parse_design_rules(file_path)
    rule = DesignRule(
        name=op.name,
        constraint_type=op.constraint_type,
        constraint_values=op.constraint_values,
        condition=op.condition,
    )
    dru.add_rule(rule)
    serialize_design_rules(dru, file_path)
    return {"rule_name": op.name, "action": "added"}


@register_project("list_lib_entries")
def _handle_list_lib_entries(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.project.lib_table import parse_lib_table
    table = parse_lib_table(file_path)
    entries = [
        {
            "name": e.name,
            "type": e.type,
            "uri": e.uri,
            "options": e.options,
            "description": e.descr,
        }
        for e in table.entries
    ]
    return {"entries": entries, "count": len(entries)}


@register_project("modify_net_class")
def _handle_modify_net_class(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.project.design_rules import (
        parse_design_rules,
        serialize_design_rules,
    )
    dru = parse_design_rules(file_path)
    updates = {
        k: v for k, v in {
            "clearance": op.clearance,
            "track_width": op.track_width,
            "via_diameter": op.via_diameter,
            "via_drill": op.via_drill,
            "uvia_diameter": op.uvia_diameter,
            "uvia_drill": op.uvia_drill,
            "diff_pair_width": op.diff_pair_width,
            "diff_pair_gap": op.diff_pair_gap,
        }.items() if v is not None
    }
    dru.modify_net_class(op.name, **updates)
    serialize_design_rules(dru, file_path)
    return {
        "net_class": op.name,
        "action": "modified",
        "updated_fields": list(updates.keys()),
    }


@register_project("remove_net_class")
def _handle_remove_net_class(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.project.design_rules import (
        parse_design_rules,
        serialize_design_rules,
    )
    dru = parse_design_rules(file_path)
    removed = dru.remove_net_class(op.name)
    serialize_design_rules(dru, file_path)
    return {"net_class": removed.name, "action": "removed"}


@register_project("list_net_classes")
def _handle_list_net_classes(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.project.design_rules import parse_design_rules
    dru = parse_design_rules(file_path)
    classes = [
        {
            "name": nc.name,
            "description": nc.description,
            "clearance": nc.clearance,
            "track_width": nc.track_width,
            "via_diameter": nc.via_diameter,
            "via_drill": nc.via_drill,
            "uvia_diameter": nc.uvia_diameter,
            "uvia_drill": nc.uvia_drill,
            "diff_pair_width": nc.diff_pair_width,
            "diff_pair_gap": nc.diff_pair_gap,
        }
        for nc in dru.net_classes
    ]
    return {"net_classes": classes, "count": len(classes)}


@register_project("modify_design_rule")
def _handle_modify_design_rule(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.project.design_rules import (
        parse_design_rules,
        serialize_design_rules,
    )
    dru = parse_design_rules(file_path)
    updates = {
        k: v for k, v in {
            "constraint_type": op.constraint_type,
            "constraint_values": op.constraint_values,
            "condition": op.condition,
            "layer": op.layer,
        }.items() if v is not None
    }
    dru.modify_rule(op.name, **updates)
    serialize_design_rules(dru, file_path)
    return {
        "rule_name": op.name,
        "action": "modified",
        "updated_fields": list(updates.keys()),
    }


@register_project("remove_design_rule")
def _handle_remove_design_rule(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.project.design_rules import (
        parse_design_rules,
        serialize_design_rules,
    )
    dru = parse_design_rules(file_path)
    removed = dru.remove_rule(op.name)
    serialize_design_rules(dru, file_path)
    return {"rule_name": removed.name, "action": "removed"}


@register_project("list_design_rules")
def _handle_list_design_rules(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.project.design_rules import parse_design_rules
    dru = parse_design_rules(file_path)
    rules = [
        {
            "name": r.name,
            "constraint_type": r.constraint_type,
            "constraint_values": r.constraint_values,
            "condition": r.condition,
            "layer": r.layer,
            "disabled": r.disabled,
        }
        for r in dru.custom_rules
    ]
    return {"rules": rules, "count": len(rules)}


@register_project("modify_project_settings")
def _handle_modify_project_settings(op: Any, file_path: Path) -> dict[str, Any]:
    from kicad_agent.project.project_file import write_project_settings
    write_project_settings(file_path, op.updates)
    return {
        "updated_sections": list(op.updates.keys()),
        "action": "modified",
    }
