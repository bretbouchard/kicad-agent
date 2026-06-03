"""Targeted S-expression patch serializer for KiCad schematics.

Instead of re-serializing the entire file via kiutils (which reformats
everything), this module generates minimal S-expression text for mutations
and inserts them into the original raw file content.

Issue #2: kiutils.to_file() reformats the entire file, making git diffs
unreadable. This module preserves original formatting by only modifying
the specific sections that changed.

KiCad schematic files use flat top-level S-expressions:
  (kicad_sch
    (version ...)
    (wire ...)
    (wire ...)
    (label ...)
    (no_connect ...)
    (symbol ...)
    ...
  )

All insertions append before the file's final closing paren (the `(kicad_sch`
closing paren). No grouped wrapper sections are created.

Supported mutation types:
- add_no_connect: Insert no_connect S-expression
- add_junction: Insert junction S-expression
- add_wire: Insert wire S-expression
- add_label: Insert label/global_label/hierarchical_label S-expression
- Coordinate patches: Replace specific coordinate values in-place

Usage:
    from kicad_agent.serializer.patch_serializer import patch_serialize

    output = patch_serialize(raw_content, mutation_log, kiutils_obj)
"""

import logging
import re
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Mapping from IR label_type values to KiCad S-expression tag names.
# The IR uses "local"/"global"/"hierarchical" while KiCad uses
# "label"/"global_label"/"hierarchical_label".
_LABEL_TYPE_TO_TAG = {
    "local": "label",
    "global": "global_label",
    "hierarchical": "hierarchical_label",
    # Also accept the direct KiCad tags for callers that already use them
    "label": "label",
    "global_label": "global_label",
    "hierarchical_label": "hierarchical_label",
}

# Allowed S-expression label tags (whitelist for injection prevention)
_VALID_LABEL_TAGS = frozenset(_LABEL_TYPE_TO_TAG.values())


def _escape_sexp_string(s: str) -> str:
    """Escape a string for safe inclusion in a KiCad S-expression quoted value."""
    # Replace backslash first, then quotes
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')
    return s


def _format_coord(value: float) -> str:
    """Format a coordinate value matching KiCad's precision.

    KiCad uses up to 6 decimal places but avoids trailing zeros.
    Zero is represented as "0" (no decimal point needed).
    """
    if value == 0:
        return "0"
    formatted = f"{value:.6f}".rstrip("0").rstrip(".")
    return formatted


def _generate_no_connect_sexp(x: float, y: float, uid: str | None = None) -> str:
    """Generate S-expression text for a no_connect flag."""
    if uid is None:
        uid = str(uuid.uuid4())
    return f'  (no_connect (at {_format_coord(x)} {_format_coord(y)}) (uuid {uid}))'


def _generate_junction_sexp(x: float, y: float, uid: str | None = None, diameter: float = 0.0) -> str:
    """Generate S-expression text for a junction."""
    if uid is None:
        uid = str(uuid.uuid4())
    parts = f'  (junction (at {_format_coord(x)} {_format_coord(y)}) (uuid {uid})'
    if diameter > 0:
        parts += f' (diameter {_format_coord(diameter)})'
    return parts + ')'


def _generate_wire_sexp(start_x: float, start_y: float, end_x: float, end_y: float, uid: str | None = None) -> str:
    """Generate S-expression text for a wire segment."""
    if uid is None:
        uid = str(uuid.uuid4())
    return (
        f'  (wire (pts (xy {_format_coord(start_x)} {_format_coord(start_y)}) '
        f'(xy {_format_coord(end_x)} {_format_coord(end_y)})) (stroke (width 0)) (uuid {uid}))'
    )


def _generate_label_sexp(name: str, x: float, y: float, angle: float = 0.0,
                          label_type: str = "label", uid: str | None = None) -> str:
    """Generate S-expression text for a label.

    Args:
        name: Label text (will be escaped for S-expression safety).
        x, y: Position in mm.
        angle: Rotation in degrees.
        label_type: One of "local", "global", "hierarchical", "label",
                    "global_label", "hierarchical_label".
        uid: Optional UUID (generated if None).
    """
    tag = _LABEL_TYPE_TO_TAG.get(label_type, "label")
    if tag not in _VALID_LABEL_TAGS:
        logger.warning("Unknown label_type '%s', falling back to 'label'", label_type)
        tag = "label"
    safe_name = _escape_sexp_string(name)
    if uid is None:
        uid = str(uuid.uuid4())
    return (
        f'  ({tag} "{safe_name}" (at {_format_coord(x)} {_format_coord(y)} {_format_coord(angle)}) '
        f'(uuid {uid}))'
    )


def _generate_power_symbol_sexp(name: str, lib_id: str, x: float, y: float,
                                  angle: float = 0.0, ref: str = "#PWR?",
                                  uid: str | None = None) -> str:
    """Generate S-expression text for a power symbol instance.

    Note: Also requires a lib_symbol entry, handled separately.
    Returns None to signal caller to fall back to full re-serialization
    (symbol additions are too complex for patch serialization).
    """
    # Symbol additions require lib_symbol management — always fall back
    return None  # noqa: RET501


def _insert_before_final_close(content: str, sexp_text: str) -> str:
    """Insert S-expression text before the file's final closing paren.

    KiCad schematic files are flat: (kicad_sch ... (wire ...) (label ...) ).
    All items are direct children of (kicad_sch ...). We insert before
    the final ')' to add new items as children.
    """
    # Find the last ')' in the file
    close_pos = content.rstrip().rfind(')')
    if close_pos == -1:
        return content  # Malformed file — don't touch

    # Insert before the final close, with a newline
    return content[:close_pos] + sexp_text + '\n' + content[close_pos:]


def _patch_coordinates(content: str, mutations: list[dict[str, Any]]) -> str:
    """Patch coordinate values in wire S-expressions for snap/modify operations.

    Mutations with type 'repair_wire_snap' or 'snap_to_grid' contain
    position data. We find coordinates by value and replace them.
    """
    for mut in mutations:
        mut_type = mut.get("type", "")
        if mut_type not in ("repair_wire_snap", "snap_to_grid"):
            continue

        if mut_type == "snap_to_grid":
            group_at = mut.get("details", {}).get("group_at")
            snapped_to = mut.get("details", {}).get("snapped_to")
            if group_at and snapped_to:
                old_x = _format_coord(group_at[0])
                old_y = _format_coord(group_at[1])
                new_x = _format_coord(snapped_to[0])
                new_y = _format_coord(snapped_to[1])
                # Replace coordinate pair occurrences.
                # This targets the (xy X Y) pattern specifically.
                old_pattern = f'(xy {old_x} {old_y})'
                new_pattern = f'(xy {new_x} {new_y})'
                content = content.replace(old_pattern, new_pattern)

    return content


def patch_serialize(
    raw_content: str,
    mutation_log: list[dict[str, Any]],
    kiutils_obj: Any,
) -> str | None:
    """Apply mutations to raw file content with minimal formatting changes.

    Issue #2: Preserves original file formatting by inserting/patching
    only the changed S-expressions instead of re-serializing via kiutils.

    KiCad files use flat top-level S-expressions. All insertions append
    before the file's final closing paren.

    Args:
        raw_content: Original file content string.
        mutation_log: List of mutation dicts from SchematicIR.mutation_log.
        kiutils_obj: The kiutils Schematic object (for UUID lookup).

    Returns:
        Modified content string with mutations applied, or None to signal
        the caller to fall back to full kiutils re-serialization.
    """
    if not mutation_log:
        return raw_content

    content = raw_content

    # Build UUID map from kiutils_obj for items that were added
    uuid_map: dict[str, str] = {}
    for nc in getattr(kiutils_obj, 'noConnects', []):
        if hasattr(nc, 'uuid'):
            pos_key = f"nc_{round(nc.position.X, 2)}_{round(nc.position.Y, 2)}"
            uuid_map[pos_key] = nc.uuid

    for junction in getattr(kiutils_obj, 'junctions', []):
        if hasattr(junction, 'uuid'):
            pos_key = f"j_{round(junction.position.X, 2)}_{round(junction.position.Y, 2)}"
            uuid_map[pos_key] = junction.uuid

    # Separate mutations into additive and coordinate-patch types
    additive_mutations: list[dict[str, Any]] = []
    coord_mutations: list[dict[str, Any]] = []

    for mut in mutation_log:
        mut_type = mut.get("type", "")
        if mut_type in ("repair_wire_snap", "snap_to_grid"):
            coord_mutations.append(mut)
        elif mut_type in (
            "add_no_connect", "add_junction", "add_wire", "add_label",
            "add_power_symbol", "remove_dangling_wire", "remove_orphaned_label",
            "place_missing_unit", "fix_shorted_net", "resolve_shorted_net",
            "add_power_flag", "break_wire_short",
        ):
            additive_mutations.append(mut)

    # Phase 1: Apply coordinate patches (in-place replacement)
    if coord_mutations:
        content = _patch_coordinates(content, coord_mutations)

    # Phase 2: Generate and collect S-expressions for additive mutations
    new_sexps: list[str] = []

    for mut in additive_mutations:
        details = mut.get("details", {})
        mut_type = mut.get("type", "")

        if mut_type == "add_no_connect":
            pos = details.get("position", [0, 0])
            pos_key = f"nc_{round(pos[0], 2)}_{round(pos[1], 2)}"
            uid = uuid_map.get(pos_key)
            new_sexps.append(_generate_no_connect_sexp(pos[0], pos[1], uid))

        elif mut_type == "add_junction":
            pos = details.get("position", [0, 0])
            pos_key = f"j_{round(pos[0], 2)}_{round(pos[1], 2)}"
            uid = uuid_map.get(pos_key)
            new_sexps.append(_generate_junction_sexp(pos[0], pos[1], uid))

        elif mut_type == "add_wire":
            start = details.get("start", [0, 0])
            end = details.get("end", [0, 0])
            new_sexps.append(_generate_wire_sexp(start[0], start[1], end[0], end[1]))

        elif mut_type == "add_label":
            name = details.get("name", "")
            pos = details.get("position", [0, 0, 0])
            label_type = details.get("label_type", "label")
            new_sexps.append(_generate_label_sexp(
                name, pos[0], pos[1], pos[2] if len(pos) > 2 else 0.0, label_type,
            ))

        elif mut_type in ("add_power_symbol", "add_power_flag"):
            # Symbol additions require lib_symbol management — fall back
            logger.warning(
                "patch_serializer: symbol additions require full "
                "re-serialization. Diff will show formatting changes."
            )
            return None

    # Phase 3: Insert all collected S-expressions before the final closing paren
    if new_sexps:
        # Insert all at once to avoid multiple string operations
        combined = '\n'.join(new_sexps)
        content = _insert_before_final_close(content, combined)

    return content


def can_patch_serialize(mutation_log: list[dict[str, Any]]) -> bool:
    """Check if mutations can be applied via targeted patching.

    Returns False if mutations require full re-serialization.
    Symbol additions, removals, and complex mutations require kiutils
    to manage the lib_symbols section and file structure.
    """
    UNSUPPORTED = frozenset({
        "remove_dangling_wire", "remove_orphaned_label",
        "place_missing_unit", "fix_shorted_net", "resolve_shorted_net",
        "break_wire_short", "fix_pin_type_mismatches",
        "update_symbols_from_library",
        "add_power_symbol", "add_power_flag",
    })
    for mut in mutation_log:
        mut_type = mut.get("type", "")
        if not mut_type:
            # Mutations without a type field (e.g. add_component with only
            # "description") require full re-serialization since we cannot
            # determine how to patch them.
            return False
        if mut_type in UNSUPPORTED:
            return False
    return True
