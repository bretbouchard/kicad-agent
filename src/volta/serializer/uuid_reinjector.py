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

from volta.parser.uuid_extractor import UUIDMap, element_signature

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


# volta-2yw: element types whose uuids kiutils DROPS during serialization
# (modeled as tstamp or absent). These get reinjected.
# Corpus-measured: kiutils 1.4.8 drops EVERY element uuid on serialization
# (0 survived across all fixtures/types). Everything with a uuid entry is
# reinjectable; skip-if-present keeps already-correct elements untouched.
_REINJECTABLE_TYPES = frozenset({
    "pad", "zone", "via", "segment", "arc", "dimension", "group", "net",
    "property", "gr_line", "gr_arc", "gr_circle", "gr_poly", "gr_rect",
    "gr_text", "graphical", "fp_line", "fp_arc", "fp_circle", "fp_poly",
    "fp_rect", "fp_text",
})

# Graphical tokens collapse to one bucket for type-keyed matching.
_GRAPHICAL_NAMES = {
    "gr_line", "gr_arc", "gr_circle", "gr_poly", "gr_rect", "gr_text",
    "graphical",
}


def _canonical_type(type_name: str) -> str:
    if type_name in _GRAPHICAL_NAMES:
        return "graphical"
    return type_name


def _element_close(content: str, start: int) -> int:
    """Index of the balanced closing paren of the sexpr at `start`.

    String-literal aware. Returns last index on unbalanced input.
    """
    depth = 0
    in_string = False
    i = start
    n = len(content)
    while i < n:
        ch = content[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n - 1


_STANDALONE_UUID_LINE = re.compile(r"^\s*\(uuid \"[0-9a-fA-F-]+\"\)\s*\n?", re.MULTILINE)


def _strip_standalone_uuid_lines(content: str) -> str:
    """Remove uuid-only lines for idempotent reinjection (PCB path).

    Reinjection appends uuids as standalone/inline tokens; re-running on
    already-reinjected content must not duplicate them. Stripping first
    makes insert(strip(C), map(extract(C))) converge across passes.
    """
    return _STANDALONE_UUID_LINE.sub("", content)


def reinject_uuids(serialized_content: str, uuid_map: UUIDMap) -> str:
    """Re-inject UUID tokens into kiutils serialized output.

    volta-2yw contract — deterministic, idempotent, order-independent:

    * Pads are matched STRUCTURALLY by (footprint index, pad number);
      pad numbers are unique per footprint and footprint order is stable,
      so kiutils reordering cannot misassign them.
    * Other reinjectable types (segment, via, gr_*, zone, net, ...) are
      matched by per-type occurrence index — same-type element i in the
      serialized output receives same-type uuid entry i.
    * Types whose uuids kiutils preserves natively (property, footprint
      level, fp_line/...) are left untouched; their entries are unused.
    * Inner (net N "name") pad references never consume slots unless net
      entries exist in the map.
    * Uuid tokens nest INSIDE their element (before its balanced closing
      paren), matching KiCad-native form so re-extraction re-parents
      correctly. Elements already carrying a uuid are skipped.
    * More reinjectable entries than assignable elements raises
      ValueError (S-BUG-003 semantics).

    Args:
        serialized_content: The kiutils serialized S-expression string.
        uuid_map: UUIDMap extracted from the original raw content.

    Returns:
        The content string with UUID tokens re-inserted.
    """
    if not uuid_map.entries:
        return serialized_content

    # Structural pad lookup + signature-keyed geometry queues + per-type
    # FIFO fallback queues.
    pad_lookup: dict[tuple[int, str], list[str]] = {}
    type_queues: dict[str, list[str]] = {}
    sig_queues: dict[tuple[str, str], list[str]] = {}
    _GEOMETRY_TYPES = {"segment", "via", "gr_line", "gr_arc",
                       "gr_circle", "gr_rect", "gr_poly"}
    for entry in uuid_map.entries:
        if not _validate_uuid_format(entry.uuid_value):
            continue
        if entry.parent_type == "pad" and entry.pad_number is not None \
                and entry.footprint_index is not None:
            # list-per-key: duplicate (footprint, pad#) keys (e.g. repeated
            # pad numbers) map in file order, first occurrence first.
            pad_lookup.setdefault(
                (entry.footprint_index, entry.pad_number), []
            ).append(entry.uuid_value)
        elif (
            entry.parent_type in _GEOMETRY_TYPES
            and entry.geometry_signature is not None
        ):
            sig_queues.setdefault(
                (_canonical_type(entry.parent_type), entry.geometry_signature), []
            ).append(entry.uuid_value)
        elif entry.parent_type in _REINJECTABLE_TYPES and entry.parent_type != "pad":
            type_queues.setdefault(_canonical_type(entry.parent_type), []).append(
                entry.uuid_value
            )

    unkeyed_pads: list[str] = [
        entry.uuid_value
        for entry in uuid_map.entries
        if entry.parent_type == "pad"
        and (entry.pad_number is None or entry.footprint_index is None)
        and _validate_uuid_format(entry.uuid_value)
    ]
    # Footprint-level entries: kiutils preserves inline footprint uuids;
    # when absent (synthetic maps / dropped), restore positionally with
    # skip-if-present idempotency.
    footprint_queue: list[str] = [
        entry.uuid_value
        for entry in uuid_map.entries
        if entry.parent_type == "footprint"
        and _validate_uuid_format(entry.uuid_value)
    ]

    if not pad_lookup and not type_queues and not unkeyed_pads and not sig_queues:
        return serialized_content

    matches = list(_ELEMENT_PATTERN.finditer(serialized_content))
    insertions: list[tuple[int, str]] = []
    footprint_idx = -1
    leftover = sum(len(q) for q in type_queues.values()) + len(unkeyed_pads)

    def _try_insert(match, uuid_value: str) -> bool:
        close = _element_close(serialized_content, match.start())
        element_text = serialized_content[match.start():close]
        if "(uuid " in element_text:
            return False  # Element already self-identifies.
        indent = match.group("indent")
        if "\n" in element_text:
            text = f'\n{indent}  (uuid "{uuid_value}")'
        else:
            text = f' (uuid "{uuid_value}")'
        insertions.append((close, text))
        return True

    pad_fallback_idx = 0
    for match in matches:
        matched_type = match.group("type")

        if matched_type == "footprint":
            footprint_idx += 1
            if footprint_queue:
                close = _element_close(serialized_content, match.start())
                span = serialized_content[match.start():close]
                if "(uuid " not in span:
                    indent = match.group("indent")
                    insertions.append(
                        (close, f'\n{indent}  (uuid "{footprint_queue[0]}")')
                    )
                    footprint_queue.pop(0)
            continue

        if matched_type == "pad":
            # The element match ends at the type token -- read the pad's
            # number from the content at the type-start position.
            tail = serialized_content[match.start("type"):match.start("type") + 64]
            m = re.match(r"pad\s+(\"[^\"]*\"|[^\s()]+)", tail)
            if m is not None:
                number = m.group(1).strip('"')
                candidates = pad_lookup.get((footprint_idx, number))
                if candidates:
                    if _try_insert(match, candidates[0]):
                        candidates.pop(0)
                        if not candidates:
                            del pad_lookup[(footprint_idx, number)]
                        continue
            if pad_fallback_idx < len(unkeyed_pads):
                if _try_insert(match, unkeyed_pads[pad_fallback_idx]):
                    pad_fallback_idx += 1
            continue

        canon = _canonical_type(matched_type)
        if matched_type in _GEOMETRY_TYPES:
            paren = match.start("type") - 1  # skip the line indent
            close = _element_close(serialized_content, paren)
            sig = element_signature(serialized_content, paren, close)
            if sig is not None:
                sigq = sig_queues.get((canon, sig))
                if sigq:
                    if _try_insert(match, sigq[0]):
                        sigq.pop(0)
                    continue
                continue
            # sig None -> FIFO below (types without signature grammar).
        queue = type_queues.get(canon)
        if queue:
            if _try_insert(match, queue[0]):
                queue.pop(0)

    leftover = (
        len(footprint_queue)
        + sum(len(q) for q in type_queues.values())
        + sum(len(q) for q in sig_queues.values())
        + len(unkeyed_pads) - pad_fallback_idx
        + sum(len(v) for v in pad_lookup.values())
    )
    if leftover > 0:
        output_type_counts: dict[str, int] = {}
        for m in matches:
            t = m.group("type")
            output_type_counts[t] = output_type_counts.get(t, 0) + 1
        map_type_counts: dict[str, int] = {}
        for entry in uuid_map.entries:
            if _validate_uuid_format(entry.uuid_value):
                map_type_counts[entry.parent_type] = (
                    map_type_counts.get(entry.parent_type, 0) + 1
                )
        leftover_detail = {
            t: len(q) for t, q in type_queues.items() if q
        }
        for (t, sig), q in sig_queues.items():
            if q:
                leftover_detail[f"{t}:{sig[:40]}"] = len(q)
        if pad_lookup:
            leftover_detail["pad(structural)"] = sum(len(v) for v in pad_lookup.values())
            leftover_detail["pad(unkeyed)"] = len(unkeyed_pads) - pad_fallback_idx
        raise ValueError(
            f"UUID reinjection count mismatch: {leftover} entries found no "
            f"assignable element. Leftover: {leftover_detail}. "
            f"Map types: {map_type_counts}. "
            f"Output types: {output_type_counts}."
        )

    result = serialized_content
    for pos, text in sorted(insertions, key=lambda x: x[0], reverse=True):
        result = result[:pos] + text + result[pos:]
    return result


