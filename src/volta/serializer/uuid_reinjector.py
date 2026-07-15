"""UUID re-injection into kiutils serialized output.

kiutils drops UUID tokens from PCB and footprint files during serialization.
This module re-inserts UUIDs into the correct positions within the kiutils
output, using a UUIDMap extracted from the original raw content.

Strategy: UUIDs in KiCad files appear in a deterministic sequential order tied
to the structural elements (footprint, pad, property, graphical items, etc.).
kiutils preserves the structural elements but drops all UUIDs. By walking the
serialized output and injecting UUIDs at the same structural positions, we
restore the original UUID layout.

The two-pass stability test proves this works: after injection, parse->serialize
produces the same output (because the UUIDs are now present in the re-parsed
raw content for the second extraction).

Usage:
    from volta.serializer.uuid_reinjector import reinject_uuids

    restored = reinject_uuids(serialized_content, uuid_map)
"""

import logging
import re

from volta.parser.uuid_extractor import UUIDMap

logger = logging.getLogger(__name__)


# UUID v4 validation pattern
_UUID_V4_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Single combined pattern that matches all structural element opening lines
# that should have UUIDs. Ordered by specificity to avoid false matches.
_ELEMENT_PATTERN = re.compile(
    r"""
    ^(?P<indent>\s*)
    \(
    (?P<type>
        footprint        |
        pad              |
        zone             |
        via              |
        segment          |
        arc              |
        property         |
        fp_line          |
        fp_arc           |
        fp_circle        |
        fp_poly          |
        fp_rect          |
        fp_text          |
        gr_line          |
        gr_arc           |
        gr_circle        |
        gr_poly          |
        gr_rect          |
        gr_text          |
        dimension        |
        group            |
        graphical        |
        model            |
        net              |
        fill             |
        outline          |
        polygon          |
        curve            |
    )\s
    """,
    re.VERBOSE | re.MULTILINE,
)


def _validate_uuid_format(uuid_value: str) -> bool:
    """Validate that a UUID matches the v4 format (36-char hyphenated hex).

    Mitigation for threat T-01-04: reject entries that don't match UUID v4 pattern.

    Args:
        uuid_value: The UUID string to validate.

    Returns:
        True if the UUID is valid v4 format.
    """
    return bool(_UUID_V4_PATTERN.match(uuid_value))


# Types that both the extractor and reinjector agree on. These are directly
# comparable and a mismatch indicates positional drift.
_DIRECTLY_MATCHABLE_TYPES = frozenset({
    "pad", "zone", "via", "segment", "arc", "dimension", "group",
    "gr_line", "gr_arc", "gr_circle", "gr_poly", "gr_rect", "gr_text",
    "graphical",
})


def _types_compatible(expected_parent_type: str, matched_type: str) -> bool:
    """Check whether a matched element type is compatible with the UUID entry's parent_type.

    The extractor and reinjector operate at different granularity. The extractor
    maps UUIDs to their enclosing S-expression parent (e.g. "footprint" for
    UUIDs inside a footprint's properties, fp_lines, etc.). The reinjector
    matches direct child types (property, fp_line, fp_text, etc.).

    Cross-checking is only enforced for types where both sides share the same
    name (pad, zone, via, gr_line, etc.). For enclosing-container types
    ("footprint", "schematic") and "unknown", positional matching is used.

    Args:
        expected_parent_type: The parent_type from the UUID entry.
        matched_type: The element type matched by the reinjector regex.

    Returns:
        True if the types are compatible.
    """
    # "unknown" means the extractor couldn't determine the parent -- positional
    if expected_parent_type == "unknown":
        return True

    # If both types are directly matchable, require an exact match (or
    # graphical equivalence). Otherwise one side is a container type and
    # positional matching applies.
    both_matchable = (
        expected_parent_type in _DIRECTLY_MATCHABLE_TYPES
        and matched_type in _DIRECTLY_MATCHABLE_TYPES
    )
    if not both_matchable:
        return True  # At least one is a container/unmapped type -- positional

    # Both are directly matchable -- check for direct match
    if expected_parent_type == matched_type:
        return True

    # Graphical catch-all: the extractor may assign "graphical" to any gr_*
    # token, while the reinjector matches the specific gr_* name.
    _GRAPHICAL_NAMES = {
        "gr_line", "gr_arc", "gr_circle", "gr_poly", "gr_rect", "gr_text",
        "graphical",
    }
    if expected_parent_type in _GRAPHICAL_NAMES and matched_type in _GRAPHICAL_NAMES:
        return True

    return False


def reinject_uuids(serialized_content: str, uuid_map: UUIDMap) -> str:
    """Re-inject UUID tokens into kiutils serialized output.

    Walks the serialized content, finding structural elements that would have
    UUIDs in the original file, and inserts the corresponding UUID from the
    UUIDMap. UUIDs are injected sequentially -- each structural element gets
    the next UUID from the map.

    Args:
        serialized_content: The kiutils serialized S-expression string.
        uuid_map: UUIDMap extracted from the original raw content.

    Returns:
        The content string with UUID tokens re-inserted.
    """
    if not uuid_map.entries:
        return serialized_content

    # Build an ordered queue of (uuid_value, parent_type) tuples.
    # Carrying parent_type enables cross-checking against matched element types
    # to prevent UUID misplacement when element counts diverge.
    uuid_queue = [
        (entry.uuid_value, entry.parent_type)
        for entry in uuid_map.entries
        if _validate_uuid_format(entry.uuid_value)
    ]

    if not uuid_queue:
        return serialized_content

    # Find all structural element positions in file order
    # Each match gives us (position, indent, match_end)
    matches = list(_ELEMENT_PATTERN.finditer(serialized_content))

    # S-BUG-003: Validate element counts match before injection.
    # If UUID map has more entries than structural elements, injection will
    # silently misassign UUIDs to wrong positions. Fail loudly instead.
    if len(uuid_queue) > len(matches):
        # Count element types in the serialized output for a helpful error
        output_type_counts: dict[str, int] = {}
        for m in matches:
            t = m.group("type")
            output_type_counts[t] = output_type_counts.get(t, 0) + 1

        map_type_counts: dict[str, int] = {}
        for _, ptype in uuid_queue:
            map_type_counts[ptype] = map_type_counts.get(ptype, 0) + 1

        raise ValueError(
            f"UUID reinjection count mismatch: UUID map has {len(uuid_queue)} entries "
            f"but serialized output has {len(matches)} structural elements. "
            f"Injection would misassign UUIDs. "
            f"Map types: {map_type_counts}. Output types: {output_type_counts}."
        )

    # Apply UUIDs sequentially to structural elements
    insertions: list[tuple[int, str]] = []
    uuid_idx = 0

    for match in matches:
        if uuid_idx >= len(uuid_queue):
            break

        uuid_value, expected_parent_type = uuid_queue[uuid_idx]
        matched_type = match.group("type")

        # Cross-check: verify the element type matches the UUID entry's
        # parent_type for directly matchable types. Log mismatches as
        # warnings to detect positional drift between extractor and
        # reinjector without disrupting the sequential injection.
        if not _types_compatible(expected_parent_type, matched_type):
            logger.warning(
                "UUID type mismatch at position %d: expected parent_type=%r "
                "but matched element type=%r for UUID %s",
                uuid_idx, expected_parent_type, matched_type, uuid_value,
            )

        indent = match.group("indent")
        match_end = match.end()

        # Find the end of this line to insert after it
        line_end = serialized_content.find("\n", match_end)
        if line_end == -1:
            line_end = len(serialized_content)

        # UUID should be indented one level deeper than the parent element
        uuid_indent = indent + "  "
        uuid_line = f'{uuid_indent}(uuid "{uuid_value}")\n'

        insertions.append((line_end, uuid_line))
        uuid_idx += 1

    # Apply insertions in reverse order to preserve positions
    result = serialized_content
    for pos, uuid_line in sorted(insertions, key=lambda x: x[0], reverse=True):
        result = result[:pos] + uuid_line + result[pos:]

    return result
