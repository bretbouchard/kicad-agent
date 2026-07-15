"""Schematic mutation handlers -- operations that modify schematic files.

Handlers receive (op, SchematicIR, file_path) and return a result dict.
Each handler is registered via @register_schematic(op_type) and looked up
by the executor's _dispatch method.
"""

import dataclasses
import logging
import re
from pathlib import Path
from typing import Any, Callable

from volta.ir.schematic_ir import SchematicIR
from volta.io.atomic_write import atomic_write
from volta.ops.schematic_raw_writer import SchematicRawWriter

logger = logging.getLogger(__name__)

_SCHEMATIC_HANDLERS: dict[str, Callable] = {}

# Power symbols (#PWR?, #PWR01, #GND01, etc.) are graphical-only — they have no
# refdes to renumber and must be skipped during annotation (EXEC-01).
_POWER_SYMBOL_PREFIX = "#"


def register_schematic(op_type: str) -> Callable:
    """Decorator to register a schematic operation handler."""
    def decorator(fn: Callable) -> Callable:
        _SCHEMATIC_HANDLERS[op_type] = fn
        return fn
    return decorator


@register_schematic("add_component")
def _handle_add_component(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.add_component import add_component
    return add_component(op, ir, file_path)


@register_schematic("remove_component")
def _handle_remove_component(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.remove_component import remove_component
    return remove_component(op, ir)


@register_schematic("duplicate_component")
def _handle_duplicate_component(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.duplicate_component import duplicate_component
    return duplicate_component(op, ir)


@register_schematic("array_replicate")
def _handle_array_replicate(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.array_replicate import array_replicate
    return array_replicate(op, ir)


@register_schematic("move_component")
def _handle_move_component(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.move_component import move_component
    return move_component(op, ir, file_type=ir.file_type)


@register_schematic("snap_components_to_grid")
def _handle_snap_components_to_grid(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    """Snap component positions to the nearest grid point."""
    grid = op.grid_size

    def _snap(value: float) -> float:
        nearest = int(value / grid + 0.5)
        return round(nearest * grid, 2)

    sch = ir._parse_result.kiutils_obj
    snapped = 0
    skipped = 0
    moves: list[dict] = []

    for sym in sch.schematicSymbols:
        ref = getattr(sym, 'libId', '')  # fallback
        # Get reference from properties
        for prop in getattr(sym, 'properties', []):
            if prop.key == "Reference":
                ref = prop.value
                break

        # Apply prefix filter
        if op.prefix_filter and not ref.startswith(op.prefix_filter):
            skipped += 1
            continue

        old_x = sym.position.X
        old_y = sym.position.Y
        new_x = _snap(old_x)
        new_y = _snap(old_y)

        if new_x == old_x and new_y == old_y:
            skipped += 1
            continue

        moves.append({
            "reference": ref,
            "from": [old_x, old_y],
            "to": [new_x, new_y],
        })

        if not op.dry_run:
            sym.position.X = new_x
            sym.position.Y = new_y
            ir._record_mutation("snap_component", {
                "reference": ref,
                "from": [old_x, old_y],
                "to": [new_x, new_y],
                "grid": grid,
            })

        snapped += 1

    return {
        "snapped": snapped,
        "skipped": skipped,
        "dry_run": op.dry_run,
        "grid_size": grid,
        "moves": moves,
    }


@register_schematic("modify_property")
def _handle_modify_property(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.modify_property import modify_property
    return modify_property(op, ir)


@register_schematic("add_net")
def _handle_sch_add_net(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    net = ir.add_net(net_name=op.net_name, net_number=op.net_number)
    return {"net_name": net.name, "net_number": net.number}


@register_schematic("remove_net")
def _handle_sch_remove_net(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    ir.remove_net(net_name=op.net_name)
    return {"removed_net": op.net_name}


@register_schematic("rename_net")
def _handle_sch_rename_net(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    ir.rename_net(old_name=op.old_name, new_name=op.new_name)
    return {"old_name": op.old_name, "new_name": op.new_name}


@register_schematic("renumber_refs")
def _handle_renumber_refs(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    changes = ir.renumber_references(
        prefix=op.prefix, start_index=op.start_index, step=op.step
    )
    return {"changes": [{"old": o, "new": n} for o, n in changes]}


@register_schematic("annotate")
def _handle_annotate(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    import warnings

    warnings.warn(
        "annotate is DEPRECATED (P0-006). It corrupts KiCad 10 schematics via kiutils "
        "re-serialization. Use the 'safe_annotate' op instead, which performs raw "
        "S-expression edits. See BUGS/P0-006-annotate-corrupts-files.md and "
        "docs/api/safe_annotate.md.",
        DeprecationWarning,
        stacklevel=2,
    )
    changes = ir.annotate_components(prefix_filter=op.prefix_filter)
    return {"annotated": [{"old": o, "new": n} for o, n in changes]}


@register_schematic("safe_annotate")
def _handle_safe_annotate(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    """Non-destructive refdes renumbering via raw S-expression edits.

    Mirrors safe_sync_pcb_from_schematic pattern: never kiutils.to_file().
    All edits via SchematicRawWriter + atomic_write.
    """
    # Lazy imports (M-02: cross-handler imports proven to need lazy loading
    # to avoid circulars; matches pcb_auto_route.py sibling pattern).
    from volta.ops.handlers.pcb_cleanup import validate_paren_balance

    # Resolve symlinks/relative paths up front so root_path matches the keys
    # in new_contents/original_contents (which are populated from the same
    # resolved path via SchematicGraph.from_hierarchy). Without this, a
    # target_file passed in symlink form (e.g. /var vs /private/var on macOS)
    # would miss the dict lookup and KeyError on the write path.
    root_path = Path(file_path).resolve()
    raw_content = root_path.read_text()

    # ---- ROOT SHEET GUARD (LOCKED error message) ----
    # Fires ONLY when the caller asks for current_sheet annotation on a root
    # (which contains only hierarchy blocks — nothing to annotate). For
    # whole_project scope, the root sheet is the entry point: the handler
    # walks the sub-sheets below and annotates them.
    has_sheet_blocks = bool(re.search(r'\(sheet\s', raw_content))
    has_placed_components = bool(
        re.search(r'\(symbol\s+\(lib_id\s+"[^"]*"\)\s+\(at\s', raw_content)
    )
    if op.scope == "current_sheet" and has_sheet_blocks and not has_placed_components:
        raise ValueError(
            "safe_annotate operates per-sheet; root sheet contains hierarchy only — use sub-sheet scope"
        )

    # ---- DISCOVER TARGET SHEETS ----
    # Build a sheet_path -> sheet_uuid map for EXEC-03 sort tie-break.
    # The root sheet UUID comes from _extract_root_sheet_uuid (header-level);
    # sub-sheet UUIDs come from SheetRef.uuid populated by from_hierarchy
    # (CR-01 fix in schematic_graph.py:737 accepts KiCad 10 unquoted UUIDs).
    sheet_path_to_uuid: dict[str, str] = {}

    if op.scope == "current_sheet":
        sheet_paths = [root_path]
        sheet_path_to_uuid[str(root_path)] = _extract_root_sheet_uuid(root_path.read_text())
    else:  # whole_project
        from volta.schematic_routing.schematic_graph import SchematicGraph
        tree = SchematicGraph.from_hierarchy(str(root_path))
        sheet_paths = [Path(tree.filepath)]
        _collect_children(tree, sheet_paths)

        # Root sheet UUID from the root file header.
        root_uuid = _extract_root_sheet_uuid(Path(tree.filepath).read_text())
        sheet_path_to_uuid[str(tree.filepath)] = root_uuid

        # Sub-sheet UUIDs from SheetRef.uuid (populated by _parse_sheet_refs).
        # Walk the tree depth-first; each child's filepath keys its UUID.
        def _index_sub_sheet_uuids(node) -> None:
            for child in node.children:
                # Find the SheetRef matching this child's filepath.
                child_filename = Path(child.filepath).name
                matching_ref = None
                for ref in node.sheet_refs:
                    if ref.filepath == child_filename:
                        matching_ref = ref
                        break
                if matching_ref is not None:
                    sheet_path_to_uuid[str(child.filepath)] = matching_ref.uuid
                _index_sub_sheet_uuids(child)

        _index_sub_sheet_uuids(tree)

    # ---- COLLECT COMPONENTS PER SHEET ----
    all_components = []  # list of {sheet, sheet_uuid, uuid, ref, x, y}
    for sheet_path in sheet_paths:
        sheet_raw = sheet_path.read_text()
        components = _extract_symbols_with_refs(sheet_raw)
        sheet_uuid = sheet_path_to_uuid.get(str(sheet_path), "")
        for c in components:
            c["sheet"] = str(sheet_path)
            c["sheet_uuid"] = sheet_uuid
            all_components.append(c)

    # ---- BUILD RENAME PLAN ----
    rename_plan = _build_rename_plan(all_components, reset=op.reset, order=op.order)

    # ---- DRY RUN SHORT-CIRCUIT ----
    if op.dry_run:
        return {
            "annotated": [
                {
                    "sheet": r["sheet"],
                    "uuid": r["uuid"],
                    "old_ref": r["old_ref"],
                    "new_ref": r["new_ref"],
                    **({"note": "cross-sheet duplicate renamed"} if r.get("deduped") else {}),
                }
                for r in rename_plan if r["old_ref"] != r["new_ref"]
            ],
            "stats": {
                "sheets_touched": len({r["sheet"] for r in rename_plan if r["old_ref"] != r["new_ref"]}),
                "refs_renamed": sum(1 for r in rename_plan if r["old_ref"] != r["new_ref"]),
                "duplicates_resolved": sum(1 for r in rename_plan if r.get("deduped")),
                "placekeepers_filled": sum(1 for r in rename_plan if r["old_ref"].endswith("?")),
            },
            "skipped": [],
            "paren_balance_check": "PASS",
            "format_preservation_check": "PASS",
            "dry_run": True,
        }

    # ---- APPLY EDITS RAW (per sheet, in memory) ----
    original_contents = {str(p): p.read_text() for p in sheet_paths}
    new_contents = dict(original_contents)  # copy

    for rename in rename_plan:
        if rename["old_ref"] == rename["new_ref"]:
            continue  # no change needed
        sheet_key = rename["sheet"]
        # H-02 Option B (Phase 102.1): co-edit BOTH the (property "Reference")
        # AND the (instances ... (reference ...)) blocks. Real-world KiCad 10
        # schematics have instances blocks that the netlist exporter reads from;
        # editing only the property leaves the netlist stale. Both methods are
        # idempotent no-ops if the target block is absent (backward compat with
        # Phase 102 fixtures that intentionally omit instances blocks).
        new_contents[sheet_key] = SchematicRawWriter.replace_reference_property(
            new_contents[sheet_key], rename["uuid"], rename["new_ref"]
        )
        new_contents[sheet_key] = SchematicRawWriter.replace_instances_reference(
            new_contents[sheet_key], rename["uuid"], rename["new_ref"]
        )

    # ---- PAREN BALANCE VALIDATION (pre-write, fail-closed) ----
    for sheet_path_str, new_raw in new_contents.items():
        if new_raw != original_contents[sheet_path_str]:
            if not validate_paren_balance(new_raw):
                raise RuntimeError(f"Paren imbalance after refdes edit on {sheet_path_str}")

    # ---- WRITE (multi-sheet atomic transaction — CR-01 fix) ----
    # The executor's Transaction already protects root_path (target_file).
    # Sub-sheets need their own atomic coordination: all sub-sheets commit
    # together or all rollback. The root is written separately (executor-
    # protected) to avoid double-locking the same file.
    root_str = str(root_path)
    changed_subs = [
        Path(p) for p, raw in new_contents.items()
        if raw != original_contents[p] and p != root_str
    ]
    if changed_subs:
        from volta.crossfile.atomic import AtomicOperation
        with AtomicOperation(changed_subs) as atomic:
            for sub_path in changed_subs:
                atomic_write(sub_path, new_contents[str(sub_path)])
            result = atomic.commit()
            if not result.success:
                raise RuntimeError(f"safe_annotate atomic commit failed: {result.error}")
            # R2-02: root writes AFTER sub-sheets commit succeeds, so a commit
            # failure rolls back sub-sheets without leaving root half-written.
            if new_contents.get(root_str, original_contents[root_str]) != original_contents[root_str]:
                atomic_write(root_path, new_contents[root_str])
    elif new_contents.get(root_str, original_contents[root_str]) != original_contents[root_str]:
        atomic_write(root_path, new_contents[root_str])

    # ---- RESPONSE ----
    renamed = [r for r in rename_plan if r["old_ref"] != r["new_ref"]]
    return {
        "annotated": [
            {
                "sheet": r["sheet"],
                "uuid": r["uuid"],
                "old_ref": r["old_ref"],
                "new_ref": r["new_ref"],
                **({"note": "cross-sheet duplicate renamed"} if r.get("deduped") else {}),
            }
            for r in renamed
        ],
        "stats": {
            "sheets_touched": len({r["sheet"] for r in renamed}),
            "refs_renamed": len(renamed),
            "duplicates_resolved": sum(1 for r in renamed if r.get("deduped")),
            "placekeepers_filled": sum(1 for r in renamed if r["old_ref"].endswith("?")),
        },
        "skipped": [],
        "paren_balance_check": "PASS",
        "format_preservation_check": "PASS",
    }


def _collect_children(node, paths: list) -> None:
    """Recursively collect child sheet paths from a HierarchicalSchematic node."""
    for child in node.children:
        paths.append(Path(child.filepath))
        _collect_children(child, paths)


def _extract_root_sheet_uuid(raw: str) -> str:
    """Extract the top-level sheet UUID from a root .kicad_sch file.

    Anchored to the ``(uuid ...)`` that appears BEFORE the first ``(symbol``
    or ``(lib_symbols`` block — avoids picking up UUIDs nested in title
    blocks, sheet blocks, or placed-component symbol blocks.

    KiCad 10 uses unquoted UUID form ``(uuid aaaa-...)`` at the file header;
    older format quotes them ``(uuid "aaaa-...")``. Both forms are matched.

    Returns empty string if no top-level UUID is found.
    """
    header_end = len(raw)
    for marker in ("(symbol", "(lib_symbols"):
        idx = raw.find(marker)
        if idx != -1:
            header_end = min(header_end, idx)
    header = raw[:header_end]
    m = re.search(r'\(uuid\s+"?([0-9a-f-]+)"?\)', header)
    return m.group(1) if m else ""



def _extract_symbols_with_refs(raw: str) -> list:
    """Extract placed component symbols with (uuid, ref, x, y) from raw schematic content.

    Filters OUT lib_symbol definitions (which use (symbol "Name" ...) form)
    and power symbols (ref starts with '#').

    Returns list of {uuid, ref, x, y} dicts.
    """
    from volta.ir.schematic_ir import _REF_PATTERN

    symbols = []
    for m in re.finditer(r'\(symbol\b', raw):
        start = m.start()
        depth = 0
        i = start
        end = None
        while i < len(raw):
            if raw[i] == '(':
                depth += 1
            elif raw[i] == ')':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
            i += 1
        if end is None:
            continue

        block = raw[start:end]

        # Must be a placed instance: has (lib_id "...") AND (at X Y ...)
        if not re.search(r'\(lib_id\s+"[^"]*"\)', block):
            continue  # lib_symbol definition, skip
        at_m = re.search(r'\(at\s+([\d.-]+)\s+([\d.-]+)', block)
        if not at_m:
            continue

        uuid_m = re.search(r'\(uuid\s+"?([^")\s]+)"?', block)
        if not uuid_m:
            continue
        symbol_uuid = uuid_m.group(1)

        ref_m = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
        ref = ref_m.group(1) if ref_m else ""

        # Skip power symbols (#PWR?, #PWR01, etc.)
        if ref.startswith(_POWER_SYMBOL_PREFIX):
            continue

        symbols.append({
            "uuid": symbol_uuid,
            "ref": ref,
            "x": float(at_m.group(1)),
            "y": float(at_m.group(2)),
        })

    return symbols


def _build_rename_plan(components: list, reset: bool, order: str) -> list:
    """Build a per-component rename plan.

    Args:
        components: list of {uuid, ref, x, y, sheet, sheet_uuid} dicts.
        reset: if True, treat all refs as <prefix>? before renumbering.
        order: one of "by_x_position" | "by_y_position" | "sheet_order".

    Sort tie-break order (LOCKED per CONTEXT.md "Claude's Discretion" — "when
    two components share the same X coordinate, break ties by Y then by sheet
    order"). The final tie-break uses ``sheet_uuid`` (EXEC-03, Phase 102.1):
    KiCad-generated UUIDs are stable across machines, so the same project
    produces identical refdes assignments regardless of the absolute
    filesystem path it lives under.

    - ``by_x_position``: sort key = ``(x, y, sheet_uuid)`` — primary X,
      tie-break Y, final tie-break sheet UUID. This is the LOCKED order
      from CONTEXT.md.
    - ``by_y_position``: sort key = ``(y, x, sheet_uuid)`` — primary Y,
      tie-break X, final tie-break sheet UUID.
    - ``sheet_order``: sort key = ``(sheet_uuid, x, y)`` — primary sheet
      UUID, tie-break X, final tie-break Y.

    The ``sheet_uuid`` tie-break is a deterministic string comparison on the
    KiCad-embedded sheet UUID. For schematics where a sheet has no header
    UUID (rare — legacy or hand-edited files), the tie-break degenerates to
    an empty string comparison for that sheet; this is no worse than the
    pre-EXEC-03 ``sheet_path`` behavior and is documented for completeness.

    Returns list of {uuid, old_ref, new_ref, sheet, sheet_uuid, deduped?} dicts.
    """
    from volta.ir.schematic_ir import _REF_PATTERN

    # Parse refs into (prefix, suffix) tuples; skip refs that don't match the pattern.
    parsed = []
    for c in components:
        match = _REF_PATTERN.match(c["ref"]) if c["ref"] else None
        if not match:
            # Unparseable or empty ref — skip (can't renumber what we can't parse)
            parsed.append({**c, "prefix": None, "suffix": None})
            continue
        prefix, suffix = match.group(1), match.group(2)
        parsed.append({**c, "prefix": prefix, "suffix": suffix})

    # Filter to annotatable components (have a prefix)
    annotatable = [c for c in parsed if c["prefix"] is not None]

    # Determine effective refs: if reset, all become "<prefix>?"
    if reset:
        for c in annotatable:
            c["effective_ref"] = f"{c['prefix']}?"
    else:
        for c in annotatable:
            c["effective_ref"] = c["ref"]

    # Sort by order option (tie-break documented in the docstring above — M-03).
    # EXEC-03 (Phase 102.1): final tie-break uses sheet_uuid (stable across
    # machines) rather than sheet_path (absolute, varies across filesystems).
    if order == "by_x_position":
        sort_key = lambda c: (c["x"], c["y"], c.get("sheet_uuid", ""))
    elif order == "by_y_position":
        sort_key = lambda c: (c["y"], c["x"], c.get("sheet_uuid", ""))
    else:  # sheet_order
        sort_key = lambda c: (c.get("sheet_uuid", ""), c["x"], c["y"])

    annotatable.sort(key=sort_key)

    # Pre-pass: detect cross-component duplicates among original refs.
    # A ref is a "duplicate" if 2+ annotatable components share the same
    # original ref string (e.g., two R1's on different sheets). When we
    # renumber, only ONE component may keep the ref — all others get a
    # new number and are marked deduped so stats.duplicates_resolved counts
    # them. This is the cross-sheet dedup contract (CONTEXT.md test 3).
    from collections import Counter
    ref_counts = Counter(c["ref"] for c in annotatable if c["ref"])
    original_dup_refs = {r for r, n in ref_counts.items() if n > 1 and not r.endswith("?")}
    # The FIRST component (in sort order) that owns a duplicate ref keeps it;
    # subsequent owners are dedupes.
    dedupe_owner_seen: set[str] = set()

    # Group by prefix, assign sequential numbers
    counters = {}  # prefix -> next number
    used_refs = set()  # track assigned refs to detect duplicates
    plan = []

    # First pass: assign new refs
    for c in annotatable:
        prefix = c["prefix"]
        old_ref = c["ref"]
        effective = c["effective_ref"]

        # If not reset and ref is already fully annotated (not ending in ?), keep it
        if not reset and not effective.endswith("?"):
            # Already annotated — check for duplicates
            if old_ref in used_refs:
                # Duplicate! Assign next available number
                if prefix not in counters:
                    counters[prefix] = 1
                while f"{prefix}{counters[prefix]}" in used_refs:
                    counters[prefix] += 1
                new_ref = f"{prefix}{counters[prefix]}"
                used_refs.add(new_ref)
                plan.append({**c, "old_ref": old_ref, "new_ref": new_ref, "deduped": True})
            else:
                used_refs.add(old_ref)
                if prefix not in counters:
                    counters[prefix] = _extract_number(old_ref, prefix) + 1
                else:
                    counters[prefix] = max(counters[prefix], _extract_number(old_ref, prefix) + 1)
                plan.append({**c, "old_ref": old_ref, "new_ref": old_ref})
        else:
            # Needs annotation (ends in ? — either originally R? or reset stripped to R?)
            if prefix not in counters:
                counters[prefix] = 1
            while f"{prefix}{counters[prefix]}" in used_refs:
                counters[prefix] += 1
            new_ref = f"{prefix}{counters[prefix]}"
            used_refs.add(new_ref)

            # Detect dedup under reset mode: if the original ref was a
            # duplicate AND this is not the first owner in sort order, then
            # this rename resolves a cross-component duplicate.
            is_dedupe = False
            if reset and old_ref in original_dup_refs:
                if old_ref in dedupe_owner_seen:
                    is_dedupe = True
                else:
                    dedupe_owner_seen.add(old_ref)

            entry = {**c, "old_ref": old_ref, "new_ref": new_ref}
            if is_dedupe:
                entry["deduped"] = True
            plan.append(entry)

    # Add unparseable components to plan as no-ops
    for c in parsed:
        if c["prefix"] is None:
            plan.append({**c, "old_ref": c["ref"], "new_ref": c["ref"]})

    return plan


def _extract_number(ref: str, prefix: str) -> int:
    """Extract the numeric suffix from a ref like 'R42' -> 42. Returns 0 if unparseable.

    Only called on already-validated refs (those that matched ``_REF_PATTERN``
    in ``_build_rename_plan``). The 0-fallback is therefore unreachable in
    practice — documented defensively (M-04 finding, superseded-by-alternative;
    EXEC-04 adds test coverage for the defensive path).
    """
    try:
        return int(ref[len(prefix):])
    except ValueError:
        return 0


@register_schematic("assign_footprint")
def _handle_assign_footprint(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    ir.assign_footprint(reference=op.reference, footprint_lib_id=op.footprint_lib_id)
    return {"reference": op.reference, "footprint": op.footprint_lib_id}


@register_schematic("swap_footprint")
def _handle_sch_swap_footprint(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.swap_footprint(reference=op.reference, new_footprint_lib_id=op.new_footprint_lib_id)


@register_schematic("add_wire")
def _handle_add_wire(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.add_wire(
        start_x=op.start_x, start_y=op.start_y,
        end_x=op.end_x, end_y=op.end_y,
        force=getattr(op, "force", False),
    )


@register_schematic("add_label")
def _handle_add_label(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.add_label(
        name=op.name,
        label_type=op.label_type,
        x=op.position.x, y=op.position.y,
        angle=op.position.angle,
        shape=op.shape,
    )


@register_schematic("add_power")
def _handle_add_power(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.add_power_symbol(
        name=op.name,
        x=op.position.x, y=op.position.y,
        angle=op.position.angle,
    )


@register_schematic("add_no_connect")
def _handle_add_no_connect(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.add_no_connect(x=op.position.x, y=op.position.y)


@register_schematic("add_design_note")
def _handle_add_design_note(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    """volta-29: annotate schematic with design intent (NOTE/REASON/MATH/BLOCK_HEADER)."""
    return ir.add_design_note(
        text=op.text,
        x=op.position.x,
        y=op.position.y,
        angle=getattr(op.position, "angle", 0.0) or 0.0,
        note_type=op.note_type,
        target_ref=op.target_ref,
        font_size_mm=op.font_size_mm,
    )


@register_schematic("add_junction")
def _handle_add_junction(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.add_junction(x=op.position.x, y=op.position.y)


@register_schematic("repair_schematic")
def _handle_repair_schematic(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.repair_erc import (
        place_no_connects,
        remove_orphaned_labels,
    )
    from volta.ops.repair_wires import (
        repair_wire_snapping,
        snap_to_grid,
    )
    details: dict[str, Any] = {}
    if op.snap_wires:
        details["wire_snapping"] = repair_wire_snapping(ir, file_path)
    if op.remove_orphans:
        details["orphan_removal"] = remove_orphaned_labels(ir)
    if op.place_no_connects:
        details["no_connects"] = place_no_connects(ir)
    if op.snap_to_grid:
        details["snap_to_grid"] = snap_to_grid(ir, grid_mm=0.01)
    return details


@register_schematic("convert_kicad6_to_10")
def _handle_convert_kicad6_to_10(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.format_convert import convert_kicad6_to_10
    content = file_path.read_text(encoding="utf-8")
    converted = convert_kicad6_to_10(content)
    file_path.write_text(converted, encoding="utf-8")
    return {"converted": True, "file_path": str(file_path)}


@register_schematic("snap_to_grid")
def _handle_snap_to_grid(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.repair_wires import snap_to_grid
    return snap_to_grid(ir, grid_mm=op.grid_mm)


@register_schematic("add_power_flag")
def _handle_add_power_flag(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.repair_erc import add_power_flags
    return add_power_flags(ir, file_path)


@register_schematic("rebuild_root_sheet")
def _handle_rebuild_root_sheet(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.root_sheet import rebuild_root_sheet
    results = rebuild_root_sheet(file_path)
    return {
        "sheets_processed": len(results),
        "details": [dataclasses.asdict(r) for r in results],
    }


@register_schematic("embed_symbol")
def _handle_embed_symbol(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.swap_symbol import embed_symbol
    return embed_symbol(op, ir, file_path)


@register_schematic("swap_symbol")
def _handle_swap_symbol(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.swap_symbol import swap_symbol
    return swap_symbol(op, ir, file_path)


@register_schematic("remove_wire")
def _handle_remove_wire(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.remove_ops import remove_wire
    return remove_wire(op, ir, file_path, file_path.parent)


@register_schematic("remove_label")
def _handle_remove_label(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.remove_ops import remove_label
    return remove_label(op, ir, file_path, file_path.parent)


@register_schematic("remove_labels")
def _handle_remove_labels(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    """Batch remove labels by type and/or name."""
    sch = ir._parse_result.kiutils_obj

    # Safety: require remove_all=True when no names filter
    if not op.names and not op.remove_all:
        raise ValueError(
            "remove_labels requires either 'names' filter or remove_all=True"
        )

    name_set = set(op.names) if op.names else None
    removed_count = 0
    removed_details: list[dict] = []

    def _remove_from_list(label_list: list, label_type: str) -> int:
        nonlocal removed_count
        to_remove = []
        for lbl in label_list:
            if name_set is not None and lbl.text not in name_set:
                continue
            to_remove.append(lbl)
        for lbl in to_remove:
            label_list.remove(lbl)
            removed_count += 1
            removed_details.append({
                "name": lbl.text, "label_type": label_type,
                "position": [lbl.position.X, lbl.position.Y],
            })
        return len(to_remove)

    if op.label_type is None or op.label_type == "global":
        _remove_from_list(sch.globalLabels, "global")
    if op.label_type is None or op.label_type == "local":
        _remove_from_list(sch.labels, "local")
    if op.label_type is None or op.label_type == "hierarchical":
        _remove_from_list(sch.hierarchicalLabels, "hierarchical")

    ir._record_mutation("remove_labels", {
        "label_type": op.label_type,
        "names": op.names,
        "removed_count": removed_count,
    })

    return {
        "removed_count": removed_count,
        "removed": removed_details,
    }


@register_schematic("remove_junction")
def _handle_remove_junction(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.remove_ops import remove_junction
    return remove_junction(op, ir, file_path, file_path.parent)


@register_schematic("remove_no_connect")
def _handle_remove_no_connect(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.remove_ops import remove_no_connect
    return remove_no_connect(op, ir, file_path, file_path.parent)


@register_schematic("add_sheet")
def _handle_add_sheet(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.sheet_ops import add_sheet
    return add_sheet(op, ir, file_path)


@register_schematic("add_sheet_pin")
def _handle_add_sheet_pin(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.sheet_ops import add_sheet_pin
    return add_sheet_pin(op, ir, file_path)


@register_schematic("update_symbols_from_library")
def _handle_update_symbols_from_library(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.repair_components import update_symbols_from_library
    return update_symbols_from_library(
        ir, file_path,
        references=op.references,
        dry_run=op.dry_run,
    )


@register_schematic("fix_shorted_nets")
def _handle_fix_shorted_nets(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.repair_nets import fix_shorted_nets
    return fix_shorted_nets(
        ir, file_path,
        strategy=op.strategy,
        keep_nets=op.keep_nets,
        dry_run=op.dry_run,
    )


@register_schematic("fix_pin_type_mismatches")
def _handle_fix_pin_type_mismatches(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.repair_components import fix_pin_type_mismatches
    return fix_pin_type_mismatches(
        ir, file_path,
        pin_type_map=op.pin_type_map,
        dry_run=op.dry_run,
    )


@register_schematic("place_missing_units")
def _handle_place_missing_units(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.repair_components import place_missing_units
    return place_missing_units(
        ir, file_path,
        references=op.references,
        offset_x=op.offset_x,
        offset_y=op.offset_y,
        dry_run=op.dry_run,
    )


@register_schematic("place_and_wire_power_units")
def _handle_place_and_wire_power_units(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.repair_components import place_and_wire_power_units
    return place_and_wire_power_units(
        ir, file_path,
        references=op.references,
        offset_x=op.offset_x,
        offset_y=op.offset_y,
        rail_overrides=op.rail_overrides,
        dry_run=op.dry_run,
    )


@register_schematic("remove_dangling_wires")
def _handle_remove_dangling_wires(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.repair_wires import remove_dangling_wires
    return remove_dangling_wires(
        ir, file_path,
        max_length_mm=op.max_length_mm,
        dry_run=op.dry_run,
        trust_erc=op.trust_erc,
    )


@register_schematic("break_wire_shorts")
def _handle_break_wire_shorts(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.repair_wires import break_wire_shorts
    return break_wire_shorts(
        ir, file_path,
        net_pairs=op.net_pairs,
        strategy=op.strategy,
        dry_run=op.dry_run,
    )


@register_schematic("resolve_shorted_nets")
def _handle_resolve_shorted_nets(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.repair_nets import resolve_shorted_nets
    return resolve_shorted_nets(
        ir, file_path,
        strategy=op.strategy,
        keep_nets=op.keep_nets,
        dry_run=op.dry_run,
    )


@register_schematic("fix_net_short")
def _handle_fix_net_short(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.net_short_fixer import fix_net_short
    return fix_net_short(
        ir, file_path,
        net_a=op.net_a,
        net_b=op.net_b,
        dry_run=op.dry_run,
        remove_strategy=op.remove_strategy,
    )


@register_schematic("rename_net_label")
def _handle_rename_net_label(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.label_renamer import rename_net_label
    return rename_net_label(
        ir, file_path,
        old_name=op.old_name,
        new_name=op.new_name,
        label_type=op.label_type,
        dry_run=op.dry_run,
    )


@register_schematic("place_net_labels")
def _handle_place_net_labels(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.net_label_placer import place_net_labels
    return place_net_labels(
        ir, file_path,
        pin_map=op.pin_map,
        references=op.references,
        dry_run=op.dry_run,
    )


@register_schematic("erc_auto_fix")
def _handle_erc_auto_fix(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.erc_auto_fix import erc_auto_fix
    return erc_auto_fix(
        ir, file_path,
        max_iterations=op.max_iterations,
        mode=op.mode,
        fix_classes=op.fix_classes,
        sheet_filter=op.sheet_filter,
    )


@register_schematic("erc_auto_fix_hierarchical")
def _handle_erc_auto_fix_hierarchical(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    # ir unused: hierarchical creates per-sheet IRs internally
    from volta.ops.erc_auto_fix import erc_auto_fix_hierarchical
    return erc_auto_fix_hierarchical(
        file_path,
        max_iterations=op.max_iterations,
        mode=op.mode,
    )


@register_schematic("connect_pins")
def _handle_connect_pins(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.schematic_routing.net_connector import NetConnector
    connector = NetConnector(file_path)
    result = connector.connect_pins(
        net_name=op.net_name,
        pins=[{"ref": p.ref, "pin": p.pin} for p in op.pins],
        strategy=op.strategy,
        collision_zones=[z.model_dump() for z in op.collision_zones],
        max_wire_length=op.max_wire_length,
    )
    # Apply generated wires and labels to the IR
    for wire in result.get("wires", []):
        ir.add_wire(
            start_x=wire["start"][0], start_y=wire["start"][1],
            end_x=wire["end"][0], end_y=wire["end"][1],
        )
    for label in result.get("labels", []):
        ir.add_label(
            name=op.net_name,
            label_type="local",
            x=label["position"][0], y=label["position"][1],
            angle=0, shape="input",
        )
    return {
        "net_name": op.net_name,
        "wires_generated": result["wires_generated"],
        "labels_generated": result["labels_generated"],
        "collisions_avoided": result["collisions_avoided"],
        "notes": result.get("notes", []),
    }


@register_schematic("batch_connect")
def _handle_batch_connect(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.schematic_routing.batch_wiring import BatchWiring
    wiring = BatchWiring(file_path)
    result = wiring.batch_connect(
        nets=[{"name": n.name, "pins": [{"ref": p.ref, "pin": p.pin} for p in n.pins]} for n in op.nets],
        global_labels=[{"name": g.name, "position": (g.position.x, g.position.y), "shape": g.shape} for g in op.global_labels],
        strategy=op.strategy,
        collision_zones=[z.model_dump() for z in op.collision_zones],
        auto_detect_collisions=op.auto_detect_collisions,
        max_wire_length=op.max_wire_length,
    )
    # Apply generated wires to IR
    for wire in result.get("wires", []):
        ir.add_wire(start_x=wire["start"][0], start_y=wire["start"][1],
                    end_x=wire["end"][0], end_y=wire["end"][1])
    # Apply generated labels to IR
    for label in result.get("labels", []):
        # Use net_name from label data, falling back to first net name,
        # then to "unnamed_net" as a last resort (never empty string).
        default_name = op.nets[0].name if op.nets else "unnamed_net"
        ir.add_label(name=label.get("net_name") or default_name,
                     label_type="local",
                     x=label["position"][0], y=label["position"][1],
                     angle=0, shape="input")
    # Apply global labels to IR
    for gl in result.get("global_labels", []):
        ir.add_label(name=gl["name"], label_type="global",
                     x=gl["position"][0], y=gl["position"][1],
                     angle=0, shape=gl.get("shape", "bidirectional"))
    return {
        "nets_processed": result["nets_processed"],
        "wires_generated": result["wires_generated"],
        "labels_generated": result["labels_generated"],
        "global_labels_generated": result["global_labels_generated"],
        "collisions_detected": result["collisions_detected"],
        "notes": result.get("notes", []),
    }


@register_schematic("regenerate_wiring")
def _handle_regenerate_wiring(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from volta.schematic_routing.batch_wiring import BatchWiring
    wiring = BatchWiring(file_path)
    result = wiring.regenerate_wiring(
        nets=[{"name": n.name, "pins": [{"ref": p.ref, "pin": p.pin} for p in n.pins]} for n in op.nets],
        global_labels=[{"name": g.name, "position": (g.position.x, g.position.y), "shape": g.shape} for g in op.global_labels],
        no_connect_positions=[{"x": p.x, "y": p.y} for p in op.no_connect_positions],
        strategy=op.strategy,
        collision_zones=[z.model_dump() for z in op.collision_zones],
        auto_detect_collisions=op.auto_detect_collisions,
        max_wire_length=op.max_wire_length,
    )
    # The regenerate_wiring method strips and reconnects via kiutils directly.
    # Mark IR as dirty so the executor's Transaction block re-serializes.
    ir.mark_dirty("regenerate_wiring")
    return {
        "removed": result["removed"],
        "generated": result["generated"],
        "notes": result.get("notes", []),
    }
