# Phase 102: Safe Annotate — Non-Destructive Refdes Renumbering - Research

**Researched:** 2026-06-29
**Domain:** KiCad 10 schematic raw S-expression manipulation, hierarchical sheet walking, op handler architecture
**Confidence:** HIGH (all claims verified against codebase with file:line citations; one MEDIUM finding flagged for planner attention)

## Summary

Phase 102 implements `safe_annotate` — a non-destructive reference designator renumbering op that mirrors the proven `safe_sync_pcb_from_schematic` (ae-26) pattern. The critical invariant is zero kiutils re-serialization: every edit must be a surgical raw S-expression replacement of `(property "Reference" "OLD")` value strings, preserving all other bytes. The existing `annotate` op (P0-006) corrupts KiCad 10 files even when reporting "no changes" because it routes through `SchematicIR.annotate_components()` → kiutils `Schematic.to_file()`.

The codebase already contains every primitive needed for this op:
- **Sheet tree walking:** `SchematicGraph.from_hierarchy()` at `src/kicad_agent/schematic_routing/schematic_graph.py:165` recursively walks `(sheet ...)` blocks, resolves absolute paths, and returns a `HierarchicalSchematic` tree `[VERIFIED: schematic_graph.py:165-216]`
- **Property-value replacement (raw):** `_replace_property_value()` at `src/kicad_agent/crossfile/pcb_populate.py:383` performs the exact surgical edit pattern needed — regex-locate `(property "NAME" "OLD")`, paren-balance to block close, replace only the value string `[VERIFIED: pcb_populate.py:383-430]`
- **Paren balance validation:** `validate_paren_balance()` at `src/kicad_agent/ops/handlers/pcb_cleanup.py:135` (returns bool) and `_check_paren_balance()` at `src/kicad_agent/schematic_routing/batch_executor.py:148` (returns int depth) `[VERIFIED: pcb_cleanup.py:135-145, batch_executor.py:148-156]`
- **Atomic writes:** `atomic_write()` at `src/kicad_agent/io/atomic_write.py:15` — fsync + rename, the only sanctioned write path `[VERIFIED: atomic_write.py:15-43]`
- **Multi-file op dispatch:** `execute_cross_file()` + `SELF_SERIALIZING_OPS` at `src/kicad_agent/ops/execution.py:114, 649` — supports ops that write multiple sub-sheet files directly, bypassing single-file IR serialization `[VERIFIED: execution.py:112, 384, 649-728]`

**Primary recommendation:** Register `safe_annotate` as a **self-serializing schematic op** (add to `SELF_SERIALIZING_OPS`) when `scope="whole_project"`, or as a **cross-file op** mirroring `safe_sync_pcb_from_schematic`. The `whole_project` scope requires dynamic sub-sheet discovery (the cross-file `target_files` list is static and cannot encode "walk the sheet tree"). The cleanest path is a **hybrid**: register as schematic op with `SELF_SERIALIZING_OPS` membership so the handler owns all file I/O via `atomic_write`, walks the sheet tree internally via `SchematicGraph.from_hierarchy()`, and applies raw edits per sheet. This avoids the cross-file handler's static `target_files` constraint entirely.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Sheet tree walking (path resolution) | SchematicGraph parser | — | `from_hierarchy()` already owns `(sheet ...)` block parsing and recursive child resolution at schematic_graph.py:165. Reuse, do not rebuild. |
| Component extraction (ref + position + uuid) | Raw S-expr parser | — | Kiutils' `schematicSymbols` is read-safe for in-memory reads but its `properties` mutation path (`_set_component_reference` at schematic_ir.py:150) triggers re-serialization. Extract via raw regex over `_parse_result.raw_content` instead. |
| Rename plan (sort by X, assign sequential refs, dedup) | Op handler logic | — | Pure Python computation; no I/O. Belongs in the handler or a new `safe_annotate.py` helper module. |
| Raw property edit (value replacement) | SchematicRawWriter (extend) | _replace_property_value (reference) | The surgical `(property "Reference" "OLD")` → `"NEW"` edit. Add a new method to SchematicRawWriter following pcb_populate.py:383 pattern. |
| Atomic write per sheet | atomic_write (io module) | — | Only sanctioned write path. fsync + rename. Never `kiutils.Schematic.to_file()`. |
| Paren balance validation | validate_paren_balance | — | Existing helper at pcb_cleanup.py:135. Run before AND after edits. |
| Format preservation verification | Test suite (diff line count) | — | The 5-case test suite IS the validation strategy. No separate runtime check needed beyond paren balance. |
| Netlist completeness check (whole_project) | kicad-cli sch export netlist | — | External CLI; confirms cross-sheet dedup worked. Optional in dry_run. |

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Op name:** `safe_annotate`
- **Inspiration:** Mirrors `safe_sync_pcb_from_schematic` (Phase 144 ae-26) — non-destructive, raw S-expr edits, never kiutils `Schematic.to_file()`
- **CRITICAL INVARIANT:** Zero calls to `kiutils.sch.Schematic.to_file()` or any kiutils writer in the new code path. All edits via `SchematicRawWriter` or direct paren-balanced S-expr manipulation.
- **API Contract:** `{op, target_file, scope: "whole_project"|"current_sheet" (default whole_project), reset: bool (default false), order: "by_x_position"|"by_y_position"|"sheet_order" (default by_x_position), dry_run: bool (default false)}`
- **Response:** `{annotated: [{sheet, uuid, old_ref, new_ref, note?}], stats: {sheets_touched, refs_renamed, duplicates_resolved, placekeepers_filled}, skipped: [], paren_balance_check: "PASS", format_preservation_check: "PASS"}`
- **Algorithm (5 steps LOCKED):** (1) Parse project tree via `(sheet ...)` blocks, (2) Collect components per sheet, (3) Build rename plan sorted by absolute X with per-prefix sequential assignment + cross-project dedup, (4) Apply edits raw via `(property "Reference" "OLD")` replacement — NEVER `Schematic.to_file()`, (5) Validate via `kicad-cli sch erc` per sheet + `kicad-cli sch export netlist` for whole_project
- **Root Sheet Guard (LOCKED):** Refuse with error `"safe_annotate operates per-sheet; root sheet contains hierarchy only — use sub-sheet scope"` if target is a root sheet (mirrors P0-005 `remove_dangling_wires` guard)
- **Test Suite (5 LOCKED cases):** (1) Idempotency, (2) Single rename, (3) Cross-sheet dedup, (4) P0-006 regression, (5) Root sheet guard

### Claude's Discretion
- **File organization:** handler in `ops/handlers/schematic.py` vs `ops/handlers/crossfile.py` vs new module — follow existing `safe_sync` precedent. **Research finding:** neither is a perfect fit; see Architecture Patterns §"The dispatch routing decision" for the recommended hybrid.
- **Registry category:** `"reference"` (matching existing annotate) or `"crossfile"` — **Research recommendation:** `"reference"` since the op semantics are refdes-focused even when scope spans files.
- **Schema location:** new `SafeAnnotateOp` in `_schema_reference.py` (alongside `AnnotateOp`) or `_schema_crossfile.py` — **Research recommendation:** `_schema_reference.py` to keep the forbidden `AnnotateOp` and safe `SafeAnnotateOp` adjacent for documentation clarity.
- **SchematicRawWriter API:** add a new `replace_reference_property(content, uuid, new_ref)` method (the existing API has no property-replacement method — see Code Examples).
- **Test fixtures:** create minimal KiCad 10 .kicad_sch fixtures under `tests/fixtures/` (do NOT depend on analog-ecosystem's hardware/ files).
- **Sort tie-breaking:** when two components share the same X coordinate, break ties by Y then by sheet order.

### Deferred Ideas (OUT OF SCOPE)
- Removing the forbidden `annotate` op entirely (keep as deprecated reference, same as `erc_auto_fix`)
- AI-assisted annotation ordering (grouping by functional block) — `by_x_position` matches KiCad GUI default
- Batch annotation of multiple projects in one call — one `target_file` per call
- Backward-compat alias from `annotate` → `safe_annotate` — users opt in by calling the new op name
</user_constraints>

## Standard Stack

### Core (all already installed — no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| kiutils | 1.4.8 | READ-ONLY parsing of KiCad schematics | Already installed. Used by `parse_schematic()` to produce `ParseResult.kiutils_obj`. Safe for in-memory reads; FORBIDDEN for `.to_file()`. `[VERIFIED: CLAUDE.md tool inventory]` |
| Pydantic | 2.x | Schema for `SafeAnnotateOp` | Already used by all `_schema_*.py` files. Provides `Literal` discriminator + `field_validator`. `[VERIFIED: _schema_reference.py:1-7, _schema_crossfile.py:178-260]` |
| Python stdlib `re` | — | Raw S-expr regex matching | All existing raw-edit helpers use stdlib re (pcb_populate.py, schematic_sync.py, schematic_raw_writer.py). `[VERIFIED: schematic_raw_writer.py:28]` |
| Python stdlib `pathlib` | — | Path resolution for sheet tree | Used by `SchematicGraph.from_hierarchy()` (schematic_graph.py:178, 193). `[VERIFIED]` |

### Supporting (internal modules — primitives to reuse)

| Module | Purpose | When to Use |
|---------|---------|-------------|
| `kicad_agent.schematic_routing.schematic_graph.SchematicGraph` | Hierarchical sheet tree walking | For `scope="whole_project"` — `from_hierarchy(target_file)` returns the full tree |
| `kicad_agent.ops.schematic_raw_writer.SchematicRawWriter` | Raw S-expr schematic manipulation | Extend with new `replace_reference_property()` method |
| `kicad_agent.io.atomic_write.atomic_write` | fsync+rename file writes | The ONLY sanctioned write path — used for every sheet file mutation |
| `kicad_agent.ops.handlers.pcb_cleanup.validate_paren_balance` | Paren balance check (bool) | Pre/post validation gate for each sheet |
| `kicad_agent.crossfile.pcb_populate._replace_property_value` | Reference implementation of property value replacement | Read this to mirror the regex + paren-balance-close pattern in the new SchematicRawWriter method |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| SchematicGraph.from_hierarchy (sheet walking) | Hand-rolled `(sheet ...)` regex walker | SchematicGraph already handles recursion, visited-set cycle protection, max_depth=10, and absolute path resolution. Rebuilding would duplicate tested code. **Use SchematicGraph.** |
| _replace_property_value pattern (pcb_populate.py:383) | kiutils `SchematicSymbol.properties[i].value = new_ref` | The kiutils path is the FORBIDDEN one (triggers `.to_file()` re-serialization). The raw regex + paren-balance pattern is the only safe path. **Use raw pattern.** |
| SELF_SERIALIZING_OPS (schematic handler, self-managed I/O) | CROSS_FILE_OP_TYPES (crossfile handler, static target_files) | Cross-file requires the caller to know all file paths upfront; safe_annotate discovers them dynamically by walking sheets. SELF_SERIALIZING is the correct fit. **Use SELF_SERIALIZING_OPS.** See Architecture Patterns for full rationale. |

## Architecture Patterns

### System Architecture Diagram

```
Caller JSON: {op: "safe_annotate", target_file, scope, reset, order, dry_run}
    │
    ▼
execute_schematic() [execution.py:337]
    │
    ├─ parse_schematic(target_file) → SchematicIR (_parse_result has raw_content)
    │
    ├─ Pre-analysis gate (existing) → may block
    │
    ▼
dispatch_schematic("safe_annotate", ...) [execution.py:417]
    │
    ▼
_handle_safe_annotate(op, ir, file_path) [NEW — handlers/schematic.py]
    │
    ├─ ROOT SHEET GUARD: if file has (sheet ...) blocks AND no own (symbol ...) blocks
    │      → raise ValueError("safe_annotate operates per-sheet; ...")
    │
    ├─ DISCOVER TARGET SHEETS:
    │   ├─ if scope == "current_sheet": sheets = [target_file]
    │   └─ if scope == "whole_project":
    │          tree = SchematicGraph.from_hierarchy(target_file)  # recursive walk
    │          sheets = _flatten_tree_to_paths(tree)  # [root_path, *child_paths]
    │
    ├─ PER-SHEET PARSE + COLLECT (READ-ONLY kiutils OK here):
    │   for sheet_path in sheets:
    │     raw = Path(sheet_path).read_text()
    │     components = _extract_symbols_with_refs(raw)  # [{uuid, ref, x, y, prop_offset}]
    │     # uses regex: \(symbol\b ... \(property "Reference" "([^"]*)" ...\)
    │
    ├─ BUILD RENAME PLAN (pure Python):
    │   ├─ if reset: strip all refs to "<prefix>?" before renumber
    │   ├─ sort by (x, y, sheet_order) per order= option
    │   ├─ group by prefix (R, C, U, ...)
    │   └─ assign sequential numbers per prefix, skip existing when !reset
    │
    ├─ APPLY EDITS RAW (per sheet, in memory):
    │   for sheet_path, sheet_raw in sheet_contents.items():
    │     for rename in plan.for_sheet(sheet_path):
    │       sheet_raw = SchematicRawWriter.replace_reference_property(
    │           sheet_raw, rename.uuid, rename.new_ref)
    │     # CRITICAL: paren balance check before write
    │     if not validate_paren_balance(sheet_raw):
    │       raise RuntimeError(f"Paren imbalance after edit on {sheet_path}")
    │     new_contents[sheet_path] = sheet_raw
    │
    ├─ DRY RUN SHORT-CIRCUIT:
    │   if op.dry_run:
    │     return {annotated: plan_as_list, dry_run: True, ...}
    │
    ├─ FORMAT PRESERVATION CHECK (pre-write):
    │   for each sheet: assert only `(property "Reference" ...)` lines changed
    │   (diff line count ≈ refs renamed on that sheet, not ≈ file size)
    │
    ├─ WRITE (atomic_write per sheet):
    │   for sheet_path, new_raw in new_contents.items():
    │     if new_raw != original_raw[sheet_path]:
    │       atomic_write(Path(sheet_path), new_raw)
    │
    └─ RETURN:
        {annotated: [...], stats: {...}, paren_balance_check: "PASS",
         format_preservation_check: "PASS"}
            │
            ▼
execute_schematic() resumes [execution.py:382]
    │
    ├─ if root.op_type in SELF_SERIALIZING_OPS:  ← safe_annotate MUST be in this set
    │      SKIP serialize_schematic()  (handler already wrote files via atomic_write)
    │
    └─ Transaction.commit()
```

**Key flow property:** The handler owns ALL file I/O when `scope="whole_project"` (writes multiple sub-sheet files). The executor's default `serialize_schematic()` path is bypassed via `SELF_SERIALIZING_OPS` membership — the same mechanism `erc_auto_fix_hierarchical` uses (execution.py:114).

### The dispatch routing decision (CRITICAL — planner must resolve)

The CONTEXT.md flags this as Claude's discretion. Research reveals a concrete constraint that determines the answer:

**Problem:** The cross-file handler dispatch (`execute_cross_file` at execution.py:649) requires `op.target_files` to be a static list resolved BEFORE the handler runs (execution.py:644-645). But `safe_annotate` with `scope="whole_project"` must **discover** sub-sheets dynamically by walking `(sheet ...)` blocks — the caller cannot know all paths upfront without duplicating the sheet-tree walk.

**Three options:**

| Option | Mechanism | Pros | Cons | Recommendation |
|--------|-----------|------|------|----------------|
| A. Schematic handler + SELF_SERIALIZING_OPS | Add `"safe_annotate"` to `SELF_SERIALIZING_OPS` (execution.py:114); handler in `handlers/schematic.py`; handler walks tree internally and writes via `atomic_write` | Mirrors `erc_auto_fix_hierarchical` precedent; single target_file in schema; handler owns multi-file I/O cleanly | Bypasses Transaction's single-file scope (but `erc_auto_fix_hierarchical` already does this) | **RECOMMENDED** |
| B. Cross-file handler with static target_files | Mirror `safe_sync_pcb_from_schematic` exactly; require caller to list all sheets in `target_files` | Consistent with ae-26 pattern; uses AtomicOperation for multi-file | Caller must pre-walk sheets (leaks abstraction); doesn't match the API contract in CONTEXT.md which takes a single root | Rejected — violates API |
| C. Cross-file handler with dynamic discovery | Add to CROSS_FILE_OP_TYPES; handler ignores `target_files[1:]` and walks tree itself | Uses AtomicOperation's multi-file rollback | Hacky — `target_files` becomes a lie; pre-flight gate runs on incomplete file set | Rejected — inconsistent |

**Recommendation: Option A.** Add `safe_annotate` to `SELF_SERIALIZING_OPS`. The handler receives `(op, ir, file_path)` where `file_path` is the root; it walks the tree itself via `SchematicGraph.from_hierarchy(file_path)`, applies raw edits in memory, and writes each changed sheet via `atomic_write`. The executor's `serialize_schematic()` is skipped (SELF_SERIALIZING), so no kiutils re-serialization occurs on ANY sheet.

**For `scope="current_sheet"`:** same handler, just operates on `file_path` alone (no tree walk).

### Recommended Project Structure

```
src/kicad_agent/
├── ops/
│   ├── handlers/
│   │   └── schematic.py            # ADD: _handle_safe_annotate (registered via @register_schematic)
│   ├── schematic_raw_writer.py     # EXTEND: add replace_reference_property() static method
│   ├── _schema_reference.py        # ADD: SafeAnnotateOp (alongside AnnotateOp at line 52)
│   ├── execution.py                # MODIFY: add "safe_annotate" to SELF_SERIALIZING_OPS (line 114)
│   └── registry.py                 # ADD: "safe_annotate" entry (near "annotate" at line 147)
└── (optional) safe_annotate.py     # NEW: pure-logic rename plan builder (if handler grows >200 lines)

tests/
├── test_safe_annotate.py           # NEW: 5-case validation suite + supporting unit tests
└── fixtures/
    └── safe_annotate/              # NEW: minimal KiCad 10 fixtures
        ├── single_sheet_unannotated.kicad_sch     # Test 1, 2 (idempotency, single rename)
        ├── multi_sheet_root.kicad_sch             # Test 3, 4 (hierarchy root with (sheet ...) blocks)
        ├── multi_sheet_child_a.kicad_sch          # (referenced by root)
        └── multi_sheet_child_b.kicad_sch          # (referenced by root, has duplicate R1)
```

### Pattern 1: Raw Property Value Replacement (the core edit)

**What:** Surgically replace the value string inside a `(property "Reference" "OLD" ...)` block, preserving every other byte (whitespace, indentation, UUID, effects block, etc.).

**When to use:** Every refdes rename in the rename plan.

**Source:** Mirrors `_replace_property_value()` at `src/kicad_agent/crossfile/pcb_populate.py:383-430`. Adapted for schematic context (target by UUID, not just first match).

```python
# Source: pcb_populate.py:383-430 (adapted for schematic symbol targeting)
import re

def replace_reference_property(content: str, symbol_uuid: str, new_ref: str) -> str:
    """Replace the Reference property value on a specific symbol by UUID.

    Locates the (symbol ... (uuid "SYMBOL_UUID") ...) block, then within it
    finds (property "Reference" "OLD_VAL" ...) and replaces OLD_VAL with new_ref.

    Returns content unchanged if the symbol UUID or Reference property is not found.
    Raises ValueError on malformed input (unbalanced parens).
    """
    # Step 1: Find the (symbol ...) block containing the target UUID.
    # KiCad 10 symbols look like: (symbol (lib_id "...") (at X Y A) ... (uuid "...") ...)
    # Strategy: scan each top-level (symbol block, check if it contains the UUID.
    safe_uuid = re.escape(symbol_uuid)
    uuid_pattern = re.compile(rf'\(uuid\s+"{safe_uuid}"')

    symbol_starts = [m.start() for m in re.finditer(r'\(symbol\b', content)]
    target_block_start = None
    target_block_end = None

    for start in symbol_starts:
        # Find matching close paren via depth tracking
        depth = 0
        i = start
        while i < len(content):
            if content[i] == '(':
                depth += 1
            elif content[i] == ')':
                depth -= 1
                if depth == 0:
                    block_end = i + 1
                    break
            i += 1
        else:
            continue  # malformed — skip

        block = content[start:block_end]
        if uuid_pattern.search(block):
            target_block_start = start
            target_block_end = block_end
            break

    if target_block_start is None:
        return content  # symbol not found — no-op

    # Step 2: Within the block, replace (property "Reference" "OLD") value.
    # Match exactly: (property "Reference" "OLD_VAL"
    # Replace with:   (property "Reference" "NEW_VAL"
    # Preserve everything after the value (at, effects, closing parens).
    safe_new = new_ref.replace('"', '\\"')  # escape any embedded quotes
    prop_pattern = re.compile(
        r'(\(property\s+"Reference"\s+)"[^"]*"',
    )

    block = content[target_block_start:target_block_end]
    new_block, n = prop_pattern.subn(rf'\1"{safe_new}"', block, count=1)

    if n == 0:
        return content  # no Reference property — no-op

    return content[:target_block_start] + new_block + content[target_block_end:]
```

**Verification step (mandatory after every edit):**
```python
# Source: pcb_cleanup.py:135-145
def validate_paren_balance(text: str) -> bool:
    depth = 0
    for ch in text:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth < 0:
                return False
    return depth == 0

# Usage in handler:
if not validate_paren_balance(new_raw):
    raise RuntimeError(f"Paren imbalance after refdes edit on {sheet_path}")
```

### Pattern 2: Hierarchical Sheet Tree Walking (for whole_project scope)

**What:** Resolve all sub-sheet absolute paths from a root schematic by walking `(sheet ...)` blocks recursively.

**When to use:** When `scope="whole_project"`.

**Source:** `SchematicGraph.from_hierarchy()` at `src/kicad_agent/schematic_routing/schematic_graph.py:165-216` — already handles recursion, cycle detection (visited set), and max_depth=10.

```python
# Source: schematic_graph.py:165-216 (usage pattern)
from kicad_agent.schematic_routing.schematic_graph import SchematicGraph

def discover_all_sheets(root_sch: Path) -> list[Path]:
    """Walk (sheet ...) blocks from root, return all sheet paths (root + children)."""
    tree = SchematicGraph.from_hierarchy(str(root_sch))
    paths = [Path(tree.filepath)]
    _collect_children(tree, paths)
    return paths

def _collect_children(node, paths: list[Path]) -> None:
    for child in node.children:
        paths.append(Path(child.filepath))
        _collect_children(child, paths)
```

**Why reuse this:** It already handles the `(property "Sheetfile" "...")` extraction (schematic_graph.py:746-750), absolute path resolution via `root_dir / ref.filepath` (line 193), and cycle protection via the `_visited` set (lines 179-201). Rebuilding would duplicate tested code.

**Sheet block format reference** `[VERIFIED: schematic_graph.py:707-776]`:
```
(sheet
  (at X Y)
  (size W H)
  (uuid "SHEET-UUID")
  (property "Sheetname" "Human Name" ...)
  (property "Sheetfile" "child-file.kicad_sch" ...)  ← this is the path
  (pin "PIN_NAME" direction (at X Y ANGLE) ...)
  ...
)
```

### Pattern 3: Component Extraction (per sheet)

**What:** Extract `(uuid, current_ref, x, y)` tuples from a sheet's raw content for the rename plan.

**When to use:** After discovering sheets, before building the rename plan.

**Source:** Combines `_parse_symbol_refs` regex (schematic_graph.py:590-594) with UUID extraction.

```python
# Source: regex adapted from schematic_graph.py:517 (symbol+at) and 590 (lib_id)
import re

_SYMBOL_WITH_AT = re.compile(
    r'\(symbol\s+\(lib_id\s+"[^"]*"\)\s+\(at\s+([\d.]+)\s+([\d.]+)\s+([\d.-]+)\)',
)
_REF_PATTERN = re.compile(r'^([#A-Za-z]+)(\d+|\?)$')  # schematic_ir.py:28

def extract_symbols(raw: str) -> list[dict]:
    """Extract per-symbol metadata from a sheet's raw S-expression.

    Returns list of {uuid, ref, x, y, block_start, block_end} dicts.
    """
    symbols = []
    for m in re.finditer(r'\(symbol\b', raw):
        start = m.start()
        # Find matching close paren
        depth = 0
        i = start
        while i < len(raw):
            if raw[i] == '(':
                depth += 1
            elif raw[i] == ')':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
            i += 1
        else:
            continue

        block = raw[start:end]

        # Extract UUID
        uuid_m = re.search(r'\(uuid\s+"([^"]+)"', block)
        if not uuid_m:
            continue  # not a component symbol (might be lib_symbol graphic)
        symbol_uuid = uuid_m.group(1)

        # Extract Reference property value
        ref_m = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
        ref = ref_m.group(1) if ref_m else ""

        # Extract position — must have (at X Y) to be a placed symbol
        at_m = re.search(r'\(at\s+([\d.-]+)\s+([\d.-]+)', block)
        if not at_m:
            continue
        x, y = float(at_m.group(1)), float(at_m.group(2))

        symbols.append({
            "uuid": symbol_uuid,
            "ref": ref,
            "x": x,
            "y": y,
            "block_start": start,
            "block_end": end,
        })

    return symbols
```

**Important filter:** KiCad schematics have TWO uses of `(symbol ...)`:
1. **lib_symbol definitions** inside `(lib_symbols ...)` — these have `(symbol "Device:R" ...)` form (quoted name after `symbol`)
2. **Placed component instances** at the body level — these have `(symbol (lib_id "...") (at X Y) ...)` form

The extraction above filters correctly because placed instances have `(lib_id ...)` and `(at X Y)` as immediate children, while lib_symbol definitions have a quoted string as the first child. The `at_m` check also filters out lib_symbols (which have no `(at ...)` at the top of their block). `[VERIFIED: tests/fixtures/schematic_intent/complete_led.kicad_sch:8, 80 — both forms present]`

### Pattern 4: Root Sheet Guard

**What:** Detect if a sheet is a "root" (hierarchy container only, no own components).

**When to use:** At handler entry, before any work.

**Logic:** A sheet is a root if it contains `(sheet ...)` blocks (has children) AND has zero placed component symbols of its own. The CONTEXT.md error message is `"safe_annotate operates per-sheet; root sheet contains hierarchy only — use sub-sheet scope"`.

```python
def is_root_sheet(raw: str) -> bool:
    """A root sheet has (sheet ...) blocks (children) but no placed components."""
    has_sheet_blocks = bool(re.search(r'\(sheet\s', raw))
    # Placed components have (symbol (lib_id ...) (at ...)) — NOT (symbol "Name" ...)
    has_placed_components = bool(
        re.search(r'\(symbol\s+\(lib_id\s+"[^"]*"\)\s+\(at\s', raw)
    )
    return has_sheet_blocks and not has_placed_components
```

### Anti-Patterns to Avoid

- **Anti-pattern 1: Calling `SchematicIR.annotate_components()` or `_set_component_reference()`** — both mutate `kiutils_obj.properties` in memory, which the executor's default `serialize_schematic()` path then writes via `Schematic.to_file()`, corrupting the file (P0-006 root cause). `[VERIFIED: schematic_ir.py:150-160, 222-289; execution.py:384-385]`
- **Anti-pattern 2: Using `kiutils.Schematic.to_file()` for "convenience"** — even with no changes, this re-serializes and produces the 1183 ins / 1131 del diff documented in P0-006. The SELF_SERIALIZING_OPS bypass exists specifically to prevent this.
- **Anti-pattern 3: Modifying shared `target_files` lists in cross-file dispatch** — the cross-file handler expects static paths; dynamically discovering sheets inside a cross-file handler breaks the AtomicOperation's pre-flight gate. Use SELF_SERIALIZING + schematic handler instead.
- **Anti-pattern 4: Line-based replacement without UUID targeting** — two symbols may share `R1` (the dedup case). Replacing "the first R1" is ambiguous. ALWAYS target by UUID, then replace within that UUID's block.
- **Anti-pattern 5: Walking `(sheet ...)` blocks with a naive regex** — sheets can be nested arbitrarily deep and the regex won't handle recursive nesting. Use `SchematicGraph.from_hierarchy()` which uses `_extract_sexp_block` with proper depth tracking (schematic_graph.py:681-704).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Sheet tree walking | Hand-rolled `(sheet ...)` regex with manual recursion + cycle detection | `SchematicGraph.from_hierarchy()` (schematic_graph.py:165) | Already handles recursion, visited-set cycle protection, max_depth=10, absolute path resolution. 50+ lines of tested code. |
| Property value replacement | String `.replace('"OLD"', '"NEW"')` or regex without paren-balance | New `SchematicRawWriter.replace_reference_property()` method mirroring `_replace_property_value()` (pcb_populate.py:383) | The pcb_populate helper is the proven pattern; line-based replacement risks matching the wrong property (e.g., a "Reference" mention in aDatasheet URL). |
| Paren balance validation | Custom depth counter | `validate_paren_balance()` (pcb_cleanup.py:135) | Already exists, already tested, already used by 3 other ops. |
| Atomic file writes | `open(path, 'w').write(content)` | `atomic_write()` (atomic_write.py:15) | The only sanctioned write path; fsync + rename + cleanup on failure. Required for crash safety. |
| Reference designator parsing (prefix + suffix split) | Custom `str.split` or manual char iteration | `_REF_PATTERN = re.compile(r"^([#A-Za-z]+)(\d+|\?)$")` (schematic_ir.py:28) | Already handles `R?`, `R1`, `#PWR?`, `#PWR01`. Verified against 8 test cases. `[VERIFIED: this research session — see Runtime Verification below]` |
| Multi-file op dispatch (when scope=whole_project) | Cross-file handler with faked target_files list | `SELF_SERIALIZING_OPS` membership + schematic handler | The SELF_SERIALIZING mechanism exists for exactly this case (ops that write multiple files themselves). Used by `erc_auto_fix_hierarchical`. |

**Key insight:** Every primitive needed for `safe_annotate` already exists in the codebase. The implementation work is assembly + a new `SchematicRawWriter.replace_reference_property()` method + the rename-plan logic. No new parsing infrastructure, no new write infrastructure, no new validation infrastructure.

## Runtime State Inventory

This phase creates a new op — it does not rename or refactor existing runtime state. However, two runtime-state concerns deserve explicit answers:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — the op reads/writes .kicad_sch files only, no DB/cache state | None |
| Live service config | None — kicad-agent has no long-running services that cache annotation state | None |
| OS-registered state | None | None |
| Secrets/env vars | None | None |
| Build artifacts | `src/kicad_agent/training/__pycache__/` — stale .pyc files present in git status (untracked, harmless) | None — Python auto-regenerates |

**Nothing found in any category.** This is a pure code-addition phase. `[VERIFIED: git status review]`

## Common Pitfalls

### Pitfall 1: Forgetting SELF_SERIALIZING_OPS membership → executor re-serializes anyway
**What goes wrong:** You write the handler correctly with raw edits + atomic_write, but the executor still calls `serialize_schematic()` afterward (execution.py:384-385), re-serializing via kiutils and producing the exact P0-006 corruption you were trying to avoid.
**Why it happens:** The default schematic dispatch path always serializes unless the op is in `SELF_SERIALIZING_OPS`.
**How to avoid:** Add `"safe_annotate"` to `SELF_SERIALIZING_OPS` at `execution.py:114` in the same commit as the handler. Test with an AST-based grep that proves `to_file` is never called (mirror `test_handler_does_not_use_kiutils_to_file` at test_safe_sync_pcb_from_schematic.py:74-88).
**Warning signs:** Test 4 (P0-006 regression) produces a diff line count ≈ file size instead of ≈ refs renamed.

### Pitfall 2: Replacing the wrong `(property "Reference" ...)` when duplicates exist
**What goes wrong:** In the cross-sheet dedup case, two symbols both have `(property "Reference" "R1")`. A naive regex `.sub` replaces the FIRST one in document order — which may not be the one the rename plan targeted.
**Why it happens:** Reference property values are not unique within a sheet when duplicates exist (that's the bug being fixed).
**How to avoid:** ALWAYS locate the symbol block by UUID first (via `(uuid "TARGET_UUID")` containment check), THEN replace the Reference property within that block only. See Pattern 1 in Architecture Patterns.
**Warning signs:** Test 3 (cross-sheet dedup) renames the wrong R1; netlist still collapses.

### Pitfall 3: Matching lib_symbol definitions instead of placed instances
**What goes wrong:** KiCad schematics have `(symbol "Device:R" ...)` blocks inside `(lib_symbols ...)` (the library definitions) AND `(symbol (lib_id "Device:R") ...)` blocks at the body level (placed instances). Both contain `(property "Reference" "...")`. Editing a lib_symbol Reference (e.g., "R" → "R1") corrupts the library.
**Why it happens:** A regex `\(property\s+"Reference"` matches both contexts.
**How to avoid:** Filter to symbols that have `(lib_id ...)` AND `(at X Y)` as immediate children — only placed instances have these. lib_symbol definitions have a quoted string as the first child. See extraction filter in Pattern 3.
**Warning signs:** Edit count is higher than expected (lib_symbols also matched); file fails to load in KiCad GUI.

### Pitfall 4: Hierarchical coordinate accumulation (KiCad 10)
**What goes wrong:** When a sub-sheet is instantiated via `(sheet (at X Y) ...)`, KiCad 10 may use the sheet's position as an offset for all components inside it. Sorting by raw `(at X Y)` from the child sheet file without accounting for the parent sheet instance's position produces wrong sort order.
**Why it happens:** KiCad's hierarchical position semantics are not documented in the file format spec; the `by_x_position` sort assumes absolute coordinates.
**How to avoid:** For Phase 102 v1, sort by the component's raw `(at X Y)` within its own sheet, then break ties by sheet order (the order sheets appear in the root). This matches KiCad GUI's "by X position" default behavior for non-hierarchical designs. Document this as a known limitation for deeply nested hierarchies; defer true absolute-coordinate resolution to a follow-up if Phase 145 testing reveals it's needed.
**Warning signs:** Components in child sheets sort before root components unexpectedly; Phase 145 GNDA test still fails.

### Pitfall 5: Power symbols (#PWR) treated as regular components
**What goes wrong:** KiCad power symbols have refs like `#PWR?` and `#PWR01`. They should NOT be renumbered by `safe_annotate` (KiCad manages them separately).
**Why it happens:** `_REF_PATTERN` matches `#PWR?` and `#PWR01` (prefix `#PWR`, suffix `?` or `01`).
**How to avoid:** Skip any symbol whose Reference prefix starts with `#` (the power-symbol marker). Add this filter to the component extraction step.
**Warning signs:** Rename plan includes `#PWR?` → `#PWR1` entries; KiCad GUI shows duplicate power flags.

## Code Examples

### Example 1: KiCad 10 schematic symbol with Reference property (the edit target)

From `tests/fixtures/schematic_intent/complete_led.kicad_sch:80-99` `[VERIFIED: this research session]`:
```
  (symbol (lib_id "Device:R") (at 50 50 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no) (fields_autoplaced yes)
    (uuid "abc12345-...")
    (property "Reference" "R1" (at 52.032 50 0)
      (effects (font (size 1.27 1.27)) (justify left))
    )
    (property "Value" "330R" (at 50 50 0)
      (effects (font (size 1.27 1.27)) (justify left))
    )
    ...
  )
```

**Edit target:** Replace `"R1"` (the second quoted string after `"Reference"`) with the new ref. Preserve the `(at 52.032 50 0)`, the `(effects ...)`, the `(justify left)`, and all whitespace/newlines EXACTLY.

**The raw edit (regex):**
```
Before: (property "Reference" "R1" (at 52.032 50 0)
After:  (property "Reference" "R42" (at 52.032 50 0)
```
Only the value string changes. Everything else byte-identical.

### Example 2: Reference designator prefix/suffix parsing

`_REF_PATTERN` at `schematic_ir.py:28` `[VERIFIED: this research session via Python test]`:
```python
_REF_PATTERN = re.compile(r"^([#A-Za-z]+)(\d+|\?)$")

# Matches:
# 'R?'    → ('R', '?')
# 'R1'    → ('R', '1')
# 'R42'   → ('R', '42')
# 'C?'    → ('C', '?')
# 'U1'    → ('U', '1')
# '#PWR?' → ('#PWR', '?')
# '#PWR01'→ ('#PWR', '01')

# Does NOT match:
# 'GNDA'  → None  (no numeric suffix — not a ref, it's a net name)
# 'R'     → None  (bare prefix, no suffix)
# '1N4148'→ None  (starts with digit — not a ref)
```

**Use this to:** (a) group components by prefix for sequential numbering, (b) detect `?` suffix (needs annotation), (c) detect `#` prefix (power symbol — skip).

### Example 3: Atomic write per sheet

```python
# Source: atomic_write.py:15-43 (the only sanctioned write path)
from kicad_agent.io.atomic_write import atomic_write
from pathlib import Path

# In the handler, after building new_contents dict:
for sheet_path, new_raw in new_contents.items():
    original = original_contents[sheet_path]
    if new_raw != original:  # skip no-op writes
        atomic_write(Path(sheet_path), new_raw)
```

**Critical:** The `if new_raw != original` guard is the idempotency check for Test 1. If the file is unchanged, do NOT write — this is what makes the op idempotent on clean schematics.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `annotate` op via `SchematicIR.annotate_components()` | FORBIDDEN (P0-006) — corrupts KiCad 10 files | Phase 133 (2026-06-27) | The op exists in registry but must never be called on production schematics |
| `erc_auto_fix` via kiutils re-serialization | FORBIDDEN (P0-003) — deprecated, emits DeprecationWarning | Phase 123 (2026-06-24) | Same root cause class; precedent for deprecation path |
| `Schematic.to_file()` (kiutils writer) | NEVER on root sheets; raw S-expr manipulation only | Project memory `kiutils-root-sheet-danger.md` | All new schematic-mutating ops must use SchematicRawWriter + atomic_write |
| `safe_sync_pcb_from_schematic` (ae-26) | PROVEN — non-destructive PCB sync via raw edits | Phase 144 | The template `safe_annotate` mirrors |

**Deprecated/outdated:**
- `annotate` op (`handlers/schematic.py:153-156`) — emit DeprecationWarning pointing to `safe_annotate` (matches `erc_auto_fix` deprecation at `ops/erc_auto_fix.py:256`) `[VERIFIED: erc_auto_fix.py:256 — "erc_auto_fix is DEPRECATED (P0-003)"]`

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `SELF_SERIALIZING_OPS` is the correct dispatch mechanism for whole_project scope (vs. cross-file handler) | Architecture Patterns §"The dispatch routing decision" | If wrong, op must be re-registered as cross-file with a different target_files contract; would require API change. Mitigation: planner confirms with code owner before implementation. |
| A2 | KiCad 10 child sheet component positions are file-local (not offset by parent sheet instance position) | Common Pitfalls §Pitfall 4 | If wrong, `by_x_position` sort produces wrong order for nested hierarchies. Mitigation: Test 4 (Phase 145 regression) would catch this; defer to follow-up if needed. |
| A3 | Power symbols (`#PWR?`, `#PWR01`) should be skipped by safe_annotate | Common Pitfalls §Pitfall 5 | If wrong, safe_annotate would renumber power flags, breaking KiCad's power-net inference. Low risk — KiCad GUI annotate also skips these. |

## Open Questions

1. **Should the `annotate` op emit a DeprecationWarning pointing to `safe_annotate`?**
   - What we know: CONTEXT.md says "Optionally emit DeprecationWarning from `annotate` pointing to `safe_annotate` (matches how `erc_auto_fix` was deprecated per P0-003)."
   - What's unclear: Is this in-scope for Phase 102 or a follow-up?
   - Recommendation: Include it — it's a 2-line change (add `warnings.warn(...)` at top of `_handle_annotate` at `handlers/schematic.py:154`) and completes the deprecation loop. The planner should add it as a low-priority task.

2. **Registry category: `"reference"` or `"crossfile"`?**
   - What we know: CONTEXT.md gives Claude discretion. The op spans multiple files when `scope="whole_project"` but its semantics are refdes-focused.
   - Recommendation: `"reference"` — the category describes the op's purpose (managing reference designators), not its file scope. The existing `annotate` is also `"reference"`. Cross-file is reserved for ops that inherently require both .kicad_sch AND .kicad_pcb (like `safe_sync_pcb_from_schematic`).

3. **Should `kicad-cli sch export netlist` run as part of the op, or only in tests?**
   - What we know: CONTEXT.md algorithm step 5 says "Run `kicad-cli sch export netlist` to confirm netlist completeness" for whole_project scope.
   - What's unclear: Is this a runtime validation (op fails if netlist incomplete) or a test-only check?
   - Recommendation: Test-only. The op's job is to apply renames correctly; netlist export is a downstream verification. Running it in the op adds kicad-cli as a hard runtime dependency for every call. Tests 3 and 4 verify netlist completeness as acceptance criteria.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| kicad-cli | Test validation (Test 3, 4 — `sch erc`, `sch export netlist`) | ✓ | 10.0.1 | — (tests skip if missing) |
| kiutils | READ-ONLY parsing (already used everywhere) | ✓ | 1.4.8 | — |
| Python 3.11 | Runtime | ✓ | 3.11.11 | — |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None.

`[VERIFIED: CLAUDE.md tool inventory — kicad-cli 10.0.1, Python 3.11.11]`

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (already configured for the project) |
| Config file | `pytest.ini` / `pyproject.toml` (existing) |
| Quick run command | `python3 -m pytest tests/test_safe_annotate.py -x -v` |
| Full suite command | `python3 -m pytest tests/test_safe_annotate.py -v` |

### Phase Requirements → Test Map

The phase has no REQUIREMENTS.md IDs (feature-driven from FEATURE-008). The 5 LOCKED test cases from CONTEXT.md serve as the requirements.

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TC-1 (Idempotency) | Clean schematic + dry_run:true → annotated:[], file byte-identical | unit + fixture | `pytest tests/test_safe_annotate.py::test_idempotency_clean_schematic -x` | ❌ Wave 0 |
| TC-2 (Single rename) | Schematic with R? + scope:current_sheet → R?→R1, one line changes | unit + fixture | `pytest tests/test_safe_annotate.py::test_single_rename_current_sheet -x` | ❌ Wave 0 |
| TC-3 (Cross-sheet dedup) | 2 sheets each with R1 + scope:whole_project, reset:true → one renamed, paren balance preserved, netlist no longer collapses | integration + fixture + kicad-cli | `pytest tests/test_safe_annotate.py::test_cross_sheet_dedup_whole_project -x` | ❌ Wave 0 |
| TC-4 (P0-006 regression) | Multi-sheet baseline + scope:whole_project, reset:true → targeted property lines only changed (diff line count ≈ refs renamed) | integration + fixture + diff assertion | `pytest tests/test_safe_annotate.py::test_p0_006_regression_no_reserialization -x` | ❌ Wave 0 |
| TC-5 (Root sheet guard) | Root sheet as target → op refuses with documented error | unit + fixture | `pytest tests/test_safe_annotate.py::test_root_sheet_guard_refuses -x` | ❌ Wave 0 |
| TC-6 (kiutils avoidance) | AST grep: handler source has no `to_file` Call nodes | unit (AST) | `pytest tests/test_safe_annotate.py::test_handler_does_not_use_kiutils_to_file -x` | ❌ Wave 0 |
| TC-7 (paren balance check) | After every edit, validate_paren_balance passes | unit | `pytest tests/test_safe_annotate.py::test_paren_balance_preserved -x` | ❌ Wave 0 |
| TC-8 (registration) | Op in SELF_SERIALIZING_OPS, registry, schema validates | unit | `pytest tests/test_safe_annotate.py::test_safe_annotate_registered -x` | ❌ Wave 0 |

### Supporting Tests (not in LOCKED 5 but recommended)

| Test | Purpose |
|------|---------|
| `test_replace_reference_property_raw` | Unit test the new SchematicRawWriter method directly — verifies byte-preserving edit |
| `test_replace_reference_property_uuid_targeting` | Two symbols with same ref — only the UUID-targeted one changes |
| `test_skip_power_symbols` | `#PWR?` symbols are not renamed |
| `test_reset_strips_to_placeholder` | reset:true strips `R42` → `R?` before renumber |
| `test_sort_by_x_position` | Components sorted by X coord, ties broken by Y then sheet order |

### Sampling Rate

- **Per task commit:** `python3 -m pytest tests/test_safe_annotate.py -x -v` (fast — no kicad-cli on most tests)
- **Per wave merge:** `python3 -m pytest tests/test_safe_annotate.py -v` + `python3 -m pytest tests/test_safe_sync_pcb_from_schematic.py -v` (regression — ensure no shared-code breakage)
- **Phase gate:** Full suite green before `/gsd-verify-work`. TC-3 and TC-4 require kicad-cli; skip with clear marker if unavailable, but DO run before marking phase complete.

### Wave 0 Gaps

- [ ] `tests/test_safe_annotate.py` — the 8-test file (5 LOCKED + 3 supporting)
- [ ] `tests/fixtures/safe_annotate/single_sheet_unannotated.kicad_sch` — minimal KiCad 10 schematic with one `R?` symbol (for TC-1, TC-2)
- [ ] `tests/fixtures/safe_annotate/multi_sheet_root.kicad_sch` — root sheet with 2 `(sheet ...)` blocks pointing to child_a and child_b (for TC-3, TC-4, TC-5)
- [ ] `tests/fixtures/safe_annotate/multi_sheet_child_a.kicad_sch` — child sheet with `R1` (the duplicate)
- [ ] `tests/fixtures/safe_annotate/multi_sheet_child_b.kicad_sch` — child sheet with `R1` (the duplicate, second instance)
- [ ] No pytest config changes needed — existing `tests/` conftest patterns apply

**Fixture creation guidance:** Use `tests/fixtures/schematic_intent/complete_led.kicad_sch` as the format template — it's a valid KiCad 10 schematic with proper `(symbol (lib_id ...) (at ...) ... (property "Reference" "R1") ...)` structure. Copy and strip down to minimal cases. For multi-sheet, model the `(sheet ...)` block structure on the format documented at `schematic_graph.py:707-776`.

*(No framework install needed — pytest already configured.)*

## Security Domain

This phase adds a file-mutating op. Security considerations:

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Op has no auth surface (local CLI tool) |
| V3 Session Management | no | Op has no session concept |
| V4 Access Control | yes | Path confinement via existing executor (execution.py:664-678 — `fp.resolve().is_relative_to(base_resolved)`). Safe_annotate inherits this when registered as a schematic op. |
| V5 Input Validation | yes | Pydantic schema validates `target_file` (TargetFile type), `scope` (Literal), `reset`/`dry_run` (bool), `order` (Literal). Regex-escape all user-provided strings used in regex (UUID, ref values). |
| V6 Cryptography | no | No crypto operations |
| V7 Error Handling | yes | Raise on paren imbalance (fail-closed). Return no-op on UUID-not-found (don't silently corrupt). |
| V8 Data Protection | yes | atomic_write prevents partial writes on crash. No secrets in schematics. |

### Known Threat Patterns for file-mutating ops

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via malicious `target_file` | Tampering | Pydantic TargetFile type + executor path confinement (execution.py:664-678). Inherited. |
| Malicious .kicad_sch with crafted `(property "Reference" "...")` to inject regex | Tampering | All user-content strings (UUIDs, refs) passed through `re.escape()` before use in regex patterns. See Pattern 1. |
| Partial write on crash leaves file half-edited | DoS | `atomic_write()` (fsync + rename). Either full edit applies or none. |
| Op silently corrupts file (the P0-006 pattern) | Tampering + DoS | SELF_SERIALIZING_OPS bypass + raw edits + paren balance check pre-write + format preservation assertion (diff line count). |

## Sources

### Primary (HIGH confidence)
- `src/kicad_agent/ops/schematic_raw_writer.py` — full file read; the raw-edit tool to extend. Confirms no property-replacement method exists yet (lines 33-439).
- `src/kicad_agent/crossfile/pcb_populate.py:383-430` — `_replace_property_value()` reference implementation. The exact pattern to mirror.
- `src/kicad_agent/schematic_routing/schematic_graph.py:165-216, 681-776` — `SchematicGraph.from_hierarchy()` + `_parse_sheet_refs()` + `_extract_sexp_block()`. Reuse for sheet tree walking.
- `src/kicad_agent/ops/handlers/crossfile.py:197-330` — `_handle_safe_sync_pcb_from_schematic` (the proven template).
- `src/kicad_agent/ops/execution.py:112, 337-414, 642-728` — `SELF_SERIALIZING_OPS`, `execute_schematic()`, `execute_cross_file()`. Determines dispatch routing.
- `src/kicad_agent/ops/handlers/pcb_cleanup.py:135-145` — `validate_paren_balance()`.
- `src/kicad_agent/io/atomic_write.py:15-43` — `atomic_write()`.
- `src/kicad_agent/ir/schematic_ir.py:28, 150-160, 222-289` — `_REF_PATTERN`, `_set_component_reference` (the FORBIDDEN path), `annotate_components` (the FORBIDDEN path).
- `tests/test_safe_sync_pcb_from_schematic.py:1-334` — test pattern template (AST grep for to_file, preserve_* assertions, dry_run, happy path, no-changes).
- `tests/fixtures/schematic_intent/complete_led.kicad_sch:8, 80-99` — valid KiCad 10 schematic format (lib_symbol vs placed instance).
- `BUGS/P0-006-annotate-corrupts-files.md` — the bug being fixed (full read).
- `BUGS/P0-003-erc-auto-fix-corrupts-files.md` — same root cause class, proven fix path (full read).
- `docs/FEATURE-008-safe-annotate.md` — canonical spec (full read).
- `.planning/phases/102-safe-annotate-non-destructive-refdes-renumbering/102-CONTEXT.md` — user decisions (full read).

### Secondary (MEDIUM confidence)
- `src/kicad_agent/crossfile/schematic_sync.py:200-357` — raw PCB manipulation helpers (`_find_footprint_block`, `_extract_pcb_footprint_refs`). Cross-reference for raw-edit conventions; the schematic equivalents need to be built but follow the same shape.
- `src/kicad_agent/schematic_routing/net_resolver.py:103-112` — `_load_sub_sheets()` (alternative flat-walk pattern, but inferior to `from_hierarchy()` for recursive sheets).

### Tertiary (LOW confidence)
- None — all findings verified against codebase.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already installed and verified against CLAUDE.md tool inventory
- Architecture: HIGH — dispatch routing (SELF_SERIALIZING_OPS) verified via execution.py:112-114, 382-385; sheet walking verified via schematic_graph.py:165-216; raw edit pattern verified via pcb_populate.py:383-430
- Pitfalls: HIGH — all 5 pitfalls grounded in codebase citations (Pitfall 4 "hierarchical coords" is MEDIUM confidence, flagged as A2 in Assumptions Log)
- Test fixtures: MEDIUM — existing single-sheet fixtures verified; multi-sheet fixtures must be created (Wave 0 gap)

**Research date:** 2026-06-29
**Valid until:** 2026-07-29 (30 days — stable codebase, no external API dependencies)
