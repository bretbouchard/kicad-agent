# Phase 205: Board Metadata Foundation — Research

**Date:** 2026-07-10
**Status:** Complete
**Purpose:** Fill technical feasibility gaps for the planner. CONTEXT.md locked design decisions; this research validates them and resolves open questions.

---

## RQ1: title_block S-expression Structure and KiCad 10 Quoting

### Fixture Analysis

Both existing PCB fixtures have minimal title_blocks (date-only):

**`tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_pcb` (lines 10-12):**
```
(title_block
    (date "mar. 31 mars 2015")
)
```

**`tests/fixtures/RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_pcb` (lines 10-12):**
```
(title_block
    (date "15 nov 2012")
)
```

The other 3 PCB fixtures (`smd_test_board.kicad_pcb`, `phase99_synthetic_4layer_mixedsignal.kicad_pcb`, `backplane.kicad_pcb`) have NO title_block element at all. This is valid — title_block is optional.

### Canonical title_block Structure (Verified)

The `(title_block ...)` element is a top-level child of `(kicad_pcb ...)`, placed after `(paper ...)` and before `(layers ...)`:

```
(title_block
    (title "Board Name")
    (date "2026-07-10")
    (rev "2.1")
    (company "Company Name")
    (comment 1 "Comment 1 text")
    (comment 2 "Comment 2 text")
    ...
    (comment 9 "Comment 9 text")
)
```

All fields are optional. A title_block with only a date is valid. A title_block with no fields at all is valid. Missing title_block entirely is valid.

### Quoting Rules (Verified via sexpdata)

**All title_block string fields are ALWAYS quoted** in KiCad 10 `.kicad_pcb` files. The fields `(title "...")`, `(date "...")`, `(rev "...")`, `(company "...")`, and `(comment N "...")` all use double-quoted strings. This matches the fixtures and KiCad's own output.

**Special character handling** — verified by parsing with sexpdata:
- Parentheses in titles: `(title "Test Board v2.1 (prototype)")` → parses correctly to `Test Board v2.1 (prototype)`
- Ampersands: `(company "Smith & Co.")` → parses to `Smith & Co.`
- Escaped quotes (KiCad doubling convention): `(company "Smith & Co. \"Inc\"")` → parses to `Smith & Co. "Inc"`

**Empty field representation:** `(title "")` — always an empty quoted string. NOT `(title)` or missing. Verified: `sexpdata.loads('(title_block (title "") (date "2026-01-01"))')` yields `title=""`.

### Comment Numbering (Verified)

Comments use `(comment N "text")` where:
- `N` is always an integer (1-9 per KiCad convention)
- Comments can be **non-sequential**: a board can have comment 1, comment 3, comment 9 with no comment 2, 4-8
- Any subset may be present (including none)

Verified test: comments at positions 1, 3, 9 all extracted correctly by iterating the title_block children.

### Existing Parser Helper Compatibility (Verified)

The helpers at `src/volta/parser/pcb_native_parser.py:77-172` work correctly for title_block extraction:

| Helper | Location | Works for title_block? |
|--------|----------|----------------------|
| `_find_symbol(tree, name)` | line 84 | YES — finds `(title_block ...)` block |
| `_find_string_child(block, name, default)` | line 156 | YES — extracts `(title "...")`, `(date "...")`, `(rev "...")`, `(company "...")` |
| `_find_first_value(block, name, default)` | line 145 | YES — alternative for any field (returns raw value) |
| `_find_property(fp_block, prop_name)` | line 166 | NO — expects `(property NAME VALUE)` format, not `(title VALUE)` |

**For numbered comments:** None of the existing helpers handle `(comment N "text")` directly. A dedicated loop is needed:

```python
comments: dict[int, str] = {}
for item in title_block:
    if isinstance(item, list) and len(item) >= 3 and _sym(item[0]) == "comment":
        try:
            num = int(item[1])
            text = item[2] if isinstance(item[2], str) else str(item[2])
            comments[num] = text
        except (ValueError, TypeError):
            continue
```

This converts to the tuple representation (index 0 = comment 1, index 1 = comment 2, etc.) after collection.

### CRITICAL: Query Path Does NOT Use Native Parser

The `execute_query` function in `src/volta/ops/execution.py:193-230` builds PcbIR via the **legacy kiutils path**, NOT the native parser:

```python
# execution.py lines 217-223
parse_result = parse_pcb(file_path)      # kiutils parse
uuid_map = extract_uuids(parse_result.raw_content, "pcb")
ir = PcbIR(_parse_result=parse_result, _uuid_map=uuid_map)
```

This means `ir.board` returns the kiutils `Board` object (NOT `NativeBoard`), so `ir.board.title_block` will not exist even after the native parser is extended.

**However:** `ir.raw_content` is ALWAYS available (from `BaseIR` at `src/volta/ir/base.py:137-139`), so the `read_board_metadata` query handler can parse the title_block from raw content using the native parser's helper functions directly. The query handler does NOT need a NativeBoard — it just needs to call `_find_symbol(sexpdata.loads(ir.raw_content), "title_block")`.

Alternatively, `execute_pcb` (line 470+) DOES use the native parser via `try_native_parse` (line 496), so mutating handlers will have `ir.board` as a NativeBoard with the new `title_block` field.

---

## RQ2: Serializer Behavior — Does the Native Serializer Emit title_block?

### CRITICAL FINDING: Serializer Does NOT Emit Typed title_block

The PCB serializer at `src/volta/serializer/pcb_ser.py:24-83` uses `kiutils_obj.to_file()` to serialize. It operates on `ParseResult.kiutils_obj`, which is the **kiutils Board** object — NOT the NativeBoard from the native parser.

```python
# pcb_ser.py lines 64-66 (the serialization call)
parse_result.kiutils_obj.to_file(tmp_path)
serialized = Path(tmp_path).read_text(encoding="utf-8")
```

The native parser's `NativeBoard` (with its `title_block` field) is NEVER passed to this serializer. The serializer only works with the kiutils `Board` object.

### How raw_content Survives (The Preservation Mechanism)

In `src/volta/ir/pcb_ir.py`, the mutation path uses `commit_raw_content()` (line 1109) for raw S-expression mutations. This writes the modified raw content directly to disk via `atomic_write`, sets `_raw_written = True`, and the executor skips kiutils serialization:

```python
# execution.py lines 533-534
if not ir.raw_written and parse_result is not None:
    serialize_pcb(parse_result, file_path, uuid_map=uuid_map)
```

When `raw_written` is True (after `commit_raw_content`), the executor does NOT call `serialize_pcb` — the raw content (which includes the title_block) is already on disk.

### DECISION: Use Option B (Raw Writer + commit_raw_content)

**Option A (native-path mutation via `replace(self._native_board, title_block=new_tb)`) will NOT work** because the serializer (`serialize_pcb`) does not emit NativeBoard fields — it uses `kiutils_obj.to_file()`. Even if we update the NativeBoard's `title_block` field, the serializer would not write it.

**Option B (raw S-expression writer + `commit_raw_content`) is the correct approach.** This matches the `assign_net_class` handler pattern (`src/volta/ops/pcb_ops.py:349-380`):

```python
# The assign_net_class pattern (pcb_ops.py lines 366-370)
raw_content = ir.raw_content
new_content = PcbRawWriter.assign_net_class(raw_content, net_name, net_class_name)
ir.commit_raw_content(new_content)
```

For title_block mutation, a new `PcbRawWriter` method is needed (e.g., `replace_title_block(content, title_block_sexp)` or field-level `set_title_field(content, field_name, value)`). The method should:
1. Find the existing `(title_block ...)` block using `_find_matching_close` (the existing helper at `pcb_raw_writer.py:938`)
2. Replace it with the new title_block S-expression, OR insert a new one if none exists
3. Return the modified content string

**PcbRawWriter has NO existing title_block methods** — they must be added during implementation. The closest existing pattern is `find_zone_block` (line 167) + `modify_zone_field` (line 221) which finds a block and replaces a field within it.

---

## RQ3: KiCad CLI Round-trip Verification

### kicad-cli Availability

`kicad-cli` version **10.0.3** is installed at `/usr/local/bin/kicad-cli` and available on PATH.

### Validation Commands

- `kicad-cli pcb export stats <file.kicad_pcb>` — validates the board structure can be loaded. Returns "Wrote board statistics" on success, "Failed to load board" on failure. Exit code 0 for both (must check stdout).
- `kicad-cli pcb upgrade <file.kicad_pcb>` — upgrades format version. Segfaults (exit 139) on malformed files.
- `kicad-cli pcb drc <file.kicad_pcb>` — runs DRC. Also validates loadability.

**Recommended validation:** `kicad-cli pcb export stats` is the lightest validation that confirms the file loads correctly. It writes a `.rpt` file.

### Verified Round-trip

Modified the title_block on `Arduino_Mega.kicad_pcb` (added title, rev, company, comments 1-2) and confirmed `kicad-cli pcb export stats` still loads it successfully. The modified file parses correctly with sexpdata and all fields are extracted as expected.

### Existing Round-trip Test Pattern

`src/volta/validation/roundtrip.py` provides `round_trip_stable(path, tmp_dir)` and `round_trip_compare(path, tmp_dir)`. However, these test kiutils parse→serialize stability, which is NOT the path used for title_block mutations (raw writer path).

For title_block round-trip testing, the pattern should be:
1. Parse original → extract title_block fields
2. Modify via raw writer → write to disk
3. Re-parse from disk → extract title_block fields
4. Assert modified fields match expected values
5. Optionally validate with `kicad-cli pcb export stats`

---

## RQ4: BoardSpec JSON Serialization Details

### Pydantic Version

**pydantic 2.13.4** is installed.

### str-Enum Serialization Behavior

`str, Enum` subclasses serialize as the **enum name string** (e.g., `SurfaceFinish.ENIG` → `"ENIG"`). Verified with test:

```python
class SurfaceFinish(str, Enum):
    HASL = 'HASL'
    ENIG = 'ENIG'
```

In JSON output: `"surface_finish": "ENIG"` (uppercase name, not lowercase).

Round-trip is perfect: `BoardSpec.model_validate_json(spec.model_dump_json(indent=2)) == spec` returns `True`.

### Sample `.kicad_build_spec.json` (Verified Output)

With impedance requirements populated:
```json
{
  "schema_version": 1,
  "surface_finish": "ENIG",
  "copper_weight_outer_oz": 1.0,
  "copper_weight_inner_oz": 0.5,
  "soldermask_color": "GREEN",
  "silkscreen_color": "WHITE",
  "impedance_requirements": [
    {
      "net_name": "USB_DM",
      "target_ohms": 90.0,
      "reference_layer": "GND"
    },
    {
      "net_name": "USB_DP",
      "target_ohms": 90.0,
      "reference_layer": "GND"
    }
  ]
}
```

With defaults only (no args):
```json
{
  "schema_version": 1,
  "surface_finish": "HASL",
  "copper_weight_outer_oz": 1.0,
  "copper_weight_inner_oz": 0.5,
  "soldermask_color": "GREEN",
  "silkscreen_color": "WHITE",
  "impedance_requirements": []
}
```

**Note:** `tuple[ImpedanceRequirement, ...]` serializes as JSON array `[]` and round-trips correctly back to a tuple.

### Sidecar File Naming

The sidecar file path convention: for `board.kicad_pcb`, the sidecar is `board.kicad_build_spec.json` (replaces `.kicad_pcb` extension with `.kicad_build_spec.json`).

No existing sidecar pattern in the codebase for JSON files. The closest is `.kicad_dru` (S-expression, in `src/volta/project/design_rules.py`) and `.floorplan.yaml` (referenced in floorplan module). Neither is a JSON sidecar — BoardSpec's JSON sidecar is a new pattern.

---

## RQ5: Atomic Write Pattern

### Existing Pattern (Verified)

`src/volta/io/atomic_write.py:15-43` provides the canonical atomic write function used across the codebase:

```python
def atomic_write(file_path: Path, content: str) -> None:
    """Write content to file atomically via temp file + fsync + rename."""
    file_path = Path(file_path)
    fd, tmp_path = tempfile.mkstemp(
        dir=file_path.parent,
        prefix=".kicad_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(file_path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
```

This is used by:
- `PcbIR.commit_raw_content()` at `src/volta/ir/pcb_ir.py:1120`
- `serialize_pcb()` at `src/volta/serializer/pcb_ser.py:81`
- Snapshot restore at `src/volta/daemon/snapshot.py` (Phase 170)

### Recommended Pattern for BoardSpec Sidecar

The `save_board_spec` function should use `atomic_write` directly:

```python
from volta.io.atomic_write import atomic_write

def save_board_spec(pcb_path: Path, spec: BoardSpec) -> Path:
    sidecar_path = pcb_path.with_suffix(".kicad_build_spec.json")
    json_content = spec.model_dump_json(indent=2)
    atomic_write(sidecar_path, json_content)
    return sidecar_path
```

The prefix `.kicad_` in `atomic_write` is PCB-specific but harmless for JSON files. If the prefix matters, the function accepts any path so it works regardless.

---

## RQ6: Registry Count and Schema Union

### Current Counts (ACTUAL — differs from CONTEXT.md)

**IMPORTANT:** The CONTEXT.md states the registry count is 142. The ACTUAL current counts are:

| Metric | CONTEXT.md says | ACTUAL | Location |
|--------|----------------|--------|----------|
| Registry entries | 142 | **151** | `src/volta/ops/registry.py` `_RAW_CATALOG` |
| Schema union variants | (not stated) | **154** | `src/volta/ops/schema.py:402` `oneOf` |
| Test assertion | `== 142` | `== 142` (STALE) | `tests/test_registry.py:26` |
| Missing from registry | 0 | **3** | `add_design_note`, `apply_floor_plan`, `place_and_wire_power_units` |

The test at `tests/test_registry.py:26` is stale — it asserts `== 142` but the actual registry has 151 entries. The test likely hasn't been run recently or was intentionally not updated.

### After Phase 205 Adds 3 New Ops

Adding `read_board_metadata`, `set_board_metadata`, `set_board_revision`:

| Metric | Current | After Phase 205 |
|--------|---------|-----------------|
| Registry entries | 151 | **154** (if the 3 missing are not also added) or **157** (if missing ops are also fixed) |
| Schema union variants | 154 | **157** |
| Test assertion | `== 142` | **Must update to match actual count** |

### Planner Action Items

1. **Update `tests/test_registry.py:26`** — change `assert len(OPERATION_REGISTRY) == 142` to the correct count (154 after adding 3 ops, assuming the 3 missing ops are pre-existing tech debt not in scope).
2. **Add 3 ops to `_RAW_CATALOG`** in `src/volta/ops/registry.py` — follow the `set_board_outline` entry pattern (lines 372-380).
3. **Add 3 Op classes to `_schema_pcb.py`** — follow `SetBoardOutlineOp` (lines 98-111) for mutating ops, `ListNetClassesOp` (lines 283-294) for read-only.
4. **Add 3 classes to the `Operation.root` union** in `schema.py:402` — add to the `oneOf` list.
5. **Import/re-export the 3 new Op classes** in `schema.py` (~line 173).
6. **Register handlers** — `read_board_metadata` via `@register_query` in `handlers/query.py`; `set_board_metadata` and `set_board_revision` via `@register_pcb` in `handlers/pcb.py`.
7. **`validate_registry_completeness()`** must pass — this cross-checks registry op_types against schema union variants. Adding schema without registry (or vice versa) will fail this check.

### Schema Union Structure

The `Operation` model at `src/volta/ops/schema.py:394-557` uses:

```python
class Operation(BaseModel):
    root: Annotated[
        AddComponentOp | RemoveComponentOp | ... | AutoLayoutSchOp,
        Field(discriminator="op_type"),
    ]
```

This is a discriminated union with `op_type` as the discriminator. Each Op class has `op_type: Literal["specific_op_name"]`.

---

## RQ7: Manufacturing Package Structure

### Package Does NOT Exist (Confirmed)

`src/volta/manufacturing/` does NOT exist. It must be created.

### Existing Package Pattern (dfm/ as reference)

`src/volta/dfm/__init__.py` shows the pattern: docstring + imports + `__all__` list:

```python
"""Design for Manufacturing module.

DFM-01 through DFM-05: Pluggable DFM check framework...
"""
from volta.dfm.checker import DfmChecker, DfmCheck, ...
from volta.dfm.profiles import ManufacturerProfile, load_profile, ...

__all__ = [
    "DfmChecker", "ManufacturerProfile", ...
]
```

For Phase 205, the `manufacturing/__init__.py` should be:

```python
"""Manufacturing layer — board specs, build records, handoff packages.

Phase 205: BoardSpec model + sidecar JSON persistence.
"""
from volta.manufacturing.board_spec import (
    BoardSpec,
    ImpedanceRequirement,
    SurfaceFinish,
    SoldermaskColor,
    SilkscreenColor,
    load_board_spec,
    save_board_spec,
)

__all__ = [
    "BoardSpec",
    "ImpedanceRequirement",
    "SurfaceFinish",
    "SoldermaskColor",
    "SilkscreenColor",
    "load_board_spec",
    "save_board_spec",
]
```

### Enum Placement Decision

**Enums should live in `board_spec.py` itself** (NOT a separate `manufacturing/enums.py`). Rationale (YAGNI):
- `SurfaceFinish`, `SoldermaskColor`, `SilkscreenColor` are only consumed by `BoardSpec`
- No other module references them (confirmed by grep)
- `dfm/profiles.py` uses free-form strings for color/finish (e.g., `"default_solder_mask": "green"` in the `extra` dict at line 137) — it does NOT use enums
- Splitting into `enums.py` adds a file with no reuse benefit
- If Phase 206 (DRC Profiles) later needs shared enums, they can be extracted then

### Relationship to dfm/profiles.py

`ManufacturerProfile` in `src/volta/dfm/profiles.py:24-54` is a **separate concern** from `BoardSpec`:
- `ManufacturerProfile` = what a fab house CAN do (capabilities/constraints for DFM checking)
- `BoardSpec` = what we WANT for THIS board (our manufacturing requirements)

They should NOT share types. `ManufacturerProfile` uses `extra: dict[str, Any]` for vendor-specific fields like `"default_solder_mask": "green"` (line 137). `BoardSpec` uses typed enums. This is intentional — they serve different purposes and may diverge.

**Do NOT import anything from `dfm/profiles.py` into `manufacturing/board_spec.py`.**

---

## Validation Architecture

### Test Strategy

**1. Parser tests** (`tests/test_pcb_native_parser.py` — extend existing):
- Test `_extract_title_block` with the Arduino_Mega fixture (date-only title_block)
- Test with a custom fixture PCB having ALL fields populated (title, date, rev, company, comments 1-9)
- Test with no title_block (should return `None`)
- Test with empty fields `(title "")`
- Test with non-sequential comments (1, 3, 9)
- Test with special characters in title/company (parens, ampersands, escaped quotes)

**2. Raw writer tests** (new tests for `PcbRawWriter` title_block methods):
- Test replacing an existing title_block
- Test inserting a new title_block when none exists
- Test modifying individual fields (rev only, title only)
- Test with special characters (verify proper escaping)
- Verify the `_find_matching_close` helper handles nested parens in quoted strings

**3. Operation tests** (`tests/test_pcb_ops.py` — extend existing):
- `read_board_metadata` on Arduino_Mega fixture → returns date, empty title/rev/company
- `read_board_metadata` on a fixture with full title_block → returns all fields
- `set_board_revision(rev="2.1")` → writes rev, round-trip reads back "2.1"
- `set_board_metadata(title="New Title", company="New Co")` → partial update, other fields preserved
- `set_board_metadata(comments=["c1", "c2"])` → comments written and read back
- Verify `kicad-cli pcb export stats` loads the modified file (structural validation)

**4. BoardSpec tests** (new file `tests/test_board_spec.py`):
- Default construction → all fields have expected defaults
- JSON round-trip: `model_dump_json` → `model_validate_json` → equality
- Sidecar load/save: `save_board_spec` → `load_board_spec` → equality
- Missing sidecar: `load_board_spec` returns `None`
- Impedance requirements: tuple of `ImpedanceRequirement` round-trips correctly

**5. Registry/schema tests** (`tests/test_registry.py`):
- Update count assertion to correct value
- `validate_registry_completeness()` passes
- All 3 new op_types appear in registry

### Test Fixture Gap

Both existing PCB fixtures have minimal title_blocks (date-only). A custom fixture with ALL fields populated is needed. Options:
1. Create a `tests/fixtures/title_block_full.kicad_pcb` fixture file
2. Generate the fixture inline in tests using a helper (like `_create_minimal_pcb` at `tests/test_pcb_ops.py:26-68`)

Option 2 is preferred — inline generation keeps the fixture maintainable and co-located with the tests that use it.

### kicad-cli Validation in Tests

```python
import subprocess
result = subprocess.run(
    ["kicad-cli", "pcb", "export", "stats", str(pcb_path)],
    capture_output=True, text=True,
)
assert "Wrote board statistics" in result.stdout  # File loads correctly
```

This validates that modifications produce structurally valid KiCad files.

---

## RESEARCH COMPLETE

### Key Decisions Resolved

1. **Mutation path: Option B (raw writer + `commit_raw_content`)** — The serializer (`serialize_pcb`) does NOT emit typed NativeBoard fields; it uses `kiutils_obj.to_file()`. Raw writer is the only path that works. (RQ2)

2. **Query handler reads from `ir.raw_content`** — The `execute_query` path uses kiutils, not native parser. The `read_board_metadata` handler must parse title_block from `ir.raw_content` using the native parser's helper functions directly, not from `ir.board.title_block`. (RQ1)

3. **Enum placement: in `board_spec.py`** — No separate `manufacturing/enums.py`. YAGNI — no reuse case exists. (RQ7)

4. **Registry count: ACTUAL is 151, not 142** — The test assertion at `tests/test_registry.py:26` is stale. After adding 3 ops: 154 registry entries, 157 schema union variants. Planner must update the assertion. (RQ6)

5. **Atomic write: use existing `atomic_write`** from `src/volta/io/atomic_write.py`. No new pattern needed. (RQ5)

6. **No `PcbRawWriter` title_block methods exist** — Must be added during implementation. Follow `find_zone_block` + `modify_zone_field` pattern. (RQ2)

7. **pydantic str-Enum serializes as enum name** — `SurfaceFinish.ENIG` → `"ENIG"`. Round-trip is perfect. (RQ4)

8. **All title_block fields are always quoted strings** — No unquoted variants exist in KiCad 10 PCB files. Empty field = `(title "")`. Missing field = absent entirely. (RQ1)

### File Paths Summary

| Purpose | File Path | Key Lines |
|---------|-----------|-----------|
| Parser (add `_extract_title_block`) | `src/volta/parser/pcb_native_parser.py` | `_UNSUPPORTED_ELEMENTS` line 62, `_KNOWN_TOP_LEVEL` line 379, `_extract_setup` pattern lines 1234-1255, helpers lines 77-172 |
| Native types (add `NativeTitleBlock`) | `src/volta/parser/pcb_native_types.py` | `NativeGeneral` pattern line 296, `NativeBoard` line 349, `__all__` line 394 |
| PCB IR (`commit_raw_content`) | `src/volta/ir/pcb_ir.py` | `commit_raw_content` line 1109, `add_net` mutation pattern line 198 |
| Raw writer (add title_block methods) | `src/volta/ops/pcb_raw_writer.py` | `_find_matching_close` line 938, `find_zone_block` line 167, `modify_zone_field` line 221 |
| PCB serializer (does NOT emit title_block) | `src/volta/serializer/pcb_ser.py` | `kiutils_obj.to_file()` line 65 |
| Schema (add 3 Op classes) | `src/volta/ops/_schema_pcb.py` | `SetBoardOutlineOp` line 98, `ListNetClassesOp` line 283 |
| Schema union (add 3 variants) | `src/volta/ops/schema.py` | `Operation.root` oneOf line 402 |
| Registry (add 3 entries) | `src/volta/ops/registry.py` | `_RAW_CATALOG` line 47, `set_board_outline` entry line 372 |
| Handler (query) | `src/volta/ops/handlers/query.py` | `register_query` line 17 |
| Handler (pcb mutating) | `src/volta/ops/handlers/pcb.py` | `register_pcb` line 19, `set_board_outline` handler line 209 |
| Handler init (merge) | `src/volta/ops/handlers/__init__.py` | merge pattern line 27 |
| Execution dispatch | `src/volta/ops/execution.py` | `execute_query` line 193, `execute_pcb` line 470 |
| ManufacturerProfile (reference) | `src/volta/dfm/profiles.py` | `BaseModel` pattern line 24 |
| Atomic write | `src/volta/io/atomic_write.py` | line 15 |
| Test fixture (date-only title_block) | `tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_pcb` | line 10 |
| Test registry (update count) | `tests/test_registry.py` | line 26 |
| Test PCB ops (extend) | `tests/test_pcb_ops.py` | `_create_minimal_pcb` line 26 |
| Round-trip validator (reference) | `src/volta/validation/roundtrip.py` | line 106 |
| Manufacturing package (CREATE) | `src/volta/manufacturing/board_spec.py` | new file |
| Manufacturing init (CREATE) | `src/volta/manufacturing/__init__.py` | new file |
