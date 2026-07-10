# Phase 205: Board Metadata Foundation - Context

**Gathered:** 2026-07-10
**Status:** Ready for planning
**Source:** Derived from v7.0 ROADMAP.md + REQUIREMENTS.md + codebase pattern analysis

<domain>
## Phase Boundary

Phase 205 adds the ability to read and write board metadata (revision, title, date, company) from `.kicad_pcb` `title_block` elements, and persist manufacturing specs (surface finish, copper weight, mask/silk color, impedance) in a sidecar JSON file. This is the **foundation phase** for the v7.0 milestone — Phase 207 (Versioned Builds) depends on the `title_block` rev field for `board_rev`.

**What ships:**
- `title_block` parsing in the native PCB parser (currently in `_UNSUPPORTED_ELEMENTS`)
- `NativeTitleBlock` frozen dataclass
- `BoardSpec` manufacturing spec model with sidecar JSON persistence
- 3 operations: `read_board_metadata` (read-only), `set_board_metadata` (mutating), `set_board_revision` (mutating)
- Round-trip fidelity for KiCad 10 quoting variations

**What does NOT ship (later phases):**
- DRC vendor profiles (Phase 206)
- Build records / manifest serialization (Phase 207)
- Handoff package / zip bundling (Phase 208)
- MCP/CLI exposure (Phase 209)
- BoardSpec is NOT wired into ManufacturingReadinessGate or any gate yet — it's just a data model + persistence layer

</domain>

<decisions>
## Implementation Decisions

### Parser Extension (META-06, META-07)

- **Remove `title_block` from `_UNSUPPORTED_ELEMENTS`** in `parser/pcb_native_parser.py` (line 62)
- **Add `"title_block"` to `_KNOWN_TOP_LEVEL`** in `_build_board` (line 379) to suppress the unsupported warning
- **Add `_extract_title_block(cls, root)` classmethod** following the `_extract_setup` pattern (lines 1234-1255):
  - Find `(title_block ...)` block via `_find_symbol(root, "title_block")`
  - Extract fields via existing helpers: `_find_first_value`, `_find_string_child`
  - Comments are numbered: `(comment 1 "...")`, `(comment 2 "...")`, etc. — use `_find_property` or a numbered lookup
  - Return `NativeTitleBlock | None` (None if no title_block present — valid for minimal boards)
- **Call `title_block = cls._extract_title_block(root)`** among the existing extractor calls (~line 376)
- **Pass `title_block=title_block` to `NativeBoard(...)` constructor** (line 399)

### NativeTitleBlock Dataclass (META-06)

- **Add to `parser/pcb_native_types.py`** following the `NativeGeneral` pattern (flat frozen dataclass, simple typed fields, default values)
- **Fields:** `title: str = ""`, `date: str = ""`, `rev: str = ""`, `company: str = ""`, `comments: tuple[str, ...] = ()`
  - Comments modeled as tuple of strings (position-indexed by KiCad comment number). Comment 1 → index 0, Comment 2 → index 1, etc. Empty comments are empty strings. Tuple (not dict) for consistency with the frozen/immutability convention (Phase 100 CR-01 closure — all collection fields use tuple).
- **Add to `__all__` export list** (lines 394-410)
- **Import in parser** and add as field on `NativeBoard`: `title_block: NativeTitleBlock | None = None`
  - `None` means no `(title_block ...)` element present in the file (valid for minimal boards)
  - A populated `NativeTitleBlock` with all empty fields means a title_block exists but has no content

### KiCad 10 Quoting Variations (META-07)

- KiCad 10 title_block fields can be **quoted or unquoted**: `(title "My Board")` vs `(title My Board)` — though in practice title_block fields are always quoted strings. Comments use the pattern `(comment 1 "text")`.
- The parser's existing `_find_string_child` and `_find_first_value` helpers already handle both quoted and unquoted values (they were built for this).
- **Pitfall 2 prevention:** Test with fixtures that have empty fields, numbered comments, and special characters in title/company.
- Empty fields: `(title "")` → `title=""`. Missing field entirely: `(title_block (date "..."))` with no title → `title=""` (default). Both must round-trip correctly.

### BoardSpec Manufacturing Model (META-04, META-05)

- **New file: `src/kicad_agent/manufacturing/board_spec.py`** (creates `manufacturing/` package — add `manufacturing/__init__.py`)
- **Pydantic `BaseModel`** (NOT frozen dataclass — matches `ManufacturerProfile` in `dfm/profiles.py`, the existing manufacturing-capability model convention)
- **Fields:**
  - `surface_finish: SurfaceFinish = SurfaceFinish.HASL` — enum (HASL, ENIG, HASL_LEAD_FREE, IMPEG, HARD_GOLD, OSP, etc.)
  - `copper_weight_outer_oz: float = 1.0` — outer layer copper weight in oz (1.0 = 1oz = 35μm)
  - `copper_weight_inner_oz: float = 0.5` — inner layer copper weight (0.5oz default for signal layers)
  - `soldermask_color: SoldermaskColor = SoldermaskColor.GREEN` — enum (GREEN, RED, BLUE, BLACK, WHITE, YELLOW, PURPLE, MATTE_BLACK, etc.)
  - `silkscreen_color: SilkscreenColor = SilkscreenColor.WHITE` — enum (WHITE, BLACK)
  - `impedance_requirements: tuple[ImpedanceRequirement, ...] = ()` — controlled impedance nets
- **ImpedanceRequirement** nested model (META-05):
  - `net_name: str` — which net has the impedance requirement
  - `target_ohms: float` — target impedance (50, 75, 90, 100, 120 common)
  - `reference_layer: str` — reference layer name (e.g., "GND", "L02")
- **Enums** defined as `str, Enum` subclasses for JSON serialization compatibility (pydantic serializes str-Enum as the string value)

### Sidecar JSON Persistence (META-04)

- **File path:** `.kicad_build_spec.json` alongside the `.kicad_pcb` file
  - For `board.kicad_pcb` → `board.kicad_build_spec.json` (replaces `.kicad_pcb` extension with `.kicad_build_spec.json`)
- **Serialization:** pydantic `.model_dump_json(indent=2)` — clean, human-readable, forward-compatible
- **Atomic write:** `tempfile.NamedTemporaryFile` + `os.replace` pattern (matches `.kicad_pro` atomic write in Phase v2.4, Council FE-02)
- **Load/dump functions:**
  - `load_board_spec(pcb_path: Path) -> BoardSpec | None` — reads sidecar, returns None if not present
  - `save_board_spec(pcb_path: Path, spec: BoardSpec) -> Path` — writes sidecar atomically, returns sidecar path
- **Round-trip:** load → modify → save → reload must reproduce the BoardSpec exactly

### Operations (META-01, META-02, META-03)

**read_board_metadata** (read-only query op — META-01):
- **Schema:** `ReadBoardMetadataOp` in `_schema_pcb.py` — `op_type: Literal["read_board_metadata"]`, `target_file: TargetFile` only
- **Registry:** `is_readonly: True`, `category: "query"`, `file_types: [".kicad_pcb"]`
- **Handler:** `@register_query("read_board_metadata")` in `handlers/query.py` (read-only dispatch path — no Transaction, no file write)
- **Returns:** dict with `title`, `date`, `rev`, `company`, `comments` (list), plus `board_spec` (dict or None if sidecar exists)
- **Implementation:** Parse PCB → `ir.native_board.title_block` → build result dict. Also load `.kicad_build_spec.json` if present.

**set_board_metadata** (mutating op — META-03):
- **Schema:** `SetBoardMetadataOp` in `_schema_pcb.py` — `target_file`, optional `title: str | None`, `date: str | None`, `rev: str | None`, `company: str | None`, optional `comments: list[str] | None`
  - Only provided fields are updated; None means "leave unchanged" (partial update pattern matching `ModifyNetClassOp` Optional fields from v2.4)
- **Registry:** `is_readonly: False`, `category: "pcb"`, `file_types: [".kicad_pcb"]`
- **Handler:** `@register_pcb("set_board_metadata")` in `handlers/pcb.py` (mutating dispatch — Transaction-wrapped, serialized, undo-tracked)
- **Mutation path:** This is a native-path mutation (modifies `title_block`). Two approaches:
  - **Option A (preferred):** PcbIR native-path mutation — `replace(self._native_board, title_block=new_tb)` + `_record_mutation`. But this requires the serializer to emit `title_block` (currently it's preserved as raw text). **Risk:** the serializer may not emit a typed title_block, only preserve raw content.
  - **Option B (fallback):** Raw S-expression writer approach — use `PcbRawWriter` to produce new content string with modified title_block, `ir.commit_raw_content(new_content)`. This matches `move_footprint`, `assign_net_class` handler pattern. Safer because it doesn't depend on serializer changes.
  - **Decision:** Research must determine whether the native serializer emits `title_block` or only preserves it as raw content. If serializer doesn't emit typed title_block, use Option B (raw writer). The plan must specify the exact approach after research.
- **Returns:** updated metadata dict (same shape as read_board_metadata)

**set_board_revision** (mutating op — META-02):
- **Schema:** `SetBoardRevisionOp` in `_schema_pcb.py` — `target_file`, `rev: str` (required, no None — this is the one field you MUST provide)
- **Registry:** `is_readonly: False`, `category: "pcb"`, `file_types: [".kicad_pcb"]`
- **Handler:** `@register_pcb("set_board_revision")` in `handlers/pcb.py`
- **Implementation:** Convenience wrapper — delegates to the title_block rev field update. Same mutation path decision as set_board_metadata.

### Schema Union + Registry Parity (Integration Pitfall IP-1, IP-2)

- Add `ReadBoardMetadataOp`, `SetBoardMetadataOp`, `SetBoardRevisionOp` to the `Operation` discriminated union in `schema.py`
- Add `_RAW_CATALOG` entries for all 3 ops in `registry.py`
- Import/re-export the 3 new Op classes in `schema.py`
- **Update `test_registry.py:26` count assertion** (currently `== 142` → becomes `== 145` for +3 ops)
- **`validate_registry_completeness()` must pass** — registry, schema union, and handlers all in sync

### Handler Registry (Integration Pitfall IP-3)

- Read-only handler (`read_board_metadata`) goes in `handlers/query.py` via `@register_query`
- Mutating handlers (`set_board_metadata`, `set_board_revision`) go in `handlers/pcb.py` via `@register_pcb`
- Both registries are already aggregated in `handlers/__init__.py` — no new merge needed (unlike Phase 207 which adds a `manufacturing.py` handler module)

### Claude's Discretion

- **Comment numbering:** How to model KiCad's numbered comments (`(comment 1 "...")` through `(comment 9 "...")`). Decision above: position-indexed tuple where index 0 = comment 1. Alternative: dict mapping `{1: "text", 2: "text"}`. Tuple is simpler and consistent with frozen convention — use tuple.
- **SurfaceFinish enum values:** The exact set of surface finishes to enumerate. Use common industry values (HASL, ENIG, HASL_LEAD_FREE, IMPEG, HARD_GOLD, OSP, ENIPIG). Can be extended later.
- **Color enums:** Use KiCad's color names (green, red, blue, black, white, yellow, purple). Match KiCad convention for consistency.
- **BoardSpec default values:** HASL finish, 1oz outer copper, green soldermask, white silkscreen. These are the most common defaults for prototype boards.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Parser Patterns
- `src/kicad_agent/parser/pcb_native_parser.py` — `_UNSUPPORTED_ELEMENTS` (line 62), `_KNOWN_TOP_LEVEL` (line 379), `_extract_setup` pattern (lines 1234-1255), helper functions `_find_symbol`/`_find_first_value`/`_find_string_child` (lines 77-172)
- `src/kicad_agent/parser/pcb_native_types.py` — `NativeGeneral` pattern (line 295), `NativeStackup` pattern (line 322), `NativeBoard` fields (line 348), `__all__` export list (lines 394-410), immutability contract (lines 1-43)

### IR Mutation Patterns
- `src/kicad_agent/ir/pcb_ir.py` — `add_net` (lines 198-205), `remove_net` (lines 230-252) showing `dataclasses.replace` + `_record_mutation` pattern, `commit_raw_content` (line 1109) for raw-string mutation path

### Operation Patterns
- `src/kicad_agent/ops/_schema_pcb.py` — `SetBoardOutlineOp` (lines 98-111) mutating op pattern, `ListNetClassesOp` (lines 283-294) read-only op pattern
- `src/kicad_agent/ops/schema.py` — `Operation` discriminated union (lines 394-557), `TargetFile` validator (lines 153-166), import/re-export section (~line 173)
- `src/kicad_agent/ops/registry.py` — `OpMeta` fields (lines 17-40), `_RAW_CATALOG` entry pattern, existing `set_board_outline` entry (lines 372-380)
- `src/kicad_agent/ops/handlers/pcb.py` — `register_pcb` decorator + `_PCB_HANDLERS` dict (lines 16-24)
- `src/kicad_agent/ops/handlers/query.py` — `register_query` decorator + `_QUERY_HANDLERS` dict (lines 14-22)
- `src/kicad_agent/ops/execution.py` — `execute_query` (line 193) read-only dispatch, `execute_pcb` (line 470) mutating dispatch, `CROSS_FILE_OP_TYPES` (line 112)

### Manufacturing Model Patterns
- `src/kicad_agent/dfm/profiles.py` — `ManufacturerProfile` pydantic BaseModel (line 24), `from_yaml`/`from_json`/`from_dict` classmethods, `_PROFILES` dict (lines 181-187)

### Test Patterns
- `tests/test_pcb_native_parser.py` — Module-scoped fixture pattern (lines 38-47), existing stackup/setup tests (lines 362-378)
- `tests/test_pcb_ops.py` — `_create_minimal_pcb` helper (lines 26-68), autouse `_clear_ir_registry` fixture, op test structure
- `tests/test_registry.py` — Registry count assertion (line 26), `validate_registry_completeness` validation

### Test Fixtures (contain title_block)
- `tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_pcb` — has `(title_block (date "mar. 31 mars 2015"))` (date only, no title/rev/company)
- `tests/fixtures/RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_pcb` — has `(title_block (date "15 nov 2012"))` (date only)
- **Note:** Both fixtures have minimal title_blocks (date only). Tests for full title/company/rev/comments round-trip will need a custom fixture PCB created during implementation.

</canonical_refs>

<specifics>
## Specific Ideas

- The `title_block` is a **top-level element** in `.kicad_pcb` S-expressions, placed after `(paper ...)` and before `(layers ...)`. Structure:
  ```
  (title_block
      (title "Board Name")
      (date "2026-07-10")
      (rev "2.1")
      (company "ACME Corp")
      (comment 1 "First comment")
      (comment 2 "Second comment")
      ...
      (comment 9 "Ninth comment")
  )
  ```
- KiCad allows 1-9 numbered comments. Comments are optional. Any subset may be present.
- A title_block with ONLY a date (as in the test fixtures) is valid: `(title_block (date "15 nov 2012"))`.
- BoardSpec sidecar should be **versioned** — include a `"schema_version": 1` field for future migration safety. This is a forward-looking decision matching the immutable/round-trip philosophy of the codebase.
- The `.kicad_build_spec.json` sidecar is NOT a KiCad file — it's our own invention. It lives alongside the PCB file but is not read by KiCad. This is intentional: KiCad has no native way to store manufacturing specs, so we extend with a sidecar.

</specifics>

<deferred>
## Deferred Ideas

- Wiring BoardSpec into ManufacturingReadinessGate or DFM checks — Phase 208 (Handoff) consumes BoardSpec for the readme generator
- BoardSpec validation against manufacturer capabilities (e.g., "does JLCPCB support purple soldermask?") — Phase 206 (DRC Profiles) adds `ManufacturerProfile` extensions; Phase 208 uses them
- Versioned BoardSpec migrations (schema_version 2+) — future, when fields are added
- Reading `title_block` from `.kicad_sch` files (this phase is PCB-only) — schematic title_block has the same structure but lives in schematic files

</deferred>

---

*Phase: 205-board-metadata-foundation*
*Context gathered: 2026-07-10 via roadmap-derivation + codebase pattern analysis*
